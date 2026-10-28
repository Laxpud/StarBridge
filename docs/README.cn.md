<a id="readme-top"></a>

<div align="right">
  <a href="../README.md">English</a> | <strong>简体中文</strong>
</div>

<div align="center">
<h1>StarBridge</h1>
<p><strong>面向 AI Agent 的 STAR-CCM+ 桥接层，计划支持读取、修改、运行算例并验证操作结果。</strong></p>
</div>

## 适合做什么

StarBridge 目前处于早期开发阶段。Inspector 已支持通过文件和后台会话入口读取算例对象、关键属性与归属关系。Modifier 已支持修改已有标量参数与用户场函数表达式、替换现有用户标签关联，并检查预期旧状态及回读值。文件修改另存后重新加载核对；会话修改保留在内存中，由显式保存命令落盘。后台会话原型也已支持复用同一个 STAR 服务连续操作，每次请求启动临时 Java 客户端；常驻 Java 适配器、GUI 接入、MCP 和工作记忆仍为后续目标。

目录驱动的 `describe/read` 已可核对当前 server 版本、定位对象，并通过经审阅的映射和共享类型适配器读取选定属性。结果独立返回会话引用及逐属性状态。目录 `modify` 已支持标量表达式与数值常量、用户场函数定义和用户标签关联，包含旧状态检查、回读及目录与快照两层 Diff。兼容 schema 1 `modify` 和 `set-scalar` 已自动使用同一目录修改器，保留原参数及既有结果字段；随附目录要求运行中 server 精确匹配 2602 Build 21.02.007，`set-scalar` 仍没有调用者提供的预期旧状态。旧 Inspector 快照迁移、更多写适配器、结构操作与模型状态检查仍未完成。

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
| [目录描述与读取](catalog-runtime.md) | 核对 server 版本、按需读取属性，并返回会话引用和逐属性错误 |
| [目录单属性修改](catalog-modifier.md) | schema 2 写入、旧状态检查、回读、Diff 与文件重载核对 |
| [离线目录工具](catalog.md) | 生成版本化候选 API、合并人工语义与比较声明 |
| [Modifier 单项修改](modifier.md) | 修改请求、旧状态检查、回读与保存契约 |
| [Inspector 对象快照](inspector.md) | 对象覆盖、快照字段、读取错误与验证边界 |
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
