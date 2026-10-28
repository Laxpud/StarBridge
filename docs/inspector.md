# Inspector 对象快照

[返回项目入口](README.cn.md) · [目录描述与读取](catalog-runtime.md) · [文件入口](bridge-file.md) · [后台会话](bridge-session.md)

Inspector 通过共享目录读取算例对象清单、关键属性和归属关系，保留原有 schema 1 输出。文件 `inspect` 的 `summary.json.snapshot` 与后台会话 `inspect` 的 `snapshot` 使用相同格式，修改与保存的 `before`、`after` 也使用此格式。[Modifier](modifier.md) 记录全部已覆盖字段的 Diff，文件修改独立重载后同时核对完整快照和目标目录属性；`set-scalar` 仍保留原 `parameter_diff`，但其重载核对也覆盖完整快照和目标目录内容。

`inspect` 的集合布局由 `snapshot.json` 描述，与按需 `describe/read` 共用候选 API、成员映射和类型适配器。后者的独立 `catalog` 结果包含当前 server 版本、会话引用和逐属性状态，详见[目录描述与读取](catalog-runtime.md)。两种输出保留不同用途：`snapshot` 兼容既有对象清单和 Diff，`catalog` 按请求返回所选属性；两种 `inspection_complete` 各自只说明声明的读取范围。

```bash
python3 bridge/runner/file_bridge.py inspect 'Base.sim~' \
  --work-dir outputs/inspect-objects

python3 bridge/runner/session_bridge.py inspect \
  --session-dir outputs/my-session
```

第二条命令要求已经用 `session_bridge.py start` 启动会话。两种入口自动加载仓库随附的候选目录、`execution.json` 和 `snapshot.json`，不需要新增参数或自行生成目录。当前 server 必须精确匹配 STAR-CCM+ 2602 Build 21.02.007。其余启动条件、目录要求与失败恢复分别见上方使用说明。

## 快照字段

`schema_version` 当前为 `1`，表示本页描述的对象快照格式；早期只有参数的快照不含此字段。原有 `simulation_name`、`session_path`、`modified` 和 `parameters` 字段继续保留。`modified` 是 STAR 返回的内存状态，不能单独据此判断磁盘文件是否发生变化。

对象条目保留 `name` 和 `object_type`，类型使用 STAR Java 类的简单名称；布局中配置了 `tags` 的对象另有排序后的标签名称数组。关系引用保留名称和类型，边界端点另带所属区域，不重复展开目标对象。名称用于当前快照内识别对象，不是跨重命名的永久 ID；目录驱动读取不会向兼容快照中加入 token/key。

| 字段 | 当前读取内容 |
|---|---|
| `parameters` | 标量表达式、单位、SI 单位对象名 `si_unit`、当前单位值和 SI 值；向量表达式、单位和当前单位分量；附加标签 |
| `field_functions` | 显示名称、可在表达式中引用的 `function_name`、`value_type`、量纲名称 `dimensions`、`user_defined`；用户场函数另有 `definition` |
| `tags` | 标签名称与对象类型 |
| `continua` | 连续体、关联区域 `regions`、其模型管理器中的 `models` |
| `regions` | `region_type`、关联物理连续体 `physics_continuum`；嵌套 `boundaries` 及各自的 `boundary_type` |
| `interfaces` | `interface_type`；边界接口另有 `enabled`、`boundary0`、`boundary1`，端点含所属 `region` |
| `mesh_operations` | 操作名称与类型、STAR 返回的 `index`、关联 `input_parts` |
| `reports` | 报告名称、类型与 `unit`；表达式报告另有 `definition` |
| `monitors` | 监视器名称、类型与 `enabled`；报告监视器另有 `report` 引用 |
| `stopping_criteria` | 准则名称、类型与 `enabled`；最大步数准则另有 `definition`、`maximum_steps`；最大物理时间准则另有数量对象 `maximum_time` |
| `simulation_operations` | 工作流及其 `blocks`；循环块内嵌 `blocks`，子工作流块使用 `workflow` 引用 |

