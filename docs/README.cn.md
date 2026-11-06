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
- **显式保存**：结构化会话修改保留在内存中，收到保存指令后才写回当前文件或另存为；Java 执行和 STAR 既有自动保存仍有其自身影响，现成网格／计算方法会先检查这些设置。独立文件流程则另存新文件并重新加载核对。具体操作见[会话说明](tech/bridge-session.md)和[文件 Bridge](tech/bridge-file.md)。

结构化目录支持范围取决于精确的 [STAR release／Build](<tech/catalog-versions.md>)；通用生命周期与执行改为要求所选安装编译及运行时身份核对。结构化属性仍有适配范围；新增的[通用 Java 执行与工作记忆接口](tech/generic-execution.md)提供了目录之外的操作途径和带场景的方法复用。后台从零创建、请求重放、保存及重新加载已在 STAR 2602 实际执行；独立的 909 单元层流通道还完成了网格生成、5 次求解迭代和结果导出。这些是操作通路证据，不是收敛或工程精度验证。通用关联写入、GUI 接入及特定中断恢复场景也已在该小算例实际执行；其他窗口的自定义布局、子菜单及全部写入链路仍未覆盖，见[验证边界](tech/bridge-session.md#验证边界)、[需求文档](<../StarBridge.md>)和[当前工作](../TODO.md)。

## 参与贡献

欢迎补充具体算例工作流、澄清需求或改进文档。可从[当前里程碑](../TODO.md)查看剩余工作，从[路线图](roadmap.md)查看范围仍待讨论的候选方向。

## 许可证

[MIT](../LICENSE) © 2026 Laxpud。
