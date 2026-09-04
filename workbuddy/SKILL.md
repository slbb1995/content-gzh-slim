---
name: content-gzh-slim
display_name: Content 公众号 Slim
display_name_en: Content GZH Slim
description: 在明确或已确认默认的 Obsidian/飞书知识库与指定 IP 上执行受控公众号内容工作流，保留两次真人确认、回读保存和不发布边界。
description_zh: 在明确或已确认默认的 Obsidian/飞书知识库与指定 IP 上执行受控公众号内容工作流，保留两次真人确认、回读保存和不发布边界。
description_en: Run the controlled Content GZH Slim workflow with two human gates, verified save, and no publishing.
category: writing
version: 1.1.0
author: slbb1995
---

# Content GZH Slim for WorkBuddy

这是 WorkBuddy 的唯一公开入口。开始、继续、配置或查看公众号任务时使用；不得发布到公众号后台。

## 第一动作

1. 将当前 Skill 目录视为 bundle 根目录。
2. Windows 用 `py -X utf8 -B scripts/content-gzh-slim probe`；macOS 用 `python3 -B scripts/content-gzh-slim probe`。
3. `probe` 未返回 `status: ready` 就停止，不得手工替代正式 Run。
4. 读取 [完整公开入口合同](skills/content-gzh-slim/SKILL.md) 和 [运行命令](skills/content-gzh-slim/references/runtime-commands.md)。

## 内部职责

只在公开入口合同规定的阶段读取对应内部 Skill，不允许用户直接触发：

- Gate A 分析：[Analyzer](skills/content-gzh-analyzer/SKILL.md)
- Gate A 后上下文：[Context Retriever](skills/content-gzh-context-retriever/SKILL.md)
- 正文：[Writer](skills/content-gzh-writer/SKILL.md)
- 标题：[Headline](skills/content-gzh-headline/SKILL.md)
- 保存后的可选分发：[Distribution Pack](skills/content-gzh-distribution-pack/SKILL.md)

## WorkBuddy 数据位置

- Registry 默认放在 `~/.workbuddy/.content-workflows/knowledge-base-registry.json`。
- Runs 默认放在 `~/.workbuddy/.content-gzh-slim/runs`。
- 调用 `configure`、`start` 和后续命令时显式传入对应绝对 `--registry` / `--store` 路径。
- 不扫描电脑，不复制 Codex Registry、凭据或客户资料；迁移现有绑定必须单独取得确认。

## 硬边界

- 严格停在 Gate A 和 Gate B，模糊回复不算确认。
- Writer 只读唯一 Context Pack，不搜索知识库，不调用 Reviewer。
- 保存必须 create-only 并回读；saved 不等于草稿箱或发布。
- 对标网页必须先形成完整的本地文本或 Markdown 快照；摘要不能冒充全文。
