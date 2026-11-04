# docs 全量 Obsidian 风格相关链接

> 状态：已完成。
> 前置：上一轮项目知识库迁移成果已提交为 `c965f7ed8acec30ebf7d956ac0f8cd3022b44675`。
> 最终范围：用户确认将相关链接扩展到 `docs/` 下全部 Markdown 文档。

## 目标

- 为 `docs/` 下全部 Markdown 文档添加 Obsidian 风格“相关链接”段落。
- `docs/backend/API_SPEC.md` 保持用户指定的三条裸 slug wiki link 原文。
- 其余文档按所在分区、主题和当前实现上下文生成 2–5 条链接；每条链接使用仓库相对路径与 `|标签` 形式，避免裸 slug 跨目录歧义。

## 执行步骤

1. 盘点 `docs/` 下全部 Markdown 文档和既有相关链接。
2. 按目录枢纽与主题关键词生成分区相关候选链接；每页过滤自身、去重并保留最相关的 2–5 条。
3. 在文件末尾追加 `## 相关链接`；已有该段落的 `API_SPEC.md` 跳过。
4. 校验每篇文档段落唯一、链接数量在 2–5 条、目标 Markdown 文件存在且不是自链接。
5. `API_SPEC.md` 的三条裸 slug 是用户指定原文，不按文件存在性校验。

## 验收标准

- `docs/` 下 181 篇 Markdown 均有唯一 `## 相关链接`。
- 除 `API_SPEC.md` 的三条用户指定裸 slug 外，所有 wiki link 指向存在的仓库 Markdown 文件。
- 相关链接按分区和主题生成；每篇 2–5 条，不自链接。
- `git diff --check -- docs prompts/tasks/current_task.md` 通过。

## 不在范围内

- 建立 Obsidian vault 配置、生成式索引或新的知识库副本。
- 修改 API 行为、OpenAPI 合约、业务代码或生产环境。

## 执行结果（2026-11-04）

- 已为除 `API_SPEC.md` 外的 180 篇 `docs/` Markdown 添加相关链接，全部文档均含该段落。
- 本次提交纳入 179 篇已跟踪 Markdown；`docs/architecture/MINIPROGRAM_CONSUMER_MAP.md` 与 `docs/architecture/REVIEW_STATS_HUB_ASSESSMENT.md` 仍为未跟踪文件，仅在工作区追加链接，不并入本次提交。
- 其余链接均指向仓库内存在的 Markdown 文件，按目录枢纽和主题上下文选择；未创建旧 Wiki slug 对应的新页面。
- `API_SPEC.md` 保持用户指定的三条裸 slug；批量脚本已跳过该文件。
- 校验结果：181/181 含唯一段落；180/180 非自链接且目标文件存在；API_SPEC 的 3 条裸 slug 按 Obsidian 名称解析处理。
- `git diff --check -- docs/backend/API_SPEC.md prompts/tasks/current_task.md` 通过。
