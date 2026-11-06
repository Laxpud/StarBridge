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
- **Save explicitly:** structured session edits remain in memory until a save request writes the current file or saves a new one. Java execution and STAR's existing automatic-save settings have their own effects; prepared mesh and solver methods check those settings before execution. The separate file workflow saves to a new file and reloads it for verification. See [session operations](docs/tech/bridge-session.md) and the [file Bridge guide](docs/tech/bridge-file.md).

Structured catalog support depends on the exact [STAR release and Build](<docs/tech/catalog-versions.md>); generic lifecycle and execution instead require compilation against the selected installation and runtime identity checks. Structured properties retain their adaptation limits; the [generic Java execution and working-memory interfaces](docs/tech/generic-execution.md) now provide a route beyond that catalog and reusable, contextual methods. Background creation, request replay, saving, and reloading have been exercised on STAR 2602; a separate 909-cell laminar channel also completed mesh generation, five solver iterations, and result export. This is operation-path evidence, not convergence or engineering validation. Generic association writes, GUI attachment, and specific interruption/recovery scenarios have also been exercised on the small case; custom GUI layouts, nested-menu presentation, and exhaustive write-path validation remain outside the verified coverage; see the [validation limits](docs/tech/bridge-session.md#验证边界), [requirements](<StarBridge.md>), and [current work](TODO.md).

## Contributing

Contributions can describe concrete simulation workflows, clarify requirements, or improve the documents. See the [current milestone](TODO.md) for remaining work and the [roadmap](docs/roadmap.md) for proposals whose scope is still open.

## License

[MIT](LICENSE) © 2026 Laxpud.
