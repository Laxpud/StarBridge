# StarBridge

[项目入口](docs/README.cn.md) · [当前工作](TODO.md) · [路线图](docs/roadmap.md) · [参考项目](docs/references.md)

## 项目定位

**StarBridge** 是一个面向 AI Agent 的 **STAR-CCM+ 交互插件**，通过 Skills、MCP、自动化接口和持久化工作记忆，使 Agent 能够读取、理解、修改、运行 STAR-CCM+ 算例，并验证操作结果。

项目当前处于初步规划阶段。本文描述目标能力和拟议架构，不代表已经实现；接口名称、目录划分和实现方式仍可在技术验证后调整。

StarBridge 不将自身限定为单纯的 CLI 或 Java Macro 工具，而是作为 AI Agent 与 STAR-CCM+ 之间的统一桥接层。

核心目标：

> 让 AI Agent 能够以结构化、安全、可验证的方式操作 STAR-CCM+ 算例。

这里的“验证”限定为检查操作是否成功、设置是否按预期改变，以及是否产生非预期修改。验证 CFD 结果可信性不属于当前定位；Agent 可以结合知识储备、技术文本和工作记忆判断物理合理性与网格质量，当前暂不考虑收敛性判断。

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
* 对修改前后的算例进行 Diff，并验证操作结果
* 为 AI Agent 提供 STAR-CCM+ 工作流知识
* 支持 StarBridge 服务常驻，以及后台或 GUI 算例会话常驻
* 持久化用户偏好、项目约定、算例知识和工作记录，为后续操作提供上下文

---

## 总体架构

```text
AI Agent
   │
   ├── Skills
   │     └── 描述如何完成 STAR-CCM+ 工作流
   │
   └── MCP / CLI
         └── 提供共享 Core API 的操作入口
                │
                ▼
         StarBridge Core
          ├── 会话管理
          ├── 工作记忆存储与检索
                │
        ┌───────┴────────┐
        │                │
   Java API Bridge      Runner
        │                │
        └───────┬────────┘
                ▼
       STAR-CCM+ 常驻算例会话
         （后台 / GUI）
                │
             .sim
```

StarBridge 的基本原则是：

> Agent 不直接依赖复杂的 STAR-CCM+ Java API，而是通过稳定的 StarBridge 接口操作算例。

工作记忆由 StarBridge 提供持久化存储与检索接口，Agent 负责结合记忆理解任务，Bridge 负责具体操作并反馈当前事实。

---

## 常驻服务与算例会话

StarBridge 服务和 STAR-CCM+ 算例会话都应支持常驻，但两者有独立的生命周期：

* **StarBridge 服务常驻**：持续接收 Agent 请求、管理会话并返回操作结果。
* **STAR-CCM+ 算例会话常驻**：算例保持加载，连续查询、修改和执行复用同一个运行状态，无需每次重新启动并加载 `.sim`。

算例会话支持两种运行模式：

| 模式 | 预期行为 |
|---|---|
| 后台常驻 | 无需打开 GUI，Agent 持续操作已加载的算例 |
| GUI 常驻 | 用户通过图形界面查看和操作，Agent 操作同一个算例会话 |

StarBridge 的操作对象既包括 `.sim` 文件，也包括已加载的算例会话。文件用于加载和保存，会话承载当前状态，包括尚未保存的修改。独立加载同一个文件会形成不同会话，不应假定这些会话的内存状态自动同步。

会话设计遵循以下要求：

1. 后台和 GUI 模式尽量使用统一的查询、修改、执行与验证接口。
2. 操作应明确指向目标会话，避免文件与会话、不同会话之间发生混淆。
3. 区分连接、断开、保存和关闭；Agent 断开连接不应隐含关闭算例或丢弃修改。
4. GUI 模式下，用户和 Agent 可能修改同一算例。Agent 执行修改前应检查当前状态，避免根据过时信息操作；具体协调机制待设计。

连接已有 GUI 会话的机制，以及后台会话能否直接接入 GUI，需要后续技术验证。支持两种模式不意味着当前要求二者无缝切换。

