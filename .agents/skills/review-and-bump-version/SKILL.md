---
name: review-and-bump-version
description: 在 ValorantToxicTamer 完成软件改动后自动审核、升版、重打包并推送发布。新功能、重大改动及高回归风险改造默认走 Beta 分支和 GitHub Pre-release；小型兼容改动、正式版小 bug 修复默认走 main 和正式 Release。main 提交交付后主动同步 Beta，Beta 开发或发布前补查遗漏；处理 Beta 内修复及转正，标题与完整标签一致。用户指定范围优先；只读咨询、仅审核和维护 skill 不自动发版。
---

# 审核改动并更新版本

适用于本仓库。用户指定的默认软件交付流程是：审核本次改动 → 选择目标分支和发布渠道 → 预检远端版本 → 更新版本及 README → 测试并重新打包 → 提交推送 → 发布 GitHub Release。软件实现或修复任务完成后主动执行，授权涵盖本次改动对应的升版、打包、推送和发布，无需逐项重复询问。用户明确指定分支、渠道、版本，或要求先审核、仅改代码、暂不升版、暂不打包、暂不推送、暂不发布时，按其限定执行。

按完成的任务批次交付，每次保存或中间修正不单独发版。同一批改动只向选定渠道发布一次；失败重试复用原计划。仅维护 skill、协作规范或其它与软件无关的内容不触发软件升版、打包和发布，其提交与分支同步按当前任务授权执行。

## 升版前提与审核

- 查看适用的 AGENTS.md、任务开始时的版本、`git status --short`、暂存与未暂存 diff 及新增文件，区分本次修改与用户原有改动。仅纳入本次授权内容。
- 如果全部改动都与软件功能、行为、界面、配置、数据、运行依赖、构建分发及使用说明无关，可以不升版、不重打包、不发布。例如只维护仓库介绍、协作规范、skill、内部记录或不随软件分发的素材。按实际影响判断，不仅看路径；软件使用说明的修正仍需审核。
- 混合改动只依据软件相关部分判级。发现本次引入的问题，在授权范围内修复；交付阻塞未解决时停止发布。没有实际改动不升版；用户明确要求升版时执行。

## 改动分级与默认渠道

| 级别 / 脚本参数 | 判定依据 | 正式版基础号变化 | 默认分支 / 发布类型 |
| --- | --- | --- | --- |
| 重大不兼容变更 / `major` | 核心使用方式发生不兼容变化，或配置、数据、接口变更需要用户迁移 | `x+1.0.0` | `Beta` / Pre-release |
| 新功能或中等改动 / `minor` | 新增用户可用能力、兼容的功能扩展或较大界面改版 | `x.y+1.0` | `Beta` / Pre-release |
| 小型兼容改动 / `patch` | 恢复既有正确行为的小 bug 修复、局部性能优化、小范围界面或使用说明修正，影响范围明确且不新增能力、不改变主要流程 | `x.y.z+1` | `main` / 正式 Release |

- 按用户影响而非改动行数或提交前缀判级。新增能力即使代码很少也走 Beta；修复既有承诺行为不因补写代码而自动算新功能。
- 混合改动取最高版本级别和较高发布风险；含新功能或重大改动的一批默认整体走 Beta。可独立交付的小修复可以拆成单独批次，不把同一项改动在两个渠道重复升版发布。
- 影响面较大的内部重构、核心流程改造或高回归风险的性能调整先走 Beta，即使其兼容性对应 `patch`。发布渠道按风险选择，版本级别按实际兼容性与功能变化判断，不为选择 Beta 人为抬高版本。
- 表中基础号用于开启新版本线；活动 Beta 继续迭代时按下文规则增加 `beta.N`，不对每次迭代重复增加基础号。选定段加 1、后续段归零，不按十进制进位；`v1.2.9` 小更新为 `v1.2.10`。

## 分支选择、同步与例外

