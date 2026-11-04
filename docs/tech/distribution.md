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
| [skills/](../../skills/) | 三端共用的 Skill 正文及 `agents/openai.yaml` |
| [server.json](../../server.json) | 待发布的 MCP Registry 元数据 |

Python 要求 3.11+，普通 CLI 使用标准库；MCP extra 声明 SDK `2.3.0` 和 JSON Schema 依赖。STAR 安装、许可证、本机 Javadoc 与 Java 编译条件见[架构依赖](architecture.md#源码对应关系)。`my-awesome-vibekits` 仓库维护聚合 catalog 和三端市场索引，不复制这里的业务源码。

## 发布准备

[`server.json`](../../server.json) 使用 `io.github.Laxpud/starbridge` 和 PyPI 包 `starbridge-cfd`；README 的 `mcp-name` 与其一致。Registry 元数据通过官方 `2025-12-11` JSON Schema 校验。`runtimeArguments --with starbridge-cfd[mcp]==0.1.0` 安装 MCP extra，发行包同名入口启动服务；本地 wheel 的 `uvx` 启动验证通过（用 `--find-links` 指向本地发行目录），发布后对应形式为 `uvx --with 'starbridge-cfd[mcp]==0.1.0' starbridge-cfd@0.1.0`。不同 Registry 消费者的实际解析仍需分别确认，Schema 通过不代表官方登记成功。[Registry PyPI 元数据规则](https://modelcontextprotocol.io/registry/package-types)要求已发布包的 README 中包含一致的身份标记。

发布物包括 wheel、源码包、同提交的 Skills、Registry 元数据和[安装兼容说明](../distribution.md)。三端安装证据及限制见[分发验证记录](../evidence/distribution.md)。外部发布仍须另获授权，并复核名称／身份可用性、生成固定发布 tag、记录最终校验和，再上传 PyPI、发布 Git Release 和登记 Registry。安装验收不代表“三个 Harness 的全部模型与算例工作流均已支持”；PyPI、Git Release 和 Registry 尚未发布；插件 Git 来源与市场安装状态见[三端插件安装](../distribution.md#三端插件安装)。
