# ValorantToxicTamer · v1.2.0-beta.1

**Valorant反嘴臭工具**。Windows 托盘快捷消息工具，支持自定义消息及队伍、全体聊天快捷发送。目标运行环境为 Windows 10 / 11、Python 3.11、PySide6。

本仓库提供源码，初始消息列表为空，不附带语录库，可自行添加消息或导入个人 TXT 文件。

- **F8**：Enter 打开队伍聊天，输入下一条消息，再按 Enter。
- **F9**：Shift+Enter 打开全体聊天，释放 Shift 后输入下一条消息，再按 Enter。
- 共用一个列表、循环索引、发送锁和默认 **500ms** 冷却；冷却从输入流程结束时开始。
- RegisterHotKey 使用 `MOD_NOREPEAT`；长按不连发，发送中和冷却中的触发直接丢弃。
- 新进程从第一条开始；本地输入流程发生异常不推进索引。
- 消息增删改、上下移动、TXT 追加导入和导出、JSON 自动保存。
- 界面字体支持 9–16 pt 调节，保存后生效并在重启后保留；长消息预览可滚动查看全文。
- 启动默认隐藏到托盘，关闭窗口隐藏到托盘，从托盘菜单退出；默认不开机启动。

## 使用

首次使用按以下顺序操作：启动程序 → 双击托盘图标 → 添加或导入消息 → 切回游戏 → 按 F8 / F9 发送。

### 1. 启动程序

如果已有打包好的程序，双击 `ValorantToxicTamer.exe` 即可启动。

