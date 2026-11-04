# ValorantToxicTamer · V1.0

**Valorant反嘴臭工具**。Windows 托盘快捷消息工具，支持自定义消息及队伍、全体聊天快捷发送。目标运行环境为 Windows 10 / 11、Python 3.11、PySide6。

本仓库提供源码，初始消息列表为空，不附带语录库，可自行添加消息或导入个人 TXT 文件。

- **F8**：Enter 打开队伍聊天，输入下一条消息，再按 Enter。
- **F9**：Shift+Enter 打开全体聊天，释放 Shift 后输入下一条消息，再按 Enter。
- 共用一个列表、循环索引、发送锁和默认 **500ms** 冷却；冷却从输入流程结束时开始。
- RegisterHotKey 使用 `MOD_NOREPEAT`；长按不连发，发送中和冷却中的触发直接丢弃。
- 新进程从第一条开始；本地输入流程发生异常不推进索引。
- 消息增删改、上下移动、TXT 追加导入和导出、JSON 自动保存。
- 启动默认隐藏到托盘，关闭窗口隐藏到托盘，从托盘菜单退出；默认不开机启动。

## 使用

使用 Python 3.11 创建项目虚拟环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe main.py
```

如果 `py` 找不到已安装的 Python，请使用 Python 3.11 的 `python.exe` 完整路径执行第一条命令。

启动后双击系统托盘图标添加消息。初始消息列表为空。进入游戏后，**先关闭聊天框，松开 Shift / Ctrl / Alt / Win，再按 F8 或 F9**。快捷键冲突会显示在主窗口，可在设置中更换为两个不同的 F1–F11 功能键（F12 为系统调试器保留）。不提供暂停、预览或退出快捷键。

修改消息列表会把索引重置为第一条。TXT 每行一条，忽略空行，导入追加到现有列表，先按 UTF-8/UTF-8 BOM 解码，失败时尝试 GB18030。导出为带 BOM 的 UTF-8。消息不允许换行、制表符或控制字符。

## 本地数据与设置

- 源码运行：项目内 `data/messages.json`、`data/config.json`。
- EXE 运行：`%LOCALAPPDATA%\ValorantToxicTamer\data\`，不写入 PyInstaller 临时解压目录。
- 首次运行自动创建数据目录、空消息列表和默认配置；本机数据不纳入版本控制。
- 消息 JSON 为字符串数组；配置字段及默认值见 `config_manager.py` 中的 `DEFAULT_CONFIG`，可通过程序设置页调整。
- JSON 先写临时文件，再原子替换；写入失败不更新内存列表。JSON 损坏时停止启动并提示路径，保留原文件，不静默重置。
- 同一数据目录使用实例锁，防止同时运行多个实例。
- 冷却可设置为 0.5–10 秒；“启动后隐藏到系统托盘”只控制启动时是否显示窗口，关闭窗口始终隐藏到托盘。
- 用户勾选并保存开机启动时，才写入当前用户的 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ValorantToxicTamer`；取消后删除该项。源码环境或 EXE 移动后需重新设置。

## 输入与验收边界

程序取得前台窗口所属 PID，再通过 Windows 公开进程列表中的可执行文件名 `VALORANT-Win64-Shipping.exe` 确认目标，不依赖窗口标题，也不再需要打开游戏进程查询完整路径。不读取游戏内存、不枚举游戏模块、不注入进程或 DLL、不使用游戏内部接口、不绕过 Vanguard。

发送前及各输入步骤检查同一窗口和进程是否仍在前台。检测到切换、修饰键干扰或 SendInput 失败时中止、尝试释放本程序按下的键、保留索引并进入冷却。退出会取消正在进行的输入并等待释放按键。

如果按 F8/F9 后没有效果，请查看主窗口底部状态。前台校验失败会显示当前前台进程名或具体 Windows 错误码。数据目录中的 `diagnostics.log` 记录快捷键是否收到、是否被冷却拦截、前台校验结果和输入调用结果；不记录消息正文或完整进程路径。日志单文件上限 256 KiB，最多保留两个轮转备份。

**“输入流程完成”仅表示本地 SendInput 调用完成，随后推进索引。当前版本没有聊天框视觉检测，不能检测“聊天框未打开但 SendInput 成功”的情况，也不能确认服务器收到消息。** 因此规格中的“聊天框未正常打开时不推进索引”尚不能完整验收。若需严格实现，需另行增加并在真实游戏界面上校准聊天框检测。

SendInput 使用 Unicode 输入中文，不修改剪贴板。打开聊天框等待 150ms，逐字符连续提交，不再额外等待 5ms；最终 Enter 前仍等待 50ms。每个字符前检查取消、前台窗口和修饰键。相较旧版，100 字减少 500ms 的预设等待，实际耗时还取决于系统调度和游戏处理速度。游戏是否接受这些输入、中文/表情是否正确显示、延迟是否合适，须实机验证。Windows 的前台检查与全局输入提交不能成为原子操作，切换前台时存在短暂竞态；发送期间请勿切换窗口。异常后可能留有部分文本，重试前请自行检查并关闭聊天框。

