# 目录驱动的属性修改与结构操作

[返回项目入口](../README.cn.md) · [技术文档](index.md) · [当前架构](architecture.md) · [目录描述与读取](catalog-runtime.md) · [旧 Modifier 契约](modifier.md) · [当前任务](../../TODO.md)

文件与后台会话的 `modify` 使用候选目录和人工执行映射修改已有属性，或执行目录声明的结构操作。属性映射包含标量与向量表达式或常量、用户场函数定义及布尔/枚举选项、重力向量、用户标签关联，体积平均报告的场函数引用和对象选择，边界当前常量标量/向量 Profile、有向自动源网格的有界标量尺寸，以及区域中已有二维或三维张量 Profile 的常量分量、方向轴向量和材料物性当前多系数方法的常量系数。结构操作支持已有二维或三维张量 Profile 的[方法切换](#张量-profile-方法切换)，以及已有材料物性的[常量与导热方法切换](#材料物性方法切换)。每次请求选择一个属性或一个操作，先核对条件与旧状态，再执行、回读并返回差异。实际验证状态见[验证范围](#验证范围与迁移边界)；创建、删除、重命名、模型切换和其他结构操作尚未实现。

## 使用方式

需要 Python 3.11+、匹配所选目录的 STAR 安装及许可证；默认 2602，其他随附版本见[版本选择](catalog-versions.md)。可直接使用随仓库分发的 `src/starbridge/catalogs/2602/generated/catalog.json` 和独立维护的 `src/starbridge/catalogs/2602/execution.json`，不需要先生成目录。自行重建和核对来源的方法见[离线目录工具](catalog.md#生成与查看)。schema 2 属性修改与 schema 3 结构操作均要求显式传入两个路径。

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
  --catalog src/starbridge/catalogs/2602/generated/catalog.json \
  --execution src/starbridge/catalogs/2602/execution.json \
  --request catalog-change.json \
  --output outputs/Base_catalog_modified.sim \
  --work-dir outputs/catalog-modify-file
```

`--output` 必须不存在，且父目录已存在；`--work-dir` 也必须是新目录。原输入只读，并在结束时核对 SHA256。失败时不生成成功摘要；若失败发生在另存后，输出文件可能已存在。

会话模式先按[会话说明](bridge-session.md)连接已有服务或启动自有服务，再操作已加载的算例：

```bash
python3 bridge/runner/session_bridge.py modify \
  --session-id SESSION_ID \
  --catalog src/starbridge/catalogs/2602/generated/catalog.json \
  --execution src/starbridge/catalogs/2602/execution.json \
  --request catalog-change.json

python3 bridge/runner/session_bridge.py save \
  --session-id SESSION_ID --output outputs/Base_catalog_session.sim
```

会话修改只改变内存，`save` 单独落盘；会话保存本身不独立重载文件。Runner 的文件锁只串行管理自身请求，不是与外部客户端或 GUI 之间的事务锁。

## 请求与支持范围

属性修改请求顶层必须且只能有 `schema_version`、`action`、`target`、`property`、`expected`、`value` 六个字段。格式版本为整数 `2`，`action` 固定为 `modify`。`target` 沿用[目录目标身份](catalog-runtime.md#请求与目标身份)：类型 ID、唯一显示名称，边界与张量 Profile 还需父区域，张量分量与方向轴需完整父 Profile 路径，材料系数需完整父物性及材料路径；同会话可附带 `reference` 严格检查 token/key。跨加载不能沿用旧引用，应重新读取并使用 `locator`。结构操作使用下文独立的 [schema 3 契约](#张量-profile-方法切换)。

| 目标类型 | 属性 ID | `expected` | `value` |
|---|---|---|---|
| `scalar_parameter` | `quantity` | 完整数量对象：`definition`、`unit`、`si_unit`、`raw_value`、`si_value` | `{"definition":"表达式", "unit":"结果单位对象名"}` |
| `scalar_parameter` | `quantity_value` | 同上 | `{"value":8, "unit":"deg"}`，数值必须有限 |
| `vector_parameter` | `quantity` | 完整向量对象：`definition`、`unit`、`components` | `{"definition":"向量表达式", "unit":"结果单位对象名"}` |
| `vector_parameter` | `quantity_value` | 同上 | `{"components":[2,0,-1], "unit":""}`，恰好三个有限数值 |
| `physics_continuum` | `gravity` | 完整向量对象 | 含 `definition` 和结果 `unit` 的对象；要求已启用 `GravityModel` |
| `physics_continuum` | `gravity_value` | 完整向量对象 | 含三个 `components` 和 `unit` 的对象；要求已启用 `GravityModel` |
| `tensor_component` | `quantity`、`quantity_value` | 所选分量的完整标量数量对象 | 分别为含 `definition` 或有限数值 `value` 的对象，均需 `unit`；父张量须为已支持布局，分量须为当前常量方法 |
| `tensor_axis` | `quantity`、`quantity_value` | 当前轴的完整向量数量 | 分别为含 `definition` 或三个有限 `components` 的对象，均需 `unit`；保持轴方法与坐标关联 |
| `material_coefficient` | `quantity`、`quantity_value` | 所选系数的完整标量数量对象 | 分别为含 `definition` 或有限数值 `value` 的对象，均需 `unit`；父物性须为当前多系数方法，系数须为当前常量材料方法 |
| `tensor_profile` | `xx`、`xy`、`xz`、`yx`、`yy`、`yz`、`zx`、`zy`、`zz` | 对应分量的完整标量数量对象 | 含 `definition` 和结果 `unit` 的对象；要求当前为受支持的三维张量方法与常量分量方法 |
| `tensor_profile` | 上述各属性加 `_value`，例如 `xx_value` | 同上 | 含有限数值 `value` 和 `unit` 的对象 |
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

## 边界 Profile 修改

`boundary_scalar_profile` 和 `boundary_vector_profile` 使用[完整边界定位路径](catalog-runtime.md#边界-profile)，分别复用标量与向量写入器。`quantity` 写入 `definition` 与 `unit`；`quantity_value` 写入标量 `value` 或三个向量 `components` 及 `unit`。`expected` 始终来自该属性的完整读取值，请求仍为 schema 2。

写入要求当前方法精确为 `ConstantScalarProfileMethod` 或 `ConstantVectorProfileMethod`，且父边界 `allow_per_part_values=false`。不会切换 Profile 方法、边界类型、速度指定方式、模型或局部表面值设置。目录额外声明保持方法对象、量纲、父边界、边界类型、区域及物理连续体，向量还保持坐标系和维数；修改后按完整编码值核对。同名同类方法若更换 key，也不能视为原方法保持不变。

向量值沿 Profile 自身坐标系解释，保留三个原始分量，不按边界法向转换或自动归一化；这些写入只证明配置按请求改变，不判断速度、湍流量或其他物理输入是否合理。函数方法、数组 Profile 和按表面值配置尚未由此入口写入。

## 张量 Profile 分量

推荐先读取父 `tensor_profile` 的 `components`，再以实际名称选择 `tensor_component`。该路径支持二维和三维的各向异性、正交、各向同性及横观各向同性方法，复用标量 `quantity` / `quantity_value` 写适配器，不自动选择分量方法。例如目标可以是：

```json
{
  "type": "tensor_component",
  "name": "XX Component",
  "parent": {
    "type": "tensor_profile",
    "name": "Porous Viscous Resistance",
    "parent": {"type": "region", "name": "_Tensor2DPorous"}
  }
}
```

用此目标先 `read`，再将 `properties.quantity.value` 放入 schema 2 请求的 `expected`，选择 `property: "quantity_value"` 和 `value: {"value":10,"unit":"kg/m^3-s"}`。实际目标名、单位和旧值以读取结果为准；同会话可为子对象及父路径附带返回的 `reference`。跨加载使用不含旧引用的完整 `locator`。

准备阶段以 `tensor_layout_valid` 核对父张量布局和维数，以 `constant_component` 核对所选分量的当前方法；写后核对该分量身份、方法及父张量 `basis` 不变。读取集合包含所写数量、子对象身份及父张量 `basis`，兄弟分量采用不支持的数量方法不会单独阻止本分量写入。此路径不读取或核对兄弟标量分量数量；自带方向轴的方法还要求全部轴的常量向量可读并保持完整方向设置，所关联坐标系或 `LocalOrientation` 的内部设置仍不展开。若需核对完整张量，可另读 `method_state`，该属性要求全部标量分量和方向轴均可读。

以下原矩阵属性入口继续保留：

`tensor_profile` 定位父区域 `getValues().getObjects()` 中已有的 `TensorProfile`，使用 Profile 的实际显示名称，不能用 Java 类名替代。必须提供 `parent: {"type":"region","name":"区域名"}`。当前读取支持三维 `CompositeTensorProfileMethod` 及其已适配子类的九个独立分量，以及 `CompositeSymmetricTensorProfileMethodWithCoordinateSystem` 的六个独立分量；具体存储和方向字段见[张量读取格式](catalog-runtime.md#张量读取格式)。这不是将九项普通数组写成张量，也不包含材料系数组织的其他张量配置。

每次请求只修改一个标量分量，复用标量表达式或数值写入契约。`xx` 与 `xx_value` 读取同一数量，分别写表达式与数值；其余八组属性相同。`expected` 取对应分量的完整 `quantity` 值，不是整个 `tensor`。以下示例来自单相多孔区域工作副本；实际名称、单位和旧值必须替换为读取结果：

```json
{
  "schema_version": 2,
  "action": "modify",
  "target": {
    "type": "tensor_profile",
    "name": "Porous Viscous Resistance",
    "parent": {"type": "region", "name": "_TensorSinglePorous"}
  },
  "property": "xx_value",
  "expected": {
    "definition": "0.0",
    "unit": "kg/m^3-s",
    "si_unit": "kg/m^3-s",
    "raw_value": 0.0,
    "si_value": 0.0
  },
  "value": {"value": 10, "unit": "kg/m^3-s"}
}
```

`three_dimensional_tensor` 检查 `is3D()`，`composite_tensor_dimension` 检查复合方法维数为 `3`，`constant_component` 检查目标分量当前方法为 `ConstantScalarProfileMethod`。普通赋值只读取所写分量、身份字段及必要保持项；其他矩阵分量的数量不属于本次读取集合。完整状态需另行读取 `method_state`，文件入口还要求兼容快照与重载核对。读取只调用无参 `getMethod()`，不会通过带 Class 参数的重载切换方法；`ConstantScalarProfileMethod` 是当前方法类型，仍可由标量数量保存表达式。

`name`、`profile_method`、`tensor`、`basis`、`components` 和 `method_state` 不能通过属性赋值修改。写后核对 `profile_method` 和 `basis` 不变，保留原量纲、三维 shape、存储方式、坐标系和局部方向引用，不变换坐标系。对称方法的上下三角属性指向同一独立量，例如 `xy` 与 `yx` 是别名；`tensor.components` 只列下三角六项。三维真实实例已确认 `xy` 与 `yx` 的别名行为，不能将九个属性名理解为九个独立可写量；验证范围见[验收说明](#验证范围与迁移边界)。

上述 `tensor_profile.xx` 等矩阵属性写入不适用于二维和非复合方法；使用 `tensor_component` 访问已支持布局的实际分量。两种入口均不支持非常量分量方法和材料系数路径。多相多孔阻力使用的 `MixturePorousViscousResistanceMethod` 不属于已支持的方法，不能自动切换为各向异性方法。模型启用与 Profile 创建尚未接入；已有受支持二维或三维 Profile 的方法切换使用下述结构操作。

## 张量方向轴修改

`tensor_axis` 修改当前主方向或轴对称方法直接拥有的一个常量向量轴。先读取父 `tensor_profile.axes`，按返回的实际名称及完整父路径读取子对象；主方向常见名称为 `XX Axis`、`YY Axis`，不要将 `direction_axes` 中的 `X`、`Y` 标签直接当作名称。

将子对象的完整 `quantity.value` 放入 schema 2 `expected`。`quantity` 的新值例如 `{"definition":"[0, 2, 1]","unit":""}`，`quantity_value` 的新值例如 `{"components":[2,1,0],"unit":""}`。这里空单位来自实际无量纲方向轴，其他请求仍须使用实际数量的兼容单位。二维同样提交并保留三个原始分量，Bridge 不裁掉第三项，也不把向量归一化。标量/向量表达式的既有有限值与单位规则继续适用。

`constant_axis` 条件要求所选轴当前方法精确为 `ConstantVectorProfileMethod`；读取和修改不会将函数轴切为常量。准备与回读要求所写数量、身份字段及 `basis` 可读，写后保持轴身份、方法、坐标关联及父 `basis`。轴 `basis` 保存各轴的名称、方法、维数和坐标关联，不保存可变的向量数量，因此兄弟函数轴不会单独阻止当前常量轴写入；其他轴数值不属于本次单轴回读核对范围。

若需要检查完整方向状态，另读父 `method_state`，它要求全部方向轴和标量分量均可读。标量分量写入也会保留这些方法的完整方向轴设置。轴坐标系选择、坐标系内部基向量和轴方法切换尚未作为产品写入入口接入；本入口仅修改当前轴的数量。

## 材料系数

`material_coefficient` 修改已有材料物性当前多系数方法中的一个标量子属性。目标需完整保留[连续体—材料模型—材料—物性—系数路径](catalog-runtime.md#材料物性与系数)，以父 `material_property.coefficients` 返回的实际系数名称定位；不能把下标或预想的矩阵分量名作为替代。

读取子对象后，将 `catalog.properties.quantity.value` 原样放入 schema 2 请求的 `expected`。选择 `property: "quantity"` 时，新值为 `{"definition":"2.5","unit":"W/m-K"}`；选择 `property: "quantity_value"` 时，新值为 `{"value":2.5,"unit":"W/m-K"}`。这里的单位来自导热系数夹具，实际请求必须采用读取到的量纲与兼容单位。完整数量旧状态、表达式和单位规则与其他标量写入相同。

`multicoefficient_method` 条件在父物性当前方法上调用 `getScalarProperties()`，要求当前方法支持多系数访问并返回非空引用；`presence` 不检查集合项数。`constant_coefficient` 条件要求所选系数的实际当前类精确为 `star.material.ConstantMaterialPropertyMethod`，不会自动把函数等方法切为常量。准备和回读要求所写数量、身份字段及 `basis` 可读，写后核对目标身份、`property_method` 和父物性 `basis` 不变。

此入口每次只修改所选数量，不切换材料物性方法、不替换材料，也不启停模型。父物性的 `basis` 保留当前方法、量纲与系数名称、类型和量纲组织，不读取兄弟数量；其他系数使用函数方法时不单独阻止当前常量系数写入。需要完整系数数量时另读父 `coefficient_state`，该读取要求所有当前系数方法均受支持。这里不补齐矩阵、推断对称别名或转换坐标，方向设置也不属于本次核对范围。

## 张量 Profile 方法切换

`tensor_profile.set_method` 在已有 Profile 的当前可选方法中选择一个方法，不创建 Profile 或模型。请求版本为整数 `3`，顶层必须且只能有 `schema_version`、`action`、`target`、`operation`、`expected`、`arguments`。`action` 为 `modify`，`operation` 为 `set_method`；`arguments` 只能包含 `method`，使用下表的目录 ID，不能提交 Java 类名或方法调用。

| 方法 ID | 当前映射的 Java 类 |
|---|---|
| `isotropic` | `star.common.IsotropicTensorProfileMethod` |
| `orthotropic` | `star.common.OrthotropicTensorProfileMethod` |
| `anisotropic` | `star.common.AnisotropicTensorProfileMethod` |
| `transverse_isotropic` | `star.common.TransverseIsotropicTensorProfileMethod` |
| `principal_axes` | `star.common.PrincipalTensorProfileMethodWithAxes` |
| `axisymmetric_axis` | `star.common.AxisymmetricTensorProfileMethodWithAxis` |
| `composite` | `star.common.CompositeTensorProfileMethodWithCoordinateSystem` |
| `symmetric` | `star.common.CompositeSymmetricTensorProfileMethodWithCoordinateSystem` |

先用 `describe` 查看 `operations.set_method.method_choices`，确认目标方法在当前 Profile 中有唯一实际实例；目标条件、当前选项与影响范围的字段见[结构操作描述](catalog-runtime.md#结构操作描述)。目录中存在方法 ID 不表示任何 Profile 都允许它；缺失或重名选项在准备阶段拒绝。`implemented` 也不表示调用者旧状态、分量方法和所有可写条件已通过。

`expected` 必须取当前 `method_state` 的完整 `value`，保留活动方法、分量组织、定义、单位、数值、量纲、shape 和方向引用。仅提供旧方法名称不足以保护源配置。自带方向轴的两个方法还必须保留完整 `direction_axes`，字段见[方向轴格式](catalog-runtime.md#张量方向轴)。请求规范化时只移除 `coordinate_system`、`local_orientation` 及各方向轴 `coordinate_system` 合法引用中的 token/key，按名称和实际 Java 类比较旧方向关联；不展开所关联坐标系或 `LocalOrientation` 的内部设置。其他字段不删减或补默认值。当前操作要求旧方法和目标方法都在映射内；二维 `is_3d: false` 对应 `shape: [2,2]`，三维 `true` 对应 `[3,3]`。不一致的维数、未知方法或不支持的分量方法拒绝。

例如，将实际区域与 Profile 名称填入 `tensor-read.json`：

```json
{
  "schema_version": 1,
  "action": "read",
  "target": {
    "type": "tensor_profile",
    "name": "Porous Viscous Resistance",
    "parent": {"type": "region", "name": "_TensorSinglePorous"}
  },
  "properties": ["name", "method_state"]
}
```

读取同一工作会话，再从结果生成请求，避免手抄长旧状态：

```bash
python3 bridge/runner/session_bridge.py read \
  --session-id SESSION_ID \
  --catalog src/starbridge/catalogs/2602/generated/catalog.json \
  --execution src/starbridge/catalogs/2602/execution.json \
  --request tensor-read.json > tensor-state.json

python3 - <<'PY_REQUEST'
import json
from pathlib import Path

catalog = json.loads(Path("tensor-state.json").read_text())["catalog"]
state = catalog["properties"]["method_state"]
if not catalog["inspection_complete"] or state["status"] != "ok":
    raise ValueError("Complete tensor method state is required")
# 本例继续操作同一会话，附带目标引用以拒绝同名重建；跨文件加载改用 locator。
target = dict(catalog["target"]["locator"], reference=catalog["target"]["reference"])
request = {
    "schema_version": 3,
    "action": "modify",
    "target": target,
    "operation": "set_method",
    "expected": state["value"],
    "arguments": {"method": "orthotropic"},
}
with Path("tensor-switch.json").open("x") as stream:
    json.dump(request, stream, ensure_ascii=False, indent=2)
PY_REQUEST

python3 bridge/runner/session_bridge.py modify \
  --session-id SESSION_ID \
  --catalog src/starbridge/catalogs/2602/generated/catalog.json \
  --execution src/starbridge/catalogs/2602/execution.json \
  --request tensor-switch.json
```

文件模式使用相同 schema 3 请求与本页 `file_bridge.py modify` 命令；先从文件读取结果生成请求，将 `target` 设为 `catalog.target.locator`，避免沿用会话引用。文件修改仍必须另存到新路径并独立重载，成功摘要要求旧快照和操作声明的目录状态均一致。

操作独立声明 `read_properties: ["name", "method_state"]`；准备、执行前复查、回读和文件重载都使用这个集合。不会为了切换 Orthotropic 方法而强制读取只属于复合矩阵方法的 `xx` 等属性，但 `method_state` 内的全部活动分量必须可读。普通属性赋值只读取目标属性、身份字段及写规则声明的必要保持项；两者按各自计划选择读取范围。

准备阶段固定目标及父路径身份、检查已声明条件、完整比较 `expected`，从当前枚举中选定唯一方法对象，并只读目标方法尚未活动的设置。这样可以在 setter 前拒绝已知无法回读的目标分量。进入 `apply()` 后再次检查版本、目标、条件、完整源状态、目标方法 key 及其尚未活动设置，然后只尝试一次 `setMethod`。

回读要求实际活动方法及其 key 与选择一致，目标身份、名称、量纲、维数状态和 shape 保持；分量布局、数量及方向关联按新方法完整返回并记录 Diff。STAR 激活方法时可能初始化设置，准备时可读不代表切换后所有值必须等于未活动时的值。Bridge 不自动逐值恢复或切回旧方法；进入执行后任何异常仍按 `uncertain` 处理。未活动方法设置保存在成功结果的 `catalog_before.selected_method_state`，便于检查本次选择所依据的状态。

## 材料物性方法切换

`material_property.set_method` 为已有物性选择已存在的方法，不替换材料或启用模型。它沿用上节 schema 3 的六个顶层字段和 `arguments: {"method": "方法 ID"}`，目标改为包含完整材料路径的 `material_property`。当前映射如下：

| 方法 ID | Java 类 |
|---|---|
| `constant` | `star.material.ConstantMaterialPropertyMethod` |
| `orthotropic` | `star.energy.OrthotropicThermalConductivityMethod` |
| `anisotropic` | `star.energy.AnisotropicThermalConductivityMethodWithValues` |

先读取目标的 `name`、`method_state`，将 `method_state.value` 完整放入 `expected`；请求构造及 CLI 与上节相同。常量状态保存完整数量，多系数状态保存全部系数的方法和数量，具体字段见[材料状态格式](catalog-runtime.md#材料物性与系数)。源方法与目标方法均须在当前映射内。旧状态不会被删减或补齐，系数顺序、名称、类型、定义、单位和数值全部参与核对。

`describe` 按这三个映射类查找既有方法，返回 `method_choices_scope: "mapped_classes"`；它不枚举物性的全部选项。导热方法映射不表示密度、比热或任意材料都支持这些方法。读取成功的实际类须与映射精确相同，方法缺失或不匹配在准备阶段拒绝。查找异常与可用状态的字段见[结构操作描述](catalog-runtime.md#结构操作描述)。

操作独立读取 `name`、`method_state`，先比较完整活动设置，再只读目标方法尚未活动的设置。执行前再次核对目标及父路径身份、源状态、所选方法 key 和目标设置，只尝试一次 `MaterialProperty.setMethodType(MaterialPropertyMethod)`。回读确认新活动方法类和 key、目标身份、名称与量纲，并返回完整新状态；`catalog_before.selected_method_state` 保留选择时的目标设置。

常量与多系数之间的切换可能隐藏、启用或初始化系数。准备检查只保证目标设置已知可读，不要求切换后数值必然等于未活动时的值，也不保证切回旧方法可恢复全部配置。执行后无法确认结果时仍为 `uncertain`，不自动回滚。文件模式另存并独立重载；会话模式需要显式保存。方向对象、其他未活动方法的设置和物理合理性不在该操作核对范围。

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
| `comment` | `Contains`、`DoesNotContain`、`Matches`、`DoesNotMatch`、`StartsWith`、`DoesNotStartWith`、`EndsWith`、`DoesNotEndWith` | `value` 为注释匹配文本，可为空，不按正则解释 |
| `includes` | `All`、`None` | 无 `value` 字段；编辑器 `Placeholder` 不支持 |
| `identity` | `Equals`、`DoesNotEqual` | `value` 为定位对象数组，可为空；当前允许区域及边界，每项可带同会话引用 |

标签谓词的读取值与 `expected` 中的 `value` 是标签的名称、Java 类及可选引用；新规则必须改用上述用户标签定位对象。复合规则中的标签也会递归处理。旧规则的标签 token/key 从预期状态中移除，新规则的标签则在准备时固定身份，并在 `apply()` 前重新核对。

身份谓词的读取值与 `expected.value` 是完整引用数组，新值改用定位对象数组；边界需包含区域父路径。旧值按名称和实际类排序，保留同名项数量，移除 token/key；新值逐项固定身份并在 setter 前复查，重复指向同一个对象时拒绝。身份集合不使用单对象 getter，不会截断多对象规则。规则仅保存和回读，不承诺在当前算例中匹配到对象。

查询根节点深度为 `0`，最大深度为 `16`，整个谓词树最多 `256` 个节点；读取、旧状态规范化与新规则构造均受限制。`modifiers` 当前只能是 `[]` 或 `["PrefilterNamedObjects"]`，不接受重复项。`value_types` 限制静态及身份集合定位对象和 `java_type` 谓词可用的类；动态名称或标签规则仍由 STAR 选择管理器解释，Bridge 不枚举或推断所有匹配对象。

静态和动态模式分别选择一条最终 setter 管线，每个请求只调用一次选中的 setter。STAR 的 `setObjects` 内部会先清除 query 再替换列表，这不是原子事务；即使只有一次外部 setter 调用，失败时也可能已有部分状态改变，仍按 `uncertain` 处理，不自动重试或回滚。

## 写入条件

人工映射可在 `write.guards` 中声明只读条件，包含唯一 `id`、读取管线 `read`、值适配器 `adapter`、预期值 `expected` 和拒绝说明 `message`。它们由维护者配置，用户请求不能更改条件或提供额外 Java 调用。`describe` 返回每项的 `guards` 摘要，并执行这些目标条件的只读管线，分别返回实际值、不满足或读取失败；状态字段及其含义见[目录描述结果](catalog-runtime.md#结果与错误)。这不替代修改准备与 setter 前的再次检查。

对象引用写入另有 `value_types` 和 `value_guards`：前者限定新关联的目录类型，后者在被关联对象上读取并检查条件，和主目标的 `guards` 分开。`describe` 同样返回它们的类型列表和条件摘要；报告的标量场函数条件不表示所有报告或其他引用属性都已适配。

当前 `physics_continuum.gravity` 和 `gravity_value` 配有 `gravity_model_enabled`：读取目标物理连续体的模型管理器，以 `presence` 检查 `GravityModel` 实例存在。未启用时在准备阶段拒绝，不自动启用模型。`presence` 将 `null` 编码为 `false`、非空返回值编码为 `true`；它只能证明这条管线返回对象，不能推导其他模型依赖均满足。

修改准备阶段在读取本次计划所需属性前检查这些条件，通过后读取并比较旧值。进入 `apply()` 后、setter 调用前再次核对版本、目标引用和条件。这不是 GUI 并发锁，也不承诺检查后状态永远不变；条件只约束写入前状态，不要求写入后继续成立。

schema 6 属性写映射可通过 `write.preserved_properties` 指定额外的写后不变属性，同一类型内名称必须存在、唯一且不同于所写属性；未声明时为空。它与内置身份字段核对共同执行，比较完整值，包括对象引用身份。声明不一致或真实写入改变了不变项时，setter 已尝试，结果仍为 `uncertain`，不会当成未写入的 `rejected` 或自动回滚。

## 执行与失败契约

本地先检查目录成员指纹、方法 effect、请求格式和写适配器，在执行前拒绝无效输入。运行时精确核对计划与 STAR server 版本，再定位目标。普通会话属性赋值读取目标属性、身份字段和规则声明的必要保持项；结构操作读取其声明的 `read_properties`。文件入口保留完整快照与重载检查；会话的完整快照审查由 `audit=true` 显式启用。

准备阶段检查声明的条件并比较 `expected`。属性赋值核对单位、分量、枚举允许值或用户标签；方法切换核对源状态、当前选项与未活动目标方法的可读设置，再解析最终 setter 及参数。这一阶段不调用 setter。只有准备通过后才允许进入一次 `apply()`，随后按对应读取集合回读，检查目标身份、写入结果及必要关联项；启用快照审查时另外读取兼容 Inspector 快照。

- `rejected` 表示宏确认在 setter 前拒绝。CLI 非零退出，后台会话保持 `ready`，可以重新读取后构造新请求。
- 一旦进入 `apply()`，包括 setter 前再次检查条件在内的任何异常，以及后续回读或保存异常，都不归为准备阶段的 `rejected`。会话记录写入结果未确认；超时或中断也可能仍有客户端执行，按[会话失败处理](bridge-session.md#身份和失败处理)排查。不会自动重试或承诺回滚。
- 文件操作只有另存并独立加载后，旧快照和目录内容都一致，才生成成功 `summary.json`。

`describe` 返回的 `writable` 只表示有写入实现，不能代替实际条件检查。当前条件覆盖重力模型存在性、新关联场函数的标量类型，以及张量布局、维数、当前分量方法和材料系数当前方法，方法切换另核对源状态、按相应发现规则选定的方法和目标方法设置。其他模型依赖、其他结构操作及跨对象事务仍待实现。

## 结果与差异

会话修改成功结果包含 `modification`、`catalog_before` 和 `catalog`；MCP／Core 传 `audit=true` 或目录会话 CLI 加 `--audit` 时，另返回 `snapshot`、`catalog_diff` 和 `snapshot_diff`。完整快照不再是普通赋值的前置条件。文件入口仍保留快照重载核对，另有 `reopened_catalog_match`、`reopened_snapshot_match` 及 `input_unchanged`。文件入口默认保留宏、命令、日志与结果，计划和请求仅在内部调试模式另存；会话正常成功请求只留简短操作记录，调试或失败诊断的保留规则见[会话运行数据](bridge-session.md#运行数据与项目产物)。

配置了写入条件并准备成功时，`catalog_before.checks` 记录各项 `id`、`expected` 和 `actual`。这是准备阶段通过的检查记录，不是全部模型状态报告，也不表示修改后的条件仍成立。

对象引用写入还在 `catalog_before.value_checks` 中记录新关联对象及其条件检查。静态选择、查询标签和身份集合会固定对象身份，但不据此生成完整模型检查报告。

两层 Diff 都使用 `path`、`before`、`after`，路径是相应比较对象的 JSON Pointer。`snapshot_diff` 覆盖旧 Inspector 已读取的对象字段；`catalog_diff` 比较目标及本次计划读取的属性：属性赋值覆盖目标、身份字段及规则声明的必要保持项，结构操作覆盖声明的 `read_properties`。同会话保留对象 key 变化，跨加载则移除协议引用中的 token/key，以名称和实际类型核对可重定位内容；查询内标签及身份集合引用也递归规范化，张量 `tensor`/`basis`/`method_state` 内的坐标系与局部方向引用同样移除会话 token/key，其他谓词字段及组合顺序保持不变，不会任意删除业务字典中的同名字段。Diff 不涵盖整个 STAR 对象树，不能证明未读取设置均未变化。

## 工作流选择配置

`workflow_settings.selected_workflow` 通过已有对象引用写入器选择一个已存在的 `workflow`。`expected` 是读取的完整旧关联或 `null`；`value` 为工作流定位对象，例如 `{"type":"workflow","name":"_SnapshotChild 1"}`，同会话可附带该工作流的引用。暂不支持清空选择。

写入前检查 `hasRunningWorkflow=false`，再次核对目标和新关联身份，调用一次 `setSelectedWorkflow()` 后回读；管理器名称、已有工作流引用集合及正在执行的工作流必须保持。它改变下次运行的选择配置，不执行任何块，不创建、删除、重排块，也不改变子工作流关联。嵌套块结构仍可用 Inspector 读取，子工作流链接修改所需的循环关系校验尚未实现。文件模式另存后独立重载，旧状态或条件不符仍在准备阶段拒绝。

## 网格尺寸修改

`mesh_scalar_control.quantity` 和 `quantity_value` 复用标量表达式与常量写入器，目标使用[完整网格父路径](catalog-runtime.md#有向网格源尺寸)。`expected` 为当前完整标量数量；新值分别为 `{"definition":"${_MeshBackgroundBaseSize} * 1.1", "unit":"m"}` 或 `{"value":12.5, "unit":"mm"}`。修改后保持名称、源网格身份和量纲。

写入器从真实 BoundedScalarInput 读取当前范围，在两个普通临时 input 副本中验证表达式、预览 SI 值并换算为原范围单位；不通过真实 setter 试值。有限值必须满足范围及其整数约束。表达式仍要求 SI 结果单位，常量允许兼容单位。准备阶段及唯一 setter 前各重新读取、预览一次，`catalog_before.bounds_check` 保存准备时的范围、`preview_si_value` 和 `range_value`。范围或依赖随后仍可能改变，检查不提供跨客户端事务保证；将来修改表达式所依赖的参数也可能让结果失效。

Base Size 的实测范围为严格大于零。未适配的 input、无法预览的表达式、量纲错误和越界值均在准备时拒绝；执行阶段异常仍使用现有 `uncertain` 契约。此入口修改已有尺寸配置，不创建控制、不生成网格，也不执行求解。

## 兼容入口与格式版本

不带 `--catalog/--execution` 的修改遵循[兼容 schema 1 契约](modifier.md)，文件与会话的版本选择见[版本说明](catalog-versions.md)。属性请求为 schema 2，结构操作请求为 schema 3；执行映射格式及旧版兼容规则统一见[人工执行映射](catalog-runtime.md#人工执行映射)。

## 验证范围与迁移边界

既有验证结果与复现材料见[验证记录](../evidence/catalog-modifier.md)。当前会话与执行改造的实测缺口统一见[会话验证边界](bridge-session.md#验证边界)。
