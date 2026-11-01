# 分发与 Harness 接入

[返回项目入口](README.cn.md) · [工具契约](mcp.md) · [实施计划](plans/plan-2026-11-01-14-42.md)

StarBridge 现在可以构建为 `starbridge-cfd` Python 发行包，运行模块与资源统一位于 `starbridge` 命名空间。当前 `0.1.0` 是本地待发布版本，尚未上传 PyPI、创建发布 tag 或登记 MCP Registry。三个 Harness 的完整验收尚未完成，具体证据与缺口见[本页验收状态](#验收状态)。后续只验收 Codex、Claude Code 和 DSH；Cursor、OpenCode 不纳入验收，已有安装器检查仅为历史证据。

## 安装程序

需要 Python 3.11+。受支持的算例操作还需要 Linux、匹配的 STAR 安装和许可证；运行时发现另需该安装的本机 Javadoc。Python 包不附带 STAR、许可证、完整 Javadoc 或用户算例。普通 CLI 没有第三方运行依赖，MCP extra 固定 Python SDK `2.3.0`，并安装 JSON Schema 校验依赖。

从源码构建，或取得维护者提供的 wheel 后，在固定环境中安装。下面的 wheel 路径需换成实际构建产物；`starbridge-env` 放在用户可写且长期保留的位置：

```bash
uv build --out-dir dist
uv venv /absolute/path/to/starbridge-env
uv pip install --python /absolute/path/to/starbridge-env/bin/python \
  '/absolute/path/to/starbridge_cfd-0.1.0-py3-none-any.whl[mcp]'
/absolute/path/to/starbridge-env/bin/starbridge contract
```

普通 CLI 可省略 `[mcp]`。固定环境安装完成后，MCP 启动不需要联网下载程序。离线机器还需提前准备该平台和 Python 版本的全部依赖 wheel，使用本地 wheelhouse 安装。

**仅在该版本正式发布到 PyPI 后**，才可使用：

```bash
uvx --from 'starbridge-cfd[mcp]==0.1.0' starbridge-mcp
```

包名 `starbridge` 已被其他项目占用，因此使用 `starbridge-cfd`；查询未占用不代表名称已经保留。稳定入口如下：

| 命令 | 用途 |
|---|---|
| `starbridge` | 共享 JSON CLI，`contract` 或方法名配合 `--arguments` |
| `starbridge-mcp` | 本机 stdio MCP 服务 |
| `starbridge-cfd` | 与 `starbridge-mcp` 相同，供按发行包名启动的 Registry 消费者使用 |
| `starbridge-file` | 文件 Bridge CLI |
| `starbridge-session` | 后台会话 CLI |
| `starbridge-catalog` | 离线目录生成与检查 CLI |

源码仓库中的 `starbridge.py`、`interfaces/mcp_server.py`、两个 `bridge/runner/*_bridge.py` 和 `tools/catalog/catalog.py` 保留为转发入口。原顶层 `core` 等 Python 导入路径已迁移到 `starbridge.core` 等命名空间，不提供旧内部导入别名。目录资源在 `src/starbridge/catalogs/`，Java 模板在 `src/starbridge/bridge/java/`；显式指定自定义目录文件的开发命令需要更新路径。

程序不会把运行结果写入安装目录。会话、请求日志、生成宏、Javadoc 元数据缓存和规则编译缓存位于调用者指定的 `session_dir`／`work-dir`；输出算例使用显式新路径。升级或删除环境不自动关闭后台 STAR 会话，也不删除这些数据。

## 接入 MCP

MCP 与 Skills 分别安装。Codex 与 Claude Code 使用 `add-mcp 2.6.0`；在目标项目目录执行以下命令，并把路径换成固定环境的实际位置：

```bash
npx add-mcp@2.6.0 /absolute/path/to/starbridge-env/bin/starbridge-mcp \
  --name starbridge -a codex -a claude-code
```

可只保留需要的 `-a`。默认项目作用域；需要用户作用域时加 `--global`。安装器会显示写入目标，安装前确认作用域。执行需要网络的 `npx` 时也可事先固定安装这些工具；它们只参与安装，不参与后续 MCP 调用。

发行版发布后，`uvx` 的接入命令使用**可执行文件绝对路径和独立参数**：

```bash
npx add-mcp@2.6.0 "$(command -v uvx)" \
  --args=--from --args='starbridge-cfd[mcp]==0.1.0' --args=starbridge-mcp \
  --name starbridge -a codex -a claude-code
```

不要把 `/absolute/path/uvx --from ...` 整段作为一个参数：该版本安装器把以路径开头的输入当成完整可执行文件路径。裸 `uvx` 也可能被识别成 npm 包名。固定环境的单个可执行文件路径最直接。

| Harness | 项目 MCP 配置 | 项目 Skill 位置 | 接入条件 |
|---|---|---|---|
| Codex CLI | `.codex/config.toml` | `.agents/skills/` | 项目配置需要宿主信任该项目；CLI、桌面与 IDE 验收分别记录 |
| Claude Code | `.mcp.json` | `.claude/skills/`，可链接到 `.agents/skills/` | 项目 MCP 服务需客户端批准后连接 |
| DeepSeek Harness | 所用 profile 的插件条目 | `.agents/skills/` 或 `.dsh/skills/` | 采用下节官方插件模板 |

用户作用域目录由固定版本安装器决定：Codex 为 `~/.codex/config.toml`，Claude Code 为 `~/.claude.json`。不要复制一份项目配置覆盖已有用户配置。执行环境必须能访问 STAR、许可证和算例；远程 IDE／云端 Agent 的运行位置不能从桌面安装位置推断。

### Codex 项目配置未加载时

先确认启动目录属于已受信任的项目。此次 `/tmp` 隔离目录中的配置虽然由安装器正确生成，Codex 实际配置层仍以 `disabledReason` 明确拒绝加载，因为该项目未受信任。把相同配置安装到已有受信任的 StarBridge 工作区内后，app-server 正常加载服务和 18 个工具；本次没有修改用户的全局信任设置。

`codex mcp get` 未找到服务不能单独证明项目配置错误。诊断时应核对实际运行目录、项目配置层是否被禁用，以及该运行时的 MCP 服务状态。不要通过复制服务到全局配置来掩盖作用域或信任问题。

### 超时与环境

`add-mcp 2.6.0 --timeout` 只作用于远程 URL，对本机 stdio 会警告并忽略。工具的 `timeout` 是 STAR 操作等待时间，不是整个 MCP 调用的硬截止时间。宿主请求超时必须更长，并为宏编译、清理和首次缓存生成留出余量。

Codex 如需长调用，可在**安装器已经生成的同一服务表**中补充 `tool_timeout_sec = 600`；这是安装器无法表达的必要宿主设置，不再维护另一套服务安装路线。`600` 秒只是示例，按任务调整；`startup_timeout_sec` 另控制服务启动。[Codex MCP 设置](https://learn.chatgpt.com/docs/extend/mcp)和[项目配置的信任条件](https://learn.chatgpt.com/docs/config-file/config-basic)说明了这些约束。Claude Code 的实际长调用配置仍待验收。Cursor、OpenCode 不再验收，也不为其新增原生配置路线。

必要环境可使用安装器的重复 `--env KEY=VALUE` 传入。只传执行所需变量；许可证设置沿用实际 STAR 部署，不在仓库模板写入凭据。`star` 参数优先使用安装内实际程序的绝对路径，方便定位同安装的 Javadoc。

取消、断线、宿主超时不表示 STAR 已撤销。重连后先查询 `session_status` 和相关结果；不能自动重复写入、保存或丢弃。服务启动本身不加载算例，后台会话需要显式关闭。

## DeepSeek Harness

`add-mcp 2.6.0` 尚无 DSH 目标。使用 [MCP 插件片段](../integrations/deepseek-harness/cordis.fragment.yml)，将该条目合并到所选 profile 的插件集合，保留现有内容。模板适用于 `@deepseek-ai/dsh` 与 `@deepseek-ai/dsh-mcp-client` `0.2.1-rc.2`，仍须在实际 profile 中验收。

profile 应已有 `@deepseek-ai/dsh-system-prompt`、`@deepseek-ai/dsh-tools`，以及该 profile 使用的资源与 Skill 服务；不要重复挂载已有服务。模板采用固定环境可执行文件路径、`serverName: starbridge`、`transport: stdio`、`toolCallTimeoutMs: 600000` 和启动失败显式报错。实际 MCP 工具展示名可能被规范化并追加摘要，不应由 Skill 拼接名称。

DSH 会清理传给子进程的部分环境变量，必须通过模板 `env` 显式补入实际必需项。探测启动与重连不能作为自动恢复写入的依据。本轮已在完整 headless profile 确认显式环境传入与长调用；自动重连和不同 profile 的探测行为仍需分别验收。[官方 MCP client](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/mcp/mcp-client)是插件配置依据。

项目 Skill 可通过下一节的 `-a universal` 安装到 `.agents/skills/`。用户级 DSH 应把 `starbridge-case-audit/` 直接放入 `~/.dsh/skills/`，或在文件系统 provider 的 `customSkillDirs` 中显式指定目录；`skills --global -a universal` 的 `~/.config/agents/skills/` 不等于 DSH 默认用户扫描目录。参考[官方 Skill provider](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/skill/skill-filesystem)。

## 安装与维护 Skill

当前交付 [starbridge-case-audit](../skills/starbridge-case-audit/SKILL.md)，用于按实际对象和值只读检查算例。它要求契约 schema 1 及当前发现／描述／读取能力；发现接口的版本范围由服务查询结果决定。没有 MCP、契约不兼容或缺少能力时应报告缺口，不能假装完成。审查不会自动修改、保存、运行网格或求解。

当前可从本地仓库安装：

```bash
npx skills@1.7.4 add /absolute/path/to/StarBridge \
  --skill starbridge-case-audit -a codex -a claude-code -a universal
```

同样可只选所需目标；DSH 项目使用 `universal`。默认项目作用域，Codex 与 Claude Code 可按需要加 `--global`；DSH 全局目录另按上节处理。

正式发布后使用不可变提交或已发布 tag 定位来源，例如 `https://github.com/Laxpud/StarBridge/tree/v0.1.0/skills/starbridge-case-audit`；**当前 tag 尚不存在**。初期 Python `0.1.0` 与同次发布的 Skill 配套，Skill 的最低契约为 schema 1，依赖的方法记录在 frontmatter `metadata`。锁文件记录来源不等于发布验收；不要用浮动主分支代替已验收组合。

更新程序时安装新版本到新的固定环境，再用相同 `--name starbridge` 和相同作用域重新执行 `add-mcp`，检查差异只涉及该服务。回退时重新指向保留的旧版本环境。Skill 更新或回退用明确 tag／提交来源重新执行 `skills add`；`skills update` 会跟随来源更新，不适合作为固定发布组合的默认升级动作。软件回退不会还原已经保存的算例。

移除项目配置与 Skill 可分别使用以下入口；MCP 目标参数按实际安装范围选择，用户作用域加 `--global`。Skill 命令不加 `-a`，表示从本作用域的所有宿主移除这一个 Skill。`skills 1.7.4` 指定目标移除时可能只清理链接并保留共享 `.agents/skills/` 目录；若只想对部分宿主停用，需确认共享目录是否仍被其他宿主扫描。

```bash
npx add-mcp@2.6.0 remove starbridge -a codex -a claude-code
npx skills@1.7.4 remove starbridge-case-audit
```

DSH 只删除对应 profile 的 `mcp-starbridge` 条目及选定目录下的该 Skill，不删除其他插件或整个扫描目录。移除前显式处理仍在运行的会话；配置移除不会结束它们。

## 验收状态

2026-11-01 在 Linux、Python 3.14.4、uv 0.11.32 及 Node 24.20.0 环境执行。打包与安装器证据保留在本地 `outputs/distribution-20261101/`，本轮三个宿主的证据位于 `outputs/harness-p3-20261101/`；运行产物不进入 Git。以下状态只适用于本次记录，不能互相替代：

| 对象 | 已确认 | 尚未覆盖／受阻 |
|---|---|---|
| Python wheel／源码包 | 仓库外固定环境启动 CLI；Core 无 MCP 依赖；两版目录可读；Java 资源完整；缺少 STAR 可查询契约并返回诊断 | 其他 Python 版本、操作系统和离线 wheelhouse 部署 |
| MCP + 真实 STAR | Python MCP SDK 注册 18 工具；STAR 2602 Build `21.02.007` 隔离副本读、旧 expected 拒绝、赋值、回读、另存与新会话重载通过；输入摘要未变，会话已关闭 | 该结果不计为三个 Harness 的各自验收；2510 包安装后的真实运行未覆盖 |
| Codex CLI 0.162.1 | 已定位并解决未受信任项目导致的配置忽略；app-server 实际连接发现 18 工具、取得契约及 Skill 元数据；经该连接完成真实 STAR 读、旧 expected 拒绝、写入、回读、另存与重载，源摘要未变且会话已关闭；独立模型 turn 加载同一 Skill 并实际读取合成参数；服务重启后已停止会话未重新加载 | 桌面／IDE 形态、取消与写入中断恢复未验收 |
| Claude Code 2.1.296 | 固定版本独立运行；读取安装器生成的项目配置；控制协议确认 StarBridge 0.1.0 为 connected、发现 18 个工具；初始化实际发现项目 Skill | 当前未登录，按用户选择只做无模型验收；模型加载／执行 Skill、真实 STAR 读写与超时恢复未覆盖 |
| DSH 0.2.1-rc.2 | 完整 headless profile 实际取得契约、加载 Skill 并完成定向只读审查；无 Skill 的真实读写、旧 expected 拒绝、回读、保存重载通过；缺少 MCP 时如实报告；环境标记传入成功；超过 300 秒的调用未被宿主 60 秒默认值截断，超时后先查状态并清理旧副本，在新副本完成审查 | 全树搜索耗尽工具预算后会话进入 uncertain（见下文）；自动断线重连、写入中途取消、用户级 Skill 根目录未验收 |

已有 10 项 Core、6 项 Java 发现及 15 项写入影响范围检查通过；这些检查不证明真实 CFD 物理有效性。Skill 格式检查通过，不等于三个宿主已完成该工作流。四个通用安装器目标的项目级 MCP 替换、移除、恢复及无关服务保留已验证；Skill 完整移除、重装及无关 Skill 保留已验证。三个宿主的用户作用域安装、实际跨发行版本回退，以及各宿主尚未覆盖的无 Skill 任务、缺失能力处理和超时恢复仍按[计划验收范围](plans/plan-2026-11-01-14-42.md#验收范围)补齐。

Claude Code 通过临时进程设置批准本次项目服务（`enabledMcpjsonServers: ["starbridge"]`），并禁用 hooks；未改动用户全局配置。控制协议初始化后需等待异步 MCP 连接，瞬时 `pending` 不表示连接失败。此次只发送初始化和状态请求，没有发送模型消息；检查方式依据[官方控制协议实现](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/query.py)。

本轮只读模型审查在 Codex 与 DSH 中均实际读到 `_DiscoveryScalar.quantity_value = 2`，未把该合成值当成工程合格结论；独立写入验收将工作副本中的值改为 `3`，另存重载后仍为 `3`。STAR 打开／检查副本后可能已有 `modified=true`，正常关闭因未保存标志被拒绝；已保存或确认没有设置写入的本轮专用副本，经状态查询后显式 `discard` 清理。这个清理授权仅属于验收副本，不改变只读 Skill 默认不保存、不擅自丢弃的规则。

DSH 的第一次只读审查以 `search_settings(expand=true, timeout=300)` 扩展全树，实际约 304 秒后返回部分结果，内部请求超时使会话进入 `uncertain`，后续读取与正常关闭被拒绝。已保留失败证据；模型没有重发写入或伪造当前值。恢复时先查询状态，显式丢弃这个无设置写入的验收副本，再在全新副本完成定向读取。Skill 已补充优先按已知类型／名称定位和逐层浏览的指导。此结果验证了真实长调用和读操作超时后的停止／清理行为，不等于全树搜索、自动重连或写入中断恢复均已通过。

## 发布准备

[`server.json`](../server.json) 使用 `io.github.Laxpud/starbridge` 和 PyPI 包 `starbridge-cfd`；README 的 `mcp-name` 与其一致。Registry 元数据通过官方 `2025-12-11` JSON Schema 校验。`runtimeArguments --with starbridge-cfd[mcp]==0.1.0` 安装 MCP extra，发行包同名入口启动服务；本地 wheel 的 `uvx` 启动验证通过（用 `--find-links` 指向本地发行目录），发布后对应形式为 `uvx --with 'starbridge-cfd[mcp]==0.1.0' starbridge-cfd@0.1.0`。不同 Registry 消费者的实际解析仍需分别确认，Schema 通过不代表官方登记成功。[Registry PyPI 元数据规则](https://modelcontextprotocol.io/registry/package-types)要求已发布包的 README 中包含一致的身份标记。

发布物包括 wheel、源码包、同提交的 Skills、Registry 元数据和本页兼容说明。外部发布前仍需补齐三个 Harness 的验收或明确调整支持范围，复核名称／身份可用性、生成固定发布 tag、记录最终校验和，然后分别上传 PyPI、发布 Git Release 和登记 Registry。当前不具备宣称“三个 Harness 全部支持”的证据，也尚未执行任何上传。
