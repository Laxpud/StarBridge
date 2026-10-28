# 路线图

[返回项目入口](README.cn.md)

## 已完成里程碑

- [Inspector 对象快照](archive/milestone-2026-10-28-15-29-inspector.md)
- [后台常驻会话与临时客户端](archive/milestone-2026-10-21-10-08-background-session.md)
- [文件 Bridge 原型](archive/milestone-2026-10-21-10-02-file-bridge.md)

## 当前里程碑

当前无进行中的里程碑；活动入口见 [TODO](../TODO.md)。

文件与后台会话的对象读取、有限设置和连续请求均已实现，后续阶段按需要推进。各阶段均需核对并同步受影响的项目文档。

## 后续里程碑

Inspector 对象清单已交付，后续按 Modifier 扩展 → MCP → Skills 的初步顺序推进。GUI 会话接入和持久化工作记忆继续保留为目标，其具体实施时点待确定：

* Modifier 阶段需考虑共享状态协调、修改前检查、回读验证和操作记录。
* MCP 阶段需统一暴露会话管理、算例操作与记忆访问能力。
* Skills 阶段需明确通用流程如何使用用户、项目及算例记忆。

具体实现里程碑在技术验证后细化。

### Modifier

在已有标量设置入口基础上扩展修改类型，并明确每类操作的检查与保存契约。

优先支持：

```text
Global Parameters
Field Functions
Tags
Mesh Controls
Boundary Parameters
Selected Physics Settings
Simulation Operations
```

修改后自动重新读取对应对象并验证。

---

### MCP

将 Core API 暴露为 MCP Tools 和 Resources。

形成：

```text
AI Agent
    ↓
StarBridge MCP
    ↓
StarBridge Core
    ↓
STAR-CCM+
```

---

### Skills

逐步积累 STAR-CCM+ 工作流 Skills。

例如：

```text
mesh-setup
overset-mesh
rotor-case
oge-case
nwse-case
vof-setup
solver-setup
case-audit
```

Skill 与底层 MCP Tool 分离：

> **Tool 决定 Agent 能做什么。**

> **Skill 决定 Agent 应该怎么做。**

---

设计依据见 [StarBridge 设计](../StarBridge.md)，参考实现与适用边界见[参考项目](references.md)。

## Backlog

### Inspector 读取深度与补充验证

当前交付对象清单及关键属性，字段契约与未实测分支统一见 [Inspector 对象快照](inspector.md)。后续结合实际算例补充非空 Simulation Operations、向量参数和读取失败场景的验证，并按工作流需要扩展边界条件、物性、网格控制及操作执行顺序；不将当前清单视为完整设置导出。

### 常驻 Java 适配器与 GUI 接入

价值：在后台服务常驻的基础上，进一步消除每次启动 Java 客户端的开销；允许用户和 Agent 操作同一个 GUI 会话。
待明确：常驻请求接收、API 调用线程、异常恢复，以及共享状态协调。当前只实施短生命周期客户端方案，此项后续再研究。

### 持久化工作记忆

价值：跨对话保留用户偏好、项目约定和算例背景。
待明确：用户、项目、算例身份关联，记忆检索、纠正与失效规则；不作为当前文件原型的前置条件。
