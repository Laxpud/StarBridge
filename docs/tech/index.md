# 技术文档

[项目入口](../README.cn.md) · [当前任务](../../TODO.md) · [目标设计](../../StarBridge.md)

先读[当前架构](architecture.md)，了解系统上下文、进程、组件和源码分工，再按下列主题查阅。架构页记录核对基线；实现状态与历史实测证据的区别见[接口与文档边界](architecture.md#接口与文档边界)。

## 接口、会话与发现

| 文档 | 负责的内容 |
|---|---|
| [MCP 与共享 Core API](mcp.md) | 公开工具、参数、结果、JSON CLI 与恢复约定 |
| [STAR 会话接入](bridge-session.md) | 连接已有 STAR、启动自有服务、保存、断开及运行数据 |
| [运行时发现](runtime-discovery.md) | 沿实际对象树导航、分页、读取、搜索及受控赋值 |

## 版本目录与适配

| 文档 | 负责的内容 |
|---|---|
| [STAR 版本选择](catalog-versions.md) | 精确版本绑定、版本材料和分版本证据 |
| [离线目录工具](catalog.md) | 候选 API、人工语义、版本比较与覆盖统计 |
| [目录描述与读取](catalog-runtime.md) | 已映射对象的定位、读取计划与值格式 |
| [目录修改](catalog-modifier.md) | 已映射属性写入、方法切换及领域约束 |

## 文件与兼容入口

| 文档 | 负责的内容 |
|---|---|
| [文件 Bridge](bridge-file.md) | 独立文件加载、另存与重载核对 |
| [Inspector 快照](inspector.md) | schema 1 对象快照、字段及覆盖范围 |
| [Modifier 兼容契约](modifier.md) | schema 1 修改和旧调用入口 |

这些入口仍有各自契约，接口迁移进度只在 [TODO](../../TODO.md#接口与执行)维护。

## 决策与参考

- [ADR 0001](../adr/0001-runtime-discovery.md)：采用运行时对象树与属性发现。
- [ADR 0002](../adr/0002-plugins-sessions-and-storage.md)：三端插件、会话复用、存储和运行简化。
- [参考项目](references.md)：设计来源、可借鉴内容及适用边界。

用户安装和客户端接入见[分发说明](../distribution.md)；需求与实施安排分别见[规格](../specs/spec-2026-11-03-14-23.md)和[计划](../plans/plan-2026-11-03-14-23.md)。
