---
name: review-and-bump-version
description: 在 ValorantToxicTamer 完成软件改动后审核并判级，预先核对远端版本，计算正式版或 beta.N，同步应用和 README，重打包 EXE 并发布 GitHub Release。main 发布正式版，Beta 发布预发布；标题只能是 vx.y.z 纯版本号。仅无关软件的改动可不升版；只读咨询、仅审核和维护 skill 时不自动发版。
---

# 审核改动并更新版本

适用于本仓库。完成软件修改任务后主动执行；用户已授权升版后自动重打包并发布 GitHub Release，无需重复询问。用户限定先审核、暂不升版、暂不打包或暂不发布时遵从其范围。

## 升版前提与审核

- 查看适用的 AGENTS.md、任务开始时的版本、`git status --short`、暂存与未暂存 diff 及新增文件，区分本次修改与用户原有改动。仅纳入本次授权内容。
- 如果全部改动都与软件功能、行为、界面、配置、数据、运行依赖、构建分发及使用说明无关，可以不升版、不重打包、不发布。例如只维护仓库介绍、协作规范、skill、内部记录或不随软件分发的素材。按实际影响判断，不仅看路径；软件使用说明的修正仍需审核。
- 混合改动只依据软件相关部分判级。发现本次引入的问题，在授权范围内修复；交付阻塞未解决时停止发布。没有实际改动不升版；用户明确要求升版时执行。

| 级别 / 脚本参数 | 判定依据 | 正式版基础号变化 |
| --- | --- | --- |
| 重大 / `major` | 核心使用方式或架构大幅改变，不兼容的配置、数据、接口变化，需要迁移主要流程 | `x+1.0.0` |
| 中等 / `minor` | 新增完整能力、较大界面改版，整体保持兼容 | `x.y+1.0` |
| 小 / `patch` | 局部修复、性能优化、小范围界面调整、文案或文档修正 | `x.y.z+1` |

按用户影响而非改动行数判级，混合改动取最高级别。选定段加 1、后续段归零，不按十进制进位；`v1.2.9` 小更新为 `v1.2.10`。

## 发版前预检与版本计算

**在修改 VERSION、README 或打包之前**，执行只读脚本 [scripts/next_version.py](scripts/next_version.py)，实时读取本地标签、远端标签及全部分页的 GitHub Release：

```powershell
# --current 必须是本次任务开始前的版本；--bump 根据审核结果选择。
.\.venv\Scripts\python.exe -B .agents\skills\review-and-bump-version\scripts\next_version.py --branch main --current 1.2.3 --bump minor
.\.venv\Scripts\python.exe -B .agents\skills\review-and-bump-version\scripts\next_version.py --branch Beta --current 1.3.0-beta.1 --bump patch
```

- 脚本依赖 Git、已登录且可读取目标仓库 Release 的 GitHub CLI；Python 使用标准库。未准备好时说明缺项，不猜版本或静默降级为离线计算。脚本不会改文件、提交、创建标签、推送或发布。
- 先核对 origin、更新器 `REPOSITORY` 与脚本目标仓库一致，当前为 `TimeseekerKK/ValorantToxicTamer`；核对来源分支已经包含远端对应分支的改动。脚本确认当前分支和 remote URL，但不证明源码已经同步或完成审核。
- **已发布且非预发布的 Release** 才定义最新正式版本基线。草稿及仅本地/远端存在的标签只代表名称占用，不能当成已完成的正式版。按数字比较版本，不按字符串或发布日期排序。
- 远端标签、Release 查询、分页、认证失败，或本地与远端同名标签指向不同提交时，停止在改版本和打包之前。分支版本落后或与远端活动 Beta 线不一致时，先同步并重新审核，不自动覆盖或凭空抬高版本。
- 记录本批计算结果（`version`、`base_version`、`tag`、`title`、渠道等），可保存到忽略提交的 `artifacts/`。同一批重试必须复用此结果，用 `--resume`，不能再次使用 `--bump` 重新分配版本。`--snapshot` 只用于离线测试，输出 `offline=true`，不能据此执行真实发布。
- 若已有同名目标标签/Release，先查询其状态。已有标签须核对剥离 annotated tag 后的完整提交 SHA，不能移动、删除、强推或覆盖它。并发导致远端状态变化时停止重新核对，不自动把同一批改动变成下一版本。
- 没有任何已发布正式 Release 时停止自动推算，先明确初始发布版本。

