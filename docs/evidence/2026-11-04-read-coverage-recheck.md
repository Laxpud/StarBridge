# 2026-11-04 新版读取覆盖与会话复查记录

状态：**历史实测证据**，记录 2026-11-04 对 `5d59f7d` 基线的一次真实算例只读复查；不是修复完成声明，也不能据此判断当前通用宏能力。文中的“新版”与“当前源码”均指当时基线，当前实现与后续差距见[目标与当前改进问题](<../specs/spec-2026-11-10-10-07.md>)。

## 1. 版本、入口与范围

- 复查源码：`5d59f7df32e1dd4e76f408ae6a1f3a581cfe6c75`，工作树当时无产品源码修改。
- 对话中已接入的 MCP 返回契约 schema 1；没有用该旧入口的结果充当新版证据。
- 实际复查直接导入当前源码的 `Service`，与 CLI／MCP 共用实现；契约 schema 2，统一使用 `object_id`、`describe_object`、`read_properties`。不是新版 MCP 传输端到端验收，也没有升级客户端配置。
- STAR：2602 / Build `21.02.007`，使用实际安装内启动器和对应本机 Javadoc。
- 算例：[当前 FA 计算快照](</home/laxpud/workspace/Cases/Airfiol_NWSE_NACA0012/cases/FA_ExportStartPoint_1@08640.sim>)。
- 未重新比较归档 FA 和基础文件；未核实实际网格、收敛结果或物理有效性。
- 只执行打开、定位、描述、读取、快照、普通关闭和状态查询。没有修改设置、生成网格、求解或保存。
- 本轮原始 JSON 保存在项目输出目录，属于本机证据而非随仓库分发的固定 fixture。下列链接在没有这些输出的其他机器上可能不可用。

## 2. 问题清单

| ID | 项目 | 新版结果 | 证据层级与范围 |
|---|---|---|---|
| R01 | Airfoil 几何选择 | `EnableControl=true`；`GeometryObjects` 的类型为 `DynamicQuerySelectorInput`，描述原因为 `unsupported_value_type`，实际读取返回 `unsupported` | 已实际描述及读取；仍无法核实控制选择了哪些表面 |
| R02 | Cl 报告关联 | `Parts`、`CoordinateSystem`、`Representation`、`PressureOption` 均不支持 | 已描述，未取得这些属性的当前值 |
| R03 | PitchMotion 坐标系 | `CoordinateSystem`、`ManagedCoordinateSystems` 不支持 | 已描述 |
| R04 | BackgroundBlock 几何 | `Vertex1`、`Vertex2`、`CoordinateSystem`、`Region`、`ContactingParts`、`DescriptionsOutput` 不支持 | 已描述 |
| R05 | 隐藏属性 | FreeAir 的 Segregated Flow 模型 `DissipationFactor`，以及 Segregated Flow 求解器 `PressureGradientInverseDistanceWeighting` 均为 `hidden_property_metadata_only` | 已描述；不能把策略拒绝混同于基本类型不支持 |
| R06 | 非 CSO 代理 | `DirectedMeshSourceSurfaces`、`DirectedMeshTargetSurfaces` 为 `Unsupported proxy`，`object_id=null` | 已浏览；没有可调用的后续导航引用 |
| R07 | 入口 Velocity 入口差异 | 运行时树描述不支持 `Method`、`DimensionsVector`、`CoordinateSystem`；目录类型入口成功读出对应方法、坐标系及量纲文本 | 两种入口均实查；不是整个 StarBridge 无法读取，也不证明这是新版新增能力 |
| R08 | 只读打开即脏及关闭失败 | 新建自有会话在打开返回时即 `modified=true`；普通关闭被未保存状态拒绝 | 已执行普通关闭并查询状态；脏状态来源未查明 |
| R09 | 完整性范围 | 混合读取支持／不支持属性返回 `inspection_complete=false`；只读开关和 Inspector 快照均可返回 `true`，但未覆盖几何选择 | 范围语义不能当作整对象或整算例审查通过 |
| R10 | 交互延迟 | 单层浏览约 5.3–5.8 秒；仅开关读取两次仍为 11.21／11.30 秒 | 端到端观察，不是严格新旧性能基准 |
| R11 | 实际安装辨识 | 当前接入 MCP 与工作区源码契约不一致；单看发行版本号不能确认执行版本 | 本次使用源码 Service 避开旧入口，未修复分发配置 |

`Units`、`TagGroup`、`Color` 等辅助类型也有不支持项；没有做全树覆盖率统计。R02—R06 不得外推为所有可能的读取路径均不支持。

### 原始证据索引

