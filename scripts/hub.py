#!/usr/bin/env python3
"""project-hub：项目群盘点 + 单项目骨架。零依赖，纯标准库。

六个动作，全部可先看后做：

  map    <项目群根>                 盘点所有项目，出总图与问题清单（只读）
  status <项目群根>                 一屏看板：在用 / 停摆 / 要处理的（只读）
  dashboard <项目群根> [--open]     生成浏览器看板（一张 HTML，可筛选）
  init   <项目目录> [--type ...]    建/补齐单项目骨架与 README
  index  <项目群根>                 生成 PROJECTS.md 空表
  git    <项目目录>                 建仓库、写忽略规则、接 GitHub
  save   <项目目录>                 推进时"存一下"：本地存档 + 有地址就上传
  publish <项目目录> [--name ...]   在 GitHub 建私有仓库并推上去（一条命令）
  sync   <项目目录>                 把本地存档补传到 GitHub
  hook   <项目目录> on|off|status   提交后自动推送（可选）
  check  <路径>                     校验是否守规矩（只读；违规时退出码 1）
  apply  <plan.json> [--apply]      按人工确认的清单移动文件（默认 dry-run）

不可违反：
  * 永不删除，只移动
  * 永不覆盖：目标已存在就跳过并报告
  * 只在 --root 之内移动
  * .wbpj 与其 <全名>_files/ 整体移动
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# pythonw.exe 下 stdout/stderr 是 None，先兜住，否则一 print 就崩
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

try:  # 中文 Windows 控制台默认 GBK，重定向时容易炸
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

VERSION = "0.17.0"

# 单项目根允许出现的条目（与全局 AGENTS.md 的骨架一致）
PROJECT_DIRS = ["docs", "src", "tests", "models", "data", "results", "archive", "_tmp"]
SKELETON_SUBDIRS = {
    "docs": ["notes", "reports"],
    "src": ["python", "matlab", "fluent"],
    "data": ["raw", "processed"],
    "results": ["runs", "figures", "tables"],
}
PROJECT_FILES = ["README.md"]
PROJECT_TOLERATED_FILES = [".gitignore", ".gitattributes", "AGENTS.md", "CLAUDE.md", ".lnk", ".url"]
PROJECT_TOLERATED_DIRS = [".git", ".idea", ".vscode", "_reports"]
PROJECT_TOLERATED_EXT = [".lnk", ".url"]

# 项目群根允许出现的条目
PORTFOLIO_FILES = ["PROJECTS.md", "README.md", "AGENTS.md"]
PORTFOLIO_DIRS = ["_inbox", "_archive", "_reports"]

# 这些目录永远不进入统计，也不参与判定
IGNORE_DIRS = {
    ".git", ".svn", ".hg", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode", "site-packages", ".ipynb_checkpoints",
}

ARCHIVE_HINT = re.compile(r"(备份|存档|backup|_old|旧版|_fixed)", re.I)
VERSION_SUFFIX = re.compile(r"^(?P<base>.+?)(?P<num>\d{1,3})$")

GITIGNORE_MARK = "# --- project-hub：大文件不进仓库（自动追加，勿删）---"
GITIGNORE_BLOCK = """# --- project-hub：大文件不进仓库（自动追加，勿删）---

# 临时和缓存
_tmp/
__pycache__/
*.pyc
.venv/
venv/
.ipynb_checkpoints/
node_modules/

# 原始数据、批量结果、模型、存档：太大，走网盘
data/raw/
results/runs/
models/
archive/

# 仿真软件的大文件
*.mph
*.wbpj
*_files/
*.cae
*.inp
*.odb
*.msh
*.cas
*.dat
*.h5
*.stl
*.scdocx
*.trn
*.rpy
*.tif
*.tiff

# 密钥、凭据：永远别提交
.env
.env.*
*.pem
*.key
*.p12
id_rsa*
id_ed25519*
*.kdbx

# 压缩包
*.zip
*.7z
*.rar

# 运行日志
*.log
"""


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------

@dataclass
class Project:
    name: str
    path: Path
    files: int = 0
    bytes: int = 0
    last: float = 0.0
    has_readme: bool = False
    has_git: bool = False
    entries: list[str] = field(default_factory=list)
    stray_files: list[str] = field(default_factory=list)
    nested_same: str = ""
    exts: list[tuple[str, int]] = field(default_factory=list)

    @property
    def last_day(self) -> str:
        if not self.last:
            return "-"
        return datetime.fromtimestamp(self.last).strftime("%Y-%m-%d")

    @property
    def idle_days(self) -> int | None:
        if not self.last:
            return None
        return max(0, (datetime.now() - datetime.fromtimestamp(self.last)).days)

    @property
    def health(self) -> str:
        problems = []
        if not self.has_readme:
            problems.append("无 README")
        if self.stray_files:
            problems.append(f"根目录散落 {len(self.stray_files)} 项")
        if self.nested_same:
            problems.append("自嵌套")
        return "；".join(problems) if problems else "ok"


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------

def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def walk_files(root: Path):
    """产出 root 下所有文件的路径；跳过 IGNORE_DIRS。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fn in filenames:
            yield Path(dirpath) / fn


def nested_same_name(root: Path, max_depth: int = 3) -> str:
    """检测 a/a 或 a/a/a 这种同名声明的自嵌套。"""
    node = root
    chain = [root.name]
    while len(chain) < max_depth + 1:
        child = node / node.name
        if child.is_dir():
            chain.append(node.name)
            node = child
        else:
            break
    return "/".join(chain) if len(chain) > 1 else ""


def scan_project(root: Path) -> Project:
    p = Project(name=root.name, path=root)
    p.has_readme = (root / "README.md").is_file()
    p.has_git = (root / ".git").is_dir()
    try:
        p.entries = sorted(c.name for c in root.iterdir())
    except OSError:
        p.entries = []
    for name in p.entries:
        full = root / name
        if full.is_file() and name not in PROJECT_FILES and name not in PROJECT_TOLERATED_FILES:
            p.stray_files.append(name)
    p.nested_same = nested_same_name(root)

    exts = Counter()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        # 目录自身的 mtime 也要算：拷进来的旧文件保住了原时间戳，但目录更新了
        for dname in dirnames:
            try:
                mt = os.stat(os.path.join(dirpath, dname)).st_mtime
            except OSError:
                continue
            if mt > p.last:
                p.last = mt
        for fn in filenames:
            try:
                st = os.stat(os.path.join(dirpath, fn))
            except OSError:
                continue
            p.files += 1
            p.bytes += st.st_size
            exts[Path(fn).suffix.lower() or "(无后缀)"] += 1
            if st.st_mtime > p.last:
                p.last = st.st_mtime
    p.exts = exts.most_common(3)
    return p


def is_portfolio(root: Path) -> bool:
    """有 PROJECTS.md 一定是项目群根；没有的话看形状：没有项目骨架、却装着多个目录。"""
    if (root / "PROJECTS.md").is_file():
        return True
    if any((root / d).is_dir() for d in ("docs", "src", "models", "data", "results", "tests")):
        return False
    try:
        subs = [c for c in root.iterdir()
                if c.is_dir() and not c.name.startswith(".") and c.name not in PORTFOLIO_DIRS]
    except OSError:
        return False
    return len(subs) >= 3


def list_projects(root: Path) -> list[Project]:
    projects = []
    try:
        children = sorted(root.iterdir(), key=lambda c: c.name.lower())
    except OSError as exc:
        raise SystemExit(f"[错误] 无法读取 {root}: {exc}") from exc
    for child in children:
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in PORTFOLIO_DIRS:
            continue
        # Workbench 工程伴生目录（xxx.wbpj 旁边的 xxx_files）不是独立项目
        if child.name.endswith("_files"):
            base = root / child.name[: -len("_files")]
            if base.with_suffix(".wbpj").is_file():
                continue
        # 子工作区（里面有 PROJECTS.md）不是项目，它自己那层另有总表
        if (child / "PROJECTS.md").is_file():
            continue
        projects.append(scan_project(child))
    return projects


def duplicate_projects(projects: list[Project]) -> dict[str, list[str]]:
    """proj / proj2 / proj3 这类命名族，大概率是同一项目的多份副本。"""
    groups: dict[str, list[str]] = defaultdict(list)
    for p in projects:
        m = VERSION_SUFFIX.match(p.name)
        if m and m.group("base").strip("_-. "):
            groups[m.group("base")].append(p.name)
    return {k: v for k, v in groups.items() if len(v) > 1}


def duplicate_files(projects: list[Project], min_size: int = 1024, limit: int = 30):
    """按（文件名, 大小）找跨项目重复文件——不做哈希，快且够用。"""
    seen: dict[tuple[str, int], list[str]] = defaultdict(list)
    for p in projects:
        for fp in walk_files(p.path):
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            if size < min_size:
                continue
            seen[(fp.name.lower(), size)].append(str(fp.relative_to(p.path.parent)))
    groups = [(k, v) for k, v in seen.items() if len(v) > 1]
    groups.sort(key=lambda kv: len(kv[1]), reverse=True)
    return groups[:limit]


# --------------------------------------------------------------------------
# status：一屏看板
# --------------------------------------------------------------------------