---

## 持久化工作记忆

训练数据和 STAR 技术文档不足以覆盖具体用户的需求与算例组织风格。StarBridge 需要提供可持续积累、可修正的工作记忆，记录实时对象树无法充分表达的背景，尤其是设置背后的原因和需要保留的约定。

记忆按作用范围区分：

| 范围 | 内容示例 |
|---|---|
| 用户偏好 | 命名风格、参数组织习惯、常用操作方式 |
| 项目约定 | 单位与坐标系约定、Tags 分类、模板规范、特定建模要求 |
| 算例知识 | 参数的实际用途、对象依赖、特殊设置的原因 |
| 工作记录 | 已完成的修改、失败尝试及原因、用户纠正、待确认问题 |

记忆参与操作的基本流程为：

```text
读取当前算例 → 检索相关记忆 → Agent 制定操作
    → Bridge 执行并回读验证 → 记录结果及必要的新知识
```

记忆机制遵循以下边界：

1. **实时状态以 Bridge 读取结果为准。** 记忆用于解释和指导，不能替代当前算例查询。
2. **记录作用范围与来源。** 区分用户明确要求、文档约定、实际操作记录与 Agent 推断，避免把局部经验泛化为通用规则，或将推断当成已确认事实。
3. **当前指令优先。** 旧偏好与当前要求冲突时遵循当前要求；失效的历史记录不再作为有效约束。
4. **操作记录与长期记忆分开。** 操作过程可以自动留痕，但将经验提升为用户偏好或项目规则需要明确依据，不能从一次操作就推断长期习惯。
5. **支持查看、修改和删除。** 用户可以纠正错误记忆；记忆跨 Agent 对话和 STAR 会话保留，后台与 GUI 模式使用同一套上下文机制。

Skills 提供通用领域工作流，工作记忆补充具体用户、项目和算例的上下文。存储介质、检索方式及具体接口留待后续设计，当前不预设文件、数据库或其他方案。

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
├── core/
│   ├── sessions/
│   └── memory/
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

除算例操作外，接口还需支持会话管理及工作记忆的检索、记录、查看、修改与删除。具体名称和参数待设计；以下算例操作应明确绑定目标会话。

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

以下是批处理调用示例，仅说明一种执行入口，不代表常驻会话的最终通信方案：

```bash
starccm+ -batch StarBridgeMacro.java case.sim
```

Bridge 负责：

1. 启动 STAR-CCM+ 或连接目标算例会话（具体连接机制待验证）
2. 获取目标会话中的 `Simulation`
3. 访问 STAR 对象树
4. 执行查询或修改
5. 将结果序列化
6. 返回给 MCP / CLI
7. 按明确的保存请求写出修改后的 `.sim`

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

上述命令展示按文件调用的初步形式。常驻会话操作还需提供明确的目标会话选择方式，具体命令语法待设计。

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

常驻模式下，这一流程作用于目标会话的当前状态；执行前结合相关记忆理解约束，并重新检查拟修改对象。执行后回读验证、记录结果，再按请求另存文件。GUI 中尚未保存的用户修改也属于当前状态，不能用磁盘文件或旧快照代替。

Diff 与回读验证用于确认修改是否符合预期，不构成 CFD 结果可信性或收敛性判断。

---

## 开发阶段

阶段顺序、预期交付和跨阶段要求统一维护在[路线图](docs/roadmap.md)。当前规划任务及完成条件见 [TODO](TODO.md)。

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

Agent 负责理解任务，Skill 提供领域知识，持久化工作记忆补充用户和算例上下文，MCP 提供操作能力，Bridge 在目标后台或 GUI 会话中完成 STAR-CCM+ 的实际读写。

---

## 一句话定义

> **StarBridge 是一个面向 AI Agent 的 STAR-CCM+ 插件，通过 Skills、MCP、持久化工作记忆和自动化 Bridge，使 Agent 能够在后台或 GUI 常驻算例会话中结构化地读取、理解、修改、运行算例并验证操作结果。**