- 任务开始时预判目标分支，完成审核后复核。先核对远端目标分支和工作区状态；当前分支不决定发布渠道。目标不同或存在无关未提交改动时，优先在隔离 worktree 中基于目标分支工作，只移植本次授权的改动，保留用户原工作区；不先把新功能提交到 main 再决定发 Beta。
- **仅修复 Beta 中尚未转正的功能**：即使只是小 bug，也留在 `Beta`，增加预发布序号并重新打包发布 Pre-release；不能为遵守“小修复走 main”把未转正的新功能带进正式版。
- **正式版已有的小 bug**：基于 `main` 独立修复并发布 patch；如果修复最初写在 Beta，只移植必要修复及其依赖，不把整条 Beta 分支合进 main。无法与未转正功能分离时，保留 Beta 交付并说明原因。
- main 改动按下方“main → Beta 主动同步”规则及时同步，并在 Beta 开发或发布前补查；不以 main 已发布 Release 为同步前提。
- **Beta 转正式版**：仅在用户明确要求转正，或已约定的转正条件实际满足时执行；不能仅因自动测试通过就自行转正。核对候选内容后合入 main，按下文 `--promote` 规则沿用基础号，在 main 重新构建并发布正式 Release。
- 用户明确指定的分支或渠道优先于默认规则；远端并发变化、实质性同步冲突或无法确定改动边界时，保留现状，先解决具体阻塞，不自动强推、覆盖用户改动或换渠道规避问题。

### main → Beta 主动同步

- **main 交付后同步**：Codex 完成本批 main 提交（含已授权的 PR 合并）后，在任务结束前将该来源提交及 Beta 尚缺的 main 改动同步到 Beta。不必等待 Release 成功，也不对每次保存或中间提交反复同步。覆盖软件修改、文档、skill 和协作规则；仅编辑文件而未提交时，不自行创建 main 提交来触发同步。
- **Beta 开工前补查**：开始以 Beta 为目标的开发或发布任务时，在修改源码或计算发布版本前更新远端分支信息，检查 Beta 是否包含 main 的最新改动。补查默认以最新 `origin/main` 为来源；本地 main 另有未推送提交时，仅纳入当前任务已授权的内容，不把其他任务的本地提交自动带入。无法读取最新远端状态时说明具体阻塞，不宣称已同步。
- **同步方式与核验**：先核对来源、目标及工作区，记录来源 main 的完整提交 SHA。优先将 main 合并到 Beta，保留 Beta 未转正功能及双方历史；已经包含的提交不重复处理。历史曾使用定向移植时，结合实际差异确认改动是否等效，不能只凭 SHA 不同认定缺失。完成后核对源码、共享文档和规则均已带入，并针对实际合并变化执行必要检查。
- **推送范围**：本批 main 已获授权并完成推送（或已授权 PR 已合并到远端 main）时，默认授权推送对应的 Beta 同步结果；Beta 开工前补查默认允许同步并推送远端 main 的遗漏改动。用户要求仅本地操作、暂不推送、暂不同步或限定只改某分支时优先遵从。本地 main 尚未推送时仅做本地同步，不借此推送 main 或泄露其未推送内容；推送前核对全部待推送提交，不夹带其他任务尚未获推送授权的本地提交。
- **保护正在进行的工作**：存在未提交修改、分支被其他 worktree 使用或并行任务正在操作时，使用隔离 worktree 和临时分支准备同步结果，不擅自暂存、stash、重置、切换或覆盖用户工作区。只有能安全更新目标分支时才推进；否则保留可复核的结果，报告哪些本地或远端步骤仍未完成。
- **版本与发布**：保留 Beta 渠道的 VERSION 和 README 当前版本表示，合入 main 的实际功能修复及文档更新，不直接照搬正式版版本号。若旧 Beta 线已关闭，在下一次实际 Beta 发布时按现有版本规则开启新线。纯同步不增加 Beta 序号、不重打包、不创建标签或 Release；Beta 本次开发的正常交付仍按原发布流程执行。
- **冲突与停止条件**：版本和渠道专属字段可按上述明确规则处理；功能、配置或数据语义存在实质性冲突、改动边界不明、分支历史异常或远端并发变化时，停止自动推进，说明具体阻塞，不整文件偏向某一分支、不强推、不丢弃任一方改动。交付分别说明来源 SHA、本地 Beta 和远端 Beta 的同步状态；main 已发布但 Beta 同步受阻时如实报告两者状态。
- **触发边界**：只读咨询、仅审核、仅维护 skill 或协作规则的任务不因此执行同步、提交或推送；若这类修改随后在已授权任务中提交到 main，仍纳入该次 main 交付后的同步范围。这是 Codex 执行任务时的规则，不安装后台监听、Git hook 或 GitHub Actions。