def _w(text: str) -> int:
    """按显示宽度算长度（中文算 2）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _w(text))


def _idle_label(days: int | None) -> str:
    if days is None:
        return "-"
    if days == 0:
        return "今天"
    if days == 1:
        return "昨天"
    return f"{days} 天前"


def _read_index_at(base: Path) -> dict[str, dict]:
    """读某个目录下的 PROJECTS.md，目录一律解析成绝对路径。"""
    path = base / "PROJECTS.md"
    if not path.is_file():
        return {}
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        name = cells[0].strip("`").strip()
        if not name or name == "项目" or set(name) <= {"-", ":", " "}:
            continue
        dirs_raw = cells[4] if len(cells) > 4 else ""
        dirs = []
        for d in re.split(r"[,，]", dirs_raw):
            d = d.strip().strip("`").strip()
            if not d:
                continue
            dp = Path(d)
            dirs.append(str(dp) if dp.is_absolute() else str((base / d).resolve()))
        rows[name] = {
            "one": cells[1],
            "status": cells[2],
            "next": cells[3] if len(cells) > 3 else "",
            "dirs": dirs,
            "base": str(base),
        }
    return rows


def _sub_portfolios(root: Path, depth: int = 3) -> list[Path]:
    """根下面所有自己有 PROJECTS.md 的目录 = 子工作区（最多往下摸 3 层）。"""
    out: list[Path] = []

    def walk(base: Path, level: int) -> None:
        if level > depth:
            return
        try:
            children = sorted(base.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / "PROJECTS.md").is_file():
                out.append(child)
                walk(child, level + 1)

    walk(root, 1)
    return out


def _read_index(root: Path) -> dict[str, dict]:
    """父工作区的表 + 所有子工作区的表，合在一起。"""
    rows = _read_index_at(root)
    for sub in _sub_portfolios(root):
        for name, meta in _read_index_at(sub).items():
            rows.setdefault(name, meta)
    return rows


def _containing_roots(project: Path, depth: int = 4) -> list[Path]:
    """从项目往上找：哪些工作区的 PROJECTS.md 收录了它。"""
    key = str(project.resolve()).lower()
    roots: list[Path] = []
    cur = project.resolve().parent
    for _ in range(depth):
        if (cur / "PROJECTS.md").is_file():
            idx = _read_index(cur)
            for meta in idx.values():
                if any(str(Path(d).resolve()).lower() == key for d in meta.get("dirs", [])):
                    roots.append(cur)
                    break
        if cur.parent == cur:
            break
        cur = cur.parent
    return roots


def _refresh_boards(project: Path) -> None:
    """项目存好后，把它所在工作区的看板重新生成一遍。"""
    for root in _containing_roots(project):
        try:
            cmd_dashboard(argparse.Namespace(path=str(root), out=None, open=False))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 看板刷新失败：{exc}")


def _read_details(root: Path) -> dict[str, dict]:
    """读 PROJECTS.details.md：每个项目一小节，写做什么 / 目的 / 流程 / 关键文件。"""
    path = root / "PROJECTS.details.md"
    if not path.is_file():
        return {}
    out: dict[str, dict] = {}
    current: str | None = None
    key = ""
    for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        if raw.startswith("## "):
            current = raw[3:].strip()
            out[current] = {"做什么": "", "目的": "", "流程": "", "关键文件": [], "主要产出": []}
            key = ""
            continue
        if current is None:
            continue
        if raw.startswith("- ") and "：" in raw:
            k, v = raw[2:].split("：", 1)
            k = k.strip()
            if k in ("做什么", "目的", "流程"):
                out[current][k] = v.strip()
                key = k
            elif k in ("关键文件", "主要产出"):
                key = k
            continue
        if raw.startswith("  - ") and key in ("关键文件", "主要产出"):
            out[current][key].append(raw[4:].strip())
    return out


def _inline_md(text: str) -> str:
    escaped = html.escape(text, quote=True)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)


def _dirty_count(root: Path) -> int:
    proc = _git(["status", "--porcelain"], root)
    if not _git_ok(proc):
        return 0
    return len([ln for ln in proc.stdout.splitlines() if ln.strip()])


def _resolve_member(root: Path, spec: str) -> Path | None:
    """目录可以写相对路径，也可以写绝对路径——项目放哪都能管。"""
    spec = spec.strip().strip("`").strip()
    if not spec:
        return None
    p = Path(spec)
    if not p.is_absolute():
        p = root / spec
    return p if p.is_dir() else None


def _build_projects(root: Path, index: dict[str, dict]) -> list[dict]:
    """把「一个项目 = 多个目录」聚合成看板要用的结构（支持任意位置的项目）。"""
    sub_roots = [root] + _sub_portfolios(root)
    local: dict[str, "Project"] = {}
    for base in sub_roots:
        try:
            children = sorted(base.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith("_"):
                continue
            if (child / "PROJECTS.md").is_file():
                continue
            if child.name.endswith("_files"):
                base_w = child.parent / child.name[: -len("_files")]
                if base_w.with_suffix(".wbpj").is_file():
                    continue
            key = str(child).lower()
            if key not in local:
                local[key] = scan_project(child)

    used: set[str] = set()
    out: list[dict] = []
    for name, meta in index.items():
        members = []
        for spec in meta.get("dirs", []):
            p = Path(spec)
            key = str(p).lower()
            m = local.get(key)
            if m is None:
                if not p.is_dir():
                    continue
                m = scan_project(p)
                local[key] = m
            members.append(m)
        if not members:
            continue
        # 已经被前面的项目认领过，就不再单独成项目（防止父子表重复）
        if all(str(m.path).lower() in used for m in members):
            continue
        used.update(str(m.path).lower() for m in members)
        out.append({
            "name": name,
            "one": meta.get("one", ""),
            "status": meta.get("status", ""),
            "next": meta.get("next", ""),
            "members": members,
            "files": sum(m.files for m in members),
            "bytes": sum(m.bytes for m in members),
            "last": max(m.last for m in members),
            "git": any(m.has_git for m in members),
        })

    leftovers = [p for k, p in local.items() if k not in used]
    for p in leftovers:
        out.append({
            "name": p.name,
            "one": "还没写进 PROJECTS.md",
            "status": "",
            "next": "在 PROJECTS.md 里加一行，或者归档掉",
            "members": [p],
            "files": p.files,
            "bytes": p.bytes,
            "last": p.last,
            "git": p.has_git,
        })
    return out


def _idle_days(last: float) -> int:
    return max(0, (datetime.now() - datetime.fromtimestamp(last)).days)


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"[错误] 不是目录: {root}", file=sys.stderr)
        return 2

    index = _read_index(root)
    if index:
        projs = _build_projects(root, index)
        groups: dict[str, list[dict]] = {"进行中": [], "暂停": [], "已完成": [], "": []}
        for p in projs:
            groups.setdefault((p["status"] or "").strip(), []).append(p)
        for items in groups.values():
            items.sort(key=lambda p: p["last"], reverse=True)
        n_dirs = sum(len(p["members"]) for p in projs)
        total = sum(p["bytes"] for p in projs)

        out: list[str] = []
        add = out.append
        add(f"项目工作台   {datetime.now():%Y-%m-%d %H:%M}")
        add(f"{root}   {len(projs)} 个项目 / {n_dirs} 个目录 / {human_bytes(total)}")
        add("")
        for label in ("进行中", "暂停", "已完成", ""):
            items = groups.get(label) or []
            if not items:
                continue
            title = label or "未标状态"
            add(f"━━ {title}（{len(items)}）" + "━" * max(6, 32 - len(title)))
            add("  " + _pad("项目", 22) + _pad("最后活动", 10) + _pad("目录", 6) + "下一步")
            for p in items[:args.limit]:
                add("  " + _pad(p["name"], 22) + _pad(_idle_label(_idle_days(p["last"])), 10)
                    + _pad(f"{len(p['members'])} 个", 6) + (p["next"] or "（待填）"))
            if len(items) > args.limit:
                add(f"  …… 还有 {len(items) - args.limit} 个")
            add("")
        print("\n".join(out).rstrip())
        return 0

    # 没有 PROJECTS.md 时退回按目录看
    projects = list_projects(root) if is_portfolio(root) else [scan_project(root)]
    active = sorted([p for p in projects if p.idle_days is not None and p.idle_days <= 30],
                    key=lambda p: p.last, reverse=True)
    out = [f"项目工作台   {datetime.now():%Y-%m-%d %H:%M}",
           f"{root}   {len(projects)} 个目录 / {human_bytes(sum(p.bytes for p in projects))}",
           "",
           "  · 还没有 PROJECTS.md：先跑 hub.py index，再把「一句话 / 状态 / 下一步 / 包含目录」填上",
           ""]
    add = out.append
    add(f"━━ 在用（最近 30 天动过）：{len(active)} 个 " + "━" * 16)
    for p in active[:args.limit]:
        add("  " + _pad(p.name, 22) + _pad(_idle_label(p.idle_days), 10))
    print("\n".join(out))
    return 0


# --------------------------------------------------------------------------
# map
# --------------------------------------------------------------------------

def cmd_map(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"[错误] 不是目录: {root}", file=sys.stderr)
        return 2

    if is_portfolio(root):
        projects = list_projects(root)
    else:
        projects = [scan_project(root)]

    families = duplicate_projects(projects)
    dupes = duplicate_files(projects) if args.dupes else []
    total_files = sum(p.files for p in projects)
    total_bytes = sum(p.bytes for p in projects)
    active = [p for p in projects if p.idle_days is not None and p.idle_days <= 30]
    dormant = [p for p in projects if p.idle_days is not None and p.idle_days > args.idle_days]
    empty = [p for p in projects if p.files == 0]

    lines: list[str] = []
    add = lines.append
    add("# 项目群盘点")
    add("")
    add(f"- 根目录：`{root}`")
    add(f"- 时间：{datetime.now():%Y-%m-%d %H:%M}")
    add(f"- 规模：{len(projects)} 个项目 / {total_files} 文件 / {human_bytes(total_bytes)}")
    add(f"- 近 30 天活跃：{len(active)} 个 ｜ 超过 {args.idle_days} 天没动：{len(dormant)} 个 ｜ 空目录：{len(empty)} 个")
    add("")

    add("## 总图")
    add("")
    add("| 项目 | 文件 | 体积 | 最后活动 | 空闲 | Git | 健康 |")
    add("|---|---:|---:|---|---:|---|---|")
    for p in sorted(projects, key=lambda x: x.last, reverse=True):
        idle = "-" if p.idle_days is None else f"{p.idle_days} 天"
        git = "有" if p.has_git else "—"
        add(f"| {p.name} | {p.files} | {human_bytes(p.bytes)} | {p.last_day} | {idle} | {git} | {p.health} |")
    add("")

    findings: list[tuple[str, list[str]]] = []

    if families:
        rows = [f"- `{base}` → " + "、".join(f"`{n}`" for n in names) for base, names in sorted(families.items())]
        findings.append(("疑似同一项目的多份副本", rows + ["- 建议：选一个做主干，其余整目录移入 `_archive/`；或改成语义名。"]))
    if dupes:
        rows = []
        for (name, size), paths in dupes:
            rows.append(f"- `{name}`（{human_bytes(size)}）× {len(paths)}：")
            rows.extend(f"  - `{p}`" for p in paths[:6])
        findings.append(("跨项目重复文件（同名同大小，未做哈希）", rows))
    strays = [p for p in projects if p.stray_files]
    if strays:
        rows = [f"- `{p.name}`：{('、'.join('`' + s + '`' for s in p.stray_files[:6]))}"
                + (" 等" if len(p.stray_files) > 6 else "") for p in strays[:12]]
        if len(strays) > 12:
            rows.append(f"- …… 还有 {len(strays) - 12} 个项目也有散落文件")
        findings.append(("项目根有散落文件（应只有 7 个条目）", rows))
    no_readme = [p.name for p in projects if not p.has_readme]
    if no_readme:
        shown = "、".join(f"`{n}`" for n in no_readme[:12])
        more = f" …… 共 {len(no_readme)} 个" if len(no_readme) > 12 else ""
        findings.append(("缺 README（项目地图）",
                         [f"- {shown}{more}", "- 先补正在用的那几个，别一次补 50 个。"]))
    no_git = [p.name for p in projects
              if not p.has_git and p.idle_days is not None and p.idle_days <= 30]
    if no_git:
        shown = "、".join(f"`{n}`" for n in no_git)
        findings.append(("在用的项目还没进 git",
                         [f"- {shown}",
                          "- 跑 `hub.py git <项目>` 建仓库；要备份到 GitHub 再加 `--remote <地址> --push`。"]))
    nested = [p for p in projects if p.nested_same]
    if nested:
        findings.append(("同名目录自嵌套", [f"- `{p.nested_same}`" for p in nested]))
    idle = [p for p in projects if p.idle_days is not None and p.idle_days >= args.idle_days]
    if idle:
        idle.sort(key=lambda x: -x.idle_days)
        rows = [f"- `{p.name}`：{p.idle_days} 天" for p in idle[:12]]
        if len(idle) > 12:
            rows.append(f"- …… 共 {len(idle)} 个")
        findings.append((f"超过 {args.idle_days} 天没动（考虑搁置或归档）", rows))

    if is_portfolio(root):
        index_path = root / "PROJECTS.md"
        if not index_path.is_file():
            findings.insert(0, ("没有 PROJECTS.md（跨项目的总图）",
                                ["- 这是乱在项目之间的根因：你知道有哪些目录，但不知道哪个在推进。",
                                 "- 先跑 `hub.py index <根目录>` 生成空表，再逐行填三列。"]))
        else:
            index_text = index_path.read_text(encoding="utf-8-sig", errors="ignore")
            unlisted = [p.name for p in projects if p.name not in index_text]
            if unlisted:
                findings.append(("未登记在 PROJECTS.md", [f"- `{n}`" for n in unlisted]))
        loose = [c.name for c in root.iterdir()
                 if c.is_file() and c.name not in PORTFOLIO_FILES]
        if loose:
            findings.append(("项目群根有散落文件", [f"- `{n}`" for n in loose]))

    add("## 发现")
    add("")
    if not findings:
        add("没有发现结构性问题。")
    for title, rows in findings:
        add(f"### {title}")
        add("")
        lines.extend(rows)
        add("")

    add("## 建议的下一步")
    add("")
    if not findings:
        add("1. 保持现状；新文件先落 `_inbox/`，周末清空。")
    else:
        for i, (title, _) in enumerate(findings, 1):
            action = {
                "疑似同一项目的多份副本": "先人工确认哪份是主干，其余归档；不要自动合并。",
                "跨项目重复文件（同名同大小，未做哈希）": "确认后再删副本——本工具永不删除。",
                "项目根有散落文件（只该有 README 和那几个目录）": "按类型归位：代码 src/、模型 models/、数据 data/、结果 results/、临时 _tmp/。",
                "缺 README（项目地图）": "每个项目补一个 README：是什么 / 现在到哪 / 下一步。",
                "同名目录自嵌套": "把内层内容上提一级，删掉空壳（逐个项目确认）。",
                "没有 PROJECTS.md（跨项目的总图）": "跑 `hub.py index <根目录>` 生成空表，再填三列——这是唯一能回答『我现在该做哪个』的地方。",
                "在用的项目还没进 git": "挑最要紧的一个跑 `hub.py git`，推上 GitHub；大文件会被自动排除。",
            }.get(title, "逐项查看，确认后再动。")
            if title.startswith("超过"):
                action = "在 PROJECTS.md 里标为 paused，或整目录移入 `_archive/`。"
            if title.startswith("未登记"):
                action = "补进 `PROJECTS.md` 的表里：一句话 + 状态 + 下一步。"
            if title.startswith("项目群根有散落文件"):
                action = "移进 `_inbox/`，或归到对应项目。"
            add(f"{i}. **{title}** — {action}")
    add("")

    report = "\n".join(lines)
    print(report)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"\n[报告已写入] {out}", file=sys.stderr)

    if args.json:
        payload = {
            "root": str(root),
            "projects": [
                {
                    "name": p.name,
                    "files": p.files,
                    "bytes": p.bytes,
                    "last_day": p.last_day,
                    "idle_days": p.idle_days,
                    "has_readme": p.has_readme,
                    "has_git": p.has_git,
                    "stray_files": p.stray_files,
                    "nested_same": p.nested_same,
                }
                for p in projects
            ],
            "duplicate_project_families": families,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------

README_TEMPLATE = """# {name}

