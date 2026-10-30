# 运行时对象树与属性发现

[返回项目入口](README.cn.md) · [MCP 与共享 JSON CLI](mcp.md) · [行为规格](archive/spec-2026-10-30-12-24.md)

发现入口从当前后台算例枚举实际对象和 Bean 属性，再用通用规则、官方 Javadoc 声明及成员指纹生成读取计划。Agent 无需先知道人工目录的 `type_id`；新增同类属性也不必逐项添加手工定位映射。它不复刻 GUI，不执行网格或求解。

当前发现规则仅登记 STAR-CCM+ **2602 Build `21.02.007`**，要求 Linux 管理会话以及该安装的本机 Javadoc。2510 的既有目录入口仍可使用，新增发现入口明确拒绝该版本。验证使用真实隔离算例和明确标记的契约模拟；具体范围见下文，不代表全部算例分支。

## 入口与参数

MCP 工具使用 `starbridge.` 前缀，JSON CLI 使用下表原名。所有调用的 `session_dir` 都是已有后台会话的绝对路径，`timeout` 单位为秒，默认 `180`。

| 方法 | 参数与默认值 | 作用 |
|---|---|---|
| `browse_tree` | `node_id=null`、`cursor=null`、`offset=0`、`limit=100`、`scope="simulation"`、`max_nodes=2000` | 从根或指定节点展开一层；不读取属性值 |
| `describe_node` | `node_id=null`、`scope="simulation"`、`property_ids=null`、`cursor=null`、`limit=100` | 刷新属性描述符并检查规则支持，省略节点表示根 |
| `read_node_properties` | 必填 `node_id`、非空且不重复的 `property_ids` | 重新定位和描述后，只读取显式选择的属性 |
| `search_settings` | 必填 `query`；`expand=false`、`max_nodes=100`、`max_depth=4`、`scope="simulation"`、`limit=100`、`cursor=null` | 搜索已有索引；显式扩展时按预算发现更多节点 |
| `relocate_node` | 必填 `locator` | 保存重载或新会话中按结构化路径重建引用 |
| `modify_node_property` | 必填 `node_id`、`property_id`、`expected`、`value` | 按已接受规则执行一次赋值，回读并验证快照影响范围；保存单独执行 |

`limit` 范围为 1–500，`max_nodes` 为 1–10000；搜索 `max_depth` 为 1–32，根深度为 0。浏览 `max_nodes` 限制单层运行时观察规模，搜索 `max_nodes` 限制扩展访问的节点数；返回页大小由 `limit` 单独限制。每次 Java 发现请求的内部时间预算最多 30 秒；Python 还用剩余时间限制多页描述和搜索扩展。STAR 客户端启动、编译和进程清理可能占用额外时间，不能把预算解释为硬实时截止。

`scope="simulation"` 按已知类型排除材料数据库分支；`scope="all"` 包含该类资源。默认范围不宣称已能识别所有第三方库或客户端设置。

## 导航、描述、读取

先打开独立工作会话，方式见[后台会话](bridge-session.md)或 [MCP 说明](mcp.md)。用以下 JSON 调用 `browse_tree`：

```json
{"session_dir": "/absolute/session", "limit": 100}
```

Core 返回 `{"status":"ok","result":...}`。读取 `result.children`，按返回的名称和上下文选择目标，把它的 `node_id` 原样传入下一次 `browse_tree`。需要下一页时传入 `result.next_cursor`，保留相同 `scope`；游标已经绑定父节点，允许省略 `node_id`。列表指纹变化会使旧游标失效，此时重新展开，不拼接前后两个树状态的页面。

到达所需设置节点后，先调用 `describe_node`：

```json
{"session_dir": "/absolute/session", "node_id": "<returned node_id>"}
```

按属性名称、说明、类型和支持状态选择一项，再调用 `read_node_properties`：

```json
{
  "session_dir": "/absolute/session",
  "node_id": "<returned node_id>",
  "property_ids": ["<returned property_id>"]
}
```

读取值在 `result.properties[property_id]` 中；只有该项 `status="ok"` 时才消费 `value`。数量或选项包装器可能另有 `relation`，已支持的范围提供器另有 `range`。二者也有独立状态；没有范围提供器时返回 `not_supported`，不能将其解释为没有上下限。原始执行结果保留在 `result.result`，便于定位请求记录。

相同参数文件也用于 JSON CLI：

```bash
python3 starbridge.py browse_tree --arguments /absolute/browse.json
python3 starbridge.py describe_node --arguments /absolute/describe.json
python3 starbridge.py read_node_properties --arguments /absolute/read-node.json
```

