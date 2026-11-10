# 分发与 Harness 接入

[返回项目入口](README.cn.md) · [工具契约](tech/mcp.md) · [维护者分发说明](tech/distribution.md)

适用范围：当前仓库的插件/源码接入方式，程序基线`f7eef68`；市场已安装提交可能不同，不能从本页推断最新源码已经发布。Codex、Claude Code和DeepSeek Harness（DSH）可使用对应插件；需要确定当前代码时使用[源码与通用接入](#源码与通用接入)。首次连接后按[使用说明](<usage.md>)开展任务。

插件从自身 Git 源码启动程序。Python 发行包名为 `starbridge-cfd`，当前本地版本 `0.1.0` 尚未发布到 PyPI；安装结果与未覆盖范围集中在[分发验证记录](evidence/distribution.md)。

## 三端插件安装

三端通过 [Vibekits](https://github.com/Laxpud/my-awesome-vibekits) 分发，程序直接来自插件 Git 提交；不依赖 PyPI、Git tag 或 npm 发行包。

三端共用 `skills/`、`src/starbridge/` 和 `uv.lock`。插件初次启动通过 `uv sync --frozen` 准备 Python 依赖，环境保存在 `~/.starbridge/runtimes/plugin-<锁文件摘要>/`；后续启动复用该环境。程序从已安装插件的源码加载，不再要求用户单独安装 `starbridge-cfd` 或 Skill，也不下载尚未发布的 PyPI 包。只读插件目录不保存虚拟环境或 Python 字节码。

执行机器需要 `python3` 和 PATH 中的 `uv`。uv 可按项目要求准备 Python 3.11+；首次准备需要访问依赖源，离线使用须预先缓存锁定依赖。算例操作仍需 Linux、适配的 STAR 安装、许可证及对应本机 Javadoc。插件启动不打开算例，不包含 STAR 或许可证。

### Codex 与 Claude Code

添加 `Laxpud/my-awesome-vibekits` 市场，再安装 `starbridge`：

```bash
codex plugin marketplace add Laxpud/my-awesome-vibekits
codex plugin add starbridge@laxpud-vibekits
```

Claude Code 中：

```text
/plugin marketplace add Laxpud/my-awesome-vibekits
/plugin install starbridge@laxpud-vibekits
```

更新和移除继续使用客户端原生插件入口；先更新市场，再更新所选插件并启动新会话。已有单独配置的 `starbridge` MCP 或手动 Skill 应在确认插件可用后停用，避免重复加载；插件不会自动修改旧配置。

Codex 使用插件根目录相对 `cwd` 启动，MCP 启动等待为 180 秒，工具调用等待为 600 秒。Claude Code 使用 `${CLAUDE_PLUGIN_ROOT}` 定位入口。首次下载受客户端启动等待时间限制时，可在已安装插件目录先执行 `python3 integrations/plugin/launch.py --prepare`，完成后重连 MCP。该命令只准备依赖，不启动协议服务或 STAR。

### DeepSeek Harness

DSH 原生 bundle 为 `@laxpud/dsh-starbridge`，当前声明支持官方 `0.2.1-rc.2`，不将其他桌面封装视为已经通过验证。从本地仓库准备和安装：

```bash
npm pack --ignore-scripts --pack-destination /absolute/path/to/output
# 替换 profile 名称和生成的 tgz 路径；不覆盖现有 profile。
dsh plugin --profile <profile> add /absolute/path/to/output/laxpud-dsh-starbridge-0.1.0.tgz --config.auto-install-peers=false
```

包内只有可直接加载的 JavaScript 和共享源码，不需要安装时构建。DSH 的官方 MCP／Skill peer 由宿主提供；使用 `auto-install-peers=false` 避免 pnpm 再安装另一份宿主服务。pnpm 可能提示包内 skills 的审批或未物理安装 peer；是否可用应以 DSH 中的 MCP 连接和 Skill 加载结果为准，无需将本插件 Skill 复制到其他宿主。

bundle 插入自己的 `starbridge` 配置行，不替换 profile 的工具或 Skill 服务。适配器通过独立 provider 扫描包内 Skill，并接入 stdio MCP。profile 需提供 DSH 的 `tools` 与 `skills` 服务；常规基础 profile 已具备。可在 profile 的用户 patch 中覆盖该行 `config`，设置 `python`、`env`、`toolCallTimeoutMs`；许可证和必要环境通过 `env` 明确传入，不把密钥写进插件。

可启用实验性的 **Custom plugin indexes**，在 **Discover** 中添加 [Vibekits DSH 索引](https://raw.githubusercontent.com/Laxpud/my-awesome-vibekits/main/dsh/index.json)。市场 catalog 的 DSH `versions` 指向实际发布的插件 commit；索引通过 GitHub Raw 提供，无需开启 Pages。DSH 更新可从 Discover 选择新版本，或用 `dsh plugin --profile <profile> add <新版本来源>` 替换固定来源；移除使用 `dsh plugin --profile <profile> remove @laxpud/dsh-starbridge`，不另设升级器。

### 确认安装可用

连接当前源码后，默认应看到`starbridge.expand_capabilities`、`starbridge.query`和`starbridge.execute`三个入口；业务方法不直接列出不表示不支持。需要完整参考时，经`query`调用`get_contract`取得schema 2契约，正常任务先按需展开相关格式。插件安装还应在宿主中找到`starbridge-case-audit`；单独MCP接入不自动安装Skill。已安装的旧提交可能返回旧契约或工具列表，应核对实际版本后重连；工具展示名可能被宿主改写。连接与Skill加载不证明完成真实算例审查。

安装不自动打开 STAR。算例连接、读取和显式保存的参数见[MCP 契约](tech/mcp.md)；已做过的客户端检查及限制见[安装证据](evidence/distribution.md#本地安装验证2026-11-03)。

## 源码与通用接入

不使用插件时仍可构建 Python wheel，并将 `starbridge-mcp` 接入任意支持 stdio 的宿主。以下说明独立安装方法；三端用户的正式安装与更新入口已改为[三端插件](#三端插件安装)，不再新增其他 Harness 专用适配。

### 安装程序

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

程序不会把运行结果写入安装目录。共享会话的运行数据位于 `~/.starbridge/sessions/`，可重建缓存位于 `~/.starbridge/cache/`，后续调用使用返回的 `session_id`。保存可写回当前文件或显式另存；文件 CLI 仍使用调用者指定的 `work-dir`。具体目录与保留规则见[会话说明](tech/bridge-session.md)。升级或删除环境不自动关闭后台 STAR 会话，也不删除这些数据。

### 接入 MCP

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

#### Codex 项目配置未加载时

先确认启动目录属于已受信任的项目，再查看实际配置层是否因 `disabledReason` 被禁用。配置文件已生成不表示 app-server 已加载它；在正确作用域恢复加载后，再确认 MCP 服务状态和工具发现结果。该问题的既有安装记录见[分发验证记录](evidence/distribution.md#配置作用域与环境排查依据)。

`codex mcp get` 未找到服务不能单独证明项目配置错误。诊断时应核对实际运行目录、项目配置层是否被禁用，以及该运行时的 MCP 服务状态。不要通过复制服务到全局配置来掩盖作用域或信任问题。

#### 超时与环境

`add-mcp 2.6.0 --timeout` 只作用于远程 URL，对本机 stdio 会警告并忽略。工具的 `timeout` 是 STAR 操作等待时间，不是整个 MCP 调用的硬截止时间。宿主请求超时必须更长，并为宏编译、清理和首次缓存生成留出余量。

Codex 如需长调用，可在**安装器已经生成的同一服务表**中补充 `tool_timeout_sec = 600`；这是安装器无法表达的必要宿主设置，不再维护另一套服务安装路线。`600` 秒只是示例，按任务调整；`startup_timeout_sec` 另控制服务启动。[Codex MCP 设置](https://learn.chatgpt.com/docs/extend/mcp)和[项目配置的信任条件](https://learn.chatgpt.com/docs/config-file/config-basic)说明了这些约束。Claude Code 的实际长调用配置仍待验收。Cursor、OpenCode 不再验收，也不为其新增原生配置路线。

必要环境可使用安装器的重复 `--env KEY=VALUE` 传入。只传执行所需变量；许可证设置沿用实际 STAR 部署，不在仓库模板写入凭据。`star` 参数优先使用安装内实际程序的绝对路径，方便定位同安装的 Javadoc。

取消、断线、宿主超时不表示 STAR 已撤销。重连后先查询 `session_status` 和相关结果；不能自动重复写入、保存或丢弃。服务启动本身不加载算例，后台会话需要显式关闭。

### DeepSeek Harness

`add-mcp 2.6.0` 尚无 DSH 目标。使用 [MCP 插件片段](../integrations/deepseek-harness/cordis.fragment.yml)，将该条目合并到所选 profile 的插件集合，保留现有内容。模板适用于 `@deepseek-ai/dsh` 与 `@deepseek-ai/dsh-mcp-client` `0.2.1-rc.2`，仍须在实际 profile 中验收。

profile 应已有 `@deepseek-ai/dsh-system-prompt`、`@deepseek-ai/dsh-tools`，以及该 profile 使用的资源与 Skill 服务；不要重复挂载已有服务。模板采用固定环境可执行文件路径、`serverName: starbridge`、`transport: stdio`、`toolCallTimeoutMs: 600000` 和启动失败显式报错。实际 MCP 工具展示名可能被规范化并追加摘要，不应由 Skill 拼接名称。

DSH 会清理传给子进程的部分环境变量，必须通过模板 `env` 显式补入实际必需项。探测启动与重连不能作为自动恢复写入的依据。显式环境传入与长调用的既有依据，以及自动重连和其他 profile 的限制，见[历史运行证据](evidence/distribution.md#历史运行证据2026-11-01)。[官方 MCP client](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/mcp/mcp-client)是插件配置依据。

项目 Skill 可通过下一节的 `-a universal` 安装到 `.agents/skills/`。用户级 DSH 应把 `starbridge-case-audit/` 直接放入 `~/.dsh/skills/`，或在文件系统 provider 的 `customSkillDirs` 中显式指定目录；`skills --global -a universal` 的 `~/.config/agents/skills/` 不等于 DSH 默认用户扫描目录。参考[官方 Skill provider](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/skill/skill-filesystem)。

### 安装与维护 Skill

当前交付[starbridge-case-audit](<../skills/starbridge-case-audit/SKILL.md>)，按实际版本Java API组织只读宏，并按需使用资料和记忆；结构化发现/描述/读取是可选辅助，不是宏审查的前置条件。它要求schema 2及声明的三个入口和业务方法，具体见Skill元数据；结构化发现的版本范围另由服务查询结果决定。没有MCP、契约不兼容或缺少能力时应报告缺口，不能假装完成。审查不会自动修改设置、保存、运行网格或求解。

当前可从本地仓库安装：

```bash
npx skills@1.7.4 add /absolute/path/to/StarBridge \
  --skill starbridge-case-audit -a codex -a claude-code -a universal
```

同样可只选所需目标；DSH 项目使用 `universal`。默认项目作用域，Codex 与 Claude Code 可按需要加 `--global`；DSH 全局目录另按上节处理。

正式发布后使用不可变提交或已发布 tag 定位来源，例如 `https://github.com/Laxpud/StarBridge/tree/v0.1.0/skills/starbridge-case-audit`；**当前 tag 尚不存在**。初期 Python `0.1.0` 与同次发布的 Skill 配套，Skill 的契约版本为 schema 2，依赖的方法记录在 frontmatter `metadata`。锁文件记录来源不等于发布验收；不要用浮动主分支代替已验收组合。

更新程序时安装新版本到新的固定环境，再用相同 `--name starbridge` 和相同作用域重新执行 `add-mcp`，检查差异只涉及该服务。回退时重新指向保留的旧版本环境。Skill 更新或回退用明确 tag／提交来源重新执行 `skills add`；`skills update` 会跟随来源更新，不适合作为固定发布组合的默认升级动作。软件回退不会还原已经保存的算例。

移除项目配置与 Skill 可分别使用以下入口；MCP 目标参数按实际安装范围选择，用户作用域加 `--global`。Skill 命令不加 `-a`，表示从本作用域的所有宿主移除这一个 Skill。`skills 1.7.4` 指定目标移除时可能只清理链接并保留共享 `.agents/skills/` 目录；若只想对部分宿主停用，需确认共享目录是否仍被其他宿主扫描。

```bash
npx add-mcp@2.6.0 remove starbridge -a codex -a claude-code
npx skills@1.7.4 remove starbridge-case-audit
```

DSH 只删除对应 profile 的 `mcp-starbridge` 条目及选定目录下的该 Skill，不删除其他插件或整个扫描目录。移除前显式处理仍在运行的会话；配置移除不会结束它们。

## 进一步阅读

- [分发验证记录](evidence/distribution.md)：安装批次、实际版本、结果与未覆盖范围。
- [会话使用说明](tech/bridge-session.md)：连接算例、保存、断开与数据保留。
- [维护者分发说明](tech/distribution.md)：打包资源、插件入口、Registry 元数据与发布准备。
