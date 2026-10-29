# 版本目录工具

[返回项目入口](README.cn.md) · [目录描述与读取](catalog-runtime.md) · [目录修改](catalog-modifier.md) · [设计文档](../StarBridge.md#版本化对象属性与操作目录) · [当前任务](../TODO.md)

目录工具从本机 STAR Javadoc 生成候选 API，校验和合并人工语义，比较不同版本的声明变化，并分别统计静态发现、执行实现和已有结果中的成功观察。本页命令只读取安装材料，不需要许可证，不启动 STAR，也不加载或修改算例。候选目录配合人工 `execution.json` 已可执行[当前算例的描述与读取](catalog-runtime.md)及[首批单属性修改](catalog-modifier.md)；兼容修改入口和 [Inspector 快照](inspector.md#快照布局与共享调用)也复用目录，快照集合与字段另由 `snapshot.json` 描述。

## 生成与查看

仓库随附 [`catalogs/2602/generated/catalog.json`](../catalogs/2602/generated/catalog.json)，供 `inspect`、`save`、兼容 `modify` 和 `set-scalar` 自动加载，也可显式传给目录 `describe/read/modify`。它保留生成器标识、安装相对来源路径和 SHA256，人工语义、执行映射和快照布局独立维护；使用现有命令无需自行生成。

需要重新生成或检查来源时，使用 Python 3.11+，无需第三方 Python 依赖。在仓库根目录执行，`--install` 指向包含 `star/` 和 `doc/` 的安装根目录：

```bash
python3 tools/catalog/catalog.py generate \
  --install '/opt/Siemens/21.02.007-R8/STAR-CCM+21.02.007-R8' \
  --selection catalogs/2602/selection.json \
  --output outputs/catalog-2602/generated/catalog.json

python3 tools/catalog/catalog.py check \
  --catalog outputs/catalog-2602/generated/catalog.json \
  --install '/opt/Siemens/21.02.007-R8/STAR-CCM+21.02.007-R8'

cmp catalogs/2602/generated/catalog.json outputs/catalog-2602/generated/catalog.json
```

生成器从同一安装的 `star/RELEASE_NOTES` 和 `star/version_info.properties` 读取产品版本与 Build，并核对两者的 Build 一致。类型清单来自 `type-search-index.js`；类型页提供类声明、成员签名、注解和继承引用。当前解析器面向安装附带的 HTML5 Javadoc，不读取 JAR 字节码，不执行 Java 反射。

`selection.json` 是完整 Java 类型名数组，当前包含 97 个根类型，为已配读写属性、类型适配器及原有修改语义提供声明材料。生成器自动加入继承列表中引用的本地声明类型。需要扫描全部 `star.*` 索引类型时，用 `--all` 替代 `--selection`；输出会明显增大。索引中的类型包括辅助 API，不应将类型总数当作算例可配置对象总数。未命名包与 `com.siemens.*` 类型尚未纳入生成范围。

所有文件输出都要求目标文件不存在，防止覆盖人工规则或此前结果。重复生成使用另一个输出路径。临时或自行生成的候选文件放在被 Git 忽略的 `outputs/` 中；用于默认运行的 2602 候选文件随仓库版本管理。更新该文件时，从匹配安装重新生成并核对差异，不能手改生成内容代替生成器。

## 人工语义与合并

人工规则维护在 [`catalogs/2602/overrides.json`](../catalogs/2602/overrides.json)。当前描述标量表达式、用户场函数表达式和替换用户标签集合三项能力，依据现有宏与使用说明整理；这些是离线语义说明，不是执行计划；对应首批写入管线单独维护在 `execution.json`，范围见[目录修改](catalog-modifier.md)。

```bash
python3 tools/catalog/catalog.py merge \
  --catalog outputs/catalog-2602/generated/catalog.json \
  --overrides catalogs/2602/overrides.json \
  --install '/opt/Siemens/21.02.007-R8/STAR-CCM+21.02.007-R8' \
  --output outputs/catalog-2602/catalog.json

python3 tools/catalog/catalog.py describe \
  --catalog outputs/catalog-2602/catalog.json \
  --type star.common.ScalarGlobalParameter
```

合并仅增加人工 `bindings`，不会改写生成的 `types`。规则必须与目录的产品版本和 Build 完全一致，规则 ID 不能重复，所有成员引用必须存在。每个引用同时锁定可读签名和成员声明的 SHA256 指纹，覆盖注解及类型链接；签名或同名类型的包来源变化都会拒绝合并。规则需要维护者核对后显式更新，生成器不会自动重写它们。

`check`、`describe` 和 `merge` 均可加 `--install` 核对目标安装版本。Core 的 `load()` 也接受同时提供的 `release`、`build` 并精确匹配。未提供版本时只校验目录本身；检测安装版本不等于确认某个已运行会话的版本。[目录运行时入口](catalog-runtime.md)会在任何目录调用前另行核对当前 server 的版本。这里的离线 `describe` 描述 API 类型，Runner 的 `describe` 则定位当前算例对象，两者作用不同。

## v1 数据格式

格式由 [`core/catalog.py`](../core/catalog.py) 校验，所有列出的字段均必需，未知字段、重复 JSON 键和非标准数值常量会被拒绝。目录格式版本、STAR 产品版本、Build 分开维护；此版本尚不包含算例实例、对象永久 ID 或当前属性值。

| 顶层字段 | 含义 |
|---|---|
| `schema_version` | 当前为整数 `1` |
| `target` | 字符串 `release` 和 `build`，例如 `2602`、`21.02.007` |
| `generator` | 当前为 `starbridge-javadoc-v1` |
| `sources` | 安装版本文件与类型索引的安装相对路径、SHA256 |
| `scope` | 显式选择的 `roots`、索引总数 `indexed_types`、是否包含继承声明 |
| `types` | 以完整 Java 类型名为键的声明集合 |
| `bindings` | 以稳定语义 ID 为键的人工属性或操作描述；生成时为空 |

每个类型保留 `java_class`、类 `signature`、签名中的 `links`、类型页 `source`、声明的 `members`、`property_candidates`、`inherited_members` 和 `status`。成员键使用 Javadoc 锚点，包含方法参数类型，可以区分重载；值保留名称、签名、返回类型、参数、修饰符、注解及链接。继承成员通过声明类和成员键引用，不复制成子类自己的方法。Java 泛型以文档声明保留，不进行类型参数代换。

只有带 `StarBeanProperty` 注解的成员自动进入属性候选。`metadata` 保存完整注解文本，包括显式的 `readOnly`、`link`、编辑器等材料；实际写入方法、单位与模型前提仍需核对。`link` 是属性变化通知联动，不是 setter 或访问路径；`readOnly` 也不代替运行时可写条件检查。没有注解的 getter 或 setter 仍保留在 `members`，不会因为不在候选表中就被视为不支持。候选只标记 `discovered`，`adapter` 为 `null`。

人工规则文件包含 `schema_version`、`target`、`bindings`。每个 binding 包含：

| 字段 | 含义 |
|---|---|
| `type`、`kind` | 目标类型；`kind` 为 `property` 或 `operation` |
| `value_type` | 属性值或操作结果的种类、单位、量纲、枚举值及引用类型 |
| `parameters` | 操作参数名到值类型的映射；属性映射使用空对象 |
| `access` | 管理器/查找关系的中文说明，以及需要核对的成员引用 |
| `read`、`write` | 相关成员的有序引用，每个引用含类型、成员键、签名和指纹 |
| `adapter` | 预留执行适配器位置，当前必须为 `null` |
| `constraints` | 条件说明和预留的 `runtime_check`，当前检查器必须为 `null` |
| `verification` | 回读与验证说明，以及需要核对的成员引用 |
| `evidence` | 规则依据的材料路径 |
| `status` | 分别记录发现、读取实现、写入实现和实测验证状态 |

值类型的 `kind` 可为 `number`、`boolean`、`string`、`enum`、`quantity`、`expression`、`vector`、`tensor`、`reference`、`collection`、`query` 或 `void`。`unit`、`dimensions`、`reference_type` 使用字符串或 `null`；`null` 表示尚未静态确定，不表示无量纲。`enum_values` 是字符串数组。动态查询必须保留查询语义，不能只记录查询当时选中的对象；已实现的读取适配与谓词范围见[运行时值格式](catalog-runtime.md#已配置属性与值格式)。

`overrides.json` 的成员引用及条件说明用于维护者核对修改语义，还不是可执行调用计划：它们不编码完整参数绑定、返回值传递或运行时定位。此离线格式仍强制这些 binding 的 `read_implemented`、`write_implemented`、`verified` 为 `false`，且离线描述结果标记 `runtime_state: not_checked`。已审阅的读写调用管线单独维护在 `execution.json`，其 schema 4 支持按值类型的写适配器、对象引用与选择，以及主目标/关联值的声明式只读条件，兼容 schema 1/2/3；新增张量读取与分量标量写入继续使用 schema 4，不新增整张量 setter。实际执行与验证边界见[运行时说明](catalog-runtime.md)。旧脚本已验证的修改能力不会自动计入目录执行覆盖。

## 版本比较

分别从两个安装生成目录，再运行：

```bash
python3 tools/catalog/catalog.py diff \
  outputs/catalog-2510/generated/catalog.json \
  outputs/catalog-2602/generated/catalog.json \
  --output outputs/catalog-diff.json
```

比较结果报告类型增删、类声明、成员签名/类型链接/注解、属性元数据、继承关系及人工规则变化。方法名称改变而参数锚点和返回类型相同时，另外给出 `rename_candidate`，要求人工确认；这不证明两者语义等价。类型改名没有自动对应规则。

`same_roots` 表示两次显式选择范围是否一致。范围不一致时，类型增删可能只是选择范围变化；即使范围一致，继承依赖变化也可能改变所包含的类型集合。文件摘要和发布材料变化保留在各目录来源中，但不单独当作 API 声明变化。`compatibility` 始终为 `not_assessed`，不根据差异数量推断兼容。

## 分项覆盖报告

`coverage` 分别读取候选目录、执行映射和已有 Runner 结果，报告明确版本与范围内的实现数量及证据缺口。命令不会重放修改或连接算例；`--execution` 可省略，此时执行状态为 `not_supplied`。提供 `--result` 时必须同时提供执行映射；该参数可重复使用。

```bash
python3 tools/catalog/catalog.py coverage \
  --catalog catalogs/2602/generated/catalog.json \
  --execution catalogs/2602/execution.json \
  --overrides catalogs/2602/overrides.json \
  --output outputs/catalog-coverage.json
```

要统计已有运行证据，在命令中加入 `--result <运行目录>/apply/result.json` 或 `--result <运行目录>/summary.json`；会话请求的 `result.json` 与命令响应也可使用。结果文件必须由维护者确认来源。报告记录其 SHA256 和实际目标定位，摘要用于追溯所读文件，不认证文件内容的真实性。

报告使用两个统计基数：

- `discovery` 按声明位置统计类型、成员和带注解的属性候选，继承引用不重复计数；人工语义的属性与操作另计。`candidates` 保留每个候选及 `not_assessed` 原因，因为候选声明与执行属性没有一对一语义映射。
- `execution.counts` 按执行映射的 `(type, property)` 计数，分别提供 `read_implemented`、`write_implemented`、`observed_read`、`observed_write` 和 `file_reload`。执行映射必须先通过现有版本、成员指纹、适配器和调用管线校验；存在 getter 不会自动计入实现。重复输入或同一属性的多个成功结果不会增加属性总数。

成功观察的计数依据如下：

| 字段 | 所需结果 |
|---|---|
| `observed_read` | 同一 `catalog_id` 和精确 server 版本的属性读取结果，属性 `status: ok` 且包含 `value`；局部错误单列，不计成功 |
| `observed_write` | 成功的 schema 2 目录修改结果，带原请求及同一目标的完整前后读取；指定属性必须具备写入实现 |
| `file_reload` | 上述修改的文件 Runner 汇总同时确认 `reopened_catalog_match`、`reopened_snapshot_match` 和 `input_unchanged`，且输出与输入不同 |

`describe` 输出、旧兼容请求、未经绑定的材料和人工 `status` 不作为写入实测依据。执行映射变更后，旧 `catalog_id` 的结果列为 `stale`；不能据同名属性继续沿用。版本不符、属性缺失或矛盾结果列为 `not_accepted` 并给出原因。拒绝或失败结果列为 `rejected/error`，不增加成功数；没有当前目录身份的拒绝结果也不能证明某个运行条件已经验证。损坏 JSON、重复键、缺失文件会使命令失败。

每个执行属性保留读写适配器、声明条件、证据索引和未实现／证据缺失原因。`runtime_state` 始终为 `not_checked`，当前目标或模型是否满足条件需要实际运行。`full_branch_verification` 始终为 `not_assessed`：成功观察只证明所给目标、方法、单位和值的样例，不能替代所有分支验收或 CFD 物理合理性判断。不同基数间不计算总覆盖百分比。

## 当前验证边界

本机 2602 Build 21.02.007 的全部 23,171 个 `star.*` 索引类型已生成并通过目录结构与继承引用校验，包含 154,743 个声明成员和 9,939 个属性候选。当前 97 个根类型及其继承依赖共生成 175 个类型、2,357 个声明成员和 144 个属性候选，新增材料用于 TensorProfile、当前方法、分量数量及方向读取；随附候选文件与本轮两次独立生成结果逐字节一致，全部既有类型记录保持不变。初始选择也已核对重复生成结果，并与 2510 Build 20.06.007 的同范围目录比较；这不代表 2510 算例读写获得支持。安装版本不匹配、人工规则版本不匹配以及成员指纹失效均已确认拒绝。

实际算例的定位与读取适配已接入目录，范围见[运行时验证](catalog-runtime.md#验证范围与剩余工作)；首批目录写入、预检查、回读及文件另存重载见[目录修改验证](catalog-modifier.md#验证范围与迁移边界)。修改兼容层见 [Modifier](modifier.md)，快照目录和验收见 [Inspector](inspector.md)。操作描述、通用模型条件及剩余覆盖仍见 [TODO](../TODO.md)；分项报告的证据输入范围由调用方显式选择，不自动扫描本机历史输出。其他格式的 Javadoc、缺失文档的 API 和供应商元数据语义仍需相应材料与验证。
