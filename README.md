# Content GZH Slim

`content-gzh-slim` 是一套可独立安装、面向多知识库和多 IP 的微信公众号内容工作流。1.1.0 起同一发布 ZIP 同时支持 Codex / WorkBuddy 与 Windows / macOS。

当前版本在 P8 已验收主链上增加 `content-source-v1`：可从明确输入或经过真人确认的公共 Registry 解析 Obsidian/飞书知识库，选择同库任意 active IP，并在 Gate A 后冻结、回读和校验所有来源。ZSK、口播和公众号仍是三个独立产品，不存在运行时代码依赖。

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
- 正文确认后保存回本次指定知识库；全平台分发包是可选支线。
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

从通用 ZIP 安装时，Codex 使用默认宿主；WorkBuddy 使用显式宿主：

```bash
python3 install.py --host codex --activate
python3 install.py --host workbuddy --activate
```

Windows 将 `python3` 换成 `py -X utf8 -B`。也可以直接在 WorkBuddy 技能页面上传通用 ZIP；ZIP 根目录包含 WorkBuddy 所需的 `SKILL.md`，同时保留 Codex 的六 Skill、Runtime、Schema 和安装器。首次绑定与 Run 数据分别保存在宿主自己的隐藏目录；不得自动复制另一宿主的 Registry、凭据或客户资料。

通用包由干净 Git 工作树构建，并把源码提交写入包清单：

```bash
python3 tools/build_universal_package.py --output dist/content-gzh-slim-universal.zip
```

验证失败就停止。安装器不会覆盖不同内容的现有包或同名 active Skill；更新前先比较并备份。

首次手动配置一个兼容知识库：

```bash
python3 scripts/content-gzh-slim configure --knowledge-base /绝对路径/知识库
python3 scripts/content-gzh-slim configure --knowledge-base /绝对路径/知识库 --confirmation 上一步返回值
```

飞书把 `--knowledge-base` 换成明确的飞书知识空间 URL。可用 `--default-profile 名称` 选择默认 IP，或用 `--default-no-ip` 明确配置无 IP；二者不能同时使用。第一次只返回 `wrote=false` 预览，确认后才登记。

日常启动可以省略知识库/IP，让已确认默认值补齐；也可以在输入 JSON 中明确指定知识库、任意 IP 或 `无IP`。默认 Runs 位置为 `~/.codex/.content-gzh-slim/runs`，仍支持 `--store` 指定隔离目录。

最终保存统一使用 `save --run-id ...`。真实 Run 的目标只能由已冻结 Manifest 推导，不能通过普通参数临时改到另一个目录或飞书节点。

## 仓库状态

- Version：1.1.0
- Implementation：P8 主链 + `content-source-v1`
- Skills：1 个公开入口 + 5 个内部 Skill
- Human Gates：2
- Writer Context Pack：1
- Publishing：不进入公众号草稿箱，不发布

## 许可证

[MIT License](LICENSE)
