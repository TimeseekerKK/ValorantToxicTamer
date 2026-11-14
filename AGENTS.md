# 项目协作规则

## main → Beta 同步

- 完成本批 `main` 提交或已授权的 PR 合并后，在任务结束前主动将改动同步到 `Beta`；开始以 `Beta` 为目标的开发或发布任务时，先检查并补齐遗漏的 main 改动。
- 执行时读取 [review-and-bump-version](.agents/skills/review-and-bump-version/SKILL.md) 的“main → Beta 主动同步”规则，按其中的来源、推送权限、版本处理和冲突边界操作。
- 只读咨询、仅审核、仅维护 skill 或协作规则时，不因此执行分支同步；用户明确限制同步或推送时遵从其要求。纯同步不触发软件升版、打包或发布。
