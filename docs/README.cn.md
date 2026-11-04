<a id="readme-top"></a>

<div align="right">
  <a href="../README.md">English</a> | <strong>简体中文</strong>
</div>

<div align="center">
<h1>StarBridge</h1>
<p><strong>帮助 AI Agent 读取 STAR-CCM+ 算例并执行受控修改的桥接层。</strong></p>
</div>

## 适合做什么

StarBridge 让 AI Agent 通过本机 [MCP 或共享 JSON CLI](tech/mcp.md) 检查 STAR-CCM+ 算例，并修改已适配的设置。项目目前处于早期开发阶段。

- **读取设置**：浏览算例对象、查找属性，读取当前值和关联关系。覆盖范围与值格式见[运行时发现](tech/runtime-discovery.md)和[目录读取](tech/catalog-runtime.md)。
- **受控修改**：写入前核对目标、预期旧值及必要约束，写入后回读结果。已适配属性、方法切换及验证记录见[修改说明](tech/catalog-modifier.md)。
- **显式保存**：会话修改保留在内存中，收到保存指令后才写回当前文件或另存为；独立文件流程则另存新文件并重新加载核对。具体操作见[会话说明](tech/bridge-session.md)和[文件 Bridge](tech/bridge-file.md)。

支持范围取决于精确的 [STAR release／Build](tech/catalog-versions.md)及已适配的属性或操作，尚未覆盖全部算例设置。本机 GUI／服务器连接已有实现，但真实 GUI 接入、保存、失败恢复及调整后的写入链路尚未经过 STAR 实测，见[验证边界](tech/bridge-session.md#验证边界)。网格生成、求解执行和持久化工作记忆仍为后续方向，见[设计文档](../StarBridge.md)和[路线图](roadmap.md)。

## 环境准备

启动器需要 PATH 中的 `python3` 与 `uv`，并准备 Python 3.11+ 环境。算例操作需要 Linux、兼容的 STAR-CCM+ 安装及许可证；运行时发现还需要该安装的本机 Javadoc。

## 快速开始

Codex、Claude Code 和 DeepSeek Harness（DSH）用户按[插件安装说明](distribution.md#三端插件安装)统一安装程序、MCP 接入和算例审查 Skill。

源码或通用 stdio 接入见[独立安装说明](distribution.md#源码与通用接入)。`starbridge-cfd` 可在源码目录外运行，当前 `0.1.0` 尚未发布到 PyPI；各客户端的安装结果和限制见[安装记录](evidence/distribution.md)。

## 接下来怎么用

安装完成后，按 [MCP 契约](tech/mcp.md)和[会话说明](tech/bridge-session.md)连接算例并读取设置。

## 更多文档

| 文档 | 职责 |
|---|---|
| [分发与 Harness 接入](distribution.md) | 插件与独立安装、版本关系及实际验收状态 |
| [技术文档](tech/index.md) | 当前实现、专题导航及源码职责 |
| [运行时对象树与属性发现](tech/runtime-discovery.md) | 按真实层级导航、描述和读取属性，有预算搜索及跨加载重定位 |
| [MCP 与共享 Core API](tech/mcp.md) | 本机 stdio 工具、版本资源、JSON CLI 与失败恢复 |
| [目录描述与读取](tech/catalog-runtime.md) | 核对 server 版本、按需读取属性，并返回会话引用和逐属性错误 |
| [目录单属性修改](tech/catalog-modifier.md) | schema 2 写入、旧状态检查、回读、Diff 与文件重载核对 |
| [STAR 版本选择](tech/catalog-versions.md) | 选择 2602 或 2510 的精确 Build，核对会话绑定及分版本证据 |
| [离线目录工具](tech/catalog.md) | 生成版本化候选 API、合并人工语义与比较声明 |
| [Modifier 单项修改](tech/modifier.md) | 修改请求、旧状态检查、回读与保存契约 |
| [Inspector 对象快照](tech/inspector.md) | 目录驱动的快照布局、兼容字段、读取错误与验证边界 |
| [文件 Bridge 使用说明](tech/bridge-file.md) | 文件操作、运行条件与实现边界 |
| [会话使用说明](tech/bridge-session.md) | STAR 会话的连接、读取、修改、保存、断开或停止 |
| [设计文档](../StarBridge.md) | 项目定位、拟议架构、会话与工作记忆 |
| [当前工作](../TODO.md) | 当前里程碑、任务与完成条件 |
| [路线图](roadmap.md) | 后续阶段与预期结果 |
| [参考项目](tech/references.md) | 来源、可借鉴设计及适用边界 |

设计与规划文档使用中文维护，仅项目入口提供英文译文。

## 参与贡献

欢迎补充具体算例工作流、澄清需求或改进文档。可从[当前里程碑](../TODO.md)查看剩余工作，从[路线图](roadmap.md)查看范围仍待讨论的候选方向。

## 许可证

[MIT](../LICENSE) © 2026 Laxpud。