## 发版前预检与版本计算

**在修改 VERSION、README 或打包之前**，执行只读脚本 [scripts/next_version.py](scripts/next_version.py)，实时读取本地标签、远端标签及全部分页的 GitHub Release：

```powershell
# --current 是本批在目标发布分支修改 VERSION 前记录的版本；--bump 根据审核结果选择。
# 正式版小修复：main 发布 patch。
.\.venv\Scripts\python.exe -B .agents\skills\review-and-bump-version\scripts\next_version.py --branch main --current 1.2.3 --bump patch
# 新功能：从当前正式基线在 Beta 开启 minor 预发布。
.\.venv\Scripts\python.exe -B .agents\skills\review-and-bump-version\scripts\next_version.py --branch Beta --current 1.2.3 --bump minor
# 继续修复同一条 Beta 版本线。
.\.venv\Scripts\python.exe -B .agents\skills\review-and-bump-version\scripts\next_version.py --branch Beta --current 1.3.0-beta.1 --bump patch
```

- 脚本依赖 Git、已登录且可读取目标仓库 Release 的 GitHub CLI；Python 使用标准库。未准备好时说明缺项，不猜版本或静默降级为离线计算。脚本不会改文件、提交、创建标签、推送或发布。
- 先核对 origin、更新器 `REPOSITORY` 与脚本目标仓库一致，当前为 `TimeseekerKK/ValorantToxicTamer`；核对选定的目标分支已经包含远端对应分支的改动。跨分支移植时记录目标分支修改 VERSION 前的版本作为 `--current`，不能直接套用来源分支的版本。脚本确认当前分支和 remote URL，但不证明源码已经同步、渠道选择正确或完成审核。
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
| `Beta` | `origin/Beta` | `1.3.0-beta.2` | `v1.3.0-beta.2` | `v1.3.0-beta.2` | 预发布 / 否 |