> 一句话：{one_liner}

## 现在到哪

- 状态：进行中 / 暂停 / 已完成
- 最近一次推进：{today}
- 卡在哪：

## 下一步

1.

## 目录约定

| 目录 | 放什么 | 进 git？ |
|---|---|---|
| `docs/` | 方案、笔记、报告、论文稿 | ✅ |
| `src/` | 代码：`python/` `matlab/` `fluent/` | ✅ |
| `tests/` | 测试、校验、对拍脚本 | ✅ |
| `models/` | 模型文件：mph / wbpj / cae / inp / scdocx | ❌ 走网盘 |
| `data/raw/` | 原始数据，只读 | ❌ |
| `data/processed/` | 清洗后的数据 | ✅ |
| `results/runs/` | 每次跑的输出（按 case 分） | ❌ |
| `results/figures/` | 出图 | ✅ |
| `results/tables/` | 汇总表 | ✅ |
| `archive/` | 冻结版本 `v1/ v2/` | ❌ |
| `_tmp/` | 临时文件，随时可清 | ❌ |

{type_note}
## 关键文件

| 文件 | 是什么 |
|---|---|
| | |
"""

TYPE_NOTES = {
    "code": "## 怎么跑\n\n```bash\n# 环境\n# 运行\n# 测试\n```\n",
    "sim": "## 仿真设置\n\n- 求解器 / 版本：\n- 网格：\n- 边界条件：\n- 结果在：\n",
    "data": "## 数据口径\n\n- 来源：\n- 清洗规则：\n- 指标定义：\n",
    "doc": "## 写作约定\n\n- 读者：\n- 篇幅 / 格式：\n- 素材在：\n",
    "generic": "",
}


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    created: list[str] = []
    root.mkdir(parents=True, exist_ok=True)

    wanted = list(PROJECT_DIRS)
    if not args.minimal:
        for parent, subs in SKELETON_SUBDIRS.items():
            wanted += [f"{parent}/{s}" for s in subs]
    for d in wanted:
        target = root / d
        if not target.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            created.append(d + "/")

    readme = root / "README.md"
    if readme.exists():
        print(f"[跳过] README.md 已存在，不覆盖：{readme}")
    else:
        readme.write_text(
            README_TEMPLATE.format(
                name=root.name,
                one_liner="（补一句这项目要解决什么）",
                today=datetime.now().strftime("%Y-%m-%d"),
                type_note=TYPE_NOTES.get(args.type, ""),
            ),
            encoding="utf-8",
        )
        created.append("README.md")

    if args.type == "code":
        gi = root / ".gitignore"
        if not gi.exists():
            gi.write_text(
                "# 运行残留\n__pycache__/\n*.pyc\n.venv/\n.idea/\n.vscode/\n\n"
                "# 过程与临时\n_tmp/\n\n# 大文件\n*.mph\n*.msh\n",
                encoding="utf-8",
            )
            created.append(".gitignore")

    if created:
        print(f"[完成] {root}")
        for c in created:
            print(f"  + {c}")
    else:
        print(f"[无变化] {root} 已经符合骨架")
    return 0


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=300)
    except FileNotFoundError:
        raise SystemExit("[错误] 没找到 git。先装：https://git-scm.com/download/win")


def _git_ok(proc: subprocess.CompletedProcess) -> bool:
    return proc.returncode == 0


def _exclude_big(root: Path, rel: str) -> None:
    """把超大文件记进本机的 .git/info/exclude，只影响这台电脑，不进仓库。"""
    info = root / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    exc = info / "exclude"
    line = "/" + rel.replace("\\", "/")
    existing = exc.read_text(encoding="utf-8", errors="ignore") if exc.exists() else ""
    if line in existing.splitlines():
        return
    with exc.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(line + "\n")


def _has_origin(root: Path) -> bool:
    proc = _git(["remote", "get-url", "origin"], root)
    return _git_ok(proc) and bool(proc.stdout.strip())


def _ensure_repo(root: Path) -> tuple[list[str], list[str]]:
    """建仓库 + 写忽略规则。返回（做了什么, 出了什么问题）。"""
    steps: list[str] = []
    problems: list[str] = []

    if (root / ".git").is_dir():
        steps.append("已经在 git 里")
    else:
        proc = _git(["init", "-b", "main"], root)
        if not _git_ok(proc):
            problems.append("建仓库失败：" + (proc.stderr or proc.stdout).strip()[:200])
            return steps, problems
        steps.append("建好本地仓库（main 分支）")

    # .gitignore 只追加，不覆盖你原来的
    gi = root / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE_BLOCK, encoding="utf-8")
        steps.append("新建 .gitignore（忽略大文件）")
    elif GITIGNORE_MARK not in gi.read_text(encoding="utf-8", errors="ignore"):
        with gi.open("a", encoding="utf-8") as f:
            f.write("\n\n" + GITIGNORE_BLOCK)
        steps.append("在 .gitignore 末尾补了忽略规则（原内容保留）")

    attrs = root / ".gitattributes"
    if not attrs.exists():
        attrs.write_text("* text=auto\n", encoding="utf-8")
        steps.append("新建 .gitattributes（统一换行符）")

    return steps, problems


def _commit_all(root: Path, message: str, max_mb: int,
                max_files: int = 2000, force: bool = False) -> tuple[int, list[str], list[str]]:
    """暂存 → 拦大文件 → 提交。返回（改动处数, 做了什么, 出了什么问题）。"""
    steps: list[str] = []
    problems: list[str] = []

    _git(["add", "-A"], root)

    big = []
    for rel in _git(["ls-files", "-z"], root).stdout.split("\0"):
        if not rel:
            continue
        try:
            size = (root / rel).stat().st_size
        except OSError:
            continue
        if size > max_mb * 1024 * 1024:
            big.append((rel, size))
    for rel, _ in big:
        _git(["reset", "-q", "--", rel], root)
        _exclude_big(root, rel)
    if big:
        names = "、".join(name for name, _ in big[:5]) + (" 等" if len(big) > 5 else "")
        problems.append(f"{len(big)} 个文件超过 {max_mb}MB，没存：{names}（已记进本机忽略清单）")

    # 文件数护栏：一次提交几千个文件，多半是选错了目录
    staged = [rel for rel in _git(["ls-files", "-z"], root).stdout.split("\0") if rel]
    if len(staged) > max_files and not force:
        _git(["reset", "-q"], root)
        problems.append(f"这个目录有 {len(staged)} 个文件，超过上限 {max_files}，"
                        f"多半是选错了目录，或者中间文件没清。确认要存就加 --force。")
        steps.append("没有提交（已中止，什么都没改）")
        return 0, steps, problems, True

    status = _git(["status", "--porcelain"], root).stdout.strip()
    count = len(status.splitlines()) if status else 0
    if count:
        proc = _git(["commit", "-m", message], root)
        if _git_ok(proc):
            steps.append(f"存了 {count} 处改动（本地）")
        else:
            problems.append("提交失败：" + (proc.stderr or proc.stdout).strip()[:300])
            count = 0
    else:
        steps.append("没有新改动")

    return count, steps, problems, False


def _push_error_hint(text: str) -> str:
    """把 git 的原始报错翻译成一句人话。"""
    low = text.lower()
    if "authentication failed" in low or "could not read username" in low or "terminal prompts disabled" in low:
        return "GitHub 没登录成功：在终端手动跑一次 git push，把登录做完"
    if "could not resolve host" in low or "unable to access" in low or "timed out" in low:
        return "网络不通，稍后再试"
    if "rejected" in low or "non-fast-forward" in low:
        return "线上有你本机没有的改动：先跑 git pull --rebase origin main"
    if "does not appear to be a git repository" in low or "not found" in low:
        return "仓库地址不对，或者线上仓库还没建"
    if "correct access rights" in low or "repository exists" in low:
        return "地址不对或没有权限（本地已经存好了）"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else "原因不明"


def _push(root: Path) -> str:
    """推送；返回空字符串表示成功，否则返回一句人话。"""
    if not _has_origin(root):
        return "还没接 GitHub"
    proc = _git(["push", "-u", "origin", "main"], root)
    if _git_ok(proc):
        return ""
    return _push_error_hint((proc.stderr or "") + "\n" + (proc.stdout or ""))


def _portfolio_root(root: Path) -> bool:
    """看形状判断这是不是「项目总根」——这种地方不该建仓库。"""
    if (root / "PROJECTS.md").is_file():
        return True
    return (root / "_inbox").is_dir() and (root / "_archive").is_dir()


def _refuse_portfolio(root: Path) -> bool:
    if not _portfolio_root(root):
        return False
    print("  ! 这是项目总根，不是单个项目。请对里面的某个项目执行，例如：")
    print(f'    hub.py save "{root}\\项目名"')
    return True


def _count_files(root: Path, limit: int) -> int:
    """数一下有多少文件，够 limit 就停，不用数完。"""
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        n += len(filenames)
        if n > limit:
            return n
    return n


def _too_many_files(root: Path, max_files: int) -> bool:
    n = _count_files(root, max_files)
    if n <= max_files:
        return False
    print(f"  ! 这个目录有 {n}+ 个文件，超过上限 {max_files}，多半是选错了目录。")
    print("    确认要存就加 --force；否则把路径换到具体的项目目录。")
    return True


def cmd_git(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"[错误] 不是目录: {root}", file=sys.stderr)
        return 2
    if _refuse_portfolio(root):
        return 2
    if not (root / ".git").is_dir() and not args.force and _too_many_files(root, args.max_files):
        return 2

    steps, problems = _ensure_repo(root)
    n, s2, p2, aborted = _commit_all(root, args.message or f"开始：{datetime.now():%Y-%m-%d %H:%M}",
                                     args.max_mb, args.max_files, args.force)
    steps += s2
    problems += p2
    if aborted:
        print(f"项目：{root}")
        for s in steps:
            print(f"  ✓ {s}")
        for p in problems:
            print(f"  ! {p}")
        return 1

    if args.remote:
        cur = _git(["remote", "get-url", "origin"], root)
        if _git_ok(cur) and cur.stdout.strip():
            if cur.stdout.strip() != args.remote:
                _git(["remote", "set-url", "origin", args.remote], root)
                steps.append("Origin 地址改成新的")
        else:
            _git(["remote", "add", "origin", args.remote], root)
            steps.append("记下 GitHub 地址（origin）")

    if args.push:
        err = _push(root)
        if err:
            problems.append("上传没成功：" + err)
        else:
            steps.append("已上传 GitHub")

    print(f"项目：{root}")
    for s in steps:
        print(f"  ✓ {s}")
    for p in problems:
        print(f"  ! {p}")
    if not _has_origin(root):
        print("")
        print("还没接 GitHub。接上以后，每次收工只要跑一次 save：")
        print(f'  hub.py git "{root}" --remote https://github.com/你/仓库.git --push')
    return 0


def cmd_save(args: argparse.Namespace) -> int:
    """推进项目时的"存一下"：本地存档 + 有地址就顺手传上去。"""
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"[错误] 不是目录: {root}", file=sys.stderr)
        return 2
    if _refuse_portfolio(root):
        return 2
    if not (root / ".git").is_dir() and not args.force and _too_many_files(root, args.max_files):
        return 2

    steps, problems = _ensure_repo(root)
    if problems:
        for s in steps:
            print(f"  ✓ {s}")
        for p in problems:
            print(f"  ! {p}")
        return 2

    n, s2, p2, aborted = _commit_all(root, args.message or f"存档：{datetime.now():%Y-%m-%d %H:%M}",
                                     args.max_mb, args.max_files, args.force)
    steps += s2
    problems += p2
    if aborted:
        print(f"项目：{root.name}")
        for s in steps:
            print(f"  ✓ {s}")
        for p in problems:
            print(f"  ! {p}")
        return 1

    print(f"项目：{root.name}")
    for s in steps:
        print(f"  ✓ {s}")
    for p in problems:
        print(f"  ! {p}")

    if _has_origin(root) and not args.local:
        err = _push(root)
        if err:
            print("  ! 上传失败：" + err)
            print("")
            print("本地已经存好了，联网后再跑一次就能补上去：")
            print(f'  hub.py sync "{root}"')
        else:
            print("  ✓ 已上传 GitHub")
    elif args.local:
        print("  ✓ 只存本地（--local，没上传）")
    else:
        print("  ! 这次只存在本机（还没接 GitHub，接法见 reference/git-github.md）")

    if not args.no_refresh:
        _refresh_boards(root)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """只补传：把本地已有的存档推到 GitHub。"""
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"[错误] 不是目录: {root}", file=sys.stderr)
        return 2
    if not (root / ".git").is_dir():
        print("  ! 这个项目还没有存档，先跑 save")
        return 1
    if not _has_origin(root):
        print("  ! 还没接 GitHub，先按 reference/git-github.md 接一次")
        return 1

    err = _push(root)
    if err:
        print("  ! 还是传不上去：" + err)
        return 1
    print("  ✓ 已同步到 GitHub")
    return 0


# 提交后自动推送：装了它，连手动 git commit 也会自动传
HOOK_MARK = "# project-hub: 每次提交后自动推送"
HOOK_BODY = """#!/bin/sh
# project-hub: 每次提交后自动推送（hub.py hook <项目> off 可关闭）
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=10 push -q origin HEAD >/dev/null 2>&1 || true
"""


def cmd_hook(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not (root / ".git").is_dir():
        print("  ! 这个项目还没有仓库，先跑一次 save")
        return 1

    hook = root / ".git" / "hooks" / "post-commit"
    current = hook.exists() and HOOK_MARK in hook.read_text(encoding="utf-8", errors="ignore")

    if args.action == "status":
        print("  ✓ 已开启：每次提交后自动推送" if current else "  · 未开启")
        return 0 if current else 1

    if args.action == "on":
        if hook.exists() and not current:
            print("  ! 这里已经有一个别的提交后钩子，不覆盖。")
            return 1
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(HOOK_BODY, encoding="utf-8", newline="\n")
        print("  ✓ 已开启：以后每次提交都会自动推送")
        print("    断网时静默失败，不影响提交；联网后跑一次 save 或 sync 即可补上。")
        return 0

    # off
    if not hook.exists():
        print("  · 本来就没开")
        return 0
    if not current:
        print("  ! 这个钩子不是 project-hub 装的，不动它")
        return 1
    hook.unlink()
    print("  ✓ 已关闭")
    return 0


# --------------------------------------------------------------------------
# publish：在 GitHub 上建私有仓库并推上去
# --------------------------------------------------------------------------

REPO_NAME_OK = re.compile(r"^[A-Za-z0-9._-]+$")


def _github_credential() -> tuple[str, str]:
    """从 Windows 凭据里取 GitHub 的登录名和令牌（取不到就返回空）。"""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", ""
    user = token = ""
    for line in proc.stdout.splitlines():
        if line.startswith("username="):
            user = line[len("username="):]
        elif line.startswith("password="):
            token = line[len("password="):]
    return user, token


def _api(method: str, url: str, token: str, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "project-hub",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}"), None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(raw).get("message", raw)
        except json.JSONDecodeError:
            msg = raw
        return None, f"{exc.code} {msg}"


def cmd_publish(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"[错误] 不是目录: {root}", file=sys.stderr)
        return 2
    if _refuse_portfolio(root):
        return 2

    if _has_origin(root):
        url = _git(["remote", "get-url", "origin"], root).stdout.strip()
        print(f"  ! 这个项目已经接了 GitHub：{url}")
        print("    想换地址请用 git ... --remote <新地址>")
        return 0

    # 还没建仓库就先存档，省得用户多跑一次
    # （放在 dry-run 之后，干跑不改任何东西）
    name = args.name or root.name
    name = name.strip().replace(" ", "-")
    if not REPO_NAME_OK.match(name):
        print(f"  ! 仓库名只能用英文字母、数字、点、下划线、减号，现在是「{name}」")
        print(f'    换一个：hub.py publish "{root}" --name my-project')
        return 2

    user, token = _github_credential()
    if not token:
        print("  ! 没找到 GitHub 登录凭据。先在终端跑一次任意 git push，把登录做完")
        return 1

    private = not args.public
    desc = args.desc or "由 project-hub 创建"

    if args.dry_run:
        print(f"  · 将创建仓库：{user}/{name}（{'私有' if private else '公开'}）")
        print(f"  · 然后推到：https://github.com/{user}/{name}.git")
        return 0

    # 还没建仓库就先存档，省得用户多跑一次
    if not (root / ".git").is_dir():
        if not args.force and _too_many_files(root, args.max_files):
            return 2
        steps, problems = _ensure_repo(root)
        if problems:
            for p in problems:
                print(f"  ! {p}")
            return 2
        _, s2, p2, aborted = _commit_all(root, f"开始：{datetime.now():%Y-%m-%d %H:%M}",
                                         args.max_mb, args.max_files, args.force)
        for s in steps + s2:
            print(f"  ✓ {s}")
        for p in p2:
            print(f"  ! {p}")
        if aborted:
            return 1

    repo, err = _api("POST", "https://api.github.com/user/repos", token, {
        "name": name, "private": private, "description": desc, "auto_init": False,
    })
    if err:
        print(f"  ! 建仓库失败：{err}")
        if "already exists" in err.lower():
            print("    换个名字：--name <别的名字>；或用 --remote 接现有仓库")
        return 1

    clone_url = repo.get("clone_url") or f"https://github.com/{user}/{name}.git"
    html_url = repo.get("html_url") or f"https://github.com/{user}/{name}"
    print(f"  ✓ 已在 GitHub 建好仓库：{html_url}（{'私有' if private else '公开'}）")

    _git(["remote", "add", "origin", clone_url], root)
    print("  ✓ 已把地址记到本地（origin）")

    err = _push(root)
    if err:
        print(f"  ! 上传失败：{err}")
        print(f"    仓库已经建好了，联网后跑：hub.py sync \"{root}\"")
        return 1
    print("  ✓ 已上传 GitHub")
    print("")
    print(f"  仓库地址：{html_url}")
    return 0


# --------------------------------------------------------------------------
# dashboard：浏览器看板
# --------------------------------------------------------------------------

DASH_HEAD = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>项目工作台</title>
<style>
:root{
  --bg:#090c11;--panel:#11161f;--line:#1f2733;--fg:#e8eef6;--muted:#7d8899;--dim:#5a6574;
  --green:#3ecf8e;--amber:#f0b429;--blue:#5aa9ff;--purple:#a78bfa;--red:#ff6b6b;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0;color:var(--fg);font:14px/1.6 "Segoe UI","Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif;
  background:
    radial-gradient(1100px 520px at 15% -12%,#172233 0%,transparent 60%),
    radial-gradient(900px 480px at 92% -8%,#1c1730 0%,transparent 55%),
    var(--bg);
  min-height:100vh;
}
header{padding:34px 40px 22px}
.hero{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;flex-wrap:wrap;max-width:1560px}
.brand{display:flex;align-items:center;gap:14px}
.logo{width:44px;height:44px;border-radius:13px;display:grid;place-items:center;font-size:20px;
  background:linear-gradient(135deg,#5aa9ff,#a78bfa);color:#0b0f16;font-weight:800;box-shadow:0 8px 24px rgba(90,169,255,.25)}
h1{margin:0;font-size:22px;font-weight:650;letter-spacing:.2px}
.sub{color:var(--muted);font-size:12px;margin-top:4px}
.stats{display:flex;gap:10px;flex-wrap:wrap}
.stat{min-width:96px;padding:10px 14px;border:1px solid var(--line);border-radius:12px;background:linear-gradient(180deg,rgba(24,31,42,.9),rgba(15,20,28,.9))}
.stat b{display:block;font-size:24px;font-weight:700;line-height:1.15}
.stat span{font-size:11px;color:var(--muted);letter-spacing:.06em}
.stat.doing b{color:var(--green)} .stat.warn b{color:var(--amber)} .stat.blue b{color:var(--blue)}
.hint{margin:16px 40px 0;padding:11px 15px;border:1px solid rgba(240,180,41,.28);border-radius:10px;
  background:rgba(240,180,41,.07);color:#f3c65b;font-size:13px}
.bar{position:sticky;top:0;z-index:20;display:flex;gap:10px;align-items:center;flex-wrap:wrap;
  padding:14px 40px;background:rgba(9,12,17,.78);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.search{position:relative}
.search input{width:268px;background:#0f141c;border:1px solid var(--line);color:var(--fg);border-radius:9px;
  padding:8px 12px 8px 34px;font-size:13px;outline:none;transition:.15s}
.search input:focus{border-color:rgba(90,169,255,.6);box-shadow:0 0 0 3px rgba(90,169,255,.12)}
.search::before{content:"⌕";position:absolute;left:12px;top:50%;transform:translateY(-52%);color:var(--dim);font-size:15px}
button{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:999px;
  padding:6px 14px;cursor:pointer;font-size:12px;transition:.15s;font-family:inherit}
button:hover{color:var(--fg);border-color:#33404f}
button.on{background:rgba(90,169,255,.12);color:#9cc6ff;border-color:rgba(90,169,255,.45)}
main{padding:10px 40px 80px;max-width:1560px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.section{grid-column:1/-1;display:flex;align-items:center;gap:12px;margin:22px 0 0;
  color:var(--muted);font-size:11px;letter-spacing:.12em;text-transform:uppercase}
.section::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,var(--line),transparent)}
.card{position:relative;display:flex;flex-direction:column;gap:12px;padding:17px 17px 15px;
  background:linear-gradient(180deg,rgba(24,31,42,.92),rgba(15,20,28,.92));
  border:1px solid var(--line);border-radius:16px;overflow:hidden;
  transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent,transparent)}
.card:hover{transform:translateY(-3px);border-color:#2f3c4e;box-shadow:0 16px 36px rgba(0,0,0,.45)}
.card.s-doing{--accent:var(--green)} .card.s-pause{--accent:var(--amber)} .card.s-done{--accent:var(--blue)}
.head{display:flex;gap:12px;align-items:flex-start}
.mono{width:36px;height:36px;flex:none;border-radius:11px;display:grid;place-items:center;
  font-weight:700;font-size:15px;background:hsla(var(--h,210),68%,58%,.13);color:hsl(var(--h,210),72%,72%);text-transform:uppercase}
.s-doing .mono{background:linear-gradient(135deg,rgba(62,207,142,.28),rgba(62,207,142,.05));color:var(--green)}
.s-pause .mono{background:linear-gradient(135deg,rgba(240,180,41,.26),rgba(240,180,41,.05));color:var(--amber)}
.s-done .mono{background:linear-gradient(135deg,rgba(90,169,255,.26),rgba(90,169,255,.05));color:var(--blue)}
.ttl{min-width:0;flex:1}
.pill{font-size:10.5px;padding:2px 9px;border-radius:999px;border:1px solid;white-space:nowrap;flex:none;margin-top:2px}
.p-doing{color:var(--green);border-color:rgba(62,207,142,.35);background:rgba(62,207,142,.1)}
.p-pause{color:var(--amber);border-color:rgba(240,180,41,.32);background:rgba(240,180,41,.09)}
.p-done{color:var(--blue);border-color:rgba(90,169,255,.32);background:rgba(90,169,255,.09)}
.name{font-size:15.5px;font-weight:650;line-height:1.35;word-break:break-all}
.one{color:var(--muted);font-size:12px;margin-top:3px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.one.ph{color:var(--dim);font-style:italic}
.next{display:flex;gap:8px;align-items:flex-start;font-size:12.5px;color:var(--muted);
  background:rgba(255,255,255,.028);border:1px solid rgba(255,255,255,.04);border-radius:10px;padding:9px 11px}
.next .arrow{color:var(--accent,var(--dim));font-weight:700;flex:none}
.next b{color:#cfd9e6;font-weight:500}
.next b.ph{color:var(--dim);font-style:italic;font-weight:400}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:auto}
.tag{font-size:10.5px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 9px;letter-spacing:.02em}
.tag.ok{color:var(--green);border-color:rgba(62,207,142,.3);background:rgba(62,207,142,.07)}
.tag.warn{color:var(--amber);border-color:rgba(240,180,41,.28);background:rgba(240,180,41,.06)}
.dirs{margin-top:2px}
.dirs summary{cursor:pointer;font-size:11px;color:var(--dim);list-style:none;user-select:none}
.dirs summary::-webkit-details-marker{display:none}
.dirs summary::before{content:"▸ ";color:var(--dim)}
.dirs[open] summary::before{content:"▾ "}
.dirlist{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.dirlist span{font-size:10.5px;color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:1px 7px}
.empty{color:var(--dim);text-align:center;padding:90px 0;display:none;font-size:13px}
.detail{display:none;max-width:1000px;margin:0 auto;padding:6px 0 80px}
.detail.on{display:block}
.back{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:8px;padding:6px 13px;margin-bottom:20px;cursor:pointer}
.back:hover{color:var(--fg);border-color:#33404f}
.detail h2{margin:0 0 8px;font-size:26px;font-weight:650;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.detail .dsub{color:var(--muted);font-size:13px;margin:0 0 6px}
.dblock{border-top:1px solid var(--line);padding:20px 0}
.dblock h3{margin:0 0 10px;font-size:11px;color:var(--dim);letter-spacing:.14em;text-transform:uppercase;font-weight:600}
.dblock p{margin:0;line-height:1.85;color:#cfd9e6;font-size:14px}
.dirmap{list-style:none;padding:0;margin:0;display:grid;gap:8px}
.dirmap li{display:flex;justify-content:space-between;gap:14px;padding:9px 13px;border:1px solid var(--line);border-radius:9px;background:rgba(255,255,255,.02)}
.dirmap b{font-weight:600;font-size:13.5px}
.dirmap span{color:var(--muted);font-size:12px;text-align:right}
.dirbox{margin-bottom:14px;border:1px solid var(--line);border-radius:11px;overflow:hidden;background:rgba(255,255,255,.015)}
.dirhead{display:flex;justify-content:space-between;gap:12px;padding:11px 14px;background:rgba(255,255,255,.03);border-bottom:1px solid var(--line)}
.dirhead b{font-size:13.5px;font-weight:650}
.dirhead span{color:var(--muted);font-size:11.5px;text-align:right}
.filelist{list-style:none;margin:0;padding:4px 0}
.filelist li{display:flex;align-items:center;gap:10px;padding:5px 14px;font-size:12.5px}
.filelist li:hover{background:rgba(255,255,255,.035)}
.filelist .ic{width:18px;flex:none;font-size:12px;opacity:.85}
.filelist .fn{flex:1;color:#cfd9e6;word-break:break-all}
.filelist .fm{color:var(--dim);font-size:11px;white-space:nowrap}
.moreitems{padding:6px 14px 10px;color:var(--dim);font-size:11px}
.outputs{list-style:none;padding:0;margin:0;display:grid;gap:8px}
.outputs li{display:flex;flex-direction:column;gap:2px;padding:10px 13px;border:1px solid var(--line);border-radius:9px;background:rgba(90,169,255,.04)}
.outputs a{color:#9cc6ff;font-size:13.5px;font-weight:600;text-decoration:none}
.outputs a:hover{text-decoration:underline}
.outputs span{color:var(--dim);font-size:11px;word-break:break-all}
.keyfiles{list-style:none;padding:0;margin:0;display:grid;gap:9px}
.keyfiles li{font-size:13.5px;color:#cfd9e6;padding-left:14px;position:relative;line-height:1.7}
.keyfiles li::before{content:"\00b7";position:absolute;left:2px;color:var(--dim)}
code{background:rgba(255,255,255,.06);padding:1px 5px;border-radius:4px;font-size:12px;color:#9cc6ff}
.more{margin-top:2px;font-size:11px;color:var(--dim)}
.card:hover .more{color:var(--blue)}
body.detail-mode .bar{display:none}
body.detail-mode .hint{display:none}
@media(max-width:640px){
  header,.bar,main{padding-left:18px;padding-right:18px}
  .search input{width:100%}
  .grid{grid-template-columns:1fr}
}
</style></head><body>
<header><div class="hero">
  <div class="brand">
    <div class="logo">◈</div>
    <div><h1>项目工作台</h1><div class="sub">__ROOT__ &nbsp;·&nbsp; __NOW__ &nbsp;·&nbsp; __N__ 个项目 / __SIZE__</div></div>
  </div>
  <div class="stats">__STATS__</div>
</div></header>
__HINT__
<div class="bar">
  <div class="search"><input id="q" placeholder="搜项目名 / 一句话"></div>
  <button data-f="all" class="on">全部</button>
  <button data-f="doing">进行中</button>
  <button data-f="pause">暂停</button>
  <button data-f="done">已完成</button>
  <button data-f="nobackup">未备份</button>
</div>
<main><div class="grid" id="grid">
__CARDS__
</div><div class="empty" id="empty">没有匹配的项目</div>
__PANELS__
</main>
<script>
const q=document.getElementById('q'),empty=document.getElementById('empty');
let f='all';
document.querySelectorAll('.bar button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.bar button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');f=b.dataset.f;render();
});
q.oninput=render;
function render(){
  const t=q.value.trim().toLowerCase();let shown=0;
  document.querySelectorAll('.card').forEach(c=>{
    const d=c.dataset;
    const hitT=!t||d.name.toLowerCase().includes(t)||d.one.toLowerCase().includes(t);
    let hitF=true;
    if(f==='doing')hitF=d.status==='doing';
    else if(f==='pause')hitF=d.status==='pause';
    else if(f==='done')hitF=d.status==='done';
    else if(f==='nobackup')hitF=d.git==='0';
    const ok=hitT&&hitF;c.style.display=ok?'':'none';if(ok)shown++;
  });
  empty.style.display=shown?'none':'block';
}
function openDetail(id){
  document.getElementById('grid').style.display='none';
  document.querySelectorAll('.detail').forEach(d=>d.classList.remove('on'));
  const el=document.getElementById(id); if(el)el.classList.add('on');
  document.body.classList.add('detail-mode');
  window.scrollTo(0,0);
}
function closeDetail(){
  document.querySelectorAll('.detail').forEach(d=>d.classList.remove('on'));
  document.getElementById('grid').style.display='';
  document.body.classList.remove('detail-mode');
  window.scrollTo(0,0);
}
</script></body></html>
"""

