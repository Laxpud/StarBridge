# 路线图

[返回项目入口](README.cn.md)

## 已完成里程碑

- [后台常驻会话与临时客户端](archive/milestone-2026-10-21-10-08-background-session.md)
- [文件 Bridge 原型](archive/milestone-2026-10-21-10-02-file-bridge.md)

## 当前里程碑

当前无进行中的里程碑；活动入口见 [TODO](../TODO.md)。

文件读取与有限设置链路、复用后台会话处理连续请求均已实现，后续阶段按需要推进。各阶段均需核对并同步受影响的项目文档。

## 后续里程碑

文件原型之后，按 Inspector 扩展 → Modifier 扩展 → MCP → Skills 的初步顺序推进。GUI 会话接入和持久化工作记忆继续保留为目标，其具体实施时点待确定：

* Inspector 扩展完善文件与后台会话的读取覆盖；GUI 会话接入另行规划。
* Modifier 阶段需考虑共享状态协调、修改前检查、回读验证和操作记录。
* MCP 阶段需统一暴露会话管理、算例操作与记忆访问能力。
* Skills 阶段需明确通用流程如何使用用户、项目及算例记忆。

具体实现里程碑在技术验证后细化。

### Inspector

在文件原型基础上扩展读取能力；以下是预期覆盖，不是当前已实现清单。

预期覆盖：

* Simulation metadata
* Global Parameters
* Field Functions
* Tags
* Continua
* Physics Models
* Regions
* Boundaries
* Interfaces
* Mesh Operations
* Reports
* Monitors
* Stopping Criteria
* Simulation Operations

预期命令形式（尚未实现）：

```bash
starbridge inspect case.sim > case.json
```

为 Agent 理解已有 STAR-CCM+ 算例提供结构化事实，并结合技术文本和工作记忆补充设置背景。

---

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

### 常驻 Java 适配器与 GUI 接入

价值：在后台服务常驻的基础上，进一步消除每次启动 Java 客户端的开销；允许用户和 Agent 操作同一个 GUI 会话。
待明确：常驻请求接收、API 调用线程、异常恢复，以及共享状态协调。当前只实施短生命周期客户端方案，此项后续再研究。

### 持久化工作记忆

价值：跨对话保留用户偏好、项目约定和算例背景。
待明确：用户、项目、算例身份关联，记忆检索、纠正与失效规则；不作为当前文件原型的前置条件。