从源码运行时，先安装 Python 3.11，在项目目录打开 PowerShell，执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe main.py
```

前两条命令只需在首次准备环境时执行，之后运行第三条即可。如果 `py` 找不到已安装的 Python，请使用 Python 3.11 的 `python.exe` 完整路径执行第一条命令。

程序默认启动后隐藏到系统托盘。双击任务栏右下角的托盘图标打开主窗口；如果没看到图标，请展开隐藏图标区域。

### 2. 添加和管理消息

在主窗口的「消息管理」页操作：

- **添加**：输入一条单行消息并确认。
- **编辑**：选中消息后点击「编辑」，或直接双击消息。
- **删除**：选中消息，点击「删除」并确认。
- **上移 / 下移**：调整消息的发送顺序。
- **TXT 导入**：从文本文件追加消息，每行一条，空行会被忽略。
- **TXT 导出**：将当前列表导出，方便备份或迁移。

所有消息更改自动保存。修改列表或重新启动程序后，循环从第一条开始；窗口上方的「下一条」显示接下来要发送的内容。选中列表中的某条消息用于编辑，不会改变发送顺序。

导入文件建议使用 UTF-8 编码，也支持 UTF-8 BOM 和 GB18030；导出文件为带 BOM 的 UTF-8。每条消息不能包含换行、制表符或控制字符。

### 3. 在游戏中发送

1. 添加好消息后，切回 Valorant，让游戏保持在前台。
2. **关闭游戏聊天框，并松开 Shift / Ctrl / Alt / Win。**
3. 按下对应快捷键，程序会打开聊天框、输入下一条消息并按 Enter 发送。

| 默认快捷键 | 聊天频道 | 操作 |
| --- | --- | --- |
| **F8** | 队伍 | 自动按 Enter 打开聊天并输入消息 |
| **F9** | 全体 | 自动按 Shift+Enter 打开聊天并输入消息 |

两个频道共用同一个消息列表和发送进度：例如先按 F8 使用第一条，再按 F9 就会使用第二条，到末尾后回到第一条。

默认发送冷却为 **0.5 秒**，从本次输入结束后开始计算。长按快捷键不会连续发送；输入期间或冷却期间再次按键会被忽略。发送过程中请保持游戏在前台，不要切换窗口或按住修饰键。

### 4. 调整设置与退出

打开主窗口的「设置」页，修改后点击 **保存设置**：

| 设置项 | 使用说明 |
| --- | --- |
| 队伍聊天快捷键 / 全体聊天快捷键 | 可选择 F1–F11，两个频道必须使用不同按键；遇到快捷键冲突时可在此更换 |
| 共用发送冷却 | 直接输入 0.2–2 秒之间的数值（如 `0.8`），点击保存后生效；无效数值会提示错误 |
| 字体大小 | 在「界面显示」中选择 9–16 pt，默认 11 pt，点击保存后生效；鼠标滚轮只滚动页面，不改变字号 |
| 启动后隐藏到系统托盘 | 默认勾选；取消后，下次启动会显示主窗口 |
| 随 Windows 登录自动启动 | 默认关闭，按需勾选并保存；移动程序位置后需重新设置 |

关闭主窗口会隐藏到托盘，程序继续运行。需要完全退出时，右键托盘图标，选择 **退出程序**。

### 5. 检查更新

在「设置」页点击 **检查更新**，程序会查询本仓库最新正式 GitHub Release，比较版本号并查找其中的 EXE。发现新版本后弹出「发现新版本,是否更新」：选择「否」保持当前程序继续运行；选择「是」则下载并校验文件，退出当前程序，覆盖原位置的 EXE，然后重新启动。仍在运行的同路径程序会被强制退出；消息和设置保留在原数据目录。

下载失败时保留当前版本；覆盖失败会显示错误并保留原文件，启动失败会尝试恢复旧 EXE。覆盖更新仅支持打包后的 Windows EXE，且程序所在目录须可写；源码运行不能覆盖 Python 解释器。仅检查正式 Release，不安装预发布版本或降级。

更新查询和下载使用 Windows 原生证书信任链，保持 HTTPS 证书与主机名校验。若仍提示证书校验失败，请检查系统日期时间、Windows 证书更新，以及代理或安全软件的 HTTPS 证书设置，然后重试。

当前版本为 Beta 预发布，仍只检查正式 Release；版本比较支持 `beta.N`，同基础号正式版高于 Beta，较低基础号不会覆盖当前版本。

正式发布时使用 `v1.2.3` 形式的版本标签，Beta 使用 `v1.2.3-beta.1`；同步修改 `valorant_toxic_tamer/app_version.py` 中的 `VERSION`，并上传单文件 `ValorantToxicTamer.exe`。通过 `scripts/build.ps1` 打包时会一并包含独立更新脚本和证书验证依赖。

### 常见问题

**按快捷键没有反应怎么办？**

打开主窗口，检查消息列表是否为空、快捷键是否注册成功，并查看窗口底部的状态提示。确认游戏处于前台、聊天框已关闭、修饰键已松开，且发送冷却已结束。快捷键被占用时，到「设置」中换一个按键并保存。

**输入中断或只出现了部分文字怎么办？**

先检查并清理游戏聊天框内残留的文字，关闭聊天框后再重试。主窗口的「下一条」可用于确认当前发送进度。

**如何备份消息，或迁移到另一份程序？**

在「消息管理」中点击「TXT 导出」保存文件，再到目标程序中使用「TXT 导入」。导入会追加到已有列表。

## 项目结构与开发

```text
ValorantToxicTamer/
├── main.py                    # 源码和打包共用的启动入口
├── valorant_toxic_tamer/       # 应用代码和随程序分发的更新脚本
│   ├── app.py                 # 应用初始化和生命周期
│   ├── ui.py / ui_theme.py    # 窗口和主题
│   ├── config_manager.py      # 配置存储和开机启动
│   ├── message_manager.py     # 消息管理
│   ├── hotkey.py / sender.py  # 快捷键和发送流程
│   ├── win32_api.py           # Windows 接口
│   └── ...                    # 托盘、更新、日志和版本等模块
├── scripts/                   # 构建脚本
├── tests/                     # 自动测试、原生检查和预览工具
├── requirements.txt           # 运行依赖
├── requirements-build.txt     # 构建依赖
├── data/                      # 源码运行数据与本地个人文件（不提交）
├── artifacts/                 # 检查报告和截图（不提交）
├── build/                     # 构建中间文件和生成的 .spec（不提交）
└── dist/                      # 打包产物（不提交）
```

在项目根目录执行自动测试和构建：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\scripts\build.ps1
```

源码启动仍使用 `main.py`，也支持 `.\.venv\Scripts\python.exe -m valorant_toxic_tamer`。应用内部使用包内相对导入，测试和辅助工具通过 `valorant_toxic_tamer` 导入模块。

源码运行继续读写项目根目录的 `data/`；打包版继续使用 `%LOCALAPPDATA%\ValorantToxicTamer\data`。移动代码目录无需迁移已有消息或设置。

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