DASH_CARD = """<article class="card __SCLS__" style="--h:__HUE__;cursor:pointer" onclick="openDetail('__TARGET__')" data-name="__NAME__" data-one="__ONE__" data-members="__MEMBERS__" data-status="__SKEY__" data-git="__GIT__">
  <div class="head">
    <div class="mono">__MONO__</div>
    <div class="ttl"><div class="name">__NAME__</div><div class="one __ONECLS__">__ONE__</div></div>
    __PILL__
  </div>
  <div class="next"><span class="arrow">→</span><b class="__NEXTCLS__">__NEXT__</b></div>
  <div class="tags"><span class="tag">__NDIR__ 个目录</span><span class="tag">__SIZE__</span><span class="tag">__IDLE__</span><span class="tag __GTAG__">__GLABEL__</span></div>
  <div class="more">点开看详情 →</div>
</article>"""

STATUS_STYLE = {
    "进行中": ("doing", "s-doing"),
    "暂停": ("pause", "s-pause"),
    "已完成": ("done", "s-done"),
}


def _dash_card(p: dict, target: str) -> str:
    status = (p["status"] or "").strip()
    skey, scls = STATUS_STYLE.get(status, ("todo", "s-todo"))
    one = (p["one"] or "").strip()
    nxt = (p["next"] or "").strip()
    esc = lambda s: html.escape(s, quote=True)
    mono = p["name"][:1] if p["name"] else "?"
    hue = sum(ord(c) for c in p["name"]) % 360
    pill = f'<span class="pill p-{skey}">{esc(status)}</span>' if status else ""
    members = [m.name for m in p["members"]]
    dirlist = "".join(f"<span>{esc(m)}</span>" for m in members)
    return (DASH_CARD
            .replace("__TARGET__", target)
            .replace("__HUE__", str(hue))
            .replace("__PILL__", pill)
            .replace("__MONO__", esc(mono))
            .replace("__NAME__", esc(p["name"]))
            .replace("__ONE__", esc(one or "还没写一句话"))
            .replace("__ONECLS__", "" if one else "ph")
            .replace("__NEXT__", esc(nxt or "还没定下一步"))
            .replace("__NEXTCLS__", "" if nxt else "ph")
            .replace("__SKEY__", skey)
            .replace("__SCLS__", scls)
            .replace("__SIZE__", human_bytes(p["bytes"]))
            .replace("__IDLE__", _idle_label(_idle_days(p["last"])))
            .replace("__NDIR__", str(len(members)))
            .replace("__DIRLIST__", dirlist)
            .replace("__MEMBERS__", esc(" ".join(members)))
            .replace("__GIT__", "1" if p["git"] else "0")
            .replace("__GTAG__", "ok" if p["git"] else "warn")
            .replace("__GLABEL__", "已备份" if p["git"] else "未备份"))


