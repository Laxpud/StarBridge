# StarBridge

## 项目定位

**StarBridge** 是一个面向 AI Agent 的 **STAR-CCM+ 交互插件**，通过 Skills、MCP 与自动化接口，使 Agent 能够读取、理解、修改、执行并验证 STAR-CCM+ 算例。

StarBridge 不将自身限定为单纯的 CLI 或 Java Macro 工具，而是作为 AI Agent 与 STAR-CCM+ 之间的统一桥接层。

核心目标：

> 让 AI Agent 能够以结构化、安全、可验证的方式操作 STAR-CCM+ 算例。

---

## 核心能力

StarBridge 计划提供以下能力：

* 读取 STAR-CCM+ 算例结构与设置
* 查询参数、场函数、标签和对象属性
* 检查物理模型、区域、边界和接口
* 检查和修改网格操作及网格控制参数
* 修改全局参数和模型设置
* 创建或修改 Simulation Operations
* 执行网格生成和求解
* 保存新的 `.sim` 文件
* 对修改前后的算例进行 Diff 和验证
* 为 AI Agent 提供 STAR-CCM+ 工作流知识

---

## 总体架构

```text
AI Agent
   │
   ├── Skills
   │     └── 描述如何完成 STAR-CCM+ 工作流
   │
   └── MCP
         └── 提供结构化操作接口
                │
                ▼
         StarBridge Core
                │
        ┌───────┴────────┐
        │                │
   Java API Bridge    CLI / Runner
        │                │
        └───────┬────────┘
                ▼
           STAR-CCM+
                │
             .sim
```

StarBridge 的基本原则是：

> Agent 不直接依赖复杂的 STAR-CCM+ Java API，而是通过稳定的 StarBridge 接口操作算例。

---

## 项目结构

```text
StarBridge/
├── skills/
│   ├── inspect-simulation/
│   ├── configure-mesh/
│   ├── configure-physics/
│   ├── configure-boundaries/
│   ├── rotor-workflow/
│   └── ...
│
├── mcp/
│   ├── server/
│   ├── tools/
│   └── resources/
│
├── bridge/
│   ├── java/
│   ├── runner/
│   └── serializer/
│
├── cli/
│   └── starbridge
│
├── schemas/
│   ├── simulation/
│   ├── parameters/
│   ├── mesh/
│   ├── physics/
│   └── operations/
│
├── tests/
└── docs/
```

---

## Skills

Skills 负责描述：

> **Agent 应该如何完成某项 STAR-CCM+ 工作。**

Skill 不负责直接操作 STAR，而是提供工作流知识、操作顺序、检查规则和约束。

例如：

```text
inspect-simulation
configure-mesh
configure-physics
configure-boundaries
configure-overset
rotor-case-management
run-and-monitor
```

旋翼算例后续可以建立专门的 Skill：

```text
rotor-case-management
```

负责理解和管理：

```text
RotorControls
Startup
Geometry
MeshControls
PhysicsControls
NWSEControls
```

以及对应的参数、场函数、Tags 和 Simulation Operations。

---

## MCP

MCP 是 Agent 操作 STAR-CCM+ 的主要结构化接口。

初步可以提供：

### Simulation

```text
starbridge.open
starbridge.inspect
starbridge.save
starbridge.save_as
starbridge.run
```

### Parameters

```text
starbridge.list_parameters
starbridge.get_parameter
starbridge.set_parameter
```

例如：

```text
set_parameter(
    name="_RotorRadius",
    value=4.91,
    unit="m"
)
```

### Field Functions

```text
starbridge.list_field_functions
starbridge.get_field_function
starbridge.set_field_function
```

### Tags

```text
starbridge.list_tags
starbridge.get_objects_by_tag
```

### Continua / Physics

```text
starbridge.list_continua
starbridge.inspect_continuum
starbridge.list_models
starbridge.enable_model
starbridge.disable_model
```

### Regions / Boundaries

```text
starbridge.list_regions
starbridge.inspect_region

starbridge.list_boundaries
starbridge.inspect_boundary
starbridge.set_boundary
```

### Mesh

```text
starbridge.list_mesh_operations
starbridge.inspect_mesh_operation
starbridge.set_mesh_control
starbridge.generate_mesh
```

### Simulation Operations

```text
starbridge.list_operations
starbridge.inspect_operation
starbridge.run_operation
```

---

## Bridge

Bridge 是 StarBridge 与 STAR-CCM+ 的实际通信层。

主要依赖：

```text
STAR-CCM+ Java API
+
STAR-CCM+ Batch / CLI
```

例如：

