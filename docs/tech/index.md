# 技术文档

[项目入口](../README.cn.md) · [当前任务](../../TODO.md) · [需求文档](<../../StarBridge.md>)

核对基线：三端插件、会话接入与运行简化里程碑；具体代码基线及实测限制见架构页。

先读[当前架构](architecture.md)，了解系统上下文、进程、组件和源码分工，再按下列主题查阅。架构页记录核对基线；实现状态与历史实测证据的区别见[接口与文档边界](architecture.md#接口与文档边界)。

## 接口、会话与发现

| 文档 | 负责的内容 |
|---|---|
| [MCP 与共享 Core API](mcp.md) | 公开工具、参数、结果、JSON CLI 与恢复约定 |
| [通用执行与工作记忆](<generic-execution.md>) | 同会话 Java 步骤、执行凭据、从零创建、方法与资料记忆 |
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
| [旧修改入口迁移](modifier.md) | 已移除入口到统一属性调用的对应关系 |

文件工作流和快照格式继续保留；已删除修改入口仅提供迁移说明，当前工作见 [TODO](../../TODO.md)。

## 分发维护

- [发行包与插件维护](distribution.md)：随包资源、三端入口、共享启动器和发布准备。

## 决策与参考

- [ADR 0001](../adr/0001-runtime-discovery.md)：采用运行时对象树与属性发现。
- [ADR 0002](../adr/0002-plugins-sessions-and-storage.md)：三端插件、会话复用、存储和运行简化。
- [参考项目](references.md)：设计来源、可借鉴内容及适用边界。

用户安装和客户端接入见[分发说明](../distribution.md)；需求与实施安排分别见[规格](../archive/spec-2026-11-03-14-23.md)和[计划](../archive/plan-2026-11-03-14-23.md)。