KEY_EXT = {".md": 0, ".docx": 1, ".pdf": 1, ".pptx": 1, ".xlsx": 1,
           ".py": 2, ".m": 2, ".ipynb": 2, ".scdocx": 3, ".mph": 3,
           ".wbpj": 3, ".cas": 3, ".dat": 3, ".csv": 4, ".png": 5, ".jpg": 5}


def _dir_rows(path: Path, folder_limit: int = 5, file_limit: int = 8) -> tuple[list[str], int]:
    """列一个目录的顶层条目：先文件夹，再按"重要性"挑几个关键文件。"""
    try:
        items = list(path.iterdir())
    except OSError:
        return [], 0
    folders = sorted([p for p in items if p.is_dir()], key=lambda p: p.name.lower())
    files = [p for p in items if not p.is_dir()]
    files.sort(key=lambda p: (KEY_EXT.get(p.suffix.lower(), 9), p.name.lower()))

    shown = folders[:folder_limit] + files[:file_limit]
    total = len(items)
    rows: list[str] = []
    for p in shown:
        try:
            st = p.stat()
        except OSError:
            continue
        day = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")
        if p.is_dir():
            try:
                n = len(list(p.iterdir()))
            except OSError:
                n = 0
            icon, meta = "📁", f"{n} 项"
        else:
            icon, meta = "📄", human_bytes(st.st_size)
        rows.append(
            f'<li><span class="ic">{icon}</span>'
            f'<span class="fn">{html.escape(p.name)}</span>'
            f'<span class="fm">{meta} · {day}</span></li>'
        )
    return rows, max(0, total - len(rows))


