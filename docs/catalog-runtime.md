# 目录驱动的描述与读取

[返回项目入口](README.cn.md) · [离线目录工具](catalog.md) · [目录修改](catalog-modifier.md) · [Inspector 快照](inspector.md) · [当前任务](../TODO.md)

文件和后台会话 Runner 的 `describe`、`read` 已通过同一份候选目录、人工调用映射和类型适配器访问当前算例。执行前精确核对正在运行的 STAR server 版本，再按类型、名称及父对象定位目标。[属性修改与张量方法切换](catalog-modifier.md)也复用这些定位与读取管线；兼容 schema 1 `modify` 和 `set-scalar` 也使用同一目录修改器；兼容 `inspect` 快照也通过独立布局复用相同候选声明、成员映射和读取适配器，见 [Inspector](inspector.md#快照布局与共享调用)。

## 使用方式

需要 Python 3.11+、可用的 STAR-CCM+ 2602 Build 21.02.007 安装和许可证。以下命令直接使用随仓库分发的 `catalogs/2602/generated/catalog.json`；可按[离线目录工具](catalog.md#生成与查看)从该安装及当前 `catalogs/2602/selection.json` 重新生成到新路径进行核对。`describe/read` 仍显式指定候选目录和人工执行映射。

保存 `read-request.json`，将对象名称换成目标算例中的实际名称：

```json
{
  "schema_version": 1,
  "action": "read",
  "target": {
    "type": "scalar_parameter",
    "name": "_AirfoilPitchAmplitude"
  },
  "properties": ["quantity", "tags"]
}
```

文件模式加载该文件、读取所选属性并核对原文件 SHA256，不保存算例：

```bash
python3 bridge/runner/file_bridge.py read 'Base.sim~' \
  --catalog catalogs/2602/generated/catalog.json \
  --execution catalogs/2602/execution.json \
  --request read-request.json \
  --work-dir outputs/catalog-read-file
```

`--work-dir` 必须是新目录。成功后命令输出 `summary.json` 路径，其中 `catalog` 是目录读取结果，`input_unchanged` 表示原输入摘要核对通过。

后台模式先按[会话说明](bridge-session.md)启动服务，再读取同一已加载工作副本：

```bash
python3 bridge/runner/session_bridge.py read \
  --session-dir outputs/my-session \
  --catalog catalogs/2602/generated/catalog.json \
  --execution catalogs/2602/execution.json \
  --request read-request.json
```

要描述当前对象的已配属性与结构操作，把请求中的 `action` 改为 `describe`，另存为 `describe-request.json`。`describe` 会核对版本、定位对象、读取已声明目标条件及操作的当前方法选项，但不读取各属性的完整值，也不执行 setter：

```bash
python3 bridge/runner/file_bridge.py describe 'Base.sim~' \
  --catalog catalogs/2602/generated/catalog.json \
  --execution catalogs/2602/execution.json \
  --request describe-request.json \
  --work-dir outputs/catalog-describe-file

python3 bridge/runner/session_bridge.py describe \
  --session-dir outputs/my-session \
  --catalog catalogs/2602/generated/catalog.json \
  --execution catalogs/2602/execution.json \
  --request describe-request.json
```

请求的 `action` 必须与 CLI 命令一致。`describe/read` 都要求 `--catalog`、`--execution` 和 `--request`，不接受修改值或另存路径。

## 请求与目标身份

本页描述与读取请求的格式版本为整数 `1`；属性修改使用独立的 schema 2 契约，结构操作使用 schema 3。顶层必需字段为 `schema_version`、`action`、`target`，可选字段为 `properties`；未知字段会被拒绝。`properties` 是不重复、非空的属性 ID 数组，省略时选择该类型当前映射中的全部属性，不能据此理解为整个 STAR 对象的全部属性。未映射属性在启动客户端或写入会话活动标记前拒绝。`properties` 只筛选属性；`describe` 另返回该类型全部已配操作，`read` 不返回操作描述。

`target` 使用目录的类型 ID 和精确显示名称。当前定位器从指定管理器枚举对象，按 Java 类型过滤后要求名称唯一匹配。边界和 `tensor_profile` 还必须提供所属区域；例如边界请求：

```json
{
  "schema_version": 1,
  "action": "read",
  "target": {
    "type": "boundary",
    "name": "BackgroundBlock.Bottom",
    "parent": {"type": "region", "name": "Background"}
  },
  "properties": ["boundary_type", "region"]
}
```

成功结果的 `catalog.target` 同时包含两种身份信息：

- `locator`：类型、显示名称和父对象路径，不含会话引用。独立加载或文件重新加载后，可以用它重新定位，但名称、类型与旧状态仍需重新核对。
- `reference`：`session_token` 与 STAR 对象 `key`。后台服务创建时生成并保存会话 token；文件模式每次加载使用新的 token。在后续同会话请求中，可将此前返回的 `reference` 加到 `target`，要求当前管理器重新定位的对象 key 也一致。父对象可以分别携带自己的引用。

跨会话引用、不同 key、对象缺失或重名会被拒绝。对象名称和 key 都不是跨重载、删除重建的永久身份；不保证删除后 ID 永不复用。关联属性中的对象引用包含名称、实际 Java 类和会话引用，但不一定包含再次定位所需的父路径。

## 结果与错误

目录结果放在独立的 `catalog` 字段中，不改动旧 Inspector 的 `snapshot` 格式。`catalog` 包含：

| 字段 | 含义 |
|---|---|
| `catalog_id` | 人工执行映射及版本的摘要标识；成员声明还由各自指纹锁定 |
| `runtime` | 当前 server 的 `release`、`build` 和本次会话 `session_token` |
| `target` | 已定位对象的类型 ID、名称、实际 Java 类、会话引用及重新定位路径 |
| `properties` | 本次选定属性的描述或读取结果 |
| `operations` | 仅 `describe` 返回：该类型已配置的结构操作描述，未配置时为 `{}` |
| `inspection_complete` | 本次选定属性，以及描述中的操作条件与选项读取是否全部成功；不表示完整读取算例或覆盖其他快照字段 |

`read` 的每项成功结果为 `{"status":"ok","value":...}`，失败结果为 `{"status":"error","error":"..."}`。单项读取失败保留其他属性结果，`inspection_complete` 为 `false`，CLI 输出警告但仍可返回零退出码。使用者必须检查每项状态，不能把失败当成空集合或 `null`。

`describe` 的每项保留 `adapter`、`writable`、`reason`、`guards`、`value_types` 和 `value_guards`。`writable` 只表示该目录属性已有写入实现。`guards` 列出目标条件的 `id`、`expected`、`message`；`value_types` 与 `value_guards` 分别描述新关联允许的目录类型和关联对象条件。

描述命令执行已声明的目标条件只读管线，新增 `guard_checks` 与 `target_condition_status`：

| 条件状态 | 含义 |
|---|---|
| `not_implemented` | 没有该属性的写入实现 |
| `not_declared` | 已有写入实现，但映射没有声明目标条件 |
| `satisfied` | 全部已声明目标条件均已读取，实际值符合预期 |
| `unsatisfied` | 条件均已读取，至少一项实际值不符合预期 |
| `error` | 至少一项条件无法读取或适配；保留其他条件结果 |

`guard_checks` 每项含 `id`、`expected`、`message` 和 `status`；正常读取还含 `actual`，失败则含 `error`。条件不满足不使描述失败；条件读取异常会令 `inspection_complete` 为 `false`。`conditions_checked` 仅在至少有一个目标条件且全部成功读取时为 `true`，不表示条件都满足。没有新值的描述请求不会检查新关联、单位、预期旧状态或全部写入约束，`value_conditions_checked` 始终为 `false`。即使目标条件满足，也不能据此保证后续修改成功；Modifier 仍在准备与执行前重新检查。写入范围见[目录修改](catalog-modifier.md#请求与支持范围)。

### 结构操作描述

当前 `tensor_profile` 的 `operations.set_method` 描述张量方法切换。`implemented` 表示已有操作实现；`read_properties` 声明准备和回读所需的属性集合，当前为 `name`、`method_state`；`state_property` 为完整预期旧状态的来源 `method_state`；`preserved_properties` 列出必须保持不变的属性。`impacts` 按 `target` 和 `owned_objects` 说明目标及其所拥有分量对象可能发生的变化，不保证切回旧方法可以恢复旧设置。

操作同样返回 `guard_checks`、`target_condition_status` 和 `conditions_checked`，含义与属性目标条件相同。映射中的 `methods` 是维护者定义的方法 ID 与 Java 类的对应关系；运行时描述通过 `method_choices` 返回每项 `id`、`java_class`、`available` 和 `matches`。只有当前 Profile 的只读方法枚举中恰好有一个相应实例时，`available` 才为 `true`；`matches` 保留实际方法的名称、类和会话引用，缺失或重名不会被当作可选。

`unmapped_methods` 保留当前枚举中尚无目录方法 ID 的实际对象引用；它们属于已发现但未接入的选项，不能用于结构修改请求。

`method_choices_checked` 表示方法枚举是否成功，失败时还有 `method_choices_error` 并令 `inspection_complete` 为 `false`。选项可用且目标条件满足仍不保证请求可执行：描述不检查调用者旧状态，也不读取全部源状态或未活动目标方法的分量设置。修改准备会继续完成这些检查。可用方法 ID、请求与失败语义见[张量方法切换](catalog-modifier.md#张量-profile-方法切换)。

目录与人工映射不匹配、请求格式错误或未知属性在本地拒绝。当前 server 版本、定位或会话引用不匹配时，宏返回 `status: rejected`，CLI 非零退出；后台会话保持 `ready`，可以重新读取。客户端异常或其他无法确认的失败仍沿用会话 `uncertain` 处理，不自动重试。底层 `result.json` 保存拒绝原因；文件失败时不生成成功 `summary.json`。

每次目录请求还会保存 `catalog-plan.json`、`catalog-request.json`、实际宏和日志。发送给 Java 的计划只包含目标、父类型、选定属性及描述所需的操作只读管线，不把整个候选目录嵌入宏。

## 已配置属性与值格式

以下是当前 `execution.json` 的读取范围，新增映射仍需材料核对和实际验证：

| 类型 ID | 属性 ID |
|---|---|
| `global_parameter` | `name`、`tags` |
| `field_function` | `name`、`tags` |
| `scalar_parameter` | `name`、`quantity`、`quantity_value`、`definition`、`unit`、`tags` |
| `vector_parameter` | `name`、`quantity`、`quantity_value`、`definition`、`unit`、`tags` |
| `physics_continuum` | `name`、`gravity`、`gravity_value` |
| `user_field_function` | `name`、`definition`、`function_name`、`dimensions`、`value_type`、`ignore_boundary_values`、`sync_name`、`tags` |
| `region` | `name`、`region_type`、`physics_continuum`、`index`、`tags` |
| `boundary` | `name`、`boundary_type`、`region`、`index`、`allow_per_part_values`、`tags` |
| `tensor_profile` | `name`、`profile_method`、`tensor`、`basis`、`method_state`；`xx`、`xy`、`xz`、`yx`、`yy`、`yz`、`zx`、`zy`、`zz` 及各自的 `_value` 属性 |
| `user_tag` | `name` |
| `volume_average_report` | `name`、`parts`、`tags`、`field_function` |

适配器按值类型复用：

| 适配器 | 返回值与边界 |
|---|---|
| `primitive` | 字符串、布尔或数值；非有限数值转成显式字符串 |
| `name` | 单个 STAR 对象的显示名称；可选关联允许 `null` |
| `type_name` | 非空对象的 Java 简单类名 |
| `java_class` | 非空对象的完整 Java 类名，用于实际 Profile 方法及方法条件检查 |
| `names` | STAR 对象集合的排序名称数组；空集合返回 `[]`，集合为 `null` 则报错 |
| `enum_name` | 非空 Java 枚举的常量名称 |
| `presence` | `null` 为 `false`，非空返回值为 `true`；用于已声明的对象存在性条件，不判断其他模型状态 |
| `reference` | 名称、实际 Java 类和会话引用；缺失的可选关联保留 `null` |
| `collection` | 基础值或对象引用的稳定列表；输出顺序不是操作执行顺序 |
| `quantity` | 标量数量的 `definition`、`unit`、`si_unit`、`raw_value`、`si_value`；两种数值分别使用对应单位 |
| `vector` | `definition`、`unit`、`components`；保持 STAR 数量对象的分量约定，不变换坐标系 |
| `tensor_profile` | 当前受支持三维张量的元数据、方向引用和独立分量；见下文 |
| `tensor_basis` | 同一张量的元数据和方向引用，不读取标量分量或 quantity |
| `tensor_method_state` | 当前三维张量方法的活动设置，保留矩阵、各向同性、主方向或轴对称方法的实际分量组织 |
| `enum` | `selected` 和当前 API 返回的 `allowed` 集合，不以枚举类全部常量替代当前允许值 |
| `query` | 静态模式为 `mode: static` 和 `objects`；动态模式为 `mode: query`、`predicate` 和 `modifiers` |

动态查询保留规则本身，不求值成当时匹配的对象列表。当前编码 `NamePredicate`、`TypePredicate`、`CompoundPredicate` 和 `TagPredicate`，分别返回 `type: name`、`java_type`、`compound` 或 `tag`。复合规则保留有序 `predicates`，标签规则的 `value` 是名称、实际 Java 类和会话引用。读取从深度 `0` 开始，最多允许深度 `16`、总计 `256` 个谓词节点；未知谓词或超限逐属性报错，不执行 `asJournal()` 生成的代码。此入口不求报告值、不生成网格、不运行求解或工作流。静态/动态选择写入以及标签旧引用与新定位对象的区别见[对象引用与选择](catalog-modifier.md#对象引用与选择)。

### 张量读取格式

`tensor_profile` 从指定父区域的 `getValues().getObjects()` 枚举并筛选 `TensorProfile`，按显示名称唯一定位。`profile_method` 返回当前方法的完整 Java 类名，可用于诊断不支持的方法。选择 `properties: ["name", "profile_method"]` 不要求读取分量；完整 `tensor` 读取失败仍保留其他属性的独立结果。

`tensor` 包含 `java_class`、`method`、`dimensions`、`is_3d`、`shape`、`storage`、`coordinate_system`、`local_orientation` 和 `components`。`dimensions` 保留 STAR 量纲文本，`shape` 当前固定为 `[3,3]`；两种方向字段使用名称、实际 Java 类与会话引用表示，没有对应关联时为 `null`。它们表示原张量的坐标约定，不代表已转换到全局坐标系。

`CompositeTensorProfileMethod` 按 `storage: full` 输出九项，顺序为 `XX, XY, XZ, YX, YY, YZ, ZX, ZY, ZZ`；`AnisotropicTensorProfileMethod` 读取 `local_orientation`，带 CoordinateSystem 的子类读取 `coordinate_system`。`CompositeSymmetricTensorProfileMethodWithCoordinateSystem` 按 `storage: symmetric_lower` 输出 `XX, YX, YY, ZX, ZY, ZZ` 六项。每项含大写 `name`、从 `0` 开始的 `row`/`column`、当前分量 `method`，以及完整标量 `quantity`；对称方法不补齐镜像项。

`basis` 与上述元数据和方向字段相同，但不含 `components`，也不访问各分量的 quantity。`tensor` 要求所有独立分量的当前方法为 `ConstantScalarProfileMethod`；不支持的方法或二维数据返回属性错误，不猜测缺失分量。读取始终使用无参 `getMethod()`，禁止通过带 Class 参数的重载暗中改变当前方法。独立分量属性及其 `_value` 属性均返回标量数量；写入边界与对称别名见[张量分量修改](catalog-modifier.md#张量-profile-分量)。对称六分量分支已实现，但尚未通过真实算例验收。

### 张量方法状态

`method_state` 与 `tensor` 使用相同的顶层字段，但补充各向同性、正交各向异性及横观各向同性方法的活动设置，供[方法切换](catalog-modifier.md#张量-profile-方法切换)核对完整旧状态。应通过 `properties: ["name", "method_state"]` 按需读取；省略 `properties` 会同时读取仍仅适用于复合矩阵方法的 `tensor`、`basis` 和分量属性，这些属性在其他方法下会分别报错。

| 当前方法 | `storage` | `components` |
|---|---|---|
| `CompositeTensorProfileMethod` 及已支持子类 | `full` | 保持原九分量格式及 `row`、`column` |
| `CompositeSymmetricTensorProfileMethodWithCoordinateSystem` | `symmetric_lower` | 保持原六分量格式及 `row`、`column` |
| `IsotropicTensorProfileMethod` | `isotropic` | 一项 `ISOTROPIC` |
| `OrthotropicTensorProfileMethod` | `principal` | 三项 `X`、`Y`、`Z` |
| `TransverseIsotropicTensorProfileMethod` | `axisymmetric` | 两项 `AXIAL`、`CROSS_STREAM` |

后三类的每项包含 `name`、当前标量分量 `method` 和完整 `quantity`，没有 `row`、`column`，不虚构九分量矩阵。`shape: [3,3]` 描述三维二阶张量，不表示独立配置项一定有九项。所有分量仍要求当前方法为 `ConstantScalarProfileMethod`，保留数量的定义、单位及数值；未知方法、二维或不支持的分量方法明确报错。

正交和横观各向同性方法保留实际 `local_orientation` 引用，各向同性方法的方向字段为 `null`；矩阵方法沿用上述方向契约。方向对象只保留关联身份，不展开其内部轴设置，不转换坐标系。新增方法分支匹配已核对的精确 Java 类，不推断未知子类的额外设置。

## 人工执行映射

[`catalogs/2602/execution.json`](../catalogs/2602/execution.json) 是维护者审阅的调用映射，由 [`core/execution.py`](../core/execution.py) 与候选目录共同校验；它与仅供离线核对的 `overrides.json` 修改语义分开维护。请求只能选择目标、属性或操作及其参数，不能覆盖映射、方法的 `effect`、Java 类或参数来源。

映射格式版本当前为 `5`，加载器兼容仅含读取管线的 schema 1 和原有写入 schema 2/3/4；顶层包含 `target`、`members`、`types`、`properties`、`operations`。旧格式没有结构操作，加载时使用空操作集合。每个 member 锁定候选声明的签名和指纹，并声明反射参数类型及 `effect: read` 或 `effect: write`。定位和读取管线只允许 `read`；写入管线仅最后一步允许 `write`，读取计划会移除写入管线。当前只接收已核对的 public 实例方法，不开放字段、构造器、静态调用或通过 `setAccessible()` 访问非 public 方法。参数类型必须能由候选材料证明，裸泛型变量 `T` 不能冒充可加载类；枚举 setter `EnumeratedOption.setSelected(T)` 仅在候选类声明和官方类型链接证明其首个上界为 `Enum` 时，使用已核对的泛型擦除规则。其他未解析泛型仍拒绝猜测；嵌套类按已核对类型页转换为 JVM 名称。

类型的 `locate` 和属性的 `read` 都是调用管线：`root` 可为 `simulation`、当前 `object` 或 `parent`，后续每一步以上一步返回值作为接收对象。参数来源只能是已核对的类字面量、JSON 标量 `literal` 或当前 `object`/`parent` 上下文，数量和类型必须与指定方法相符。只读管线允许 `steps: []`，直接将所选 root 传给适配器；张量 `tensor`/`basis`/`method_state` 使用此形式读取当前对象。写入管线仍要求非空并以受控 setter 结束。对象定位管线最终必须返回集合，父类型关系须明确且不能成环。

schema 3 新增通用 `primitive`、`enum`、`vector_expression` 和 `vector_value` 写适配器，并将场函数定义命名为 `field_definition`；schema 2 的旧 `primitive` 加载时规范化为 `field_definition`。`write.guards` 使用同样受 `effect: read` 限制的管线，在修改准备和 setter 前检查；读计划移除写入执行管线；`describe` 额外保留目标条件的只读管线，以返回实际检查结果，新关联条件仍只提供摘要。schema 4 新增 `reference` 与 `object_selection`：`value_types` 限定允许的关联类型，引用写入的 `value_guards` 在新关联上检查；对象选择以 `pipelines.static` 和 `pipelines.query` 分别声明最终 setter，每次请求只选一条。属性请求版本仍为读取 schema 1、修改 schema 2，详细值格式与条件行为见[目录修改](catalog-modifier.md#写入条件)。

schema 5 按类型新增 `operations`。首个 `profile_method` 操作声明方法 ID、只读 `available` 管线、`guards`、独立 `read_properties`、`state_property`、`preserved_properties` 和 `impacts`，以及最终 `write` 管线。`available` 从目标枚举现有方法；setter 的唯一 `method` 参数必须来自其中选定的实际 `ProfileMethod` 对象。属性 writer 不能使用这个操作专用参数。描述计划移除操作 setter，普通读取和兼容修改计划移除操作集合；结构修改计划则只保留所选操作与声明的读取集合。结构请求独立使用 schema 3。

运行时先用 `getCurrentVersion()` 和 `getReleaseNumber()` 读取当前 server 版本，与目录精确匹配，不使用文件保存版本，也不截断版本后缀。离线 `check --install` 只核对安装材料，不能代替这项会话检查。

Javadoc 的 `StarBeanProperty.link` 表示属性变化通知联动，不能作为 setter 或访问路径；`readOnly` 元数据也不能替代实际条件检查。现有写入流程核对预期旧状态、类型、单位、允许枚举值、向量分量及标签并回读；重力模型存在性、报告新关联的标量场函数类型以及张量三维形状和分量方法已配置为声明式条件，其他模型条件与适配器仍待补齐，新增路径的实际验证状态见[修改验证范围](catalog-modifier.md#验证范围与迁移边界)。写入参数、单次 setter 尝试及失败契约见[目录修改](catalog-modifier.md)。

## 验证范围与剩余工作

本机 Linux、2602 Build 21.02.007 已通过文件标量读取并确认原输入 SHA256 不变。后台工作副本中，当时 7 种类型共 33 个已配属性均返回 `status: ok`，`describe` 也已运行。向量来自工作副本专用对象，分量为 `[1.25, -2.5, 3.75]`；动态查询分别完整回读 `NamePredicate` 的 `Matches Background` 和 `TypePredicate` 的 `Is Region` 规则，没有求值成匹配对象列表。

跨会话旧引用、同名向量删除重建后的旧 key，以及错误 Build `21.02.999` 均明确拒绝，随后同会话读取成功且状态保持 `ready`。未映射属性在活动请求前拒绝，会话记录未变。人为设置错误读取适配器时，仅该属性返回错误，其他选定属性成功，整体 `inspection_complete` 为 `false`；会话仍可继续使用和保存。

工作副本另存后独立加载，向量全部已配属性与会话读取一致，新的文件加载 token 与此前会话不同。原始 `Base.sim~` 的摘要保持不变，验证服务已关闭。运行产物位于本地 `outputs/catalog-runtime-20261028/`，不进入源码版本管理。

`describe` 已在 2602 工作副本验证张量目标条件全部满足、缺失重力模型不满足、受控条件适配错误的逐项隔离，以及无条件属性与未实现写入的区分；错误后会话仍为 `ready`，张量读取值和原输入 SHA256 未变。文件模式的标量描述及原输入保护也已核对。产物位于本地 `outputs/catalog-conditions-20261029/`。

张量 Profile 已在单相多孔区域完成三维各向异性九分量读取、代表性分量写入与方法条件拒绝，并核对会话保存、文件修改和独立重载一致；四种方法的状态读取、操作描述与切换也已通过代表性检查，具体转换及未测分支见[张量修改验证](catalog-modifier.md#验证范围与迁移边界)。新增 `physics_continuum` 属性、布尔/枚举/向量写入及模型条件已完成代表性写入、拒绝和保存重载验收，范围见[修改验证](catalog-modifier.md#验证范围与迁移边界)；报告对象引用、静态选择及复合/标签查询已通过代表性写入、拒绝和保存重载检查；未知谓词、其他 STAR 版本及完整对象覆盖也不能据此认定通过。新增 `quantity_value` 与首批写入的验收见[目录修改验证](catalog-modifier.md#验证范围与迁移边界)。`global_parameter` 和 `field_function` 是兼容旧标签目标范围的通用定位类型，不据此承诺参数或场函数的所有其他属性可写。兼容 `inspect` 已通过独立布局生成原 schema 1 快照，其验收单独记录在 [Inspector](inspector.md#验证范围)；schema 1 `modify` 和 `set-scalar` 也通过兼容层复用目录修改器。分项覆盖报告见[离线目录工具](catalog.md#分项覆盖报告)；已有操作描述覆盖张量方法切换，其他结构操作、类型与模型条件仍待补齐，不能据此宣布[当前里程碑](../TODO.md)全部完成。