## Beta 序号与正式发布规则

正式版仍按 `major/minor/patch` 增加基础号。Beta 引入独立的预发布序号，以完整版本 `x.y.z-beta.N` 标识，N 从 1 开始。

1. **开启 Beta 版本线**：从最新正式版本按改动级别计算基础号，再加 `-beta.1`。例如正式版 `v1.2.3` 的中等更新为 `v1.3.0-beta.1`。
2. **继续未发布的版本线**：基础号保持不变，只增加 Beta 序号；例如 `v1.3.0-beta.1` → `v1.3.0-beta.2`。将本次判级作用于最新正式版得到的候选基础号，与活动 Beta 基础号取较大者；若需要更高基础号则新开该基础号的 `beta.1`，否则继续序号。不会因相同等级的迭代反复增加基础号。
3. **已占用序号**：同基础号下，本地标签、远端标签及草稿/已发布 Release 的序号均保留占用，新批次取最大序号加 1。失败批次优先 `--resume` 原计划；这不是通过增加序号掩盖失败的许可。
4. **关闭旧版本线**：基础号小于或等于最新已发布正式版的 Beta 线已经关闭，不能继续新发该线或把旧草稿发布出去。先确认 Beta 分支已包含正式版代码，再按级别计算新基础号，从 `beta.1` 开始。例如 `v1.3.0` 已正式发布，后续小更新为 `v1.3.1-beta.1`。
5. **Beta 转正式版不重复加号**：在 main 上发布已经验证的 Beta 内容，且无新增软件改动时，使用 `--promote` 沿用基础号，例如 `v1.3.0-beta.2` → `v1.3.0`。不得重新执行一次 minor/patch。必须检查该 Beta 已发布、基础号尚未正式发布、main 已包含该 Beta 提交，并核对软件源码、数据、依赖和构建输入与候选版等效（允许版本和发布说明差异）。脚本只能验证候选记录，不能替代代码等效审核。若有新增软件改动，先在 Beta 完成新的候选发布或重新判级，不能冒用无新增改动的晋升流程。
6. **兼容旧标签**：历史 `v1.3.0-beta` 视为该基础号的序号 0，只读保留，后续使用 `v1.3.0-beta.1`；不重命名旧标签。脚本忽略其它不符合正式版或 Beta 格式的历史标签。

```powershell
# 仅当 main 确实在晋升已验证的同一批 Beta 内容时使用。
.\.venv\Scripts\python.exe -B .agents\skills\review-and-bump-version\scripts\next_version.py --branch main --current 1.3.0-beta.2 --promote v1.3.0-beta.2
# 同一批失败重试；目标标签已存在时必须提供对应的完整提交 SHA。
.\.venv\Scripts\python.exe -B .agents\skills\review-and-bump-version\scripts\next_version.py --branch Beta --current 1.3.0-beta.2 --resume v1.3.0-beta.2 --expected-commit <full-commit-sha>
```

## 分支、版本表示和构建

| 来源分支 | 代码推送目标 | 应用 VERSION | Git 标签 | Release title | 发布类型 / Latest |
| --- | --- | --- | --- | --- | --- |
| `main` | `origin/main` | `1.3.0` | `v1.3.0` | `v1.3.0` | 正式版 / 是 |
| `Beta` | `origin/Beta` | `1.3.0-beta.2` | `v1.3.0-beta.2` | `v1.3.0` | 预发布 / 否 |