def _detail_section(pid: str, p: dict, det: dict) -> str:
    esc = html.escape
    status = (p["status"] or "").strip()
    skey, _ = STATUS_STYLE.get(status, ("todo", ""))
    pill = f'<span class="pill p-{skey}">{esc(status)}</span>' if status else ""
    one = (p["one"] or "").strip()
    members = p["members"]
    boxes = []
    for m in members:
        rows, more = _dir_rows(m.path)
        exts = "、".join(f"{e}×{n}" for e, n in m.exts)
        more_html = f'<div class="moreitems">还有 {more} 项没列</div>' if more else ""
        boxes.append(
            f'<div class="dirbox"><div class="dirhead"><b>{esc(m.name)}</b>'
            f'<span>{m.files} 文件 · {human_bytes(m.bytes)} · {exts or "—"}</span></div>'
            f'<ul class="filelist">{"".join(rows)}</ul>{more_html}</div>'
        )
    dirs_html = "".join(boxes)
    kfs = det.get("关键文件") or []
    kf_html = "".join(f"<li>{_inline_md(k)}</li>" for k in kfs) or "<li>（还没写关键文件）</li>"

    out_items = det.get("主要产出") or []
    out_html = ""
    for item in out_items:
        label, _, path = item.partition("→")
        label = label.strip()
        path = path.strip()
        if not path:
            continue
        url = "file:///" + path.replace("\\", "/").replace(" ", "%20")
        out_html += (
            f'<li><a href="{html.escape(url, quote=True)}" target="_blank">{esc(label or path)}</a>'
            f'<span>{esc(path)}</span></li>'
        )
    out_block = ""
    if out_html:
        out_block = f'<div class="dblock"><h3>主要产出</h3><ul class="outputs">{out_html}</ul></div>'

    def block(title: str, text: str) -> str:
        return f'<div class="dblock"><h3>{title}</h3><p>{_inline_md(text or "（还没填）")}</p></div>'

    return (f'<section class="detail" id="{pid}">'
            f'<button class="back" onclick="closeDetail()">← 返回看板</button>'
            f'<h2>{esc(p["name"])} {pill}</h2>'
            f'<p class="dsub">{_inline_md(one)} · {len(members)} 个目录 · '
            f'{human_bytes(p["bytes"])} · {_idle_label(_idle_days(p["last"]))}动过</p>'
            + block("做什么", det.get("做什么", ""))
            + block("目的", det.get("目的", ""))
            + block("流程", det.get("流程", ""))
            + f'<div class="dblock"><h3>目录与文件（{len(members)} 个目录）</h3>{dirs_html}</div>'
            + out_block
            + f'<div class="dblock"><h3>关键文件</h3><ul class="keyfiles">{kf_html}</ul></div>'
            + '</section>')