- 分支大小写以实际仓库为准，当前为 `main` 和 `Beta`。按“分支选择、同步与例外”确定发布来源并准备目标工作区；默认授权必要的定向移植和分支准备，不把 Beta 整体合入 main 作为日常小修复的捷径。其它分支或 detached HEAD 也先按改动性质选择目标，不直接从不明来源发布。
- `valorant_toxic_tamer/app_version.py` 的 `VERSION` 写入脚本返回的完整 `version`，不带 v。README 标题和表示当前版本的内容用 `v` 加完整版本；保留历史记录与测试样例。**Release title 必须与完整 Git 标签完全一致**，使用脚本的 `title`，其值应等于 `tag`：正式版如 `v1.3.0`，Beta 如 `v1.3.0-beta.2`，保留 Beta 序号，不加软件名、空格、日期或说明。渠道由预发布标记表示，正文说明修改内容及安装包与免安装版的区别。
- **核对目标分支的更新器兼容性**：发布 Beta 前检查当前源码及相关测试，确认支持完整 `-beta.N` 解析与比较：Beta 序号按整数比较，同基础号正式版高于任何 Beta，较高基础号始终更高。正式渠道仅接收正式 Release；Beta 渠道能力以目标分支实际实现为准，不因发布 Pre-release 自动改变用户的更新渠道。不以旧版技能中的实现状态代替当前代码证据；已支持的能力核实即可。
- 完成版本同步和兼容性检查后，从对应分支本次源码执行 `scripts/build.ps1`，由脚本读取 `VERSION`，重新构建 `dist/ValorantToxicTamer-v<完整版本号>.exe`，保留 `-beta.N` 后缀；打包依赖检查使用同一生成路径。由同次构建生成安装包 `dist/ValorantToxicTamer-Setup-v<完整版本号>.exe` 和固定名称的免安装附件 `dist/ValorantToxicTamer.exe`，本地保留带版本号的免安装 EXE 便于追溯。不能复用另一分支的旧产物或重命名旧 EXE；正式交付双附件时不能使用 `-SkipInstaller` 跳过安装包。若有 Windows 版本资源，数字元组使用基础号的 `x.y.z.0`，字符串版本保留完整版本；未配置资源时不声称 Windows 文件属性已更新。

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
3. 先创建草稿 Release，显式设置计划的 tag 和与其完全一致的 title，并上传同次构建的两个附件：`ValorantToxicTamer-Setup-v<完整版本号>.exe` 和 `ValorantToxicTamer.exe`。安装包名称必须与本次应用 `VERSION` 和 Release 标签一致，并保留 `-beta.N` 后缀；固定名称的免安装附件也必须来自本次版本构建。新版更新器明确选择安装包；固定名称的免安装附件供手动运行，并兼容旧版更新器的过渡更新。撰写正文时读取并遵循 [write-release-notes](../write-release-notes/SKILL.md)，用简体中文说明本次修改，并在末尾提醒安装包与免安装版的区别及免安装版应用内自动更新会转为安装版；不另列完整版本、来源分支、源码提交和验证说明，实际附件名中的版本号保留。CLI 多行正文使用文件传入。
4. 核对源码提交、标签、标题、附件与远端最新状态后发布：main 的基础号须高于最新正式版，设置 `draft=false, prerelease=false, latest=true`；Beta 须仍处于开放版本线，设置 `draft=false, prerelease=true, latest=false`。Beta 不得替换正式版 Latest。
5. 重试先使用 `--resume` 原目标，已有标签需传 `--expected-commit`。结果 `status=published` 只代表元数据匹配，仍须核实附件；草稿补齐缺项后再发布。同名已发布内容不匹配则停止，不擅自覆盖附件、使用 `--clobber`、删除 Release 或切换渠道。Beta 晋升用 main 的提交和正式标签重新构建，不直接把 Beta Release 改为正式版。
6. 发布后重新读取远端，检查完整 tag、与 tag 完全一致的 title、tag 指向、渠道、非草稿状态和 Latest，再逐一核对两个附件的名称、上传状态、大小及 SHA-256（优先服务端摘要，不可用时下载校验），并确认正文包含与实际附件一致的下载说明。上传或发布失败时报告实际远端状态，不能只凭本地标签、推送或脚本计划声称发布完成。

GitHub CLI 参数参考：[API 与分页](https://cli.github.com/manual/gh_api)、[创建 Release](https://cli.github.com/manual/gh_release_create)、[编辑 Release](https://cli.github.com/manual/gh_release_edit)。main 发布草稿用 `--draft=false --prerelease=false --latest=true`，Beta 用 `--draft=false --prerelease=true --latest=false`，创建 Beta 草稿也显式指定 `--prerelease --latest=false`。`--verify-tag` 只检查远端标签存在，仍需核对完整提交。

## 验证与交付

修改本 skill 的版本脚本时，执行离线回归测试：

```powershell
.\.venv\Scripts\python.exe -B .agents\skills\review-and-bump-version\scripts\test_next_version.py -v
```

交付说明判级依据、旧版 → 完整新版、来源分支、发布渠道、源码/README/EXE 同步状态、实际验证结果、对应提交和 Release 链接。静态检查、脚本回归与真实 EXE/游戏验证分别说明。仅维护 skill 时不触发软件升版或发布。
