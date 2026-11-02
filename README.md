# project-hub

**一个 DSH skill + 本地看板：帮你管住一堆项目。**

它解决四个问题：

- 项目散落在十几个文件夹里，**不知道哪个在推进**
- 每个项目里文件乱放，**找东西靠翻**
- 代码和模型没有版本，**改坏了回不去**
- 想备份到 GitHub，但**不知道哪些该提交、哪些太大**

## 看板长什么样

![看板](docs/preview.png)

点任意卡片进详情：做什么 / 目的 / 流程 / 目录与文件 / 主要产出 / 关键文件。

## 它做什么

| 命令 | 干什么 |
|---|---|
| `map` | 盘点所有项目，出总图和问题清单（只读） |
| `status` | 终端一屏：进行中 / 暂停 / 已完成的、下一步 |
| `dashboard` | 生成浏览器看板（单文件 HTML，可搜可筛） |
| `index` | 生成总表空壳 |
| `init` | 给新项目建骨架和 README |
| `save` | 推进时"存一下"：本地存档 + 有地址就上传（存完自动刷看板） |
| `publish` | 在 GitHub 建**私有**仓库并推上去 |
| `sync` | 断网后补传 |
| `hook` | 提交后自动推送（可选） |
| `check` | 查一个项目乱不乱（只读） |
| `apply` | 按人工确认的清单挪文件（默认只看不动） |

## 核心约定

**一个项目 ≠ 一个文件夹。** 同一个课题换过工具、试过十种做法、做了十个目录——那是**一个项目的十个版本**，不是十个项目。总表里一行，目录列全列上，看板就合成一张卡。

**项目骨架**（GitHub 风格）：

```
<项目>/
├── README.md     这是什么 / 怎么跑 / 结果在哪
├── docs/         方案、笔记、报告、论文
├── src/          代码（python / matlab / fluent）
├── tests/        测试、对拍脚本
├── models/       模型文件
├── data/         raw 只读 / processed 清洗后
├── results/      runs / figures / tables
├── archive/      冻结的旧版本
└── _tmp/         临时，随时可清
```

**大文件不进 git**：`models/`、`data/raw/`、`results/runs/`、`archive/`、`_tmp/` 走网盘，只有代码、文档、小结果进仓库。

## 安装

1. 把整个 `project-hub` 文件夹放进：

```
%USERPROFILE%\.dsh\skills\project-hub
```

2. 验证：

```powershell
python "$env:USERPROFILE\.dsh\skills\project-hub\scripts\hub.py" --version
```

要求：DSH + Python 3.10 以上。**零第三方依赖。**

## 快速开始

```powershell
# 1. 在项目总目录生成总表空壳
python "$env:USERPROFILE\.dsh\skills\project-hub\scripts\hub.py" index "D:\Projects"

# 2. 打开 PROJECTS.md，每个项目填一行：
#    项目 | 一句话 | 状态 | 下一步 | 包含目录

# 3. 生成看板
python "$env:USERPROFILE\.dsh\skills\project-hub\scripts\hub.py" dashboard "D:\Projects" --open

# 4. 新项目
python "...\hub.py" init "D:\Projects\my-project" --type code
python "...\hub.py" publish "D:\Projects\my-project"      # 自动建私有仓库并上传

# 5. 以后收工
python "...\hub.py" save "D:\Projects\my-project"
```

## 安全设计

- `publish` **默认建私有仓库**，不会把东西公开
- 大文件自动排除（`mph/wbpj/msh/zip/...`，单文件超 50MB 也会拦）
- **只移不删**，移动前默认 dry-run
- 对项目总根、超大目录会直接拒绝建仓库
- 永不覆盖同名文件

## 文档

- [`SKILL.md`](SKILL.md) —— 给 agent 的完整规范
- [`docs/guide.md`](docs/guide.md) —— 人的工作流说明
- [`reference/git-github.md`](reference/git-github.md) —— Git/GitHub 大白话教程
- [`reference/playbooks.md`](reference/playbooks.md) —— 四个场景怎么处理
