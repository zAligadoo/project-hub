# 工作流

这份文档说清楚：日常怎么用这套东西。

## 两个层次

```
① 项目群（一个总目录）
   ├── PROJECTS.md          总表：一个项目一行
   ├── PROJECTS.details.md  每个项目的说明 + 主要产出
   ├── _inbox/              没归位的东西先扔这
   ├── _archive/            退役项目
   ├── _reports/            看板、报告
   └── 各个项目目录
```

```
② 单个项目
   └── README.md / docs / src / tests / models / data / results / archive / _tmp
```

## 每天

| 时间点 | 做什么 | 命令 |
|---|---|---|
| 开工 | 看一屏：哪个在推进、哪个没存 | `hub.py status "<总目录>"` |
| 干活 | 按规范放文件，拿不准扔 `_inbox/` | — |
| 收工 | 存一下（agent 会自动做） | `hub.py save "<项目>"` |

## 每周（15 分钟）

1. 清 `_inbox/`
2. 打开 `PROJECTS.md` 改状态和"下一步"
3. 两周没动的项目改成"暂停"
4. 看板重新生成一次

## 文件该放哪

| 文件 | 去处 | 进 git |
|---|---|---|
| `.py` `.m` `.ipynb` | `src/` | ✅ |
| 模型 `.mph` `.wbpj` `.cae` `.inp` | `models/` | ❌ |
| 原始数据 `.csv` `.tif` | `data/raw/` | ❌ |
| 清洗后数据 | `data/processed/` | ✅ |
| 单次跑的输出 | `results/runs/<case>/` | ❌ |
| 图 | `results/figures/` | ✅ |
| 汇总表 | `results/tables/` | ✅ |
| 报告、论文 | `docs/` | ✅ |
| 压缩包、废弃版本 | `archive/` | ❌ |
| 今天就能删的 | `_tmp/` | ❌ |

## 版本怎么管

| 管什么 | 用什么 | 规则 |
|---|---|---|
| 代码 | git | 不建 `code_v2/`，改坏了 `git checkout` |
| 模型 | 目录 + 清单 | 当前版在 `models/`；旧版 `archive/v1/models/`；`models/MANIFEST.md` 记一行 |
| 结果 | `results/runs/<case>/` | 定型后整体进 `archive/vN/results/` |
| 临时 | `_tmp/` | 检验标准：能不能整个删掉而不丢成果 |

## 看板

```powershell
python "...\hub.py" dashboard "D:\Projects" --open
```

生成 `_reports/dashboard.html`，双击就能看。改完数据要重新生成（`save` 会自动刷）。

## 边界

- 只移不删
- 不覆盖同名文件
- 项目总根不建仓库
- 单次提交超过 2000 个文件会拒绝
