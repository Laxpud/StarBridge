# 分发与客户端验证记录

[安装说明](../distribution.md)

以下原文记录各批安装及运行结果，历史行为不能代替当前链路的实测。文中的`starbridge-case-audit`是已删除的旧安装样本；当前[最小安装测试Skill](<../../skills/starbridge-install-test/SKILL.md>)不继承这些宿主验证结论。

## 本地安装验证（2026-11-03）

| 客户端 | 安装方式与实际结果 |
|---|---|
| Codex CLI 0.162.1 | 隔离 `CODEX_HOME`，通过本地 marketplace 和 `codex plugin add` 安装；app-server 确认插件 MCP 为 connected、18 个工具，枚举到带插件身份的 `starbridge:starbridge-case-audit` |
| Claude Code 2.1.316 | 隔离 `CLAUDE_CONFIG_DIR`，通过原生 marketplace／install 安装；控制协议确认插件 MCP connected、18 个工具，并发现插件 Skill |
| 官方 DSH 0.2.1-rc.2 | 隔离 `DSH_HOME`，原生命令安装本地 tgz；官方 profile 解析器确认 bundle 配置层，加载实际安装适配器后发现 18 个工具、取得 schema 1 契约，官方 Skill provider 加载包内正文 |

验证只发送初始化、工具列表、状态和无会话契约请求，没有发送模型消息、打开 STAR 或改动日常插件配置。运行证据保存在本地 `outputs/plugin-install-20261103/`，不进入 Git。执行沙箱内的 stdio 检查曾超时，最终结果来自正常本机环境。Codex／Claude 的本地市场来源指向本轮源码快照；Codex／Claude 的远端原生安装未在本轮重测，四个外部插件的已发布市场来源与包内入口已通过远端检查。DSH 索引已通过官方 format 1 解析器；公开 Raw 索引返回 HTTP 200 且无重定向，原生安装器按索引中的 `c5f878173e0e32a0a807f799874d0c1b823af612` 完成 Git 安装，关键文件与该提交一致。远端安装后再次确认 18 个工具、schema 1 契约和 bundled Skill 正文；证据在本地 `outputs/plugin-remote-20261103/`。未操作 Discover UI。

## 独立安装接入验收（2026-11-02）

2026-11-02 按用户调整后的范围，只检查 Codex、Claude Code 和官方 DSH 的安装配置、MCP 连接／工具发现及 Skill 发现／本机加载。没有发送模型 user 消息、启动模型 turn 或打开 STAR 会话，模型登录不作为前提。P3 在此安装范围内完成，不代表三端模型工作流或全部 STAR 操作均已支持。

本轮使用 Linux 上现有固定环境 `0.1.0-aebd491` 的 `starbridge-mcp`，安装器为 `add-mcp 2.6.0` 与 `skills 1.7.4`。在受信任工作区下创建独立项目，通过安装器安装 Codex／Claude Code 配置及三端 Skill；DSH MCP 使用交付的原生插件片段。证据在本地 `outputs/harness-install-20261102/`，不进入 Git。

| 目标与实际版本 | 安装入口与作用域 | 本机验证结果 |
|---|---|---|
| Codex CLI 0.162.1 | `add-mcp -a codex`；项目 `.codex/config.toml`，Skill 位于 `.agents/skills/` | 项目配置层启用；app-server 连接 StarBridge 0.1.0，发现 18 工具，取得 schema 1 契约，实际枚举到 Skill |
| Claude Code 2.1.316 | `add-mcp -a claude-code`；项目 `.mcp.json`，Skill 位于 `.claude/skills/` | 控制协议确认 connected、18 工具及项目 Skill；只发送 initialize／mcp_status，不调用模型 |
| 官方 DSH 0.2.1-rc.2 | 原生 MCP 插件片段；`skills -a universal` 安装到项目 `.agents/skills/` | 官方 MCP client 实际 stdio 握手、18 工具及 schema 1 契约；官方 Skill registry／filesystem provider 实际发现并加载 Skill，来源为 project-agents |

三份安装后的 Skill 均与仓库内容一致。相同版本安装器的替换、移除、恢复及保留无关内容的既有证据继续适用。未重复验收所有用户级／项目级组合，也未演练不存在的跨发行版本回退。DSH 本轮直接装载官方本机插件，不启动完整模型 profile；不把桌面封装的行为归于这个结果。

**日常配置与隔离验收不同。** 检查时 Codex 的用户配置已连接 StarBridge；Claude Code 的用户级配置及检查到的 DSH profile 中未发现 StarBridge 条目，三端常用用户／仓库 Skill 根目录中也未发现该 Skill。本轮没有向这些日常配置安装或写入内容。当前 PATH 中的 `dsh` 来自桌面版 shim，返回 0.1.5-rc.3；表中验证的是另一个已安装的官方 npm 0.2.1-rc.2，不能据此宣称默认桌面命令已通过相同检查。

## 历史运行证据（2026-11-01）

