# 目录驱动的单属性修改

[返回项目入口](README.cn.md) · [目录描述与读取](catalog-runtime.md) · [旧 Modifier 契约](modifier.md) · [当前任务](../TODO.md)

文件与后台会话的 `modify` 使用候选目录和人工执行映射修改已有属性。当前映射包含标量与向量表达式或常量、用户场函数定义及布尔/枚举选项、重力向量、用户标签关联，以及体积平均报告的场函数引用和对象选择。每次请求修改一个属性，先核对条件与旧状态，再写入、回读并返回差异。新增写入的实际验证状态见[验证范围](#验证范围与迁移边界)；创建、删除、重命名、模型切换和其他结构操作尚未实现。

## 使用方式

需要 Python 3.11+、STAR-CCM+ 2602 Build 21.02.007 安装及许可证。可直接使用随仓库分发的 `catalogs/2602/generated/catalog.json` 和独立维护的 `catalogs/2602/execution.json`，不需要先生成目录。自行重建和核对来源的方法见[离线目录工具](catalog.md#生成与查看)。schema 2 命令仍要求显式传入两个路径。

先通过 `read` 读取目标属性，将 `catalog.properties.<属性 ID>.value` 原样放入 `expected`，不要复制包含 `status` 的外层对象。保存 `catalog-change.json`，例如：

```json
{
  "schema_version": 2,
  "action": "modify",
  "target": {"type": "scalar_parameter", "name": "_AirfoilPitchAmplitude"},
  "property": "quantity",
  "expected": {
    "definition": "5.0",
    "unit": "deg",
    "si_unit": "radian",
    "raw_value": 5.0,
    "si_value": 0.08726646259971649
  },
  "value": {"definition": "3 * <1 deg> + 3 * <1 deg>", "unit": "radian"}
}
```

示例旧值来自本项目算例，实际使用必须替换为当前读取结果。文件入口另存为新 `.sim` 后独立加载核对：

```bash
python3 bridge/runner/file_bridge.py modify 'Base.sim~' \
  --catalog catalogs/2602/generated/catalog.json \
  --execution catalogs/2602/execution.json \
  --request catalog-change.json \
  --output outputs/Base_catalog_modified.sim \
  --work-dir outputs/catalog-modify-file
```

`--output` 必须不存在，且父目录已存在；`--work-dir` 也必须是新目录。原输入只读，并在结束时核对 SHA256。失败时不生成成功摘要；若失败发生在另存后，输出文件可能已存在。

后台模式先按[会话说明](bridge-session.md)启动服务，再操作已加载工作副本：

```bash
python3 bridge/runner/session_bridge.py modify \
  --session-dir outputs/my-session \
  --catalog catalogs/2602/generated/catalog.json \
  --execution catalogs/2602/execution.json \
  --request catalog-change.json

python3 bridge/runner/session_bridge.py save \
  --session-dir outputs/my-session --output outputs/Base_catalog_session.sim
```

会话修改只改变内存，`save` 单独落盘；会话保存本身不独立重载文件。Runner 的文件锁只串行管理自身请求，不是与外部客户端或 GUI 之间的事务锁。

## 请求与支持范围

请求顶层必须且只能有 `schema_version`、`action`、`target`、`property`、`expected`、`value` 六个字段。格式版本为整数 `2`，`action` 固定为 `modify`。`target` 沿用[目录目标身份](catalog-runtime.md#请求与目标身份)：类型 ID、唯一显示名称，边界还需父区域；同会话可附带 `reference` 严格检查 token/key。跨加载不能沿用旧引用，应重新读取并使用 `locator`。

| 目标类型 | 属性 ID | `expected` | `value` |
|---|---|---|---|
| `scalar_parameter` | `quantity` | 完整数量对象：`definition`、`unit`、`si_unit`、`raw_value`、`si_value` | `{"definition":"表达式", "unit":"结果单位对象名"}` |
| `scalar_parameter` | `quantity_value` | 同上 | `{"value":8, "unit":"deg"}`，数值必须有限 |
| `vector_parameter` | `quantity` | 完整向量对象：`definition`、`unit`、`components` | `{"definition":"向量表达式", "unit":"结果单位对象名"}` |
| `vector_parameter` | `quantity_value` | 同上 | `{"components":[2,0,-1], "unit":""}`，恰好三个有限数值 |
| `physics_continuum` | `gravity` | 完整向量对象 | 含 `definition` 和结果 `unit` 的对象；要求已启用 `GravityModel` |
| `physics_continuum` | `gravity_value` | 完整向量对象 | 含三个 `components` 和 `unit` 的对象；要求已启用 `GravityModel` |
| `user_field_function` | `definition` | 当前定义字符串 | 非空定义字符串 |
| `user_field_function` | `ignore_boundary_values` | 当前 JSON 布尔值 | JSON 布尔值，例如 `true`，不能使用字符串 `"true"` |
| `user_field_function` | `value_type` | 完整枚举对象：`selected`、`allowed` | 当前 `allowed` 中的一个枚举名称字符串 |
| `volume_average_report` | `field_function` | 当前关联的 `name`、`java_class`，可带读取结果中的 `reference`；未关联时为 `null` | 已存在场函数的 `field_function` 定位对象；要求其值类型为 `SCALAR` |
| `volume_average_report` | `parts` | 当前完整静态选择或查询规则 | 完整 `static` 或 `query` 选择对象，见[对象引用与选择](#对象引用与选择) |
| `global_parameter`、`scalar_parameter`、`vector_parameter`、`field_function`、`user_field_function`、`region`、`boundary`、`volume_average_report` | `tags` | 当前标签对象数组 | 已存在且不重复的用户标签名称数组 |

`quantity` 和 `quantity_value` 读取同一数量对象，分别选择表达式写入和数值常量写入；`gravity` 与 `gravity_value` 也是如此。参数的独立 `definition`、`unit` 属性仍只读，不能以它们的属性 ID 发起修改。所有数量旧状态字段都参与比较，包括依赖其他参数的求值结果；保留 JSON 数值与字符串类型，不能把 `5.0` 改成 `"5.0"`。读取到的非有限值以 `"NaN"`、`"Infinity"` 或 `"-Infinity"` 保留，不能作为新的数值常量提交。

单位必须使用 STAR 单位对象的名称，并与原数量量纲兼容；无量纲单位对象名称可以是空字符串。非常量标量表达式应在表达式中明确量纲，例如 `<1 deg>`，结果单位必须等于读取结果的 `si_unit`。上例回读为 `0.1047197551196598 rad`，即 `6 deg`。纯数值表达式允许兼容单位，并接受 STAR 将 `6` 规范化为 `6.0`；标量 `quantity_value` 按指定单位写入数值。

向量始终使用当前 STAR 数量对象的原坐标约定，不变换坐标系。`components` 必须恰好有三个有限数值，二维数据也需显式补第三项；不接受布尔、数值字符串或省略分量。旧状态中的定义、单位和三个分量全部比较；当前向量含非有限分量时，准备阶段也拒绝写入。非常量向量表达式要求 SI 结果单位，纯三分量常量可使用兼容单位；当前向量读取没有 `si_unit` 字段，SI 单位对象名需根据该数量的 STAR 单位与量纲确认。回读核对接受纯常量的空白或数字格式规范化，动态表达式保持文本一致，数值分量按数量精度容差核对。

例如向量数值请求如下；名称和 `expected` 必须换成实际读取结果：

```json
{
  "schema_version": 2,
  "action": "modify",
  "target": {"type": "vector_parameter", "name": "_SnapshotVector"},
  "property": "quantity_value",
  "expected": {"definition": "[1.25, -2.5, 3.75]", "unit": "", "components": [1.25, -2.5, 3.75]},
  "value": {"components": [2, 0, -1], "unit": ""}
}
```

布尔选项使用同类型 JSON 值。通用 `primitive` 写适配器可以处理布尔、文本或有限数值，但当前目录只将 `ignore_boundary_values` 映射到它，不能据此提交任意未映射属性。场函数定义单独使用 `field_definition`，要求非空文本。枚举的 `expected` 必须原样保留 `selected` 和 `allowed`，包括允许值顺序；新值既要出现在这个旧列表中，也须是运行时 option 当前返回的允许实例，不能提供 Java 枚举类或自行构造常量。

场函数定义修改保持名称、引用名称、值类型和量纲。修改 `value_type` 时只放行该目的属性的变化，其他已检查身份字段仍保持；回读要求新的选择值仍在当前允许列表中。这些操作不计算场数据，也不证明表达式在所有时间或空间位置均可求值。

标签写入**替换完整用户标签集合**，保留旧标签时要一起列出；`[]` 清除全部用户标签关联。未知标签、非用户标签、重复名称或目标已有系统标签会在写入前拒绝，不创建或删除标签对象。例如：

```json
{
  "schema_version": 2,
  "action": "modify",
  "target": {
    "type": "boundary",
    "name": "BackgroundBlock.Bottom",
    "parent": {"type": "region", "name": "Background"}
  },
  "property": "tags",
  "expected": [],
  "value": ["AirfoilMotion"]
}
```

标签 `expected` 可直接使用读取到的条目，也可只提供每项的 `name` 和 `java_class`。请求规范化会移除标签条目中的 `reference`，按名称和实际 Java 类型集合比较；同名同类型标签删除重建不会被这一旧状态检查识别。目标对象自身及父对象的 `target.reference` 仍严格核对，不受此规则影响。

## 对象引用与选择

关联属性的旧值和新值使用不同形状。`expected` 直接取读取结果，比较已有对象的 `name` 和实际 `java_class`，规范化时移除引用条目中的 token/key。新 `value` 使用类型 ID、名称及父路径定位对象，可带同会话 `reference`；准备阶段解析后会固定对象及父路径的身份，`apply()` 在 setter 前重新核对，回读也比较新关联的实际 key。旧关联按名称和类型比较不能识别同名同类型对象的删除重建，这不会削弱新值或修改目标的身份检查。

报告 `field_function` 的新值统一使用 `type: field_function` 定位内置或用户场函数，不能传读取结果中的引用对象，也暂不支持用 `null` 清空。`value_guards` 在被关联场函数上检查 `scalar_field_function`，要求其值类型为 `SCALAR`。以下仅示例请求形状，报告必须已存在，`expected` 必须替换为当前读取值：

```json
{
  "schema_version": 2,
  "action": "modify",
  "target": {"type": "volume_average_report", "name": "MyVolumeAverage"},
  "property": "field_function",
  "expected": null,
  "value": {"type": "field_function", "name": "Pressure"}
}
```

`parts` 写入替换完整选择，不能将静态对象列表当成增量添加。静态模式的 `value` 形状如下；边界必须携带所属区域，空 `objects` 数组表示清空静态选择：

```json
{
  "mode": "static",
  "objects": [
    {"type": "region", "name": "Background"},
    {"type": "boundary", "name": "BackgroundBlock.Bottom", "parent": {"type": "region", "name": "Background"}}
  ]
}
```

静态新值只允许映射声明的 `region` 和 `boundary`，还需通过 STAR 选择管理器的过滤模型校验；同一对象出现两次会被拒绝。静态旧值的 `objects` 则是读取到的名称/Java 类引用数组，按名称和类型排序后比较，并保留同名同类条目的数量，避免合并不同区域下的同名边界。旧引用没有父路径，这种比较不能区分名称、类型及数量均相同但父区域不同的替换。

动态模式保留规则，不展开成当前匹配对象，也不要求规则当前匹配到对象。例如 `parts` 的新 `value` 可以是：

```json
{
  "mode": "query",
  "predicate": {
    "type": "compound",
    "operator": "And",
    "predicates": [
      {"type": "java_type", "operator": "Is", "value": "star.common.Region"},
      {"type": "tag", "operator": "Contains", "value": {"type": "user_tag", "name": "AirfoilMotion"}}
    ]
  },
  "modifiers": []
}
```

支持的规则及写入限制如下：

| `type` | `operator` | 值 |
|---|---|---|
| `name` | `Contains`、`DoesNotContain`、`Matches`、`DoesNotMatch`、`StartsWith`、`DoesNotStartWith`、`EndsWith`、`DoesNotEndWith`、`RegexContains`、`RegexDoesNotContain` | 文本，可为空；只有两个 Regex 算子按 Java 正则解释并在准备阶段校验 |
| `java_type` | `Is`、`IsNot` | 当前写映射允许的 Java 类：`star.common.Region` 或 `star.common.Boundary` |
| `compound` | `And`、`Or` | `predicates` 数组，保持子规则顺序 |
| `tag` | `Contains`、`DoesNotContain`、`ContainsInherited`、`DoesNotContainInherited` | 新写入使用 `type: user_tag` 定位对象，可带同会话引用 |

标签谓词的读取值与 `expected` 中的 `value` 是标签的名称、Java 类及可选引用；新规则必须改用上述用户标签定位对象。复合规则中的标签也会递归处理。旧规则的标签 token/key 从预期状态中移除，新规则的标签则在准备时固定身份，并在 `apply()` 前重新核对。

查询根节点深度为 `0`，最大深度为 `16`，整个谓词树最多 `256` 个节点；读取、旧状态规范化与新规则构造均受限制。`modifiers` 当前只能是 `[]` 或 `["PrefilterNamedObjects"]`，不接受重复项。`value_types` 限制静态定位对象和 `java_type` 谓词可用的类；动态名称或标签规则仍由 STAR 选择管理器解释，Bridge 不枚举或推断所有匹配对象。

静态和动态模式分别选择一条最终 setter 管线，每个请求只调用一次选中的 setter。STAR 的 `setObjects` 内部会先清除 query 再替换列表，这不是原子事务；即使只有一次外部 setter 调用，失败时也可能已有部分状态改变，仍按 `uncertain` 处理，不自动重试或回滚。

## 写入条件

人工映射可在 `write.guards` 中声明只读条件，包含唯一 `id`、读取管线 `read`、值适配器 `adapter`、预期值 `expected` 和拒绝说明 `message`。它们由维护者配置，用户请求不能更改条件或提供额外 Java 调用。`describe` 返回每项的 `guards` 摘要（`id`、`expected`、`message`），但 `conditions_checked` 仍为 `false`，描述命令不会执行这些检查。

对象引用写入另有 `value_types` 和 `value_guards`：前者限定新关联的目录类型，后者在被关联对象上读取并检查条件，和主目标的 `guards` 分开。`describe` 同样返回它们的类型列表和条件摘要；报告的标量场函数条件不表示所有报告或其他引用属性都已适配。

当前 `physics_continuum.gravity` 和 `gravity_value` 配有 `gravity_model_enabled`：读取目标物理连续体的模型管理器，以 `presence` 检查 `GravityModel` 实例存在。未启用时在准备阶段拒绝，不自动启用模型。`presence` 将 `null` 编码为 `false`、非空返回值编码为 `true`；它只能证明这条管线返回对象，不能推导其他模型依赖均满足。

修改准备阶段在读取目标全部属性前检查这些条件，通过后读取并比较旧值。进入 `apply()` 后、setter 调用前再次核对版本、目标引用和条件。这不是 GUI 并发锁，也不承诺检查后状态永远不变；条件只约束写入前状态，不要求写入后继续成立。

## 执行与失败契约

本地先检查目录成员指纹、方法 effect、请求格式、快照布局和写适配器，在创建工作目录或会话活动标记前拒绝无效输入。运行时先精确核对快照计划与写入计划的 server 版本，再定位目标；要求兼容 Inspector 快照及目标类型全部已配置目录属性读取完整。

准备阶段检查声明的条件，比较 `expected`，核对单位、分量、枚举允许值或用户标签，解析最终 setter 及参数；这一阶段不调用 setter。只有准备通过后才允许进入一次 `apply()`，随后回读目标全部已配置属性，检查目标身份、写入值及相关身份字段，再读取兼容 Inspector 快照。

- `rejected` 表示宏确认在 setter 前拒绝。CLI 非零退出，后台会话保持 `ready`，可以重新读取后构造新请求。
- 一旦进入 `apply()`，包括 setter 前再次检查条件在内的任何异常，以及后续回读或保存异常，都不归为准备阶段的 `rejected`。后台会话进入 `uncertain`；超时或中断也可能保留活动请求标记，按[会话失败处理](bridge-session.md#身份隔离与失败处理)排查。不会自动重试或承诺回滚。
- 文件操作只有另存并独立加载后，旧快照和目录内容都一致，才生成成功 `summary.json`。

`describe` 返回的 `writable` 只表示有写入实现，不能代替实际条件检查。当前条件示例覆盖重力模型存在性和新关联场函数的标量类型，其他模型依赖、方法切换条件、结构操作及跨对象事务仍待实现。

## 结果与差异

成功结果包含 `modification`、`catalog_before`、`catalog`、`snapshot`、`catalog_diff` 和 `snapshot_diff`。文件结果另有 `reopened_catalog_match`、`reopened_snapshot_match` 及 `input_unchanged`。目录计划与规范化请求分别保存在运行目录的 `catalog-plan.json`、`catalog-request.json`，底层 `result.json` 保留宏执行结果。

配置了写入条件并准备成功时，`catalog_before.checks` 记录各项 `id`、`expected` 和 `actual`。这是准备阶段通过的检查记录，不是全部模型状态报告，也不表示修改后的条件仍成立。

对象引用写入还在 `catalog_before.value_checks` 中记录新关联对象及其条件检查。静态选择和查询标签会固定对象身份，但不据此生成完整模型检查报告。

两层 Diff 都使用 `path`、`before`、`after`，路径是相应比较对象的 JSON Pointer。`snapshot_diff` 覆盖旧 Inspector 已读取的对象字段；`catalog_diff` 比较目标及该类型已配置属性。同会话保留对象 key 变化，跨加载则移除协议引用中的 token/key，以名称和实际类型核对可重定位内容；查询内标签引用也递归规范化，其他谓词字段及组合顺序保持不变，不会任意删除业务字典中的同名字段。Diff 不涵盖整个 STAR 对象树，不能证明未读取设置均未变化。

## 验证范围与迁移边界

本机 STAR-CCM+ 2602 Build 21.02.007 的 `_SelectionReport` 体积平均报告已由 `Pressure` 关联到 `Density`，`value_checks` 记录 `scalar_field_function` 的预期和实际值均为 `SCALAR`。`parts` 已完成名称查询→静态 `Background` 区域→嵌套查询→空静态选择→同一嵌套查询的回读；嵌套规则为 `And(Type Is Region, Or(Name Matches Background, Tag Contains AirfoilMotion))`，保留 `PrefilterNamedObjects` 修饰符。

非标量 `Velocity`、不存在的场函数、跨会话新引用、重复静态对象、非法正则 `[` 和过时选择旧值均被写入前拒绝，会话保持 `ready`。本地校验拒绝不允许的关联类型、`java.lang.Runtime` 类型谓词、未知算子、深度 `17` 和 `257` 个节点的规则，并确认旧 schema 2/3 执行映射仍可加载。`describe` 返回场函数的 `value_types: ["field_function"]`、值条件 `SCALAR`，且 `conditions_checked` 保持 `false`。

会话保存后，文件 `modify` 将报告由 `Density` 改回 `Pressure`，嵌套标签查询保持不变；完整快照与目录内容的重载核对及输入摘要核对均通过。文件修改前的全部已配目录属性也与会话恢复后的结果跨加载规范化一致，确认原 `Density` 关联和嵌套标签规则均已持久化。原 `Base.sim~` 摘要未变，会话均已停止，未执行报告求值、网格或求解。本轮静态选择只验证单个区域与空集合；边界选择、多对象选择、其他谓词算子、未知谓词类型，以及并发或中断场景尚未实测。运行产物位于 `outputs/catalog-selection-20261028/`。

本机 STAR-CCM+ 2602 Build 21.02.007 已完成新增写入的内存回读：`ignore_boundary_values` 从 `false` 改为 `true`、`value_type` 从 `SCALAR` 改为 `VECTOR`、向量分量写入 `[2.25, -3.5, 4.75]`、向量表达式写入 `[5, -6, 7]`，以及重力分量写入 `[0, -9.8, 0] m/s^2`。重力修改的 `catalog_before.checks` 记录 `gravity_model_enabled` 的预期值和实际值均为 `true`。

没有重力模型的 `_NoGravity` 连续体被明确条件消息拒绝；过时布尔旧值及不兼容的 `m` 单位也被拒绝，三者会话均保持 `ready` 且最后请求状态为 `rejected`。本地请求校验拒绝用数值 `1` 写入布尔属性、非法枚举值、长度为 2 的向量和包含布尔分量的向量，并确认 schema 2 的 `primitive` 仍规范化为 `field_definition`。`describe` 正确返回重力条件摘要，且 `conditions_checked` 仍为 `false`。

会话另存后，文件 `modify` 将向量改为 `[8, -9, 10]` 并另存，`reopened_snapshot_match`、`reopened_catalog_match` 和 `input_unchanged` 均通过。再次独立加载该输出，用户场函数、向量和重力的全部已配目录属性与对应修改结果一致，完整快照也与文件摘要一致；原 `Base.sim~` 和输入 `fixture-saved.sim` 的摘要未变。未执行求解；本轮向量表达式只验证常量形式，重力只验证分量写入，动态向量表达式、其他枚举选项及其他单位尚未验证。本地运行产物位于 `outputs/catalog-typed-write-20261028/`。

本机 Linux、2602 Build 21.02.007 已通过文件标量表达式修改：由 `5 deg` 改为上例 `6 deg` 表达式，回读 SI 单位，另存重载后的旧快照和目录内容均一致，源文件 SHA256 未变。后台同一服务已完成 `quantity_value` 写入 `8 deg`、用户场函数定义写入 `0`、边界标签完整替换为 `AirfoilMotion`；重放旧数量预期值被明确拒绝，随后 `inspect` 成功且会话保持 `ready`。

不兼容量纲的单位和不存在的用户标签均在写入前拒绝。通过专用故障映射制造 setter 执行后的回读值不符时，操作失败并使会话进入 `uncertain`，后续 `inspect` 被阻断，未把写入后失败误报为 `rejected`。这项检查不覆盖进程崩溃或中断恢复。本地运行产物位于 `outputs/catalog-write-20261028/`。

正常会话修改显式另存后，已独立加载 `session-saved.sim`：完整旧快照与保存结果一致，标量、场函数、边界三个目标的全部已配目录属性也与对应修改结果一致，跨加载引用按上述规则规范化。原始 `Base.sim~` 的 SHA256 保持不变。

以上没有执行网格或求解，也不代表其他 STAR 版本、其他量纲、所有标签目标、系统标签、模型状态或中断恢复均已验证。其余值类型写入、结构操作和完整分项覆盖报告仍见 [TODO](../TODO.md)；Inspector 快照目录迁移与验收见[快照说明](inspector.md)。

不带 `--catalog/--execution` 的 `modify` 保留[兼容 schema 1 契约](modifier.md)，`set-scalar` 保留原 CLI 参数；内部自动加载随仓库分发的 2602 目录并桥接到同一修改器，用户无需生成目录或转换旧请求。旧 `modify` 提供的全部 `expected` 字段仍先按旧快照检查；`set-scalar` 没有调用者提供的预期旧值，因此仍不保护陈旧请求。两者也精确检查 server 为 2602 Build 21.02.007。

新 schema 2 仍由 `--catalog` 和 `--execution` 明确选择；读取请求仍是 schema 1。候选目录 schema 1、人工执行映射 schema 4 和修改请求 schema 2 分开版本化，新增写适配器不要求升级用户请求。执行映射加载器兼容 schema 1/2/3；schema 2 中原来专用于场函数定义的 `primitive` 会规范化为 `field_definition`，不会因 schema 3 新增通用 `primitive` 而放宽旧定义契约。兼容快照仍用于旧状态校验和结果输出，其读取通过独立 `snapshot.json` 布局共享成员映射和适配器。
