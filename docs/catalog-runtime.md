# 目录驱动的描述与读取

[返回项目入口](README.cn.md) · [离线目录工具](catalog.md) · [目录修改](catalog-modifier.md) · [Inspector 快照](inspector.md) · [当前任务](../TODO.md)

文件和后台会话 Runner 的 `describe`、`read` 已通过同一份候选目录、人工调用映射和类型适配器访问当前算例。执行前精确核对正在运行的 STAR server 版本，再按类型、名称及父对象定位目标。首批[目录修改](catalog-modifier.md)也已复用这些定位与读取管线；兼容 schema 1 `modify` 和 `set-scalar` 也使用同一目录修改器；旧 `inspect` 快照迁移仍未完成。

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

要描述当前对象的已配属性，把请求中的 `action` 改为 `describe`，另存为 `describe-request.json`。`describe` 会核对版本并定位对象，但不执行各属性的读取管线：

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

本页描述与读取请求的格式版本为整数 `1`；目录修改使用独立的 schema 2 契约。顶层必需字段为 `schema_version`、`action`、`target`，可选字段为 `properties`；未知字段会被拒绝。`properties` 是不重复、非空的属性 ID 数组，省略时选择该类型当前映射中的全部属性，不能据此理解为整个 STAR 对象的全部属性。未映射属性在启动客户端或写入会话活动标记前拒绝。

`target` 使用目录的类型 ID 和精确显示名称。当前定位器从指定管理器枚举对象，按 Java 类型过滤后要求名称唯一匹配。边界还必须提供所属区域：

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
| `inspection_complete` | 本次选定属性是否全部成功；不表示完整读取算例或完成旧快照迁移 |

`read` 的每项成功结果为 `{"status":"ok","value":...}`，失败结果为 `{"status":"error","error":"..."}`。单项读取失败保留其他属性结果，`inspection_complete` 为 `false`，CLI 输出警告但仍可返回零退出码。使用者必须检查每项状态，不能把失败当成空集合或 `null`。

