# 运行时对象树与属性发现

[返回项目入口](../README.cn.md) · [技术文档](index.md) · [当前架构](architecture.md) · [MCP 与共享 JSON CLI](mcp.md) · [行为规格](../archive/spec-2026-10-30-12-24.md)

发现入口从当前连接的算例枚举实际对象和 Bean 属性，再用通用规则、官方 Javadoc 声明及成员指纹生成读取计划。Agent 无需先知道人工目录的 `type_id`；新增同类属性也不必逐项添加手工定位映射。它不复刻 GUI，不执行网格或求解。

当前发现规则仅登记 STAR-CCM+ **2602 Build `21.02.007`**，要求 Linux 管理会话以及该安装的本机 Javadoc。2510 的既有目录入口仍可使用，新增发现入口明确拒绝该版本。验证使用真实隔离算例和明确标记的契约模拟；具体范围见下文，不代表全部算例分支。

`open_session.star` 应指向安装目录内的实际可执行文件。发现机制解析符号链接后，沿该路径的父目录查找 `doc/client/html/type-search-index.js`，不解析外部包装脚本；包装脚本即使能启动 STAR，也可能无法定位 Javadoc。此时描述保留属性元数据并返回 `write_plan_error`／不支持原因，读取可能因计划编译失败而不完整。改用实际安装路径重新连接，或补齐匹配版本文档；不能把这种环境错误当成属性不存在。

## 入口与参数

MCP 工具使用 `starbridge.` 前缀，JSON CLI 使用下表原名。所有调用的 `session_id` 都是 `open_session` 返回的会话标识，`timeout` 单位为秒，默认 `180`。

| 方法 | 参数与默认值 | 作用 |
|---|---|---|
| `browse_tree` | `object_id=null`、`cursor=null`、`offset=0`、`limit=100`、`scope="simulation"`、`max_nodes=2000` | 从根或指定节点展开一层；不读取属性值 |
| `describe_object` | `object_id=null`、`scope="simulation"`、`property_ids=null`、`cursor=null`、`limit=100` | 刷新属性描述符并检查规则支持，省略节点表示根 |
| `read_properties` | 必填 `object_id`、非空且不重复的 `property_ids` | 核对当前身份和所选描述符，只读取显式选择的属性；可复用已有描述计划 |
| `search_settings` | 必填 `query`；`expand=false`、`max_nodes=100`、`max_depth=4`、`scope="simulation"`、`limit=100`、`cursor=null` | 搜索已有索引；显式扩展时按预算发现更多节点 |
| `relocate_object` | 必填 `locator` | 保存重载或新会话中按结构化路径重建引用 |
| `modify_property` | 必填 `object_id`、`property_id`、`expected`、`value`；`audit=false` | 按已接受规则赋值一次并回读目标及必要关联项；可选快照审查，保存单独执行 |

`limit` 范围为 1–500，`max_nodes` 为 1–10000；搜索 `max_depth` 为 1–32，根深度为 0。浏览 `max_nodes` 限制单层运行时观察规模，搜索 `max_nodes` 限制扩展访问的节点数；返回页大小由 `limit` 单独限制。每次 Java 发现请求的内部时间预算最多 30 秒；Python 还用剩余时间限制多页描述和搜索扩展。STAR 客户端启动、编译和进程清理可能占用额外时间，不能把预算解释为硬实时截止。

`scope="simulation"` 按已知类型排除材料数据库分支；`scope="all"` 包含该类资源。默认范围不宣称已能识别所有第三方库或客户端设置。

## 导航、描述、读取

先连接或打开工作会话，方式见[后台会话](bridge-session.md)或 [MCP 说明](mcp.md)。用以下 JSON 调用 `browse_tree`：

```json
{"session_id": "<returned session_id>", "limit": 100}
```

Core 返回 `{"status":"ok","result":...}`。读取 `result.objects`，按返回的名称和上下文选择目标，把它的 `object_id` 原样传入下一次 `browse_tree`。需要下一页时传入 `result.next_cursor`，保留相同 `scope`；游标已经绑定父节点，允许省略 `object_id`。列表指纹变化会使旧游标失效，此时重新展开，不拼接前后两个树状态的页面。

到达所需设置节点后，先调用 `describe_object`：

