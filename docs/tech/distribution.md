# 发行包与插件维护

[技术入口](index.md) · [当前架构](architecture.md) · [用户安装说明](../distribution.md)

核对基线：三端插件交付的 `pyproject.toml`、`uv.lock`、插件声明及启动器。本文说明程序、MCP 与 Skill 如何打包和启动；用户安装步骤见安装说明，任务状态见 [TODO](../../TODO.md)。

## 交付内容与启动过程

Python 生产代码统一位于 `src/starbridge/`。构建出的 `starbridge-cfd` 包包含 Python 模块、按版本保存的 JSON 目录及 Java 宏资源；不包含 STAR、许可证、完整 Javadoc、用户算例或运行产物。源码根目录的旧脚本只负责转发到包内实现，不提供原顶层内部模块的导入别名。

插件复用同一份源码、Skill 和锁文件，各宿主只适配声明、启动及 Skill 发现。共享启动器依次定位插件根目录、按锁文件摘要选择用户目录环境、运行 `uv sync --frozen --no-dev --extra mcp --no-install-project`，再从插件的 `src/` 启动 `starbridge.mcp`。依赖环境可以复用，业务源码始终来自当前插件安装位置。

`STARBRIDGE_PLUGIN_DATA` 可覆盖启动器的数据根目录，默认是 `~/.starbridge`；环境位于其 `runtimes/plugin-<锁文件摘要>/`。启动器设置 `PYTHONDONTWRITEBYTECODE=1`，Python 使用 `-P` 避免宿主工作目录中的同名脚本遮蔽包。准备信息写入 stderr，stdout 留给 MCP 协议；`--prepare` 只准备依赖。

| 文件或分组 | 维护职责 |
|---|---|
| [pyproject.toml](../../pyproject.toml)、[MANIFEST.in](../../MANIFEST.in) | Python 构建、命令入口和随包资源；版本来自包内 `__version__` |
| [uv.lock](../../uv.lock) | 插件依赖版本与复用环境标识的依据 |
| [launch.py](../../integrations/plugin/launch.py) | 三端共用的依赖准备及 stdio 启动器 |
| [.codex-plugin/](../../.codex-plugin/)、[.claude-plugin/](../../.claude-plugin/) | Codex 和 Claude Code 插件声明 |
| [integrations/plugin/](../../integrations/plugin/) | 宿主 MCP 启动配置 |
| [package.json](../../package.json)、[DSH 适配器](../../integrations/deepseek-harness/) | DSH bundle、provider 和可打包文件范围 |
| [安装测试Skill](<../../skills/starbridge-install-test/SKILL.md>)及[显示配置](<../../skills/starbridge-install-test/agents/openai.yaml>) | 三端共用的最小加载样本，仅返回固定标记；不提供业务工作流或调用MCP/STAR |
| [server.json](../../server.json) | 待发布的 MCP Registry 元数据 |