- R01：[描述](<../../outputs/new-api-audit-20261104/14-airfoil-description.json>)、[实际读取](<../../outputs/new-api-audit-20261104/15-airfoil-read.json>)。
- R02：[Cl 描述](<../../outputs/new-api-audit-20261104/16-cl-description.json>)。
- R03：[运动描述](<../../outputs/new-api-audit-20261104/22-motion-description.json>)。
- R04：[几何描述](<../../outputs/new-api-audit-20261104/21-background-description.json>)。
- R05：[模型描述](<../../outputs/new-api-audit-20261104/24-flow-model-description.json>)、[求解器描述](<../../outputs/new-api-audit-20261104/17-flow-solver-description.json>)。
- R06：[MeshSliding 子节点](<../../outputs/new-api-audit-20261104/10-meshsliding.json>)。
- R07：[树入口描述](<../../outputs/new-api-audit-20261104/38-velocity-runtime-description.json>)、[目录入口读取](<../../outputs/new-api-audit-20261104/31-velocity-catalog-read.json>)。
- R08：[打开](<../../outputs/new-api-audit-20261104/01-open.json>)、[普通关闭](<../../outputs/new-api-audit-20261104/39-normal-close.json>)、[最终状态](<../../outputs/new-api-audit-20261104/40-final-session-status.json>)。
- R09：[仅开关读取](<../../outputs/new-api-audit-20261104/26-airfoil-enable-only.json>)、[Inspector 网格摘要](<../../outputs/new-api-audit-20261104/33-inspector.json#L1972-L2029>)。
- 运行前能力查询的完整结果：[能力记录](<../../outputs/new-api-audit-20261104/03-capabilities.json>)。

## 3. Velocity 的实际成功值

对象：`Background → BackgroundBlock.Inlet → Velocity`，目录类型 `boundary_vector_profile`。

| 属性 | 值 |
|---|---|
| `profile_method` | `star.common.ConstantVectorProfileMethod` |
| `method` | 名称 `Constant`，类型 `star.common.ConstantVectorProfileMethod`，返回会话内引用 |
| `coordinate_system` | 名称 `Laboratory`，类型 `star.common.LabCoordinateSystem`，返回会话内引用 |
| `dimensions` | 文本 `Velocity`，不是 `DimensionsVector` 的指数数组 |

本次未以这组结果推断实际速度分量或其数值正确性。

## 4. 性能观察

计时覆盖本轮 Service 调用的端到端时长，不含人工决策间隔；部分批次在独立 Python 进程内执行，因此不能把全部结果称为同一常驻 MCP 的热缓存基准。

| 操作 | 耗时 |
|---|---:|
| 打开算例 | 约 78.08 秒，来自当时任务输出 |
| 单层树浏览 | 约 5.3–5.8 秒 |
| 运行时描述 | 约 5.4–6.8 秒 |
| Airfoil 开关与几何选择混合读取 | 12.35 秒 |
| Airfoil 仅开关读取 | 11.21 秒 |
| 同一进程内立即重复仅开关读取 | 11.30 秒 |
| 目录入口读取 Velocity 四项 | 5.83 秒 |
| Inspector 快照 | 6.23 秒 |
| 普通关闭检查并拒绝 | 5.94 秒 |

浏览结果内的 `elapsed_ms` 通常只有约 64–136 毫秒；它是 Java 发现函数内计时，不包含完整客户端启动、连接、宏准备与退出。不能据两者相减直接把所有差额归因于网络或 JVM。

旧记录使用两会话并行等不同条件；本轮不能给出严格加速比例。原始结果中已有 `elapsed_seconds`，后续应进一步分阶段计时，而不是重复把全量契约打印到终端。

## 5. 会话交接

复查结束时（2026-11-04 15:53 左右，Asia/Shanghai）：

- `session_id=70b6236a748641ce858b35c17361fc4d`
- `ownership=owned`，端口 `51765`
- `state=ready`，`server_alive=true`，`modified=true`，`active_request=null`
- 普通关闭返回 `Unsaved changes exist; save first or use stop --discard`。

此为当时最后一次查询结果，不是持续存活保证。没有执行 `save_session` 或 `discard=true`，旧会话未关闭。任何后续清理必须先核对当前状态，并获得明确丢弃授权；不能通过自动保存或强制退出掩盖 R08。

## 6. 当时结论与方案去向

本次复查表明，`5d59f7d` 基线的统一接口并未消除复杂值读取、代理导航或只读生命周期缺口。当时据此提出了按对象和属性契约组合读取能力、减少客户端往返并保留身份与描述符核验的建议。

详细的源码依据、适配限制和分阶段建议保留在[已归档的读取覆盖与性能改进分析](<../archive/read-coverage-and-performance.md>)。该方案已取消作为当前待实施方案，不代表上述问题已修复。后续方向以[最新需求](<../../StarBridge.md>)和[当前工作](<../../TODO.md>)为准；本记录保留用于追溯历史读取范围、性能观察和会话交接，不作为逐项扩展专用适配的任务清单。