```json
{"session_id": "<returned session_id>", "object_id": "<returned object_id>"}
```

从 `result.properties[id]` 按属性名称、说明、类型和支持状态选择一项，再调用 `read_properties`：

```json
{
  "session_id": "<returned session_id>",
  "object_id": "<returned object_id>",
  "property_ids": ["<returned property_id>"]
}
```

读取值在 `result.properties[property_id]` 中；只有该项 `status="ok"` 时才消费 `value`。数量或选项包装器可能另有 `relation`，已支持的范围提供器另有 `range`。二者也有独立状态；没有范围提供器时返回 `not_supported`，不能将其解释为没有上下限。公开属性结果不再重复附带底层执行封套；请求诊断的保留方式见[会话说明](bridge-session.md#运行数据与项目产物)。

相同参数文件也用于 JSON CLI：

```bash
python3 starbridge.py browse_tree --arguments /absolute/browse.json
python3 starbridge.py describe_object --arguments /absolute/describe.json
python3 starbridge.py read_properties --arguments /absolute/read-node.json
```

`describe_object` 不读取全部当前属性值。首次描述以最多 500 项为一页汇集运行时描述符，在预算内形成一次观察，再按 `property_ids` 和 `limit` 返回所选页面。显式选择接受 1–500 个不重复的 ID，并按选择顺序返回；未知或过时 ID 拒绝。只为当前页准备写入能力说明，不调用 setter。

描述结果默认每页 100 项，返回 `offset`、所选集合的 `total_count`、完整观察集合的 `descriptor_total_count` 和 `next_cursor`。下一页保留同一 `object_id` 和 `scope`，传回游标；省略 `property_ids` 时沿用原选择。后续页使用同一次描述快照，过期需重新描述；读写时仍刷新运行时对象与描述符。有效期及缓存位置见[身份、重定位和缓存](#身份重定位和缓存)。分页不会把 `partial` 观察变为 `complete`，`descriptor_next_offset` 非空表示内部描述仍有未汇集部分。

## 搜索后确认上下文

先搜索已发现范围：

```json
{"session_id": "<returned session_id>", "query": "松弛"}
```

若索引范围不足，显式要求扩展：

```json
{
  "session_id": "<returned session_id>",
  "query": "松弛",
  "expand": true,
  "max_nodes": 80,
  "max_depth": 4,
  "timeout": 180,
  "limit": 20
}
```

搜索字段包括对象名称、路径、Java 类、属性名称、显示名及说明，并提供小规模中英文术语别名，例如“松弛”、`relaxation`、`URF`。这不是完整领域词典或语义搜索。每项命中包含 `matched_by`、节点上下文、可选属性、`observed_at` 和 `validity="cached_may_be_stale"`。

后续结果页使用返回的 `next_cursor`、同一 `query` 和 `scope`，保持 `expand=false`，避免重新扩展改变索引。索引或匹配集合变化会使游标失效。拿到命中后先描述节点确认上下文，再读取指定属性；搜索候选本身不证明对象仍存在或属性值仍有效。

`coverage` 报告索引节点数、此次访问节点数、未展开数量、错误、截断、不支持代理及预算。搜索会按对象身份去重重复路径的命中，但不会把搜索范围冒充完整算例；`whole_simulation_complete` 不会因为空命中变成 `true`。

## schema 与完整性

公开结果统一使用 `schema_version: 2`、`schema_id: starbridge.objects`，与目录对象共用描述和属性读写入口。内部发现提供器仍使用自己的数据格式，不作为第二套公开 API。

| 对象 | 关键字段及含义 |
|---|---|
| 节点 | `object_id` 是不透明会话引用；`name`、`java_class` 是观察信息；`breadcrumbs` 与带 `source` 的 `locator` 保留上下文，内部 key/path 不作为调用参数 |
| 节点状态 | `children_state`、`property_state` 区分未加载和不支持；未展开不表示没有子对象 |
| 关系 | `relations` 保留运行时已有归属或引用信息；树的展示父节点不一定等于对象的真实 `getParent()` |
| 属性 | `property_id` 绑定实际 getter、setter 和属性上下文；保留 `name`、`display_name`、`description`、`property_type`、隐藏标记及来源 |
| 能力 | `discovered`、`read_support`、`setter_present`、`write_support`、`write_enabled`、`target_conditions`、`value_conditions`、`evidence` 分别表达发现、支持和条件状态 |
| 浏览分页 | `state`、`total_count`、`observed_count`、`next_cursor`、`fingerprint`；观察集合截断时总量可能为 `null` |
| 读取 | 每属性 `status`、`value` 或错误；顶层 `inspection_complete` 仅描述此次显式请求 |

`read_support`、`write_support` 的 `supported/unsupported/unknown` 不等同于当前值已经读取或条件已经满足。描述符符合规则、但成员尚未编译核验时，读取支持保持 `unknown`。条件未检查使用 `not_checked`；存在 setter 也不代表允许写入。

隐藏、内部、弃用和未知复杂属性保留元数据及原因；禁止规则优先于通用值规则。单个属性的成员声明缺失会形成局部编译错误，其他可编译项仍可读取。Getter 运行时错误同样属于对应属性。只有服务外层 `status="ok"` 不足以证明全部读取成功。

## GUI 显示名称与位置

非 CSO 虚拟分组如果声明了 `@StarBean`，现在通过当前安装的 `ObjectNameFactory.getPresentationName(Class)` 取得官方本地化类标签，不再一律显示为 `Unsupported proxy`。`presentation` 给出读取状态、`source="star_bean_localization"`、客户端 `locale` 以及 `gui_path_status="not_observed"`；没有声明或标签读取失败时明确保留不可用／错误。该机制不逐个适配功能，不调用未知实例属性 getter，也不按 Java 类名拼造 GUI 名称。

代理的 `breadcrumbs` 包括该分组自身的标签，但只是本次 `getChildren()` 观察上下文，标为 `context_kind="runtime_children_not_gui_path"`。取得名称不等于取得业务身份：`object_id` 仍为 null，展开和属性读取仍是不支持。关联引用的 `ownership_not_gui_path` 同样只表示拥有者链。向用户呈现位置时应说明这些区别，不把它们称为已核实的完整 GUI 路径。

2602 的[公开浏览结果](<../../outputs/requirements-first/final-recovery-workflow/20-browse_tree.json>)已返回 `Fonts`、`Ensemble`、`Cartesian 2D Plots` 和 `Hardcopy`；同次任务的[官方类标签读取](<../../outputs/requirements-first/final-recovery-workflow/11-execute_macro.json>)还取得 `Source Surfaces` 与 `Target Surfaces`，后两者是类元数据，不是当前算例中已观察到的分组。最后补充的 Core 路径投影用这些实际观察[离线核对](<../../outputs/requirements-first/final-recovery-workflow/proxy-projection-final-source.json>)，去除代理上下文中的内部 key，不称作新的 STAR 实跑。更新后的 Java helper 已用2602、2510各自安装的 JDK／库编译；这不扩大运行时发现的版本登记范围。

需要 GUI 对应位置时，可通过 `execute_recipe` 选择 `objects.gui_locations`，一次绑定最多32个当前对象。方法复用已加载的 Simulation，读取官方标准树节点的祖先、可选的属性栏元数据和首层上下文菜单组件文本，不打开视图或显示菜单，也不执行动作。普通宏不会因此加载 GUI 表示辅助类。下面示例的当前对象是表面自定义网格控制，`GeometryObjects` 是其描述给出的属性名称。

```json
{
  "session_id": "<当前会话>",
  "request_id": "<本次稳定标识>",
  "recipe_id": "objects.gui_locations",
  "parameters": {
    "targets": [
      {"object": {"object_id": "<当前对象引用>"}, "property_name": "GeometryObjects"}
    ],
    "include_properties": true,
    "include_actions": true,
    "max_items": 128
  }
}
```

每个目标的 `object` 使用当前 `n_`、`o_` 或 `r_` 引用；内置方法与记忆方法一样，按 `object_reference` 契约在所有步骤前核对身份。需要虚拟分组时，在具有业务引用的父目标下给 `child_path`，例如 `[{"java_class":"star.common.XYPlotStyleDefaults"}]`；逐层按实际 GUI 直接子项的 Java 类及可选当前 `name` 唯一匹配，不按旧序号猜测。该定位不为代理创建可修改的业务引用。

读取 `result.execution.steps[].result.presentation` 时，区分以下结果：

- `source="official_gui_node_model"`、`tree_scope="standard_simulation_tree"` 表示本客户端的标准节点模型。`locale` 给出标签语言，`remote_gui_observed=false`：没有观察另一 GUI 的当前选择、自定义布局或窗口状态，也不是原子快照。
- 只有节点父链实际到达当前官方根节点，才返回 `gui_path_status="resolved"` 与 `path`；否则明确不可用，不回退成拥有者链。`target_index` 对应输入目标，`path[].bean_class` 描述实际 GUI 节点对象。
- 属性区段是节点属性栏的名称、标签、类型及 GUI 可读写元数据，不是当前值，也不替代 Bridge 的写入契约。可按描述中的属性 `name` 筛选，不使用 `property_id`；找不到时明确 `not_found`。方法不调用 `Node.Property.getValue()`，但原生节点、属性及动作构造可能内部读取所需状态。
- 菜单标签来自实际轻量弹出组件的文本，而不是把 `Action.NAME` 当作最终文案。菜单不显示、不执行；子菜单明确 `children_state="not_requested"`，不能称为空菜单或完整菜单，也不推断另一窗口中的启用状态。
- `read_status="partial"` 时逐目标、逐区段检查 `not_found`、`ambiguous`、`unavailable`、`error` 或预算耗尽。一个目标失败不抹掉其他已取得的位置；GUI 的 `AWTError` 在对应区段保留。`max_items` 默认64、最大256，是每目标各区段的检查预算，不是 STAR 内部节点构建的耗时或内存上限。

实际无界面客户端没有现成 GUI 根节点。此前的 [HeadlessException](<../../outputs/requirements-first/gui-location-workflow/02-execute_macro.json>) 已定位为 `RootProcessObject.getRootProcessNode()` 调用 `preLoad()`、继而构造窗口，并非节点模型本身必须有显示器。现在以公开构造器及文档中的 protected `setRootObject` 关联已有 Simulation，直接构造 `SimulationProcessNode`，不调用该预加载路径，也不改 JVM headless 状态或加载副本。

2602 的[最终实现实跑](<../../outputs/requirements-first/gui-location-current/15-execute_recipe.json>)在一次调用中取得区域、自定义表面网格控制、关联 PartSurface 和 `Cartesian 2D Plots` 分组的真实祖先、属性栏及首层菜单。其中 `GeometryObjects` 的 GUI 标签是 `Part Surfaces`；关联面在自建会话中显式改名后，同一个输入引用返回了当前名称和路径。另有[局部缺失](<../../outputs/requirements-first/gui-location-current/08-execute_recipe.json>)、[预算耗尽](<../../outputs/requirements-first/gui-location-current/09-execute_recipe.json>)、[凭据重放](<../../outputs/requirements-first/gui-location-current/10-execute_recipe.json>)与[旧会话引用拒绝](<../../outputs/requirements-first/gui-location-current/11-execute_recipe.json>)的实际结果。任务自建会话已[丢弃临时改名并停止](<../../outputs/requirements-first/gui-location-current/16-close_session.json>)，保存源文件的 SHA-256 未变。辅助类及嵌入方法已分别通过2602、2510安装的静态编译；2510 没有 GUI 模型实跑证据，不扩大结构化引用的版本覆盖。

## 身份、重定位和缓存

`object_id` 和分页游标是会话内短 ID，服务从会话引用表查找已观察的路径、关系身份或分页状态，并核对种类与会话世代，没有 HMAC 或专用密钥。树路径引用逐层检查 key、名称、类型及实际父身份；属性关系引用使用固定公开 registry 读取接口按已观察 key 取得对象，再检查当前 Simulation、真实类型与拥有者链，不按名称猜测、不创建业务对象。关系引用不因单纯重命名自动失效，但删除、换会话或无法核对归属时拒绝；它的拥有者上下文不等于 GUI 树路径，因此不伪造跨加载 `locator`。旧签名引用需重新浏览取得短 ID。调用方原样传递引用，不解析或构造其内容。

跨加载使用此前返回的 `locator`，调用 `relocate_object`：

```json
{
  "session_id": "<newly returned session_id>",
  "locator": {"source": "runtime", "path": [
    {"name": "<previous root name>", "java_class": "<returned root class>"},
    {"name": "<child name>", "java_class": "<returned child class>"}
  ]}
}
```

实际调用应复制完整返回路径，不能省略中间节点。根绑定当前 `Simulation` 并核对类，允许另存后根名称改变；其余各层必须按名称和类唯一匹配。成功返回新会话引用，不宣称是旧 Java 实例。属性描述和 ID 仍应重新获取。

会话 `discovery-cache/` 保存元数据、搜索索引和描述分页快照，不缓存当前属性值。描述后续页沿用同一次观察，有效期为 300 秒，只准备当前页的写入能力；过期需要重新描述。节点与属性分别记录观察时间，浏览节点不会刷新旧属性观察时间。读取与修改仍刷新运行时对象和描述符。

安装 Javadoc 元数据保存在 `~/.starbridge/cache/metadata/`，按安装路径、精确版本、规则版本和所需类集合复用，不在每次读取时重新计算文档内容摘要。内部执行计划直接在内存中编译、裁剪和传递，进程内缓存稳定的类型适配；不再把计划写成 JSON 后读回。原安装路径内修订 Javadoc 时，需要清理对应元数据缓存并重启服务。

普通读取不准备写入计划。已有所选属性描述且至少一项可读时，复用服务端元数据编译计划；同一个 STAR 请求先逐层核对对象身份和全部所选 Bean 声明，再调用 getter，返回 `descriptor_source="reused_with_runtime_validation"`。缓存不足时仍先单独描述。任何绑定声明变化都会拒绝本次计划，不保证与 GUI 并发编辑的事务隔离。部分属性编译失败仍被隔离，其他可执行计划合并读取；`properties` 是唯一属性值结果，不重复附带底层封套。

文档说明属性与操作含义、版本限制和副作用；Skill 组织任务及检查顺序，通过 Bridge 获取实例事实。训练知识只用于提出导航或搜索方向，不能替代真实引用、当前值或已验证的调用规则。缓存保存已有观察及其依据，帮助重复查询，但它不是独立事实来源；使用搜索候选后仍要重新描述或读取。

## 已实现规则与边界

规则集中在 [discovery_policy.py](<../../src/starbridge/core/discovery_policy.py>)，编译器在 [discovery_rules.py](<../../src/starbridge/core/discovery_rules.py>)。除基础值、数量 input 和枚举 input，还按声明类型的继承／接口图识别 CSO 引用、轻量 key 引用、选择输入、查询和序列，不依赖属性名称。官方声明证明调用签名，规则仍限制公开无参 getter，禁止／内部成员优先拒绝；不扫描后调用全部 `get*`。

静态选择返回 `mode=static`、按 API 顺序保留的 `objects`，空选择明确为空数组。动态选择返回查询配置与 `resolved_selection.status=not_requested`，不假装已枚举命中对象。未知元素、过长序列或 null 包装器报错，不冒充空集合。轻量引用只返回实际可得的 key、类和名称，并区分 `metadata_state=key_only`。属性值中的当前会话引用会追加可继续描述、读取及用于已支持赋值契约的 `object_id`，不为发 ID 提前实例化整个选择；真正使用时再核对身份。`reference_registration` 明确报告登记失败，不抹掉已成功读写的 STAR 值。传回完整 `expected` 时，Core 验证并剥离自己追加的 ID，仍按原始 STAR 状态进行比较。实际关联读取、静态替换和动态配置观察见[任务证据](<generic-execution.md#当前实际证据与未完成项>)。

普通有界标量 input 使用已核验的范围适配器。动态范围仅登记 `star.resurfacer.PartsResurfacerAnisotropicSizing.ratioRange()`；其他 `rangeMethod` 注解保留为元数据，不能据方法名自行执行。单位和范围仅按提供器实际结果返回，不推断缺失单位。

非 CSO 代理没有已核验的通用提供器时，返回 `kind="proxy"`、不支持原因和 `object_id=null`，不会把父节点引用冒充代理身份。GUI 分组、插件节点、未知复杂值和未登记版本可能因此仅有部分覆盖。

## 受控写入

`modify_property` 当前开放已接受的普通赋值规则。禁止规则、资源范围限制和特殊语义优先；特殊规则缺少上下文或存在歧义时不退回通用规则。目录对象也使用 `modify_property`，内部沿用已有[目录适配](catalog-modifier.md)。

当前规则族及限制：

- 特殊规则按完整读取声明匹配原目录 writer，保留其 guards、范围和保持项；只迁移已接受的普通赋值，不移植依赖旧父级定位的条件。全局标量／向量参数的 quantity input 可映射到已有数量 writer，写前确认读取数量与 setter 接收对象的 key 相同；名称和维度等保持项继续读取验证。
- 通用标量仅接受已支持的 `BoundedScalarInput` 常量，使用实际 input 范围及单位检查；通用向量仅接受 `VectorPhysicalQuantityInput` 常量，完整描述中存在未处理的坐标、方向或模型／方法上下文时拒绝。向量保留原始分量，不转换或归一化。
- 通用静态选择接受已核验的 `ObjectSelectorInput`、`OrderedObjectSelectorInput`、`DynamicQuerySelectorInput` 与普通 `SelectorDescriptor`。新值为 `{"mode":"static","objects":[{"object_id":"<当前ID>"}]}`，表示完整替换，也可显式清除原查询。保持原 descriptor 约束，用其完整可选域验证候选；不先塞入候选再“自证合法”。预算为10,000项，超限拒绝。setter 前重验最新 descriptor、身份与可选域；不保证不透明隐藏状态的原子 CAS 或 GUI 锁定。Ordered 按身份列表回读，其余按无重复身份集合回读。未知 descriptor 子类、新查询值仍不开放此规则。
- 隐藏、只读、未知注解、未知编辑器、跨属性通知关联、库资源以及规则不完整的属性不开放自动写入。创建删除、模型启停、方法切换及复杂查询不作为通用属性赋值；明确任务可使用[通用宏](<generic-execution.md>)调用当前安装的公开 API。

先描述并读取目标，再把返回的完整 `value` 原样作为 `expected`。以下示例假设本次实际读取恰为 `0 m`，不能将示例值替代真实读取：

```json
{
  "session_id": "<returned session_id>",
  "object_id": "<returned object_id>",
  "property_id": "<returned property_id>",
  "expected": {"definition": "0.0", "unit": "m", "si_unit": "m", "raw_value": 0.0, "si_value": 0.0},
  "value": {"value": 0.001, "unit": "m"}
}
```

向量新值格式为 `{"components":[0,0,0.125],"unit":"m"}`；其他已接受类型按其 writer 的契约提供新值。通过 JSON CLI 执行 `python3 starbridge.py modify_property --arguments /absolute/write-node.json`，或使用相同参数调用 `starbridge.modify_property`。`write_enabled=true` 只证明发布范围和规则支持；`target_conditions`、`value_conditions` 在描述时仍为 `not_checked`。

修改刷新节点描述，只为目标属性和已接受规则要求的关联项生成写计划，在会话锁内核对版本、引用、`expected`、单位、范围及声明条件，临近 setter 再核对必要状态。通用常量赋值不再读取并保持同节点所有其他属性，也不要求旧 Inspector 全范围保持不变。

成功结果返回 `before[id]`、`properties[id]`、`change` 和 `setter_attempts: 1`。显式传入 `audit: true` 时附带完整 Inspector 前后快照、`snapshot_diff` 和 `property_diff`，供审查；审查结果不作为全范围不变的强制赋值条件。也可按需调用 `inspect_session` 取得快照。旧 `snapshot_scope` 不再作为普通写入结果返回。

写前明确拒绝返回 `rejected`，不会执行 setter。请求仍在执行时返回 `busy`；状态查询可在执行中读取记录。只读失败在客户端结束后记录为本次错误，不冻结会话。写入结果未确认时保留 `uncertain_request`，允许状态查询和只读核对，阻止新的修改与保存；成功读取不会自动清除未确认写入，也不自动重试、回滚或保存。重连同一未确认外部会话仍沿用其限制。

成功修改仍须显式调用 `save_session`，省略 output 写回当前文件，指定新路径则另存为。重载后重新定位、描述和读取；旧 `object_id` 不能跨加载使用。锁和回读不提供跨客户端原子事务或 CFD 合理性保证。

## 验证范围

既有验证结果与复现材料见[验证记录](../evidence/runtime-discovery.md)。当前会话与执行改造的实测缺口统一见[会话验证边界](bridge-session.md#验证边界)。