对象集合按名称、类型排序，标签按名称排序。边界嵌套在所属区域中；接口的边界引用也带区域，避免不同区域里的同名边界发生混淆。缺失的可选关系保留为 `null`。

数量对象的 `raw_value` 使用 `unit` 对应单位，`si_value` 使用 `si_unit` 指明的 SI 单位；无量纲单位名称可能为空字符串。向量不转换坐标系，只保留 STAR 返回的分量，不应推断为另一坐标系下的向量。`NaN`、`Infinity` 等非有限数值编码为字符串，保持 JSON 合法。

## 快照布局与共享调用

[`catalogs/2602/snapshot.json`](../catalogs/2602/snapshot.json) 单独维护集合与字段布局，目前包含 16 种节点、11 个根集合和 57 条读取管线。它不复制 Java 成员声明：成员签名、指纹和调用参数继续由 [`execution.json`](../catalogs/2602/execution.json) 与[候选目录](../catalogs/2602/generated/catalog.json)共同核对。快照布局版本和输出 `schema_version` 分开维护，目前都为 `1`。

[`core/snapshot.py`](../core/snapshot.py) 校验版本、节点引用、类型分支、输出字段和只读管线；每个调用必须声明 `effect: read`，请求不能加入任意 Java 调用。编译结果作为 `SNAPSHOT_PLAN` 交给共享 `CatalogRuntime` 遍历，运行目录保存 `snapshot-plan.json`。文件和后台会话的 `inspect`、`save`、修改前后快照及重载核对都使用该布局，Java 不再单独维护各对象的固定快照读取表。

节点自动输出名称和类型，其他字段按布局明确读取；`tags` 通过 `names` 适配器生成，并非所有节点都隐式读取标签。字段有四种形式：

| 字段形式 | 作用 |
|---|---|
| `adapter` 与 `select` | 对管线结果使用共享值适配器；`select` 可沿结果对象逐层选择字段。完整 `quantity` 可用 `output: null` 将五个数量字段展开到当前节点 |
| `record` | 用指定节点描述单个关联对象，允许关系值为 `null` |
| `collection` | 枚举关联对象，用指定节点逐项读取并稳定排序；可表达区域边界、连续体模型和嵌套循环块 |
| `literal` | 写入布局中明确声明的 JSON 标量，例如类型分支的布尔标记，不调用 STAR 方法 |

节点先读取公共字段，再按声明 Java 类执行所有匹配的 `variants`；分支可按布局覆盖公共字段，例如将用户场函数的 `user_defined` 设为 `true`。参数节点要求至少一个已支持类型分支；无匹配时返回 `unsupported` 和读取错误。工作流的循环块递归展开，子工作流使用引用记录；遍历最多允许 64 层节点，并通过当前活动路径中的节点 ID 与对象 key 检测循环，错误仍按下节规则返回。不同路径上再次引用同一对象不会被误判为当前路径的循环。

完整性仍以读取到的字段为准。快照迁入共享目录不代表新增了所有模型设置、所有操作描述或完整的发现/读写/实测分项覆盖报告。

## 空集合、读取错误与覆盖范围

先检查 `inspection_complete` 和 `read_errors`，再使用快照做判断：

- `inspection_complete: true`：本版声明的字段均成功读取。它不表示完整导出了所有 STAR 设置。
- `inspection_complete: false`：至少一处读取失败或存在未支持的参数类型。`read_errors` 中的 `location` 和 `message` 指明对象或集合位置；单个对象失败时另有 `read_error`，已读字段继续保留。
- `[]`：对应位置及其子项没有读取错误时，才表示该管理器返回空集合；读取失败时也可能返回空或部分集合。
- `unsupported: true`：该参数类型的数值读取尚未实现。其他对象只保证本表明确列出的属性；没有额外属性不等于这些属性在 STAR 中不存在。

错误位置使用“集合/对象名称/子集合”的可读路径，名称本身可能含 `/`，因此它不是可供分割解析的 JSON Pointer。`inspect` 对部分读取输出警告并保留结果，退出码仍可为零。宏的 `status: ok` 表示执行和结果写出成功；使用者必须另外检查快照完整性。