def cmd_dashboard(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"[错误] 不是目录: {root}", file=sys.stderr)
        return 2

    projects = list_projects(root) if is_portfolio(root) else [scan_project(root)]
    index = _read_index(root)

    if index:
        projs = _build_projects(root, index)
    else:
        projs = [{
            "name": p.name, "one": "", "status": "", "next": "",
            "members": [p], "files": p.files, "bytes": p.bytes,
            "last": p.last, "git": p.has_git,
        } for p in projects]

    cards = []
    panels = []
    details = _read_details(root)
    counter = {"i": 0}

    def emit(items: list[dict]) -> None:
        for p in items:
            tid = f"d-{counter['i']}"
            counter["i"] += 1
            cards.append(_dash_card(p, tid))
            panels.append(_detail_section(tid, p, details.get(p["name"], {})))

    for label in ("进行中", "暂停", "已完成"):
        group = sorted([p for p in projs if (p["status"] or "").strip() == label],
                       key=lambda p: p["last"], reverse=True)
        if not group:
            continue
        cards.append(f'<div class="section">{label}（{len(group)}）</div>')
        emit(group)
    others = [p for p in projs if (p["status"] or "").strip() not in ("进行中", "暂停", "已完成")]
    if others:
        cards.append(f'<div class="section">未标状态（{len(others)}）</div>')
        emit(others)

    doing_n = sum(1 for p in projs if (p["status"] or "").strip() == "进行中")
    n_dirs = sum(len(p["members"]) for p in projs)
    total = sum(p["bytes"] for p in projs)
    no_git = sum(1 for p in projs if not p["git"])
    strays = [p for p in projects if p.stray_files]

    def stat(num: int, label: str, cls: str = "") -> str:
        return f'<div class="stat {cls}"><b>{num}</b><span>{label}</span></div>'

    stats = "".join([
        stat(len(projs), "项目"),
        stat(doing_n, "进行中", "doing"),
        stat(n_dirs, "目录", "blue"),
        stat(no_git, "未备份", "warn"),
    ])

    hint = ""
    if not index:
        hint = ("<div class='hint'>还没有 PROJECTS.md（总表）。先跑 <b>hub.py index</b>，"
                "再把「一句话 / 状态 / 下一步 / 包含目录」填上，这张看板才有内容。</div>")
    elif strays:
        hint = f"<div class='hint'>{len(strays)} 个目录的根上还有散落文件，跑 hub.py check 看看。</div>"

    page = (DASH_HEAD
            .replace("__ROOT__", html.escape(str(root)))
            .replace("__NOW__", f"{datetime.now():%Y-%m-%d %H:%M}")
            .replace("__N__", str(len(projs)))
            .replace("__SIZE__", human_bytes(total))
            .replace("__STATS__", stats)
            .replace("__HINT__", hint)
            .replace("__CARDS__", "\n".join(cards))
            .replace("__PANELS__", "\n".join(panels)))

    out = Path(args.out) if args.out else (root / "_reports" / "dashboard.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")

    # 项目自己的 results/ 里如果有一份看板，跟着更新
    for p in projs:
        for m in p["members"]:
            tgt = m.path / "results" / "dashboard.html"
            try:
                if tgt.is_file() and tgt.resolve() != out.resolve():
                    shutil.copyfile(out, tgt)
            except OSError:
                pass

    print(f"  ✓ 看板已生成：{out}")
    print(f"    {len(projs)} 个项目卡片 / 共 {n_dirs} 个目录")
    if args.open:
        try:
            os.startfile(str(out))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 自动打开失败，手动双击也行：{exc}")
    else:
        print(f"    双击打开，或把路径拖进浏览器；加 --open 可以直接弹出来")
    return 0


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------

INDEX_TEMPLATE = """# 项目总图

> 更新于：{today} ｜ 进行中不超过 3 个

| 项目 | 一句话 | 状态 | 下一步 | 包含目录 |
|---|---|---|---|---|
{rows}

## 状态约定

- 状态只写 `进行中` / `暂停` / `已完成`，三选一。
- 「一句话」写它解决什么问题，别写「各种资料」。
- 「下一步」写一个今天就能动手的具体动作。
- **同一个课题的多个目录，合成一行**，目录名都写在最后一列（英文逗号分隔）。
- 新项目：先建目录，再登记到这。
"""


def cmd_index(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"[错误] 不是目录: {root}", file=sys.stderr)
        return 2
    target = root / "PROJECTS.md"
    if target.exists() and not args.force:
        print(f"[跳过] 已存在，不覆盖：{target}")
        print("       要重建请加 --force（旧文件会被覆盖，先备份）")
        return 0

    projects = sorted(list_projects(root), key=lambda p: (-p.last, p.name.lower()))
    rows = "\n".join(
        f"| `{p.name}` | （待填） | 待填 | | `{p.name}` |" for p in projects
    ) or "| | | | | |"
    target.write_text(INDEX_TEMPLATE.format(today=datetime.now().strftime("%Y-%m-%d"), rows=rows),
                      encoding="utf-8")
    print(f"[完成] 生成 {target}，共 {len(projects)} 行")
    print("下一步：把「一句话」「状态」「下一步」三列填掉——只填还在用的项目，其余标 `暂停`。")
    return 0


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------

