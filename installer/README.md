安装脚本使用 Inno Setup 6.7.4，构建入口为 `scripts/build.ps1`。

`ChineseSimplified.isl` 来源于 [简体中文翻译维护仓库](https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation)，固定提交 `1ff90acc4ed4aee82b1cda43253243deee3daed4`；许可证保存在 `ChineseSimplified.LICENSE`。

日常安装默认申请管理员权限。隔离验证使用 `/CURRENTUSER` 和独立 AppId，不改动正式安装记录。

静默卸载必须显式传入 `/KEEPDATA=1`（保留）或 `/KEEPDATA=0`（删除整个软件安装目录）。交互卸载默认“不保留个人数据”，界面会展示完整删除范围。