```bash
starccm+ -batch StarBridgeMacro.java case.sim
```

Bridge 负责：

1. 启动 STAR-CCM+
2. 获取 `Simulation`
3. 访问 STAR 对象树
4. 执行查询或修改
5. 将结果序列化
6. 返回给 MCP / CLI
7. 保存修改后的 `.sim`

AI Agent 不需要了解具体的 STAR Java API 实现。

---

## Schema

StarBridge 应尽量避免把 STAR Java 对象直接暴露给 Agent。

所有信息统一转换为结构化 Schema，例如：

```json
{
  "name": "_RotorRadius",
  "objectType": "ScalarGlobalParameter",
  "dataType": "Scalar",
  "value": 4.91,
  "unit": "m",
  "tags": [
    "Geometry",
    "Rotor"
  ]
}
```

这样可以实现：

```text
STAR Java Object
        ↓
StarBridge Schema
        ↓
MCP / CLI
        ↓
AI Agent
```

JSON Schema 也可以成为 StarBridge API 的稳定边界。

---

## CLI

CLI 主要用于：

* 开发
* 调试
* 自动化脚本
* Agent 无 MCP 环境下的调用
* CI 测试

例如：

```bash
starbridge inspect case.sim
```

```bash
starbridge inspect case.sim --parameters
```

```bash
starbridge inspect case.sim --mesh
```

```bash
starbridge get case.sim parameter _RotorRadius
```

```bash
starbridge set case.sim parameter _RotorRadius 4.91 m
```

CLI 与 MCP 应尽可能共享同一个 Core API。

---

## 安全修改机制

StarBridge 不应默认允许 Agent 无限制修改原始算例。

推荐采用：

```text
Inspect
   ↓
Understand
   ↓
Propose Changes
   ↓
Apply
   ↓
Verify
   ↓
Save As
```

即：

```text
case.sim
   │
   ├── inspect
   ▼
case.json
   │
   ▼
AI Agent
   │
   ▼
changes.json
   │
   ▼
StarBridge
   │
   ▼
case_modified.sim
   │
   ▼
inspect
   │
   ▼
diff
```

默认原则：

> 不覆盖原始 `.sim`。

修改操作尽量采用：

> **Read → Diff → Write → Verify**

---

## 开发阶段

### Phase 1 — Inspector

首先实现只读能力。

支持：

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

目标：

```bash
starbridge inspect case.sim > case.json
```

让 Agent 能够完整理解一个已有 STAR-CCM+ 算例。

---

### Phase 2 — Modifier

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

### Phase 3 — MCP

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

### Phase 4 — Skills

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
convergence-check
case-audit
```

Skill 与底层 MCP Tool 分离：

> **Tool 决定 Agent 能做什么。**

> **Skill 决定 Agent 应该怎么做。**

---

## 与参数化 STAR 模板的关系

StarBridge 与结构化 STAR-CCM+ 模板天然互补。

推荐继续采用统一的：

```text
Global Parameters
Field Functions
Tags
Simulation Operations
```

组织算例。

例如旋翼模板：

```text
_RotorRadius
_RotorPosition

RotorControls
├── _Theta0
├── _Theta1
└── _Theta2

Startup
├── _RotorOmega
├── _RotorPeriod
└── ...
```

对象命名越稳定、Tags 越规范，StarBridge 对算例的理解就越可靠。

长期可以形成：

```text
STAR Template Convention
        +
StarBridge Schema
        +
StarBridge Skills
        +
StarBridge MCP
```

从而使 STAR-CCM+ 算例真正具备 Agent-friendly 的结构。

---

## 长期目标

StarBridge 最终希望实现：

```text
用户
 │
 ▼
自然语言
 │
 ▼
AI Agent
 │
 ▼
StarBridge
 │
 ▼
STAR-CCM+
 │
 ▼
Simulation
```

用户可以直接提出：

> 检查这个算例的网格设置。

> 找出当前 OGE 模板中不符合规范的设置。

> 将旋翼半径修改为 4.91 m。

> 将背景计算域调整为 ±10R。

> 检查 RotorControls 是否完整。

> 检查 Startup ramp 是否存在单位或逻辑错误。

> 根据当前算例生成一个 NWSE 版本。

Agent 负责理解任务，Skill 提供领域知识，MCP 提供操作能力，Bridge 完成 STAR-CCM+ 的实际读写。

---

## 一句话定义

> **StarBridge 是一个面向 AI Agent 的 STAR-CCM+ 插件，通过 Skills、MCP 和自动化 Bridge，使 Agent 能够结构化地读取、理解、修改、运行和验证 STAR-CCM+ 算例。**

