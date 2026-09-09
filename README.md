# Content GZH Slim

`content-gzh-slim` 是一套可独立安装、面向多知识库和多 IP 的微信公众号内容工作流。

当前版本在 P8 已验收主链上增加 `content-source-v1`：可从明确输入或经过真人确认的公共 Registry 解析 Obsidian/飞书知识库，选择同库任意 active IP，并在 Gate A 后冻结、回读和校验所有来源。ZSK、口播和公众号仍是三个独立产品，不存在运行时代码依赖。

## 一段想法也能开始

例如：“我想讲讲服务签约之后，持续陪伴还有什么价值。”有明确对标就优先拆解；没有对标，Agent 会查看已绑定知识库的同行素材和结构方法，选择有用的观点、场景、理由及组织方式，再结合当前客户的业务事实和 IP，给出一个推荐方向。客户确认方向后才继续正文与标题，最后仍需第二次真人确认。

Agent 负责选材，客户无需先找对标或选择结构卡。04 同行材料提供可展开的内容价值，方法材料提供讲述和论证方式；公众号保留长文的段落发展和证据组织，不直接拉长口播模板。已有材料不足时说明具体缺口，不把空检索说成已经使用知识库。

当前实现支持同库目录发现、完整候选预览和内部语义选材计划；两个后端都支持，飞书可发现 04 内的子目录。正式读取预算仍为 5 张业务、3 张同行、2 张方法。口播专用方法不会自动当成公众号方法。内部写作要求与需要逐字保留的正文分开处理。使用方法见 [运行命令](skills/content-gzh-slim/references/runtime-commands.md)。拉取仓库不等于更新本机安装或确认客户知识库绑定。

## 当前真相源

1. `CONTENT-GZH-SLIM-SPEC.md`：Master SPEC，产品与开发的最高真相源。
2. `SLIM-COMPASS.md`：每次执行前的轻量入口，不得新增 Master SPEC 中不存在的要求。
3. `project-state.json`：当前阶段和授权状态。
4. `PHASE-P8.md`：已完成的 P8 交付验收记录；当前发布状态以本 README、`VERSION` 和发布校验为准。

## 核心结论

- 可以明确填写知识库和 IP，也可以读取 `~/.codex/.content-workflows/knowledge-base-registry.json` 中已确认的工作流默认值。
- 同一知识库可以有多个 IP；同一套流程可以服务多个知识库、项目和 IP。
- primary 只是默认 IP；任何 active IP 都可显式选择。单个 Run 冻结一个知识库和一个 IP；换库或换 IP 会创建新 Run。
- 有 IP 时按 `05 IP → 03 业务知识 → 04 内容方法` 的顺序按需检索，不全量读取。
- 支持真实 Obsidian 与飞书读取、create-only 保存和回读；测试 Fixture 不参与真实运行。
- Gate A 后 Manifest、Profile 索引、03、04、05、Registry 或显式参考发生变化，会保留旧产物并停止。
- 主链只有两次真人确认：方向、正文与标题。
- Writer 只读取一份唯一 Article Context Pack。
- 正文确认后保存回本次指定知识库；单张封面和全平台分发包是可选支线。
- 现役 `shu-gongzhonghao-v1` 只作为冻结对照组，不在本仓库修改。

## 与 ZSK、口播的关系

三套产品各自安装、运行和发布：

```text
ZSK → 03 / 04 / 05 + content-source-v1
                         ├─ Content 口播 Slim（仅 Obsidian）
                         └─ Content 公众号 Slim（Obsidian / 飞书）
```

ZSK 负责建库、入库与维护资料；公众号只读取经过 Manifest 授权的少量资料，不调用 ZSK。只安装公众号时，也可以用 `configure` 对一个已经兼容 `content-source-v1` 的知识库做零写入预览，确认后登记。

公共合同有三个对象：

- Registry：`~/.codex/.content-workflows/knowledge-base-registry.json`
- Manifest：`06-Agent与Workflow/content-source-manifest.json`
- Profile 索引：`06-Agent与Workflow/content-profile-index.json`

飞书在 06 下使用同名文档和稳定对象引用，不保存凭据。

IP 解析顺序：本次明确指定 → 已确认的公众号默认 → primary → 唯一 active → 要求选择。`无IP` 只能明确指定或明确配置。

## 安装与验证

```bash
git clone https://github.com/slbb1995/content-gzh-slim.git
cd content-gzh-slim
python3 tools/verify.py
python3 install.py --activate
```

验证失败就停止。安装器不会覆盖不同内容的现有包或同名 active Skill；更新前先比较并备份。

1.1.1 的 Windows 兼容仍待完整验收：PR #7 提交者报告封面专项 16 项通过，但 Windows 全量 109 项测试仍有 12 failures / 7 errors，涉及换行与 Profile fixture 哈希、路径分隔符和符号链接权限；尚未逐项确认是否为新增回归。macOS 全量通过不代表 Windows 已通过，Windows 验证失败时不要跳过检查安装。

首次手动配置一个兼容知识库：

```bash
python3 scripts/content-gzh-slim configure --knowledge-base /绝对路径/知识库
python3 scripts/content-gzh-slim configure --knowledge-base /绝对路径/知识库 --confirmation 上一步返回值
```

飞书把 `--knowledge-base` 换成明确的飞书知识空间 URL。可用 `--default-profile 名称` 选择默认 IP，或用 `--default-no-ip` 明确配置无 IP；二者不能同时使用。第一次只返回 `wrote=false` 预览，确认后才登记。

日常启动可以省略知识库/IP，让已确认默认值补齐；也可以在输入 JSON 中明确指定知识库、任意 IP 或 `无IP`。默认 Runs 位置为 `~/.codex/.content-gzh-slim/runs`，仍支持 `--store` 指定隔离目录。

最终保存统一使用 `save --run-id ...`。真实 Run 的目标只能由已冻结 Manifest 推导，不能通过普通参数临时改到另一个目录或飞书节点。

## 仓库状态

- Version：1.1.1
- Implementation：P8 主链 + `content-source-v1` + 单张封面
- Skills：1 个公开入口 + 6 个内部 Skill
- Human Gates：2
- Writer Context Pack：1
- Publishing：不进入公众号草稿箱，不发布

## 许可证

[MIT License](LICENSE)

## 可选封面

文章保存后，一次性用文字介绍三种风格并按本篇推荐一种；用户选择或委托后，由 `content-gzh-cover` 生成一张并保存。支持麦肯锡商业咨询、实拍写实杂志风、复古图纸聚焦风。已指定风格无需再次选择，不新增正文 Gate。Obsidian 支持封面写回；飞书仅生成本地封面，不自动插入飞书文章。

封面从正文提炼短标题和画面，保持所选风格。先保证 2.35:1 横图构图均衡，再检查同图左侧 1:1 裁切文字完整；字少保留合理留白，不放大填满方形。

生图需要当前宿主的 `imagegen` Skill 和实际图片工具；Runtime 负责已有文章绑定、保存和回读，不声称能自行生图。缺少生图能力时停止对应环节。安装应使用完整包，不单独复制封面 Skill。

独立隔离验收已实跑知识库读取、两次合成确认、正文保存、一次真实生图、封面写回与重复保存；测试保持正文及原 Run 文件不变。另已复现并修复特殊附件路径的写前校验与保存中断后的图片复用问题。上述合成验收不等于真实客户生产批准，不包含飞书远端插图或真实 WorkBuddy 宿主验收。