布局或成员校验失败在启动客户端、创建工作目录或写入会话活动标记之前拒绝。运行时版本检查先于快照字段读取；版本不符返回 `rejected` 和最小会话元数据，不将其当作完整快照。已有后台会话保持 `ready`；`save` 也在保存前核对版本，修改同时核对快照计划与写入计划。`start` 的首次检查若被拒绝会关闭刚启动的服务；普通 `stop` 的关闭前检查被拒绝则保留原服务。`status` 和 `stop --discard` 不依赖目录，便于查看状态和明确放弃服务。超时或其他无法确认的操作失败仍按[会话失败处理](bridge-session.md#身份隔离与失败处理)处理。

Inspector 不调用报告求值、网格生成、求解或工作流执行。当前不读取场数据数组、监视器历史、完整边界条件、网格控制、物性及模型的全部设置；多相子连续体不递归展开。Simulation Operations 输出结构清单，数组位置不代表执行顺序，也不重建条件和循环的控制逻辑。子工作流仅引用，避免引用循环。

## 验证范围

2026-10-28，本机 Linux、STAR-CCM+ 2602 Build 21.02.007 的 `Base.sim~` 已通过迁移后的文件 `inspect`：快照完整，去除加载元数据后与迁移前快照逐字段一致，原输入 SHA256 未变。

后台工作副本另建 `_SnapshotVector`，快照正确保留定义 `[1.25, -2.5, 3.75]`、空单位名和三个当前单位分量；另建两个工作流，覆盖两层 `LoopAutomationBlock` 嵌套、内层子工作流引用以及子工作流内的停止块。目录快照完整且无读取错误，与迁移前只读 Inspector 在同一服务上读取的内容逐字段一致，比较排除加载元数据。未执行任何工作流。

受控故障适配器使 32 个标量节点分别产生 `read_error` 和全局 `read_errors`，向量与两个工作流仍完整读取；参数根集合的枚举故障则只产生一条 `parameters` 集合错误并返回 `[]`，165 个场函数等其他集合继续正常读取。同一不完整快照计划用于旧 `set-scalar` 写入数值 `77` 时，在写入前拒绝；恢复默认计划后完整读取，角度仍为 `5 deg`。

快照计划注入错误 Build `21.02.999` 时，`inspect` 在字段读取前返回 `rejected`，会话保持 `ready` 且清除活动请求标记。布局中插入 `effect: write` 成员也被 Core 在执行前拒绝。这些检查使用专用故障计划，确认错误隔离与拒绝行为，不代表所有实际模型错误都已覆盖。

使用新快照布局的后台旧 `set-scalar` 成功写入 `7 deg`，并显式另存为 `fixture-saved.sim`。schema 2 文件 `modify` 独立加载该副本后，修改前完整快照与会话保存结果一致；写入 `8 deg`、另存并独立重载后，`reopened_catalog_match`、`reopened_snapshot_match` 和 `input_unchanged` 均通过。向量字段和两工作流的嵌套结构保持一致，原始 `Base.sim~` 摘要未变，本轮服务均已关闭。

该基准算例包含 32 个标量参数、165 个场函数（3 个用户场函数）、6 个标签、1 个连续体及 18 个模型、2 个区域及 17 个边界、3 个接口、4 个网格操作、6 个报告、15 个监视器和 4 个停止准则。迁移前的文件及后台会话读取均没有 `read_errors`；除工作副本的名称和路径外，对象快照一致，连续两次会话快照完全一致，服务只加载一次算例。原文件与工作副本 SHA256 未变化，参数原有字段与更早版本读取结果一致。

基准文件没有 Simulation Operations，非空工作流与向量分支来自上述专用工作副本；其他参数类型、未注入的错误场景及其他 STAR 版本尚未验证。按需目录读取此前的向量与逐属性错误结果见其[独立验证范围](catalog-runtime.md#验证范围与剩余工作)，不混作本次快照验收。Java API 已对照本机安装目录的 `doc/client/html`；实际覆盖以各入口声明的字段及验证范围为准。
