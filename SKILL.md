---
name: project-hub
description: 帮你管住一堆项目：有哪些项目、哪个在做、文件该放哪、推进时怎么一键存档并备份到 GitHub。当用户说"项目太乱""文件散落找不到""不知道该做哪个""新建项目""整理一下""存一下""用 git 管起来""传到 GitHub"时使用。
---

# 项目总台

## 一句话

就两层：**一张总表**告诉你有哪些项目、哪个在做；**每个项目一个文件夹**，东西按四类放。

## 第一层：总表

在总目录（比如 `D:\Projects`）放一个 `PROJECTS.md`，一张表：

| 项目 | 一句话 | 状态 | 下一步 | 包含目录 |
|---|---|---|---|---|
| 示例项目 | 一句话说清这项目在做什么 | 进行中 | 下一步要做什么 | `demo-a`, `demo-b`, … |
| 另一个项目 | 另一个项目的说明 | 暂停 | 暂时不推进 | `demo-c` |

- 「包含目录」可以写相对路径，也可以写**绝对路径**——项目放在哪个盘、哪个子文件夹都能管
- 目录里如果自己也有 `PROJECTS.md`，它就是**子工作区**：看板会自动把它里面的项目也并进来（最多往下 3 层）
- 没写进任何表的目录，会以"未标状态"的卡片出现在看板上——提醒你还没归类
- 某个目录里如果自己也有 `PROJECTS.md`（子工作区），扫描时会跳过它，不当项目

**最重要的一条：一个项目 ≠ 一个文件夹。**

同一个课题，换过工具、换过助手、试过十种做法，做了十个目录——那是**一个项目的十个版本**，不是十个项目。最后一列把这些目录都列上，看板就合成一张卡。

状态只有三种：`进行中`、`暂停`、`已完成`。**进行中的不要超过 3 个**——多了就是骗自己。

没有这张表，先生成空表再填：

```powershell
python "<DSH_HOME>\skills\project-hub\scripts\hub.py" index "D:\Projects"
```

它会把现有文件夹按最近动过的顺序排好，一个目录一行；你把同一课题的几行合成一个项目，填上「一句话 / 状态 / 下一步」，把目录名挪进最后一列。

### 项目详情（点卡片进去看到的内容）

同一个目录放一个 `PROJECTS.details.md`，一个项目一小节：

```md
## 示例项目

- 做什么：把模型做成算例，批量跑求解器
- 目的：得到参数和结果的关系，支撑论文
- 流程：`models` 出模型 → `src` 跑批量 → `results` 出图
- 主要产出：
  - 工作台看板 → D:\Projects\_reports\dashboard.html
- 关键文件：
  - `models`：`README.md` — 说明
  - `results`：`tables/汇总.csv` — 结果
```

看板里点任意卡片，就展开这个项目的详情：做什么、目的、流程、包含的目录（文件数 / 体积 / 主要类型）、关键文件。没写的栏目显示"还没填"。

## 第二层：每个项目的文件夹（GitHub 式）

一个项目 = 一个仓库，结构照社区惯例来，谁打开都认得：

```
项目/
├── README.md        首页：这是什么 / 怎么跑 / 结果在哪
├── docs/            文档：方案、笔记、报告、论文稿
│   ├── notes/
│   └── reports/
├── src/             代码
│   ├── python/
│   ├── matlab/
│   └── fluent/      .jou / .tcl 批处理
├── tests/           测试、校验、对拍脚本
├── models/          模型：mph / wbpj / cae / inp / scdocx
├── data/
│   ├── raw/         原始数据，只读
│   └── processed/   清洗后的
├── results/
│   ├── runs/        每次跑的输出（按 case 分）
│   ├── figures/     出图
│   └── tables/      汇总表
├── archive/         冻结的旧版本 v1/ v2/
└── _tmp/            临时文件，随时可清
```

进不进 git，看这张表：

| 放哪 | 进 git | 为什么 |
|---|---|---|
| `src/` `tests/` `docs/` | ✅ | 文本，越小越好管 |
| `data/processed/` `results/figures/` `results/tables/` | ✅ | 小结果，值得留版本 |
| `models/` `data/raw/` `results/runs/` `archive/` `_tmp/` | ❌ | 太大，走网盘 |

