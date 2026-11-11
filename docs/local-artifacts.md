# 本地产物管理

应用源码位于 `valorant_toxic_tamer/`，自动测试位于 `tests/`，构建和性能检查脚本位于 `scripts/`。以下约定用于整理本地工作文件，不改变应用启动、数据存储或发布流程。

## 目录职责

| 位置 | 内容 | 是否提交 |
| --- | --- | --- |
| `artifacts/performance/` | 性能报告与可比较的基线，保留现有 CI 路径 | 否 |
| `artifacts/checks/` | 检查报告和日志；旧根目录报告放在 `legacy/`，专题报告保留专题名 | 否 |
| `artifacts/screenshots/` | 窗口截图和预览结果，专题截图放在对应子目录 | 否 |
| `artifacts/releases/<完整版本>/` | 对应版本的发布记录、说明、校验结果与日志 | 否 |
| `artifacts/releases/legacy/` | 本次整理时未按文件名确定版本的历史发布记录 | 否 |
| `artifacts/archive/` | 历史源码快照和个人素材，保留原始内容 | 否 |
| `artifacts/migrations/` | 本地整理清单，记录原路径、新路径、文件大小和 SHA-256 | 否 |
| `scripts/local/release/` | 本地发布命令环境与 CLI 入口 | 否 |
| `scripts/local/diagnostics/` | 本地进程模块查询、内存采样脚本 | 否 |
| `scripts/local/archive/` | 一次性实验、旧版发布和检查脚本，保留原目录关系及内容 | 否 |
| `.tools/` | 便携工具及其原有文档，如 `gh.exe`、`actionlint/` | 否 |
| `build/`、`dist/` | 构建中间文件和打包 EXE | 否 |
| `data/` | 个人配置和语录，独立保留 | 否 |

报告目录按需创建；历史发布记录可以按需要清理，不要求保留空的 `releases/`。

`scripts/local/` 与 `.tools/` 由 `.gitignore` 排除，属于本机辅助文件，新克隆仓库不会包含它们。适合团队复用的脚本应单独审核，再纳入受版本控制的 `scripts/`。

## 当前入口

- 性能检查继续使用 `scripts/performance_baseline.py`，默认输出到 `artifacts/performance/`。
- `tests/native_smoke.py`、`tests/hotkey_delivery_probe.py` 输出到 `artifacts/checks/`。
- `tests/test_windows_ui.py` 的示例截图输出到 `artifacts/screenshots/`。
- `tests/ui_preview.py` 输出到 `artifacts/screenshots/ui-redesign/`。
- 本地发布 CLI 入口为 `scripts/local/release/run_release_cli.py`，同目录的 `release_env.py` 使用 `.tools/` 中的便携 GitHub CLI。它只在明确执行命令时使用已有认证环境。
- `scripts/local/diagnostics/read_process_modules.py`、`sample_live_memory.py` 的输出位于 `artifacts/checks/processes/`。前者接受目标 PID，后者采样本仓库 `dist/` 中正在运行的应用。

旧脚本可能绑定已经删除的 EXE、旧模块接口、旧产物路径或历史发布版本。归档保留其原始内容作为记录，不作为当前发布或检查入口；重新使用前应逐项检查。历史 JSON、日志中记录的原路径也保持原样。

## 工作树与源码快照

`artifacts/release-main-v1.6.0/` 目前仍是已登记的 main 分支 Git 工作树，本次整理不移动或修改它。它是当前目录约定的例外：其中的源码、脚本、报告和 `.venv` 链接由该工作树管理。后续迁出应单独处理 Git 登记和目录链接，不能作为普通报告目录直接删除。

`artifacts/archive/snapshots/` 保存历史源码快照，其中的 Python 文件属于快照资料，不是当前工具入口。

## 后续文件存放

新报告直接输出到对应类别；手工检查与截图工具应先创建输出目录。需要归档某次实验时，给检查结果和截图使用相同的专题名，脚本单独存放。发布记录使用完整版本号，包括 `-beta.N` 后缀。

本次仅整理本地文件和报告输出位置，不新增自动清理行为。清理前先区分报告、个人数据、工具、源码快照与 Git 工作树。
