# PHASE P9：干货文章人设融合与素材检索修复

## 状态

- 当前：源码实现、回归、1.0.1 构建与本机安装回读完成；未打 Tag、未建外部 Release、未发布内容
- 授权：`EXECUTE_PHASE: P9`
- RED 检查点：`ef73308`
- GREEN 检查点：`6a99d7a`

## 用户结果

`ganhuo` 继续交付方法、解释、清单和避坑价值，同时使用已批准 IP 的表达方式与专业判断连接读者。Gate A 在进入正文前冻结读者处境、专业判断和用户可执行的核验动作，Writer 不再因“有人设、有观点”而切换为 `huati`。

## 范围

1. `writer_mode` 与 `voice_and_viewpoint` 解耦。
2. Gate A 强制包含 `voice_mode`、`professional_judgments`、`reader_situations`、`verification_actions`。
3. Profile 按章节语义装配身份事实、表达方式、专业判断、读者理解、真实经历和业务边界；每类最多四条，总计最多二十条。
4. `ganhuo` 的主要问题单元使用“读者真实处境→IP 明确判断→专业解释或证据→用户可执行核验动作”，不要求每个自然段机械重复。
5. 飞书04只在 Manifest 指定根下递归两层；03保持直接子级；读取数量预算不变。

## 非目标

- 不修改 `must_keep` / `must_avoid` 合同。
- 不增加 Reviewer、Skill、Gate 或第二份 Context Pack。
- 不读取或修改客户01—05资料。
- 不构建候选、不安装、不打 Tag、不建 Release、不保存或发布内容。

## 验证

- 目标 RED：8项预期失败，分别覆盖 Context 缺字段、Gate A 未拦截缺字段、Profile 未分类、04不递归和 Writer 规则缺失。
- 目标 GREEN：5个测试方法全部通过。
- 全量回归：79个测试全部通过。
- 覆盖率：当前 Python 环境未安装可选 `coverage` 模块，未生成百分比，不擅自安装依赖。
- 发布校验：初次在未获构建授权时因清单未重建而停止；补充安装授权后已重建并通过，结果见下节。

## 1.0.1 构建与安装补充授权

- 用户随后明确要求安装新版，并确认目标 `C:\Users\z4636\.codex\skills` 及删除旧版。
- `VERSION` 更新为 `1.0.1`，发布清单重建后通过：6 个技能、70 个交付文件。
- 本机包：`content-gzh-slim-1.0.1`；来源提交：`2abc24fef9774fcd2f10612087e3130cbc7bb190`。
- 激活模式：`copy`；安装器 `probe`：`ready`。
- 旧包与六个旧技能目录先进入同盘临时回滚目录；新版完全验证后，该临时旧版已按用户要求永久删除。
- 没有改动客户知识库、现役 V1、草稿箱或公众号发布状态。

## 闭环决定

- 决定：`writeback`
- 写回：Master SPEC、Analyzer/Context/Writer 契约、Runtime、Schema、fixtures 和回归测试。
- 下一轮复用键：`ganhuo_persona_viewpoint_and_bounded_feishu04_depth`
