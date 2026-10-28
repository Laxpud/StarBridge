# 目录驱动的单属性修改

[返回项目入口](README.cn.md) · [目录描述与读取](catalog-runtime.md) · [旧 Modifier 契约](modifier.md) · [当前任务](../TODO.md)

文件与后台会话的 `modify` 已可使用候选目录和人工执行映射，修改已有标量参数表达式或常量、用户场函数定义，以及已有用户标签关联。每次请求修改一个属性，先核对旧状态，再写入、回读并返回差异。创建、删除、重命名、模型切换和其他结构操作尚未实现。

## 使用方式

需要 Python 3.11+、STAR-CCM+ 2602 Build 21.02.007 安装及许可证。先按[离线目录工具](catalog.md#生成与查看)用当前 `selection.json` 生成候选目录；下文假定输出位于 `outputs/catalog-2602/generated/catalog.json`。人工执行映射使用仓库中的 `catalogs/2602/execution.json`。

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
  --catalog outputs/catalog-2602/generated/catalog.json \
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
  --catalog outputs/catalog-2602/generated/catalog.json \
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
| `user_field_function` | `definition` | 当前定义字符串 | 非空定义字符串 |
| `scalar_parameter`、`vector_parameter`、`user_field_function`、`region`、`boundary`、`volume_average_report` | `tags` | 当前标签对象数组 | 已存在且不重复的用户标签名称数组 |

`quantity` 和 `quantity_value` 读取同一数量对象，分别选择表达式写入和数值常量写入。标量的 `definition`、`unit` 属性仍只读，不能以它们的属性 ID 发起修改。所有数量旧状态字段都参与比较，包括依赖其他参数的求值结果；保留 JSON 数值与字符串类型，不能把 `5.0` 改成 `"5.0"`。读取到的非有限值以 `"NaN"`、`"Infinity"` 或 `"-Infinity"` 保留，不能作为新的数值常量提交。

单位必须使用 STAR 单位对象的名称，并与原数量量纲兼容；无量纲单位对象名称可以是空字符串。非常量表达式应在表达式中明确量纲，例如 `<1 deg>`，结果单位必须等于读取结果的 `si_unit`。上例回读为 `0.1047197551196598 rad`，即 `6 deg`。纯数值表达式允许兼容单位，并接受 STAR 将 `6` 规范化为 `6.0`；`quantity_value` 按指定单位写入数值。

场函数只检查定义保存与回读，并保持名称、引用名称、值类型和量纲。它不计算场数据，也不证明表达式在所有时间或空间位置均可求值。

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

## 执行与失败契约

本地先检查目录成员指纹、方法 effect、请求格式和写适配器，在创建工作目录或会话活动标记前拒绝无效输入。运行时精确核对 server 版本、定位目标，并要求旧 Inspector 快照及目标类型全部已配置目录属性读取完整。

准备阶段比较 `expected`，核对单位或用户标签，解析最终 setter 及参数；这一阶段不调用 setter。只有准备通过后才允许尝试一次写入，随后回读目标全部已配置属性，检查目标身份、写入值及相关身份字段，再读取旧 Inspector 快照。

- `rejected` 表示宏确认在 setter 前拒绝。CLI 非零退出，后台会话保持 `ready`，可以重新读取后构造新请求。
- 写入调用、后续回读或保存发生异常，不能归为“未修改”。后台会话进入 `uncertain`；超时或中断也可能保留活动请求标记，按[会话失败处理](bridge-session.md#身份隔离与失败处理)排查。不会自动重试或承诺回滚。
- 文件操作只有另存并独立加载后，旧快照和目录内容都一致，才生成成功 `summary.json`。

`describe` 返回的 `writable` 只表示有写入实现，`conditions_checked: false` 表示尚未检查本次修改条件。现有检查覆盖这些适配器的类型、旧状态、单位和标签约束；通用模型状态、方法切换条件及跨对象事务仍待实现。

## 结果与差异

成功结果包含 `modification`、`catalog_before`、`catalog`、`snapshot`、`catalog_diff` 和 `snapshot_diff`。文件结果另有 `reopened_catalog_match`、`reopened_snapshot_match` 及 `input_unchanged`。目录计划与规范化请求分别保存在运行目录的 `catalog-plan.json`、`catalog-request.json`，底层 `result.json` 保留宏执行结果。

两层 Diff 都使用 `path`、`before`、`after`，路径是相应比较对象的 JSON Pointer。`snapshot_diff` 覆盖旧 Inspector 已读取的对象字段；`catalog_diff` 比较目标及该类型已配置属性。同会话保留对象 key 变化，跨加载则移除协议引用中的 token/key，以名称和实际类型核对可重定位内容；不会任意删除业务字典中的同名字段。Diff 不涵盖整个 STAR 对象树，不能证明未读取设置均未变化。

## 验证范围与迁移边界

本机 Linux、2602 Build 21.02.007 已通过文件标量表达式修改：由 `5 deg` 改为上例 `6 deg` 表达式，回读 SI 单位，另存重载后的旧快照和目录内容均一致，源文件 SHA256 未变。后台同一服务已完成 `quantity_value` 写入 `8 deg`、用户场函数定义写入 `0`、边界标签完整替换为 `AirfoilMotion`；重放旧数量预期值被明确拒绝，随后 `inspect` 成功且会话保持 `ready`。

不兼容量纲的单位和不存在的用户标签均在写入前拒绝。通过专用故障映射制造 setter 执行后的回读值不符时，操作失败并使会话进入 `uncertain`，后续 `inspect` 被阻断，未把写入后失败误报为 `rejected`。这项检查不覆盖进程崩溃或中断恢复。本地运行产物位于 `outputs/catalog-write-20261028/`。

正常会话修改显式另存后，已独立加载 `session-saved.sim`：完整旧快照与保存结果一致，标量、场函数、边界三个目标的全部已配目录属性也与对应修改结果一致，跨加载引用按上述规则规范化。原始 `Base.sim~` 的 SHA256 保持不变。

以上没有执行网格或求解，也不代表其他 STAR 版本、其他量纲、所有标签目标、系统标签、模型状态或中断恢复均已验证。其余值类型写入、结构操作、旧 Inspector 快照迁移和完整分项覆盖报告仍见 [TODO](../TODO.md)。

不带 `--catalog/--execution` 的 `modify` 仍使用[旧 schema 1 契约](modifier.md)，`set-scalar` 也保留原流程；两者尚未迁入目录。新 schema 2 由这两个目录参数明确选择，不自动翻译旧请求。读取请求仍是 schema 1；候选目录 schema 1、人工执行映射 schema 2 和修改请求 schema 2 分开版本化。