def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"[错误] 不是目录: {root}", file=sys.stderr)
        return 2

    violations: list[str] = []
    warnings: list[str] = []

    if is_portfolio(root):
        for c in sorted(root.iterdir()):
            if c.is_file() and c.name not in PORTFOLIO_FILES:
                violations.append(f"项目群根不应有文件：`{c.name}`")
            elif c.is_dir() and c.name.startswith("."):
                continue
        index_path = root / "PROJECTS.md"
        if not index_path.is_file():
            violations.append("缺 PROJECTS.md（项目总图）")
            index = ""
        else:
            index = index_path.read_text(encoding="utf-8-sig", errors="ignore")
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and child.name not in PORTFOLIO_DIRS:
                if index and child.name not in index:
                    warnings.append(f"项目未登记在 PROJECTS.md：`{child.name}`")
        inbox = root / "_inbox"
        if inbox.is_dir():
            n = sum(1 for _ in inbox.rglob("*") if _.is_file())
            if n > 0:
                warnings.append(f"_inbox 有 {n} 个文件待归位")
    else:
        for c in sorted(root.iterdir()):
            if c.is_file() and c.name not in PROJECT_FILES + PROJECT_TOLERATED_FILES \
                    and c.suffix.lower() not in PROJECT_TOLERATED_EXT:
                violations.append(f"项目根不应有文件：`{c.name}`")
            elif c.is_dir() and c.name in PROJECT_DIRS + PROJECT_TOLERATED_DIRS:
                continue
            elif c.is_dir():
                violations.append(f"项目根不应有目录：`{c.name}`")
        if not (root / "README.md").is_file():
            violations.append("缺 README.md（项目地图）")
        archive = root / "archive"
        if archive.is_dir() and any(archive.iterdir()) and not (archive / "MANIFEST.md").is_file():
            warnings.append("archive 有内容但没有 MANIFEST.md（记不住各版差别）")
        tmp = root / "_tmp"
        if tmp.is_dir():
            old = [f for f in walk_files(tmp)
                   if datetime.now().timestamp() - f.stat().st_mtime > args.tmp_days * 86400]
            if old:
                warnings.append(f"_tmp 有 {len(old)} 个文件超过 {args.tmp_days} 天，该清了")

    for v in violations[:15]:
        print(f"[违规] {v}")
    if len(violations) > 15:
        print(f"[违规] …… 还有 {len(violations) - 15} 条，同类问题")
    for w in warnings[:10]:
        print(f"[提醒] {w}")
    if len(warnings) > 10:
        print(f"[提醒] …… 还有 {len(warnings) - 10} 条")
    if violations or warnings:
        print("")
        print(f"[合计] {len(violations)} 条违规 / {len(warnings)} 条提醒")
    else:
        print("[通过] 结构没问题")
    return 1 if violations else 0


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------

def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def cmd_apply(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan).resolve()
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[错误] 读不了计划文件 {plan_path}: {exc}", file=sys.stderr)
        return 2

    root = Path(args.root or data.get("root") or ".").resolve()
    moves = data.get("moves") or []
    if not moves:
        print("[空] 计划里没有 moves")
        return 0

    print(f"根目录：{root}")
    print(f"计划：{len(moves)} 项；模式：{'执行' if args.apply else 'dry-run'}")
    print("")
    ok = skipped = 0
    for i, m in enumerate(moves, 1):
        try:
            src = (root / m["from"]).resolve()
            dst = (root / m["to"]).resolve()
        except KeyError:
            print(f"{i:>3}. [跳过] 条目缺 from/to：{m}")
            skipped += 1
            continue
        if not _inside(src, root) or not _inside(dst, root):
            print(f"{i:>3}. [跳过] 越界：{m['from']} -> {m['to']}")
            skipped += 1
            continue
        if not src.exists():
            print(f"{i:>3}. [跳过] 源不存在：{m['from']}")
            skipped += 1
            continue
        if dst.exists():
            print(f"{i:>3}. [跳过] 目标已存在，不覆盖：{m['to']}")
            skipped += 1
            continue
        companions = []
        if src.is_file() and src.suffix.lower() == ".wbpj":
            comp = src.with_name(src.name + "_files")
            if comp.is_dir():
                companions.append(comp)
        mark = "移动" if args.apply else "将移动"
        print(f"{i:>3}. [{mark}] {m['from']} -> {m['to']}")
        for comp in companions:
            print(f"      + 伴生目录 {comp.name}")
        if args.apply:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                for comp in companions:
                    target = dst.parent / comp.name
                    if not target.exists():
                        shutil.move(str(comp), str(target))
            except OSError as exc:
                print(f"       [失败] {exc}")
                skipped += 1
                continue
        ok += 1

    print("")
    print(f"合计：{ok} 项{'已移动' if args.apply else '待移动'}，{skipped} 项跳过")
    if not args.apply:
        print("确认无误后加 --apply 真正执行。")
    return 0


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hub", description="project-hub：项目群盘点与单项目骨架")
    parser.add_argument("--version", action="version", version=f"project-hub {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_map = sub.add_parser("map", help="盘点项目群（只读）")
    p_map.add_argument("path")
    p_map.add_argument("--json", action="store_true", help="额外输出 JSON")
    p_map.add_argument("--dupes", action="store_true", help="找跨项目重复文件（慢一些）")
    p_map.add_argument("--idle-days", type=int, default=60, help="超过多少天算停摆，默认 60")
    p_map.add_argument("--out", help="把报告写到指定文件")
    p_map.set_defaults(func=cmd_map)

    p_status = sub.add_parser("status", help="一屏看板：在用 / 停摆 / 要处理的")
    p_status.add_argument("path")
    p_status.add_argument("--limit", type=int, default=10, help="在用列表最多显示几个，默认 10")
    p_status.set_defaults(func=cmd_status)

    p_dash = sub.add_parser("dashboard", help="生成浏览器看板（一张 HTML）")
    p_dash.add_argument("path")
    p_dash.add_argument("--out", help="输出文件，默认 <根>/_reports/dashboard.html")
    p_dash.add_argument("--open", action="store_true", help="生成后直接弹出来")
    p_dash.set_defaults(func=cmd_dashboard)

    p_init = sub.add_parser("init", help="建单项目骨架（幂等）")
    p_init.add_argument("path")
    p_init.add_argument("--type", choices=list(TYPE_NOTES), default="generic")
    p_init.add_argument("--minimal", action="store_true", help="只建 4 个常用目录")
    p_init.set_defaults(func=cmd_init)

    p_index = sub.add_parser("index", help="生成 PROJECTS.md 空表（项目群入口）")
    p_index.add_argument("path")
    p_index.add_argument("--force", action="store_true", help="已存在也重建（会覆盖）")
    p_index.set_defaults(func=cmd_index)

    p_git = sub.add_parser("git", help="建仓库、写忽略规则、提交、推到 GitHub")
    p_git.add_argument("path")
    p_git.add_argument("--remote", help="GitHub 仓库地址，如 https://github.com/你/仓库.git")
    p_git.add_argument("--push", action="store_true", help="推送到 GitHub（第一次会弹登录窗）")
    p_git.add_argument("-m", "--message", help="这次提交的说明，不填就按时间")
    p_git.add_argument("--max-mb", type=int, default=50, help="单个文件超过多少 MB 就不提交，默认 50")
    p_git.add_argument("--max-files", type=int, default=2000, help="单次最多提交多少个文件，默认 2000")
    p_git.add_argument("--force", action="store_true", help="超过文件数上限也强行提交")
    p_git.set_defaults(func=cmd_git)

    p_save = sub.add_parser("save", help="推进时存一下：本地存档 + 传到 GitHub")
    p_save.add_argument("path")
    p_save.add_argument("-m", "--message", help="这次改了什么，不填就按时间")
    p_save.add_argument("--max-mb", type=int, default=50, help="单个文件超过多少 MB 就不存，默认 50")
    p_save.add_argument("--max-files", type=int, default=2000, help="单次最多存多少个文件，默认 2000")
    p_save.add_argument("--force", action="store_true", help="超过文件数上限也强行存")
    p_save.add_argument("--local", action="store_true", help="只存本地，不往 GitHub 传")
    p_save.add_argument("--no-refresh", action="store_true", help="不自动刷新看板")
    p_save.set_defaults(func=cmd_save)

    p_sync = sub.add_parser("sync", help="把本地已有的存档补传到 GitHub")
    p_sync.add_argument("path")
    p_sync.set_defaults(func=cmd_sync)

    p_hook = sub.add_parser("hook", help="提交后自动推送（可选，装进 .git/hooks）")
    p_hook.add_argument("path")
    p_hook.add_argument("action", choices=["on", "off", "status"])
    p_hook.set_defaults(func=cmd_hook)

    p_pub = sub.add_parser("publish", help="在 GitHub 建私有仓库并推上去")
    p_pub.add_argument("path")
    p_pub.add_argument("--name", help="仓库名，默认用文件夹名（只能用英文、数字、. _ -）")
    p_pub.add_argument("--desc", help="仓库描述")
    p_pub.add_argument("--public", action="store_true", help="建成公开仓库（默认私有）")
    p_pub.add_argument("--dry-run", action="store_true", help="只看会建什么，不真的建")
    p_pub.add_argument("--max-mb", type=int, default=50, help="单个文件超过多少 MB 就不存，默认 50")
    p_pub.add_argument("--max-files", type=int, default=2000, help="单次最多提交多少个文件，默认 2000")
    p_pub.add_argument("--force", action="store_true", help="超过文件数上限也强行提交")
    p_pub.set_defaults(func=cmd_publish)

    p_check = sub.add_parser("check", help="校验结构（只读；违规退出码 1）")
    p_check.add_argument("path")
    p_check.add_argument("--tmp-days", type=int, default=30)
    p_check.set_defaults(func=cmd_check)

    p_apply = sub.add_parser("apply", help="按计划移动（默认 dry-run）")
    p_apply.add_argument("plan")
    p_apply.add_argument("--root", help="计划里的相对路径以谁为基准")
    p_apply.add_argument("--apply", action="store_true", help="真的移动")
    p_apply.set_defaults(func=cmd_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