- 分支大小写以实际仓库为准，当前为 main 和 Beta。不自动切换、合并分支，不默认把 Beta 推送到 main；其他分支或 detached HEAD 先明确发布来源。
- `valorant_toxic_tamer/app_version.py` 的 `VERSION` 写入脚本返回的完整 `version`，不带 v。README 标题和表示当前版本的内容用 `v` 加完整版本；保留历史记录与测试样例。**Release title 始终是基础纯版本号**，必须使用脚本的 `title`，例如 `v1.3.0`，不得加 beta.N、软件名、空格、日期或说明；渠道与完整版本写进正文。
- **首次采用完整 Beta VERSION 前先检查更新器兼容性**：当前 `updater.py` 的数字解析器不支持 `-beta.N`，不能仅修改 VERSION 后直接打包。实际软件发版任务必须先适配并测试完整版本解析及比较：Beta 序号按整数比较，同基础号正式版高于任何 Beta，较高基础号始终更高。默认仍只检查正式 Release；发布预发布不代表已实现 Beta 自动更新渠道。本次仅维护 skill 时不修改应用代码，也不声称此兼容性工作已完成。
- 完成版本同步和兼容性检查后，从对应分支本次源码重新构建 `dist/ValorantToxicTamer.exe`，不能复用另一分支的旧产物或重命名旧 EXE。若有 Windows 版本资源，数字元组使用基础号的 `x.y.z.0`，字符串版本保留完整版本；未配置资源时不声称 Windows 文件属性已更新。

在仓库根目录使用现有环境，依次执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\scripts\build.ps1
```

`scripts/build.ps1` 当前包含 `tests/check_package.py` 的打包检查，执行时核实实际入口。不得擅自结束占用 EXE 的用户进程；缺环境、文件占用、测试或构建失败时先修复，沿用原目标版本重试。若构建后改了软件源码，重新检查并打包。

## 提交、标签与 GitHub Release

仅在实际软件版本更新或补齐该批发版流程时执行。预检并非版本号锁；创建标签、正式发布前重新核对远端状态。

1. 审核并提交本次软件改动、VERSION 和 README，推送到来源分支对应的远端分支；不夹带无关内容、个人数据或构建目录。记录完整提交 SHA，确保构建源码与其一致；已完成步骤只核实并复用。
2. 按计划创建指向该准确提交的 annotated tag 并推送该标签；已有标签须验证指向一致，禁止默认指向远端默认分支最新提交。记录软件提交、完整版本、渠道及 EXE SHA-256 的对应关系。
3. 先创建草稿 Release，显式设置计划的 tag 和纯版本号 title，并上传本次生成的 EXE，附件名为 `ValorantToxicTamer.exe`。正文用简体中文说明完整版本、来源分支、改动和实际验证结果；CLI 多行正文使用文件传入。
4. 核对源码提交、标签、标题、附件与远端最新状态后发布：main 的基础号须高于最新正式版，设置 `draft=false, prerelease=false, latest=true`；Beta 须仍处于开放版本线，设置 `draft=false, prerelease=true, latest=false`。Beta 不得替换正式版 Latest。
5. 重试先使用 `--resume` 原目标，已有标签需传 `--expected-commit`。结果 `status=published` 只代表元数据匹配，仍须核实附件；草稿补齐缺项后再发布。同名已发布内容不匹配则停止，不擅自覆盖附件、使用 `--clobber`、删除 Release 或切换渠道。Beta 晋升用 main 的提交和正式标签重新构建，不直接把 Beta Release 改为正式版。
6. 发布后重新读取远端，检查完整 tag、纯版本 title、tag 指向、渠道、非草稿状态和 Latest，再核对附件名、上传状态、大小及 SHA-256（优先服务端摘要，不可用时下载校验）。上传或发布失败时报告实际远端状态，不能只凭本地标签、推送或脚本计划声称发布完成。

GitHub CLI 参数参考：[API 与分页](https://cli.github.com/manual/gh_api)、[创建 Release](https://cli.github.com/manual/gh_release_create)、[编辑 Release](https://cli.github.com/manual/gh_release_edit)。main 发布草稿用 `--draft=false --prerelease=false --latest=true`，Beta 用 `--draft=false --prerelease=true --latest=false`，创建 Beta 草稿也显式指定 `--prerelease --latest=false`。`--verify-tag` 只检查远端标签存在，仍需核对完整提交。

## 验证与交付

修改本 skill 的版本脚本时，执行离线回归测试：

```powershell
.\.venv\Scripts\python.exe -B .agents\skills\review-and-bump-version\scripts\test_next_version.py -v
```

交付说明判级依据、旧版 → 完整新版、来源分支、发布渠道、源码/README/EXE 同步状态、实际验证结果、对应提交和 Release 链接。静态检查、脚本回归与真实 EXE/游戏验证分别说明。仅维护 skill 时不触发软件升版或发布。
