<a id="readme-top"></a>

<!-- mcp-name: io.github.Laxpud/starbridge -->

<div align="right">
  <strong>English</strong> | <a href="docs/README.cn.md">简体中文</a>
</div>

<div align="center">
<h1>StarBridge</h1>
<p><strong>A bridge for AI agents to inspect STAR-CCM+ simulations and make controlled changes.</strong></p>
</div>

## What this project is for

StarBridge lets AI agents inspect STAR-CCM+ cases and change supported settings through a local [MCP interface or shared JSON CLI](docs/tech/mcp.md). It is in early development.

- **Read settings:** browse simulation objects, find properties, and read their current values and relationships. See [runtime discovery](docs/tech/runtime-discovery.md) and [catalog reads](docs/tech/catalog-runtime.md) for coverage and value formats.
- **Make controlled changes:** check the target, expected old value, and required constraints before applying a change, then read back the result. Supported properties, method changes, and validation evidence are documented in the [modification guide](docs/tech/catalog-modifier.md).
- **Save explicitly:** session changes remain in memory until a save request writes the current file or saves a new one. The separate file workflow saves to a new file and reloads it for verification. See [session operations](docs/tech/bridge-session.md) and the [file Bridge guide](docs/tech/bridge-file.md).

Support depends on the exact [STAR release and Build](docs/tech/catalog-versions.md) and the adapted property or operation; it does not cover every simulation setting. Local GUI/server attachment is implemented, but real GUI attachment, saving, failure recovery, and the revised write path have not yet been exercised against STAR; see the [validation limits](docs/tech/bridge-session.md#验证边界). Mesh generation, solver execution, and persistent working memory remain future work in the [design](StarBridge.md) and [roadmap](docs/roadmap.md).

## Getting started

For Codex, Claude Code, or DeepSeek Harness (DSH), follow the [plugin installation guide](docs/distribution.md#三端插件安装) to install the program, MCP connection, and shared case-audit Skill together. The launcher needs `python3` and `uv` on PATH and prepares a Python 3.11+ environment. Simulation operations require Linux, a compatible STAR-CCM+ installation, and a license; runtime discovery also needs that installation's local Javadoc.

For source or generic stdio use, follow the [standalone installation instructions](docs/distribution.md#源码与通用接入). The `starbridge-cfd` package can run outside the source checkout; version `0.1.0` has not been published to PyPI. The same guide records each client's installation results and limits. After installation, use the [MCP contract](docs/tech/mcp.md) and [session guide](docs/tech/bridge-session.md) to connect a case and read its settings.

## More documentation

| Document | Purpose |
|---|---|
| [Distribution and Harness integration](docs/distribution.md) | Plugin and standalone installation, versions, and validation gaps |
| [Technical documentation](docs/tech/index.md) | Current implementation, topic navigation, and source-code responsibilities |
| [Runtime discovery](docs/tech/runtime-discovery.md) | Browse actual nodes, describe and read discovered properties, search within a budget, and relocate references |
| [MCP and shared Core API](docs/tech/mcp.md) | Local stdio tools, version resources, JSON CLI, and recovery behavior |
| [Catalog describe/read](docs/tech/catalog-runtime.md) | Read selected properties with server-version checks, session references, and per-property errors |
| [Catalog modification](docs/tech/catalog-modifier.md) | Schema 2 property writes, expected state, readback, diffs, and file reload verification |
| [STAR version selection](docs/tech/catalog-versions.md) | Exact release/Build matching, session binding, and per-version evidence |
| [Offline catalog tools](docs/tech/catalog.md) | Generate versioned API candidates, merge reviewed semantics, and compare declarations |
| [Modifier guide](docs/tech/modifier.md) | Single-object requests, expected-state checks, readback, and save behavior |
| [Inspector snapshot](docs/tech/inspector.md) | Catalog-driven snapshot layout, compatible fields, read errors, and validation limits |
| [File Bridge guide](docs/tech/bridge-file.md) | File operations, requirements, and implementation limits |
| [Session guide](docs/tech/bridge-session.md) | Connect, inspect, modify, save, and disconnect or stop a STAR session |
| [Design](StarBridge.md) | Product scope, proposed architecture, sessions, and working memory |
| [Current work](TODO.md) | Current milestone, tasks, and completion criteria |
| [Roadmap](docs/roadmap.md) | Future stages and expected outcomes |
| [Reference projects](docs/tech/references.md) | Sources, relevant design ideas, and applicability limits |

The design and planning documents are maintained in Chinese. Only the project entry page has an English translation.

## Contributing

Contributions can describe concrete simulation workflows, clarify requirements, or improve the documents. Use the [current milestone](TODO.md) to identify open planning questions; implementation choices remain under discussion.

## License

[MIT](LICENSE) © 2026 Laxpud.