以下保留此前的模型、真实 STAR 与异常恢复记录；它们不再构成当前安装验收的完成条件，也不应被改写为本轮执行结果。

2026-11-01 在 Linux、Python 3.14.4、uv 0.11.32 及 Node 24.20.0 环境执行。打包与安装器证据保留在本地 `outputs/distribution-20261101/`，本轮三个宿主的证据位于 `outputs/harness-p3-20261101/`；运行产物不进入 Git。以下状态只适用于本次记录，不能互相替代：

| 对象 | 已确认 | 尚未覆盖／受阻 |
|---|---|---|
| Python wheel／源码包 | 仓库外固定环境启动 CLI；Core 无 MCP 依赖；两版目录可读；Java 资源完整；缺少 STAR 可查询契约并返回诊断 | 其他 Python 版本、操作系统和离线 wheelhouse 部署 |
| MCP + 真实 STAR | Python MCP SDK 注册 18 工具；STAR 2602 Build `21.02.007` 隔离副本读、旧 expected 拒绝、赋值、回读、另存与新会话重载通过；输入摘要未变，会话已关闭 | 该结果不计为三个 Harness 的各自验收；2510 包安装后的真实运行未覆盖 |
| Codex CLI 0.162.1 | 已定位并解决未受信任项目导致的配置忽略；app-server 实际连接发现 18 工具、取得契约及 Skill 元数据；经该连接完成真实 STAR 读、旧 expected 拒绝、写入、回读、另存与重载，源摘要未变且会话已关闭；独立模型 turn 加载同一 Skill 并实际读取合成参数；服务重启后已停止会话未重新加载 | 桌面／IDE 形态、取消与写入中断恢复未验收 |
| Claude Code 2.1.296 | 固定版本独立运行；读取安装器生成的项目配置；控制协议确认 StarBridge 0.1.0 为 connected、发现 18 个工具；初始化实际发现项目 Skill | 当日未登录，按用户选择只做无模型验收；未覆盖模型工作流和真实 STAR，不据此判断当前登录状态 |
| DSH 0.2.1-rc.2 | 完整 headless profile 实际取得契约、加载 Skill 并完成定向只读审查；无 Skill 的真实读写、旧 expected 拒绝、回读、保存重载通过；缺少 MCP 时如实报告；环境标记传入成功；超过 300 秒的调用未被宿主 60 秒默认值截断，超时后先查状态并清理旧副本，在新副本完成审查 | 全树搜索耗尽工具预算后会话进入 uncertain（见下文）；自动断线重连、写入中途取消、用户级 Skill 根目录未验收 |

已有 10 项 Core、6 项 Java 发现及 15 项写入影响范围检查通过；这些检查不证明真实 CFD 物理有效性。Skill 格式检查通过，不等于三个宿主已完成该工作流。四个通用安装器目标的项目级 MCP 替换、移除、恢复及无关服务保留已验证；Skill 完整移除、重装及无关 Skill 保留已验证。当时未覆盖的用户级组合、跨发行版本回退、模型任务及异常恢复作为历史限制保留；后续仅按调整后的[安装验收范围](../archive/plan-2026-11-01-14-42.md#验收范围)执行。

Claude Code 通过临时进程设置批准本次项目服务（`enabledMcpjsonServers: ["starbridge"]`），并禁用 hooks；未改动用户全局配置。控制协议初始化后需等待异步 MCP 连接，瞬时 `pending` 不表示连接失败。此次只发送初始化和状态请求，没有发送模型消息；检查方式依据[官方控制协议实现](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/query.py)。

本轮只读模型审查在 Codex 与 DSH 中均实际读到 `_DiscoveryScalar.quantity_value = 2`，未把该合成值当成工程合格结论；独立写入验收将工作副本中的值改为 `3`，另存重载后仍为 `3`。STAR 打开／检查副本后可能已有 `modified=true`，正常关闭因未保存标志被拒绝；已保存或确认没有设置写入的本轮专用副本，经状态查询后显式 `discard` 清理。这个清理授权仅属于验收副本，不改变只读 Skill 默认不保存、不擅自丢弃的规则。

DSH 的第一次只读审查以 `search_settings(expand=true, timeout=300)` 扩展全树，实际约 304 秒后返回部分结果，内部请求超时使会话进入 `uncertain`，后续读取与正常关闭被拒绝。已保留失败证据；模型没有重发写入或伪造当前值。恢复时先查询状态，显式丢弃这个无设置写入的验收副本，再在全新副本完成定向读取。Skill 已补充优先按已知类型／名称定位和逐层浏览的指导。此结果验证了真实长调用和读操作超时后的停止／清理行为，不等于全树搜索、自动重连或写入中断恢复均已通过。


## 配置作用域与环境排查依据

独立安装验证曾在 `/tmp` 隔离目录中正确生成 Codex 配置，但实际配置层以 `disabledReason` 拒绝加载未受信任项目。将相同配置安装到已有受信任的 StarBridge 工作区内后，app-server 正常加载服务和 18 个工具；当时没有修改用户的全局信任设置。