### 三条版本与临时规则

**1. 代码版本 → 交给 git。** 不要建 `code_v2/`、`code_FIXED/`。改坏了 `git checkout` 回去。

**2. 模型版本 → 目录 + 清单。**
- 正在用的放 `models/`（文件名带语义：`dual_sphere_R1.5.mph`）
- 冻结的旧版放 `archive/v1/models/`、`archive/v2/models/`
- 每个模型在 `models/MANIFEST.md` 记一行：哪来的、什么参数、跟上一版差在哪
- 模型不进 git（太大），但 MANIFEST 进

**3. 临时文件 → 只进 `_tmp/`。** 求解器日志、跑废的 case、导出中断、编辑器锁文件，全扔这。`_tmp/` 必须能随时整个删掉而不丢成果——这是检验它有没有被用对的唯一标准。

### 测试放哪

- `tests/` 放校验脚本：`test_*.py`、`check_*.m`、`*_smoke.py`
- 批量跑之前，先拿**一个已知 case 对拍**：单例跑通、结果和上次一致，再上批量
- 对拍脚本要留在 `tests/`，别跑完就删——下次换机器还要用

新建项目：

```powershell
python "<DSH_HOME>\skills\project-hub\scripts\hub.py" init "D:\Projects\新项目" --type sim
```

`--type` 可以写 `code` / `sim` / `data` / `doc`，只影响 README 里的提示；`--minimal` 只建顶层 8 个目录。重复跑没关系，已有的文件不会覆盖。

## 东西该放哪：看扩展名，不用想

| 文件 | 放哪 |
|---|---|
| `.py` `.m` `.ipynb` `.jou` `.tcl` | `src/` |
| `.mph` `.wbpj` `.cae` `.inp` `.scdocx` `.CATPart` | `models/` |
| 原始 `.csv` `.tif` `.dat` | `data/raw/` |
| 清洗后的数据 | `data/processed/` |
| 单次跑的 `.cas` `.h5` `.log` | `results/runs/<case>/` |
| 出的图 `.png` `.pdf` | `results/figures/` |
| 汇总表 `.xlsx` `.csv` | `results/tables/` |
| 报告、论文、笔记 `.md` `.docx` | `docs/` |
| 压缩包、废弃版本 | `archive/` |
| 今天就能删的 | `_tmp/` |

拿不准 → 先扔 `_inbox/`（项目总目录下），周末再分。

## 用 Git 存起来（代码不怕丢）

Git 是给文件夹拍快照，改坏了能翻回去；GitHub 是把快照再存一份到网上。

### 一次性接上 GitHub（一条命令）

```powershell
python "...\hub.py" publish "D:\Projects\demo-case"
```

它一口气做完：**在 GitHub 上建一个私有仓库**（名字默认取文件夹名）→ 记下地址 → 把本地存档推上去。最后会打印仓库地址。

改名字、加描述、想公开：

```powershell
python "...\hub.py" publish "D:\Projects\demo-case" --name demo-case --desc "示例项目"
python "...\hub.py" publish "D:\Projects\demo-case" --public          # 默认是私有
python "...\hub.py" publish "D:\Projects\demo-case" --dry-run         # 只看会建什么
```

仓库名只能用英文、数字、`.` `_` `-`；中文文件夹名要自己加 `--name`。

> 用的是你电脑上已保存的 GitHub 登录凭据。没有凭据时，先在终端跑一次任意 `git push` 把登录做完。

### 已经在网页上建好仓库的项目

那就直接接地址：

```powershell
python "...\hub.py" git "D:\Projects\demo-case" --remote <仓库地址> --push
```

网页建仓库时**别勾 README**；勾了推送会被拒，得先 `git pull --rebase origin main`。

### 以后收工，跑这一条

```powershell
python "...\hub.py" save "D:\Projects\demo-case"
```

它做两件事：**本地存一份** + **有 GitHub 地址就顺手传上去**。输出就两三行：

