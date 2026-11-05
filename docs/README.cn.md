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

支持范围取决于精确的 [STAR release／Build](tech/catalog-versions.md)及已适配的属性或操作，尚未覆盖全部算例设置。本机 GUI／服务器连接已有实现，但真实 GUI 接入、保存、失败恢复及调整后的写入链路尚未经过 STAR 实测，见[验证边界](tech/bridge-session.md#验证边界)。网格生成、求解执行和持久化工作记忆仍为后续方向，见[需求文档](<../StarBridge.md>)和[路线图](roadmap.md)。

## 参与贡献

欢迎补充具体算例工作流、澄清需求或改进文档。可从[当前里程碑](../TODO.md)查看剩余工作，从[路线图](roadmap.md)查看范围仍待讨论的候选方向。

## 许可证

[MIT](../LICENSE) © 2026 Laxpud。