`describe_node` 不读取全部当前属性值。内部先以最多 500 项为一页汇集当前描述符并检查规则，再对返回结果应用 `property_ids` 选择和分页；不裁剪内部写入保持范围。省略选择表示全部已观察属性，显式选择接受 1–500 个不重复的 ID，并按选择顺序返回；未知或过时 ID 拒绝。

描述结果默认每页 100 项，可用 `limit` 调整，返回 `offset`、所选集合的 `total_count`、完整观察集合的 `descriptor_total_count` 和 `next_cursor`。下一页保留同一 `node_id`，传回游标；省略 `property_ids` 时沿用游标中的选择。游标绑定节点、完整描述指纹和选择集合；描述或能力状态变化时拒绝旧游标，需重新描述。分页只裁剪响应，不把原本 `partial` 的观察改成 `complete`；`descriptor_next_offset` 非空表示内部描述仍有未汇集部分。通用赋值能力说明可能编译相应规则，但不调用 setter。

## 搜索后确认上下文

先搜索已发现范围：

```json
{"session_dir": "/absolute/session", "query": "松弛"}
```

若索引范围不足，显式要求扩展：

```json
{
  "session_dir": "/absolute/session",
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

发现结果使用独立 `schema_version: 1`。它与旧 Inspector schema、目录请求 schema 分开，不把新节点引用当作旧目录 `target`。

| 对象 | 关键字段及含义 |
|---|---|
| 节点 | `node_id` 是不透明会话引用；`key`、`name`、`java_class` 是观察信息；`path`、`breadcrumbs`、`locator` 保留上下文 |
| 节点状态 | `children_state`、`property_state` 区分未加载和不支持；未展开不表示没有子对象 |
| 关系 | `relations` 保留运行时已有归属或引用信息；树的展示父节点不一定等于对象的真实 `getParent()` |
| 属性 | `property_id` 绑定实际 getter、setter 和属性上下文；保留 `name`、`display_name`、`description`、`property_type`、隐藏标记及来源 |
| 能力 | `discovered`、`read_support`、`setter_present`、`write_support`、`write_enabled`、`target_conditions`、`value_conditions`、`evidence` 分别表达发现、支持和条件状态 |
| 浏览分页 | `state`、`total_count`、`observed_count`、`next_cursor`、`fingerprint`；观察集合截断时总量可能为 `null` |
| 读取 | 每属性 `status`、`value` 或错误；顶层 `inspection_complete` 仅描述此次显式请求 |

`read_support`、`write_support` 的 `supported/unsupported/unknown` 不等同于当前值已经读取或条件已经满足。描述符符合规则、但成员尚未编译核验时，读取支持保持 `unknown`。条件未检查使用 `not_checked`；存在 setter 也不代表允许写入。

隐藏、内部、弃用和未知复杂属性保留元数据及原因；禁止规则优先于通用值规则。单个属性的成员声明缺失会形成局部编译错误，其他可编译项仍可读取。Getter 运行时错误同样属于对应属性。只有服务外层 `status="ok"` 不足以证明全部读取成功。

## 身份、重定位和缓存

`node_id` 和分页游标由会话目录中的独立私钥签名；公开 `session_token` 不是签名密钥。引用包含会话世代和完整观察路径，运行时逐层核对 key、名称、类型及实际父身份。调用方应原样保存和传递引用，不解析或构造其内容。名称相同不证明是同一实例；重命名、删除重建、关系变化或换会话都可能使旧引用失效。

跨加载使用此前返回的 `locator`，调用 `relocate_node`：

```json
{
  "session_dir": "/absolute/reloaded-session",
  "locator": [
    {"name": "<previous root name>", "java_class": "<returned root class>"},
    {"name": "<child name>", "java_class": "<returned child class>"}
  ]
}
```

实际调用应复制完整返回路径，不能省略中间节点。根绑定当前 `Simulation` 并核对类，允许另存后根名称改变；其余各层必须按名称和类唯一匹配。成功返回新会话引用，不宣称是旧 Java 实例。属性描述和 ID 仍应重新获取。

会话 `discovery-cache/` 保存元数据、索引和生成计划，不缓存当前读取值。索引按会话、版本和规则隔离；Javadoc 缓存核对安装路径、精确 Build 和源文件内容指纹。节点与属性分别记录观察时间，浏览节点不会把旧属性元数据伪装成新观察。读取前始终重新核对运行时对象和描述符；缓存不能代替此检查。

文档说明属性与操作含义、版本限制和副作用；Skill 组织任务及检查顺序，通过 Bridge 获取实例事实。训练知识只用于提出导航或搜索方向，不能替代真实引用、当前值或已验证的调用规则。缓存保存已有观察及其依据，帮助重复查询，但它不是独立事实来源；使用搜索候选后仍要重新描述或读取。

## 已实现规则与边界

规则集中在 `core/discovery_policy.py`，编译器在 `core/discovery_rules.py`。当前提供 CSO 子对象与 Bean 描述符机制，以及基础值、标量 input、向量 input、枚举 input 的固定解包规则。官方声明证明调用签名，实际规则和限定类型决定是否允许执行；不扫描后调用全部 `get*` 方法，也不因单独存在 Bean 注解就开放任意类型。

普通有界标量 input 使用已核验的范围适配器。动态范围仅登记 `star.resurfacer.PartsResurfacerAnisotropicSizing.ratioRange()`；其他 `rangeMethod` 注解保留为元数据，不能据方法名自行执行。单位和范围仅按提供器实际结果返回，不推断缺失单位。

非 CSO 代理没有已核验的通用提供器时，返回 `kind="proxy"`、不支持原因和 `node_id=null`，不会把父节点引用冒充代理身份。GUI 分组、插件节点、未知复杂值和未登记版本可能因此仅有部分覆盖。

## 受控写入

`modify_node_property` 当前开放已接受的普通赋值规则。禁止规则、资源范围限制和特殊语义优先；特殊规则缺少上下文或存在歧义时不退回通用规则。既有目录 `modify` 继续按其[原契约](catalog-modifier.md)使用。

当前规则族及限制：

- 特殊规则按完整读取声明匹配原目录 writer，保留其 guards、范围和保持项；只迁移已接受的普通赋值，不移植依赖旧父级定位的条件。全局标量／向量参数的 quantity input 可映射到已有数量 writer，写前确认读取数量与 setter 接收对象的 key 相同；名称和维度等保持项继续读取验证。
- 通用标量仅接受已支持的 `BoundedScalarInput` 常量，使用实际 input 范围及单位检查；通用向量仅接受 `VectorPhysicalQuantityInput` 常量，完整描述中存在未处理的坐标、方向或模型／方法上下文时拒绝。向量保留原始分量，不转换或归一化。
- 隐藏、只读、未知注解、未知编辑器、跨属性通知关联、库资源以及规则不完整的属性不开放自动写入。创建删除、模型启停、方法切换及复杂查询不作为通用属性赋值。

先描述并读取目标，再把返回的完整 `value` 原样作为 `expected`。以下示例假设本次实际读取恰为 `0 m`，不能将示例值替代真实读取：

```json
{
  "session_dir": "/absolute/session",
  "node_id": "<returned node_id>",
  "property_id": "<returned property_id>",
  "expected": {"definition": "0.0", "unit": "m", "si_unit": "m", "raw_value": 0.0, "si_value": 0.0},
  "value": {"value": 0.001, "unit": "m"}
}
```

向量新值格式为 `{"components":[0,0,0.125],"unit":"m"}`；其他已接受类型按其 writer 的契约提供新值。通过 JSON CLI 执行 `python3 starbridge.py modify_node_property --arguments /absolute/write-node.json`，或使用相同参数调用 `starbridge.modify_node_property`。`write_enabled=true` 只证明发布范围和规则支持；`target_conditions`、`value_conditions` 在描述时仍为 `not_checked`。

修改刷新完整节点描述并编译全部已支持读取项，在会话锁内核对版本、引用、`expected`、单位、范围及声明条件，临近 setter 再核对必要状态。成功结果保留 `catalog_before`、`catalog`、`catalog_diff`、`snapshot`、`snapshot_diff` 和 `setter_attempts: 1`。读取计划始终没有 writer，描述支持状态不会暗中执行赋值。

`snapshot_scope` 用实际对象和数量 key 将原快照字段绑定到目标：目标在快照内时，仅允许对应数量的声明值字段变化，模式为 `bound_quantity_fields`；目标不在原快照时，模式为 `unchanged_snapshot`，要求原快照内容和全部绑定保持不变。`modified` 元数据单独忽略，名称、维度及其他内容不能随之放行。通用规则还保持同节点其他已支持读取结果。该范围仍不等于全部算例设置或完整物理依赖。

写前明确拒绝返回 `rejected`，不会执行 setter。写后回读失败、超时或影响超出声明范围返回 `uncertain`，会话阻止继续操作，不重试、不回滚、不保存。快照影响验证失败的原始请求记录保留前后快照、目录结果、绑定证据、错误和 `setter_attempts: 1`；其他异常以日志和已有结果为准，不猜测尝试次数。先查看 `session_status` 及错误中给出的请求路径，当前恢复方式是明确关闭并弃置该会话，再从已知文件新建会话。

成功修改仍须显式调用 `save_session` 另存到新文件。重载后使用 `relocate_node`、重新描述和读取，核对目标值及已有快照覆盖内容；旧 `node_id` 不能跨加载使用。锁和回读不提供跨客户端原子事务或 CFD 合理性保证。


## 验证范围

2026-10-30，在 Linux、2602 Build `21.02.007` 的 `Base.sim~` 隔离副本上验证了公开 Core、JSON CLI 和 stdio MCP 入口。原件 SHA256 为 `33d98c6cad076ae9959c2039b988c0aecb0154f7ac63d79a2a805a88ae5ce895`；读取前后的既有快照内容和原件摘要保持不变。

- 真实导航及读取覆盖时间步长、压力松弛、枚举允许项、隐藏与未知属性、非 CSO 代理、静态范围，以及旧目录未映射的 Surface Proximity 标量与 Reference Altitude 向量；保留 input 背后对象身份、单位和原始分量。
- 独立 fixture 实际实例化了 `PartsResurfacerAnisotropicSizing` 的 `dynamic=true` 属性。产品生成计划调用已核验的 `ratioRange()`，读取 `[3,25]` 且两端包含；该读取前后快照不变。未登记的其他动态范围方法仍为元数据。
- 真实验证了名称含 `/`、同名删除重建后旧引用拒绝、旧分页游标失效、跨会话引用拒绝、显式重定位、缓存缺失重建、属性选择及分页、搜索别名和预算截断。材料库范围按真实类型过滤。2510 新发现入口明确拒绝。
- 该算例未出现对象循环，STAR 参数管理器也会给重复名称自动加后缀。同名歧义、循环、重复引用、局部描述与编译失败、私钥并发初始化等使用契约模拟验证，不能计为真实 STAR 分支覆盖。

可复现入口为 `tools/validation/discovery_acceptance.py`（已有 Base 隔离会话上的只读验收）、`discovery_contract_checks.py`（Core 契约模拟）和 `discovery_java_contracts.py`（生产 Java 提供器配最小接口替身）。本机逐项 JSON、命令和日志位于 `outputs/runtime-20261030/`，不进入源码仓库。P1—P3 的只读验收当时保持发现写入关闭；P4 已独立启用并完成下列真实验收，不能把前一阶段的门控状态解释为当前能力。


### 受控写入验收

同一精确版本的独立工作副本完成四项正常赋值：Surface Proximity 的 `Floor` 从 `0` 到 `0.001 m`、Reference Altitude 从零向量到 `[0,0,0.125] m`、全局标量参数从 `1` 到 `2`、全局向量参数从 `[4,5,6]` 到 `[2,4,6]`。最后两项使用迁移规则，标量经真实 stdio MCP 调用；每项均只尝试一次 setter，回读、保持项和快照范围验证通过。前两项要求原快照不变，后两项只允许目标数量绑定字段变化。

七项写前拒绝覆盖负范围、不匹配的旧值、不相容标量单位、错误节点引用、不支持属性、成功后再次使用旧 `expected` 和不相容向量单位。四个成功值显式另存后，在新会话重新定位、描述和读取均一致，原快照覆盖内容一致，旧引用被拒绝。

另在重载副本添加依赖参数：源值 `2→3` 导致依赖值 `4→6`。目标赋值只执行一次，但依赖变化超出允许字段，真实结果为 `uncertain`，保存前后证据并阻止下一次调用创建任何新请求；未重试或保存该失败场景。原始 `Base.sim~` 和此前验证的保存文件摘要保持不变，三个验收会话已关闭。以上均未执行网格或求解。

`tools/validation/discovery_write_contracts.py` 另有 15 项快照比较器检查，使用本机 STAR 库编译生产 Java，但不连接算例、不执行 setter，不能计为真实写入覆盖。本机 `write-rules-report.json`、`write-reload-report.json`、`write-uncertain-report.json`、`write-final-report.json` 及逐请求日志位于 `outputs/runtime-20261030/`。这些证据仅涵盖本节规则与实例；其他版本、值类型、模型状态和物理依赖仍需单独核验。