```
项目：demo-case
  ✓ 存了 5 处改动（本地）
  ✓ 已上传 GitHub
```

断网、或者 GitHub 抽风也不会丢：本地已经存好了，联网后跑 `hub.py sync "<路径>"` 补传。

**存完会顺手刷新看板**（不用再单独跑 `dashboard`）：它会把项目所在工作区的看板重新生成，连项目 `results/` 里的副本一起更新。不想刷新就加 `--no-refresh`。

想写清楚这次改了什么：

```powershell
python "...\hub.py" save "D:\Projects\demo-case" -m "补了一批数据"
```

**大文件不会进去**：`mph`、`msh`、`cas`、`dat`、`h5`、`wbpj`、`zip` 这类自动跳过；超过 50MB 的也会被拿出来，并记到本机忽略清单里。数据和模型放网盘，代码和文字放 GitHub——GitHub 单个文件超过 100MB 就直接拒绝。

细节和常见问题见 `reference/git-github.md`。

## 自动存档（默认行为，不用用户提醒）

只要是在某个项目里干活，就按这个来：

1. **做完一段实质工作**（改了代码、跑出结果、写完一段报告），收尾自动跑一次
   `save "<项目>"`，不用先问。
2. **项目还没接 GitHub**：先用 `publish "<项目>"` 建一个**私有**仓库并推上去（见上）。默认私有，**不要**建成公开。永远不要对 `D:\Projects` 这种总目录建仓库。
3. **上传失败**（断网、没登录）：说一句"本地已存，联网后 `sync`"就够，不要反复重试。
4. **用户说"这次别传"**：用 `save "<项目>" --local`，只存本地。
5. 想连手动提交也自动传：`hook "<项目>" on`（装一个提交后自动推送的钩子）。

**什么时候不存**：只读操作（map/check）、还在试的过程中、用户明确说不用。

## 看全局、查问题

```powershell
# 看一眼所有项目的状态（只读，不改任何东西）
python "...\hub.py" map "D:\Projects"

# 终端一屏：在用 / 停摆 / 要处理的（只读）
python "...\hub.py" status "D:\Projects"

# 浏览器卡片墙（生成一张 HTML，可搜索、可筛选，`--open` 直接弹出来）
python "...\hub.py" dashboard "D:\Projects" --open

# 查一个项目有没有乱（只读，有问题返回"不通过"）
python "...\hub.py" check "D:\Projects\demo-case"
```

要批量挪文件，得先写一份清单给人看，确认了才动：

```json
{"moves": [{"from": "旧位置/a.msh", "to": "models/a.msh"}]}
```

```powershell
python "...\hub.py" apply plan.json --root "D:\Projects\demo-case"          # 先看
python "...\hub.py" apply plan.json --root "D:\Projects\demo-case" --apply  # 再动
```

## 三条习惯（比工具重要）

1. **收工前跑一次 `save`**。花了半小时的改动没有存档，等于没做过。
2. **新东西先扔 `_inbox/`**，别直接塞进某个项目。周末花 10 分钟清。
3. **项目文件夹里多出第 8 样东西时，停一下问"它属于哪个目录"**，而不是"先放这吧"。

## 底线

- **只挪，不删。** 重复文件只报告，删不删你决定。
- **不覆盖。** 目标位置已经有同名文件就跳过，列出来给你看。
- **不偷偷批量整理。** 用户说"整理一下"，先 `map`，再问是整堆项目还是某一个。
- **不改已有的中文文件名**（有些仿真软件认路径），只改位置。
- **拿不准就不动。** 一个"待确认"比十个错误归位有用。
- **防呆**：对项目总根（有 `PROJECTS.md` 或 `_inbox`+`_archive` 那种）、或文件数超过 2000 的目录，`save` / `git` / `publish` 会直接拒绝、连仓库都不建。确认要存才加 `--force`。

## 做完的样子

- 3 分钟内能说出"我现在该推进哪个项目"。
- 找文件最多两步：先看 `PROJECTS.md`，再看那个项目的 `README.md`。
- 每个在用的项目都在 GitHub 上有备份，改坏了能翻回去。