`describe` 的每项包含 `adapter`、`writable`、`reason` 和 `conditions_checked`。`writable` 表示该目录属性是否已有写入实现，当前 `conditions_checked` 为 `false`；它不是模型状态或当前可写条件的运行时结论。写入范围与实际预检查见[目录修改](catalog-modifier.md#请求与支持范围)。

目录与人工映射不匹配、请求格式错误或未知属性在本地拒绝。当前 server 版本、定位或会话引用不匹配时，宏返回 `status: rejected`，CLI 非零退出；后台会话保持 `ready`，可以重新读取。客户端异常或其他无法确认的失败仍沿用会话 `uncertain` 处理，不自动重试。底层 `result.json` 保存拒绝原因；文件失败时不生成成功 `summary.json`。

每次目录请求还会保存 `catalog-plan.json`、`catalog-request.json`、实际宏和日志。发送给 Java 的计划只包含目标、父类型和选定属性，不把整个候选目录嵌入宏。

## 已配置属性与值格式

以下是当前 `execution.json` 的读取范围，新增映射仍需材料核对和实际验证：

| 类型 ID | 属性 ID |
|---|---|
| `global_parameter` | `name`、`tags` |
| `field_function` | `name`、`tags` |
| `scalar_parameter` | `name`、`quantity`、`quantity_value`、`definition`、`unit`、`tags` |
| `vector_parameter` | `name`、`quantity`、`definition`、`unit`、`tags` |
| `user_field_function` | `name`、`definition`、`function_name`、`dimensions`、`value_type`、`ignore_boundary_values`、`sync_name`、`tags` |
| `region` | `name`、`region_type`、`physics_continuum`、`index`、`tags` |
| `boundary` | `name`、`boundary_type`、`region`、`index`、`allow_per_part_values`、`tags` |
| `user_tag` | `name` |
| `volume_average_report` | `name`、`parts`、`tags` |

适配器按值类型复用：

| 适配器 | 返回值与边界 |
|---|---|
| `primitive` | 字符串、布尔或数值；非有限数值转成显式字符串 |
| `reference` | 名称、实际 Java 类和会话引用；缺失的可选关联保留 `null` |
| `collection` | 基础值或对象引用的稳定列表；输出顺序不是操作执行顺序 |
| `quantity` | 标量数量的 `definition`、`unit`、`si_unit`、`raw_value`、`si_value`；两种数值分别使用对应单位 |
| `vector` | `definition`、`unit`、`components`；保持 STAR 数量对象的分量约定，不变换坐标系 |
| `enum` | `selected` 和当前 API 返回的 `allowed` 集合，不以枚举类全部常量替代当前允许值 |
| `query` | 静态模式为 `mode: static` 和 `objects`；动态模式为 `mode: query`、`predicate` 和 `modifiers` |

动态查询保留规则本身，不求值成当时匹配的对象列表。当前只编码 `NamePredicate` 和 `TypePredicate`，分别返回 `type: name` 或 `type: java_type`、操作符及值；其他谓词逐属性报错，不执行 `asJournal()` 生成的代码。此入口不求报告值、不生成网格、不运行求解或工作流。

## 人工执行映射

[`catalogs/2602/execution.json`](../catalogs/2602/execution.json) 是维护者审阅的调用映射，由 [`core/execution.py`](../core/execution.py) 与候选目录共同校验；它与仅供离线核对的 `overrides.json` 修改语义分开维护。请求只能选择目标与属性，不能覆盖映射、方法的 `effect`、Java 类或参数来源。

映射格式版本当前为 `2`，加载器兼容仅含读取管线的版本 `1`；顶层包含 `target`、`members`、`types`、`properties`。每个 member 锁定候选声明的签名和指纹，并声明反射参数类型及 `effect: read` 或 `effect: write`。定位和读取管线只允许 `read`；写入管线仅最后一步允许 `write`，读取计划会移除写入管线。当前只接收已核对的 public 实例方法，不开放字段、构造器、静态调用或通过 `setAccessible()` 访问非 public 方法。参数类型必须能由候选材料证明，裸泛型变量 `T` 不能冒充可加载类；嵌套类按已核对类型页转换为 JVM 名称。

类型的 `locate` 和属性的 `read` 都是调用管线：`root` 可为 `simulation`、当前 `object` 或 `parent`，后续每一步以上一步返回值作为接收对象。参数来源只能是已核对的类字面量、JSON 标量 `literal` 或当前 `object`/`parent` 上下文，数量和类型必须与指定方法相符。对象定位管线最终必须返回集合，父类型关系须明确且不能成环。

运行时先用 `getCurrentVersion()` 和 `getReleaseNumber()` 读取当前 server 版本，与目录精确匹配，不使用文件保存版本，也不截断版本后缀。离线 `check --install` 只核对安装材料，不能代替这项会话检查。

Javadoc 的 `StarBeanProperty.link` 表示属性变化通知联动，不能作为 setter 或访问路径；`readOnly` 元数据也不能替代实际条件检查。首批目录写入已核对预期旧状态、类型、单位、标签并回读；通用模型条件与其他适配器仍待补齐。写入参数、单次 setter 尝试及失败契约见[目录修改](catalog-modifier.md)。

## 验证范围与剩余工作

本机 Linux、2602 Build 21.02.007 已通过文件标量读取并确认原输入 SHA256 不变。后台工作副本中，当时 7 种类型共 33 个已配属性均返回 `status: ok`，`describe` 也已运行。向量来自工作副本专用对象，分量为 `[1.25, -2.5, 3.75]`；动态查询分别完整回读 `NamePredicate` 的 `Matches Background` 和 `TypePredicate` 的 `Is Region` 规则，没有求值成匹配对象列表。

跨会话旧引用、同名向量删除重建后的旧 key，以及错误 Build `21.02.999` 均明确拒绝，随后同会话读取成功且状态保持 `ready`。未映射属性在活动请求前拒绝，会话记录未变。人为设置错误读取适配器时，仅该属性返回错误，其他选定属性成功，整体 `inspection_complete` 为 `false`；会话仍可继续使用和保存。

工作副本另存后独立加载，向量全部已配属性与会话读取一致，新的文件加载 token 与此前会话不同。原始 `Base.sim~` 的摘要保持不变，验证服务已关闭。运行产物位于本地 `outputs/catalog-runtime-20261028/`，不进入源码版本管理。

静态查询分支目前尚未实测；未知谓词、其他 STAR 版本及完整对象覆盖也不能据此认定通过。新增 `quantity_value` 与首批写入的验收见[目录修改验证](catalog-modifier.md#验证范围与迁移边界)。`global_parameter` 和 `field_function` 是兼容旧标签目标范围的通用定位类型，不据此承诺参数或场函数的所有其他属性可写。旧 `inspect` 仍按固定字段生成快照；不带目录参数的 schema 1 `modify` 和 `set-scalar` 已通过兼容层复用目录修改器。当前能力不完成整个 Inspector/Modifier 迁移，也不改变[当前里程碑](../TODO.md)的全部完成条件。