F9 的组合键使用左 Shift 扫描码：在同一次 SendInput 调用中提交 Shift、Enter 两个按下事件，中间不等待；保持 80ms 后释放 Enter，再等 30ms 释放 Shift。组合键阶段共 110ms。“同时按下”指同批提交，Windows 仍按顺序处理事件。随后等待聊天框并输入正文，最终发送只按 Enter。SendInput 返回成功仍不代表游戏接受了组合键。

程序不会自动提权。SendInput 受 Windows UIPI 限制，失败时显示实际结果，不尝试绕过限制。

## 测试与打包

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\build.ps1
```

输出：`dist/ValorantToxicTamer.exe`。EXE 首次启动创建独立的空消息列表；可用 TXT 从源码环境迁移消息。

请使用 `build.ps1` 构建：脚本临时隔离 `PATH`，避免把其他工具的 ICU DLL 打入程序，退出时恢复原环境；构建后自动检查这一依赖冲突。

最终 EXE 可在普通 Windows 会话中执行启动检查（请先退出正在运行的程序以释放 F8/F9）：

```powershell
Start-Process -FilePath .\dist\ValorantToxicTamer.exe -ArgumentList '--startup-check', '.\artifacts\packaged-startup.json' -Wait
Get-Content .\artifacts\packaged-startup.json
```

检查使用临时空消息列表，短暂打开设置页后退出，不调用 SendInput、不修改用户消息或开机启动项。报告中的 `passed: true` 表示检查通过。

测试覆盖共享索引、冷却起点、发送期间丢弃请求、异常释放、取消、前台切换、文件损坏保护、保存失败、TXT 编码、Windows 结构体布局、Unicode 代理对、快捷键防重复标记、冲突回退、过期事件丢弃及离屏界面。测试中的键盘输入均为替身，**不会向游戏或其他应用发送消息**。本机截图及检查报告不随仓库发布。

用户已实机确认 F8 队伍聊天、F9 全体聊天可用（F9 为原 80/80/80ms 时序）。同批按下及取消逐字等待的版本仍需复测，重点检查长消息是否完整、中文是否丢字。其余实机验收包括：长按与交替快速触发、游戏内切换窗口、Windows 10/11 托盘交互和开机启动。不要把离线测试当成游戏内验证。

### 验证范围

截至 2026-11-04，Python 3.11.9 / PySide6 6.12.0 / PyInstaller 6.22.3：

- 48 项自动测试通过，涵盖进程列表识别、非游戏窗口拒绝、查询失败、识别期间切换前台、输入期间的窗口/PID 校验，以及 F9 同批按下、批次部分提交失败、取消/失焦释放和最终单独 Enter；新增长消息不增加预设输入等待、连续输入期间逐字符中止检查。
- 此前本机原生检查已验证快捷键注册、默认隐藏、托盘菜单打开设置、关窗隐藏和退出释放；旧输入时序的 EXE 也通过过启动检查。这些记录不代表当前输入时序已在游戏中验收。
- 当前同批按下 Shift+Enter、取消逐字等待的版本尚需游戏内速度与完整性复测。之前用户确认成功的 F9 版本使用原 80/80/80ms 时序。
- 可运行 `python tests/native_smoke.py` 复核原生界面行为（会短暂显示窗口并自动退出，使用临时数据目录且不调用 SendInput）；受限沙箱可能阻止快捷键注册。
- 开机启动注册表行为尚未实际开启验收。

## 许可证

Copyright (c) 2026 TimeseekerKK。

本项目采用[自定义限制性许可证](LICENSE)，提供源码供非商业使用，不是开源许可证，也不是 GitHub 标准许可证。

- **禁止商用**：未经书面授权，不得销售、提供收费服务、广告获利或集成到商业产品中等。
- **禁止二改**：未经书面授权，不得修改、改编、移植或制作衍生版本，包括私下修改；允许按原流程构建未经修改的项目。
- **保留署名**：原样复制或分发时，必须保留 TimeseekerKK 署名、项目来源及完整许可证。
- 程序内正常编辑个人消息、导入导出文本和调整设置不属于二次修改。
- 第三方依赖遵循各自许可证；适用法律和 GitHub 平台条款所保留的权利不受排除。

以上为摘要，具体授权范围以 `LICENSE` 全文为准。

## 参考文档

- [Qt for Python 托盘示例](https://doc.qt.io/qtforpython-6/examples/example_widgets_desktop_systray.html)
- [RegisterHotKey 与 MOD_NOREPEAT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey)
- [SendInput 返回值及 UIPI 限制](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
- [KEYBDINPUT Unicode 输入](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput)
- [Windows 进程列表快照](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot)
- [PyInstaller 运行路径](https://pyinstaller.org/en/stable/runtime-information.html)
