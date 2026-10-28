<a id="readme-top"></a>

<div align="right">
  <strong>English</strong> | <a href="docs/README.cn.md">简体中文</a>
</div>

<div align="center">
<h1>StarBridge</h1>
<p><strong>A planned bridge for AI agents to inspect, modify, and run STAR-CCM+ simulations with verifiable operation results.</strong></p>
</div>

## What this project is for

StarBridge is in early development. The Inspector reads simulation objects, key properties, and relationships through both file and background-session entry points. The Modifier can update existing scalar-parameter and user-field-function definitions and replace existing user-tag assignments, with expected-state checks and readback. File changes are saved to a new simulation and reloaded for verification; session changes remain in memory until an explicit save. A background-session prototype also reuses one loaded STAR server for successive requests. Each request starts a temporary Java client; a persistent Java adapter, GUI integration, MCP, and working memory remain future work.

Catalog-driven `describe` and `read` commands now check the running server version, locate objects, and read selected properties through reviewed mappings and shared type adapters. They return separate catalog results with session-scoped references and per-property status. Catalog-based `modify` now supports scalar expressions and numeric constants, user-field-function definitions, and user-tag assignments, with expected-state checks, readback, and both catalog and snapshot diffs. The existing schema 1 `modify` and `set-scalar` commands now use the same catalog modifier automatically, with their arguments and existing result fields preserved. They use the bundled catalog and require the running server to match 2602 Build 21.02.007 exactly; `set-scalar` still has no caller-provided expected state. Migration of the existing Inspector snapshot, broader write adapters, structural operations, and model-state checks remain unfinished.

The proposed system combines structured simulation access, workflow Skills, persistent working memory, and long-lived background or GUI simulation sessions. See the [design document](StarBridge.md) for scope and boundaries.

## Getting started

Start with the [file Bridge guide](docs/bridge-file.md) (Chinese). The prototype requires Python 3.11+ and a usable STAR-CCM+ installation and license; it has been exercised on Linux with STAR-CCM+ 2602. From the repository root:

```bash
python3 bridge/runner/file_bridge.py inspect 'Base.sim~' --work-dir outputs/read-parameters
```

Supply your own compatible simulation file and a new work directory. For repeated operations on one loaded simulation, use the [background-session guide](docs/bridge-session.md). See the guides for modification, explicit save, shutdown, results, and current limits. The `starbridge` commands shown in the design and roadmap are still proposals.

## More documentation

| Document | Purpose |
|---|---|
| [Catalog describe/read](docs/catalog-runtime.md) | Read selected properties with server-version checks, session references, and per-property errors |
| [Catalog modification](docs/catalog-modifier.md) | Schema 2 property writes, expected state, readback, diffs, and file reload verification |
| [Offline catalog tools](docs/catalog.md) | Generate versioned API candidates, merge reviewed semantics, and compare declarations |
| [Modifier guide](docs/modifier.md) | Single-object requests, expected-state checks, readback, and save behavior |
| [Inspector snapshot](docs/inspector.md) | Object coverage, snapshot fields, read errors, and validation limits |
| [File Bridge guide](docs/bridge-file.md) | File operations, requirements, and implementation limits |
| [Background-session guide](docs/bridge-session.md) | Start, inspect, modify, save, and stop a persistent STAR server |
| [Design](StarBridge.md) | Product scope, proposed architecture, sessions, and working memory |
| [Current work](TODO.md) | Current milestone, tasks, and completion criteria |
| [Roadmap](docs/roadmap.md) | Future stages and expected outcomes |
| [Reference projects](docs/references.md) | Sources, relevant design ideas, and applicability limits |

The design and planning documents are maintained in Chinese. Only the project entry page has an English translation.

## Contributing

Contributions can describe concrete simulation workflows, clarify requirements, or improve the documents. Use the [current milestone](TODO.md) to identify open planning questions; implementation choices remain under discussion.

## License

[MIT](LICENSE) © 2026 Laxpud.
