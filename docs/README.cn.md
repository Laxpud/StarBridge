<a id="readme-top"></a>

<div align="right">
  <a href="../README.md">English</a> | <strong>简体中文</strong>
</div>

<div align="center">
<h1>StarBridge</h1>
<p><strong>面向 AI Agent 的 STAR-CCM+ 桥接层，计划支持读取、修改、运行算例并验证操作结果。</strong></p>
</div>

## 适合做什么

StarBridge 目前处于早期开发阶段。文件 Bridge 原型已支持读取全局参数、修改已有标量并另存，以及重新加载核对保存值。后台会话原型也已支持复用同一个 STAR 服务连续操作，每次请求启动临时 Java 客户端；常驻 Java 适配器、GUI 接入、MCP 和工作记忆仍为后续目标。

拟议系统结合结构化算例访问、工作流 Skills、持久化工作记忆，以及后台或 GUI 常驻算例会话。具体定位与边界见[设计文档](../StarBridge.md)。

## 快速开始

先阅读[文件 Bridge 使用说明](bridge-file.md)。原型需要 Python 3.11 或更新版本、可用的 STAR-CCM+ 安装及许可证；目前已在 Linux 和 STAR-CCM+ 2602 上实际运行。在仓库根目录执行：

```bash
python3 bridge/runner/file_bridge.py inspect 'Base.sim~' --work-dir outputs/read-parameters
```

请提供自己的兼容算例文件，并使用新的工作目录。需要连续操作同一个已加载算例时，使用[后台会话入口](bridge-session.md)。修改、显式保存、关闭、结果查看及当前限制见相应说明。设计和路线图中的 `starbridge` 命令仍为拟议形式。

## 更多文档

| 文档 | 职责 |
|---|---|
| [文件 Bridge 使用说明](bridge-file.md) | 文件操作、运行条件与实现边界 |
| [后台会话使用说明](bridge-session.md) | 常驻 STAR 服务的启动、读取、修改、保存和关闭 |
| [设计文档](../StarBridge.md) | 项目定位、拟议架构、会话与工作记忆 |
| [当前工作](../TODO.md) | 当前里程碑、任务与完成条件 |
| [路线图](roadmap.md) | 后续阶段与预期结果 |
| [参考项目](references.md) | 来源、可借鉴设计及适用边界 |

设计与规划文档使用中文维护，仅项目入口提供英文译文。

## 参与贡献

欢迎补充具体算例工作流、澄清需求或改进文档。可从[当前里程碑](../TODO.md)查看待讨论的规划问题；实现方案仍在讨论中。

## 许可证

[MIT](../LICENSE) © 2026 Laxpud。
