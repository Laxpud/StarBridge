# 路线图

[返回项目入口](README.cn.md)

## 当前里程碑

[初步规划与设计边界](../TODO.md)；当前任务及完成条件仅在 TODO 维护。

下述阶段为拟议顺序，不表示已启动实现，也不构成运行 STAR 或编写测试的授权。各阶段均需核对并同步受影响的项目文档。

## 后续里程碑

以下保留 Inspector → Modifier → MCP → Skills 的初步推进顺序。常驻会话和持久化工作记忆是贯穿各阶段的设计要求，不另行假定为已经完成的基础设施：

* Inspector 阶段需验证后台和 GUI 会话的读取路径，明确会话身份及实时状态来源。
* Modifier 阶段需考虑共享状态协调、修改前检查、回读验证和操作记录。
* MCP 阶段需统一暴露会话管理、算例操作与记忆访问能力。
* Skills 阶段需明确通用流程如何使用用户、项目及算例记忆。

具体实现里程碑在技术验证后细化。

### Inspector

首先实现只读能力。

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

增加有限、明确、安全的修改能力。

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
