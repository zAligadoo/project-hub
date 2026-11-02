# Git + GitHub 怎么用（大白话版）

## 先说清楚这两个东西

- **Git**：装在你电脑上的"存档机"。每按一次存档，它记下当时所有文件的样子。改坏了能回到任意一次存档。
- **GitHub**：一个网站，把存档机里的东西再存一份到网上。电脑坏了、硬盘挂了，东西还在。

两个是一套的：Git 干活，GitHub 备份。

## 一个项目一个仓库，别搞大杂烩

- **在用的项目**：每个项目一个仓库。`demo-a` 一个、`demo-b` 一个。
- **停了的项目**：不用建。建了也不会用，只是多一堆要维护的东西。
- **别把所有项目塞进一个仓库**：一次改动会牵扯全部，翻记录时根本找不到。

## 一条命令搞定（推荐）

```powershell
python "<DSH_HOME>\skills\project-hub\scripts\hub.py" publish "D:\Projects\demo-case"
```

它替你做完三件事：**在 GitHub 上建一个私有仓库**（名字默认取文件夹名）→ 把地址记到本地 → 推上去。

```
  ✓ 建好本地仓库（main 分支）
  ✓ 存了 3 处改动（本地）
  ✓ 已在 GitHub 建好仓库：https://github.com/your-name/demo-case（私有）
  ✓ 已把地址记到本地（origin）
  ✓ 已上传 GitHub

  仓库地址：https://github.com/your-name/demo-case
```

几个参数：

| 参数 | 作用 |
|---|---|
| `--name demo-case` | 改仓库名（默认用文件夹名，只能用英文、数字、`.` `_` `-`） |
| `--desc "示例项目"` | 仓库描述 |
| `--public` | 建成公开仓库（**默认私有**） |
| `--dry-run` | 只看会建什么，不真的建 |

用的是你电脑上已保存的 GitHub 登录凭据；没有的话先在终端跑一次任意 `git push` 把登录做完。

## 手动三步（自动建库失败时再用）

### 第 1 步：本地建仓库（不上网）

```powershell
python "<DSH_HOME>\skills\project-hub\scripts\hub.py" git "D:\Projects\demo-case"
```

它做了四件事：

1. 在项目文件夹里建 `.git`（就是存档机）
2. 写一个 `.gitignore`，把大文件排除在外（工程文件、压缩包、日志）
3. 建 `.gitattributes`，统一换行符（以后换电脑不会满屏"改动"）
4. 把当前所有文件存成第一次存档

输出里会有一行 `! N 个文件超过 50MB，没提交`——这是好事，说明大文件被拦下了。

### 第 2 步：在 GitHub 建一个空仓库

网页上：

1. 右上角 `+` → `New repository`
2. 名字填项目名（比如 `demo-case`）
3. **选 `Private`**（研究数据默认别公开）
4. **不要勾** "Add a README file"、不要选 .gitignore、不要选 license——空仓库就行
5. 点 `Create repository`

建完页面会显示仓库地址，长这样：

```
https://github.com/你的用户名/demo-case.git
```

### 第 3 步：连起来，推上去

```powershell
python "...\hub.py" git "D:\Projects\demo-case" --remote https://github.com/你的用户名/demo-case.git --push
```

第一次会弹一个窗口让你登录 GitHub（浏览器授权），登一次就行，以后再也不用登。

看到 `✓ 已推送到 GitHub` 就成了。

## 以后每天怎么用

改完东西，收工前跑这一条：

```powershell
python "...\hub.py" save "D:\Projects\demo-case"
```

它会：把改动存到本地 → 有 GitHub 地址就顺手传上去。输出是这样：

```
项目：demo-case
  ✓ 存了 5 处改动（本地）
  ✓ 已上传 GitHub
```

没有改动时只说"没有新改动"，不会产生空记录。

**断网了也不要紧**：本地那份已经存好，联网后跑一次补传：

```powershell
python "...\hub.py" sync "D:\Projects\demo-case"
```

想写清楚这次改了什么：

```powershell
python "...\hub.py" save "D:\Projects\demo-case" -m "补了一批数据"
```

这次不想传上去（只想本地存一下）：

```powershell
python "...\hub.py" save "D:\Projects\demo-case" --local
```

### 让"手动 commit"也自动传

如果你有时会自己在终端敲 `git commit`，可以装一个钩子：

```powershell
python "...\hub.py" hook "D:\Projects\demo-case" on      # 开启
python "...\hub.py" hook "D:\Projects\demo-case" status  # 查看
python "...\hub.py" hook "D:\Projects\demo-case" off     # 关闭
```

装了以后，任何一次提交（不管谁提交的）都会自动推一次。断网时静默跳过，**不影响提交**；联网后跑 `save` 或 `sync` 补一次就行。

## 哪些东西不该进 git

| 类型 | 例子 | 放哪 |
|---|---|---|
| 原始数据 | 几 GB 的 tif、csv | 网盘 / 移动硬盘（放 `00_input/02_data_raw/`，默认不进 git） |
| 仿真模型 | `.mph`、`.wbpj`、`.msh` | 网盘；要版本就在项目里放 `90_archive/v1/` |
| 结果大文件 | 几十 GB 的 case/data | 网盘 |
| 密码、密钥 | `.env`、token | **永远别提交** |

`.gitignore` 已经帮你挡了一部分。**GitHub 单文件超过 100MB 会直接拒绝**，别硬传。

## 常见问题

**弹窗没出来 / 登录失败**
先跑 `git config --global credential.helper manager` 确认用的是 Windows 凭据管理器，再试一次。

**推送被拒绝（rejected / non-fast-forward）**
说明网上有你本机没有的改动。先 `git pull --rebase origin main`，再推。

**提示 "remote origin already exists"**
说明这个文件夹之前连过别的地址。加 `--remote <新地址>` 会自动改，不用手动删。

**已经有一个 GitHub 仓库，想接管本地的项目**
先 `git init`（也就是跑第 1 步），再 `--remote <地址>`，最后 `--push`。如果网上仓库不是空的，先 `git pull --rebase origin main`。

**不想让某个文件被 git 看见**
加进项目根目录的 `.gitignore`，一行一个。已经提交过的要先 `git rm --cached 文件名`。

**项目里有已经存在的 git 仓库（比如从别处 clone 的）**
跑 `hub.py git` 会检测到，不会重新初始化，只在需要时补 `.gitignore` 和提交。

## 想看历史 / 回退

这三条够用了：

```powershell
git -C "项目路径" log --oneline -10     # 最近 10 次存档
git -C "项目路径" show 存档编号          # 某次改了什么
git -C "项目路径" checkout 存档编号 -- 文件名   # 把某个文件恢复到那次的样子
```

回退整个项目要小心，先问人再做。