Python 要求 3.11+，普通 CLI 使用标准库；MCP extra 声明 SDK `2.3.0` 和 JSON Schema 依赖。STAR 安装、许可证、本机 Javadoc 与 Java 编译条件见[架构依赖](architecture.md#源码对应关系)。`my-awesome-vibekits` 仓库维护聚合 catalog 和三端市场索引，不复制这里的业务源码。

## DSH 本地安装与发布自动化

[本地安装脚本](../../scripts/dsh_local_install.py)将当前工作区打包为独立快照并安装到指定 DSH profile；使用和快照保留规则见[用户安装说明](../distribution.md#deepseek-harness)。它不更新市场，也不提交、推送或创建发布。

### 准备版本

在仓库根目录执行以下命令；版本只接受严格递增的 `X.Y.Z`，示例版本需按实际情况替换：

```bash
python3 scripts/release_version.py                 # 检查现有声明一致
python3 scripts/release_version.py --set 0.1.3    # 只准备本地版本修改
```

[版本脚本](../../scripts/release_version.py)核对并修改 Python 包版本、DSH 包、两端插件 manifest 及 Registry 版本与依赖 pin，不执行 Git 操作。它不改写历史记录，也不自动调整本文和用户安装说明中带版本号的示例；发布前须人工检查这些说明、更新仍指当前版本的示例，并确认 `uv.lock` 与打包结果。确认差异后，提交及推送仍需维护者明确操作。

### 通过 GitHub Actions 创建发布并提出市场更新

[发布工作流](../../.github/workflows/release-vibekits.yml)提供两种入口：在 GitHub 上对已推送的 `main` 手动运行工作流（按当前版本创建 `vX.Y.Z` GitHub Release），或在仓库已有的正式 GitHub Release 发布时自动运行。手动运行前先确认版本、源码和发布范围；**创建 GitHub Release 是公开发布操作**，该流程不发布 npm／PyPI 包。已有 tag 但没有 Release 时不会自动接管；源码 checkout、发布 tag 和远端 `main` 必须指向同一完整提交；流程在多个关键步骤复核 `main`，发现变化即中止，但不能与远端并发推送形成原子事务。

工作流使用正式 Release 的 `publishedAt` 和 Release URL 作为绑定版本、提交的发布时间和证据，调用市场已有的 `--fetch-external --plugin starbridge --release-info` 预览并写入，然后运行市场既有检查；成功后只提交 catalog 和三份生成目录到新分支，并向 Vibekits 提交 PR，不自动合并。当前 `0.1.1` 已推送到固定提交；合入这套自动化后的不同提交应先提升到新版本，不能把它当成同一版本的原提交重新发布。市场来源使用 `main`，因此如果发布后 StarBridge `main` 已前进，不能重试并假装同步旧版本；需先按实际发布状态处理。若发布成功但 PR 步骤失败，Release 不会自动撤销；先检查 Actions 日志、市场分支和 PR，再排除原因后重试，避免重复创建或覆盖。

启用前须完成以下配置：

1. Vibekits 远端 `main` 必须包含支持 `--release-info`、逐版本历史检查和待补拒写的市场同步器；本工作流在创建 Release 前会检查参数是否存在，但不能代替核对远端的实际实现。
2. 在 StarBridge 仓库配置 Actions secret `VIBEKITS_SYNC_TOKEN`，使用仅限 Vibekits 仓库、具备 `Contents: read/write` 和 `Pull requests: read/write` 的细粒度 personal access token，并确认市场仓库策略允许创建 PR。工作流自身的 `GITHUB_TOKEN` 用于 StarBridge Release；不要将 token 写入仓库或日志。
3. 两仓库的工作流和市场同步器须分别提交并推送后才会在 GitHub 运行。未经实际触发与检查，不应声称 PR、权限、市场同步或客户端升级已经验证。

## 发布准备

[`server.json`](../../server.json) 使用 `io.github.Laxpud/starbridge` 和 PyPI 包 `starbridge-cfd`；README 的 `mcp-name` 与其一致。Registry 元数据通过官方 `2025-12-11` JSON Schema 校验。`runtimeArguments --with starbridge-cfd[mcp]==0.1.2` 安装 MCP extra，发行包同名入口启动服务；此前 `0.1.0` 本地 wheel 的 `uvx` 启动验证通过（用 `--find-links` 指向本地发行目录），该历史结果不代表 `0.1.2` 已重新构建或验收，发布后对应形式为 `uvx --with 'starbridge-cfd[mcp]==0.1.2' starbridge-cfd@0.1.2`。不同 Registry 消费者的实际解析仍需分别确认，Schema 通过不代表官方登记成功。[Registry PyPI 元数据规则](https://modelcontextprotocol.io/registry/package-types)要求已发布包的 README 中包含一致的身份标记。

发布物包括 wheel、源码包、同提交的 Skills、Registry 元数据和[安装兼容说明](../distribution.md)。三端安装证据及限制见[分发验证记录](../evidence/distribution.md)。外部发布仍须另获授权，并复核名称／身份可用性、生成固定发布 tag、记录最终校验和，再上传 PyPI、发布 Git Release 和登记 Registry。安装验收不代表“三个 Harness 的全部模型与算例工作流均已支持”；PyPI 和 Registry 尚未发布；Git Release 状态以仓库为准，插件 Git 来源与市场安装状态见[三端插件安装](../distribution.md#三端插件安装)。
