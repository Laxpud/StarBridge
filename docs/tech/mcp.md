# MCP 与共享 Core API

[任务用法](<../usage.md>) · [技术入口](<index.md>) · [当前架构](<architecture.md>)

核对基线：`f7eef68`的公开方法与契约。当前接口格式与历史协议度量分开记录；变更后的代码须重启MCP进程才能生效。

MCP 和 JSON CLI 共用 Core Service。正常任务以实际版本的 Java API／宏为主：按需取得资料和可靠代码，在同一已加载会话组织读取、判断、修改与回读，再检查逐步凭据和实际结果。结构化对象接口是可选辅助；它们使用契约 schema 2 的 `object_id` 与 `property_id`，结构操作有独立入口，不作为普通属性赋值。

版本仍由实际安装决定：目录支持 2602 Build `21.02.007` 和 2510 Build `20.06.007`，运行时发现仅登记前者。结构化接口仍有值类型和操作范围；新增的 `execute_macro` 可在同一会话使用完整 Java 宏 API，记忆接口帮助复用方法。具体契约与实际证据见[通用执行与工作记忆](<generic-execution.md>)；实现与真实 STAR 验证的区别见[验证边界](bridge-session.md#验证边界)。

## 安装与连接

三端使用[插件安装入口](../distribution.md#三端插件安装)，源码与通用 stdio 接入见[独立安装说明](../distribution.md#源码与通用接入)。stdout 仅承载协议消息；算例与输出路径均指 MCP 进程所在机器的绝对路径。

MCP 进程不热重载 Python。源码或插件升级后，应先处理执行中的请求，再重启 MCP 连接以取得新入口；这不要求重新加载已有 STAR 算例。

初始化提供简短说明，默认工具列表只含 `starbridge.expand_capabilities`、`starbridge.query`、`starbridge.execute`。AI 按任务明确选择所需能力或方法，取得相关参数格式后调用；不是按关键词触发，不要求每次重新展开，也不依赖客户端动态刷新工具列表。能力展开只返回接口元数据，API 正文读取和相关记忆检索分别由业务方法完成。完整 `get_contract` 与 `starbridge://contract` 保留为显式参考，不再是默认前置步骤。已有有效会话、对象引用、格式、资料和代码可以复用。

安装未知时用 `discover_installations` 探测实际程序；用户已指定程序时可直接交给 `open_session`。`get_capabilities()` 的 `supported`、`catalog_supported` 和 `supported_versions` 只描述结构化目录，不能证明本机安装；通用生命周期与宏另见 `session_lifecycle`、`generic_execution`，发现另查 `runtime_discovery.supported`。顶层 `ok` 仅表示查询完成，不表示未知版本已经验证。

`open_session` 从所选程序检测版本，并核对可选的 `release/build` 预期；无法检测或不匹配时在加载前拒绝，不自动换安装。未登记版本可尝试独立通用路径，但须先用所选安装内 JDK／库编译最小生命周期模板，再核对实际 server 版本与加载对象；不借用邻近目录或系统 JDK。返回 `star_version`、`version_source`、编译凭据以及可为 `null` 的 `catalog_target`，不把成功接入推广成全部 API 已验证。需要运行时规则时，还要求已有精确适配与本机 Javadoc。接入、保存与关闭语义见[会话说明](<bridge-session.md>)。

## 按需取得调用格式

`expand_capabilities` 的 `capabilities` 可选择 `work`（会话／通用宏）、`api`（版本资料）、`memory`（工作记忆）、`recipes`（现成方法）、`structured`（可选结构化）或 `reference`（完整契约）。也可只传 `methods` 选择已知业务方法；两种选择合并去重，均省略时只给简短索引，不列出全部参数说明。

```json
{"methods": ["read_api", "get_execution"]}
```

返回的 `methods[]` 给出 `method`、应使用的 `tool` 和完整 `arguments_schema`。例如，向 `starbridge.query` 传入：

```json
{"method": "get_execution", "arguments": {"session_id": "<current session_id>", "request_id": "<original request_id>"}}
```

向 `starbridge.execute` 传入的方法及参数使用同样结构。它承载生命周期、宏和记忆写入等可能有副作用的动作；`query` 明确拒绝这些方法。任意 Java 宏即使声明 `effect=read` 仍走 `execute`，不把调用者声明当作代码沙箱。正常业务结果保持原封套、局部状态和 `isError`，不套第二层结果或自动重试；原 SDK 的 Strict 类型与默认值仍生效。

能力展开的成功 `result` 最多32 KiB（32768字节），按 `json.dumps(..., ensure_ascii=False, allow_nan=False)` 的默认分隔符计量 UTF-8 字节，不含外层封套及协议转义；只在完整方法之间分页，不截坏 schema。`limit` 默认16、上限100；分别展开当前 `work` 的9个方法或 `structured` 的10个方法时，不再仅因原默认8项被拆页，但仍受字节预算约束。按 `next_offset` 继续并保持选择不变。末页只说明没有后续页，`coverage.selection_complete` 才表示本页包含整个选择。单项超预算会明确报错，不返回无法推进的空页。

这一层只改变入口和契约获取，不增加一次 STAR 往返。展开不读取 API 正文、记忆条目或算例；查询和执行才调用选定业务方法，已有方法格式可以直接复用。完整契约的 `usage.workflow.task` 描述正常宏任务，`structured_read/structured_write` 是可选路径；`usage.defaults` 来自 Core 签名，是可覆盖的省略行为。

程序基线`f7eef68`默认提供三个稳定工具，当前业务方法共30个（含`search_guide/read_guide`）。以下保留新增指南方法之前的[历史 stdio MCP 度量](<../../outputs/requirements-first/bounded-interface-a2nqrbgm/entry-metrics.json>)：当时默认定义4120字节、28个业务方法完整定义63608字节；[工作能力展开](<../../outputs/requirements-first/bounded-interface-a2nqrbgm/work-contracts.json>)一次返回9个方法，result为24588字节，无后续页。这是同口径 JSON 定义大小，不是 token 数或端到端提速。

提交 `91a87f7` 时的真实 stdio MCP [默认定义](<../../outputs/requirements-first/on-demand/final-entry-tools.json>)与[同口径 UTF-8 JSON 度量](<../../outputs/requirements-first/on-demand/final-entry-metrics.json>)记录为4118字节、当时27个业务方法完整定义为59369字节；这些是新增材料读取方法和调整默认页大小之前的历史值，不是本轮结果，也不是 token 数或总任务提速比例。按需路径已取得[工作方法格式](<../../outputs/requirements-first/on-demand/final-work-contracts.json>)、[已关闭会话的原研究凭据](<../../outputs/requirements-first/on-demand/study-receipt.json>)、[记忆候选](<../../outputs/requirements-first/on-demand/memory-candidates.json>)和[完整记忆](<../../outputs/requirements-first/on-demand/reviewed-memory.json>)；通过 `execute` [记录上轮已有研究经验](<../../outputs/requirements-first/on-demand/recorded-study-memory.json>)后，按相关任务[再次检索到该经验](<../../outputs/requirements-first/on-demand/source-reuse-candidates.json>)，没有启动 STAR 或为记忆另行验证。只读／写入分类及参数异常分支另有静态复核，不冒充全部故障已实跑。

## 业务方法与资源

下表是可按需取得的业务方法，不是默认工具列表。MCP 将方法名和参数交给上面的稳定入口；JSON CLI 继续使用原业务方法名。会话内操作需要 `session_id`；契约、安装发现、能力查询及工作记忆接口不需要。`timeout` 单位为秒，会话操作默认180，安装发现默认30；客户端超时应更长。超时或断开不证明 STAR 操作已取消。

| 方法 | 主要参数 | 结果与限制 |
|---|---|---|
| `get_contract` | 无 | schema 2 调用流程、默认值、结果位置与恢复约定 |
| `discover_installations` | `star` 或 `search_roots`，可选 `timeout` | 有界探测实际版本，不加载算例、不自动选择 |
| `get_capabilities` | 可选 `release/build` | 目录类型、执行和发现能力；不是当前实例条件 |
| `search_api` | `query`；`installation` 或 `session_id`，可选 `kind/offset/limit` | 官方类／成员索引候选及来源；不搜索正文，不连接 STAR；按[结果预算](<#api-资料的预算与续页>)分页 |
| `read_api` | `java_class`；`installation` 或 `session_id`，可选 `member` 或 `members`、`offset/limit` | 单成员或同类最多32个成员共享读取；`member/members`互斥。保留签名、说明、继承及各选择器覆盖，见[资料使用](<generic-execution.md#按任务取得实际版本的-api-资料>)和[续页规则](<#api-资料的预算与续页>) |
| `search_guide` | `query`；`installation` 或 `session_id`，可选 `language/offset/limit` | 实际安装用户指南标题/摘要检索；不是全文或独立宏库搜索，不连接STAR |
| `read_guide` | `topic`；`installation` 或 `session_id`，可选 `language/offset/limit_chars/link_offset/link_limit/expected_sha256` | 有界正文、代码窗口与链接；代码块完整不代表宏可独立执行，见[指南读取](<generic-execution.md#用户指南宏示例与操作前提>) |
| `find_objects` | `type_id`，可选 `name/parent_id/offset/limit` | `objects[]`；名称精确匹配，子类型使用父对象 ID |
| `browse_tree` | 可选 `object_id/cursor/offset/limit/scope/max_nodes` | `object` 与 `objects[]`；展开树的一层，不读取属性值 |
| `search_settings` | `query`，可选 `expand/max_nodes/max_depth/scope/limit/cursor` | `matches[].object/property` 与覆盖信息；默认仅搜索缓存 |
| `relocate_object` | `locator` | `object.object_id`；新会话重新定位，不继承旧身份 |
| `describe_object` | 可选 `object_id/property_ids/cursor/limit/scope` | `properties[id]` 与 `operations[id]`；省略对象仅表示运行时树根 |
| `read_properties` | `object_id`、非空 `property_ids` | `properties[id]` 的独立状态和值，必须显式选择 |
| `modify_property` | `object_id/property_id/expected/value`，可选 `audit` | `before[id]`、`properties[id]`、`change`、`setter_attempts`；修改内存 |
| `execute_operation` | `object_id/operation_id/expected/arguments`，可选 `audit` | 相同前后属性结果；仅执行已适配的目录结构操作 |
| `list_recipes` | 无 | 网格、求解和导出的现成方法、参数契约及证据；不连接 STAR |
| `execute_recipe` | `request_id/recipe_id`，可选 `parameters/expected_revision/project_dir` | 执行内置方法或已审阅的 `memory:ID`；记忆方法必须匹配修订，不自动绑定历史对象 |
| `execute_macro` | `request_id/steps`，可选 `parameters/object_parameters/imports/declarations/intent/working_directory` | 同会话组合 `code` 与完整源码 `macro` 步骤；原宏、辅助源码和显式 JAR 原样编译；[路径及结果边界](<generic-execution.md#原样复用完整宏与辅助源码>)；完整宏权限，不是代码沙箱 |
| `get_execution` | `request_id` | 原宏凭据、读取诊断、活动状态、可用审阅 token，以及固定材料清单与读取指引；不重做操作 |
| `read_execution_artifact` | `request_id/artifact`，可选 `offset/limit_bytes/tail/expected_version` | 按需读取固定执行材料的字节窗口；区分缺失、变化与正文不完整，见[材料读取](<#按需读取执行材料>)；不启动 STAR、不解除未知结果 |
| `reconcile_execution` | `request_id/expected_review_token/assessment` | 根据已有依据显式接受当前状态；不重放、不保存、不追认旧任务完成，见[接受条件与边界](<generic-execution.md#根据已有观察接受当前状态>) |
| `search_memory` | `query`，可选 `context/limit/offset/project_dir` | 有界候选摘要与 `full_record` 获取指引；检查摘录及 `next_offset`，不返回完整代码与依据列表 |
| `get_memory` | `memory_id`，可选 `project_dir` | 完整做法、场景和证据范围 |
| `record_memory` | `entry`，可选 `project_dir` | 记录实际任务已有依据，不额外验证或执行方法 |
| `update_memory` | `memory_id/expected_revision/changes`，可选 `project_dir` | 乐观并发修订，保留例外与纠正 |
| `inspect_session` | 可选 `timeout` | Inspector 范围快照，不表示全算例导出 |
| `open_session` | `input`、`port+project_dir` 或 `create=true+project_dir` | 优先连接匹配算例；显式 create 从零创建空算例 |
| `session_status` | 无其他必填参数 | 状态、进程身份与未确认请求；不启动 Java 客户端 |
| `save_session` | 可选 `output` | 省略写回，给新路径另存；`output` 为实际绝对路径 |
| `close_session` | 可选 `discard` | 外部会话断开，自有服务检查修改状态后停止 |

资源 `starbridge://contract` 与 `get_contract.result` 同源，`starbridge://catalog/{release}` 与该 release 的能力查询同源。精确 Build 查询使用工具。

## API 资料的预算与续页

`read_api`的`members`是同一类的非空成员选择器数组，最多32项，与`member`互斥。联合页共享类准备和预算，返回`selectors`及`selected_by`，顺序沿官方声明而非输入数组；一个选择器成功不代表整组完整。指南采用正文字符窗口及独立链接分页，不套用本节的成员分页，见[指南读取规则](<generic-execution.md#用户指南宏示例与操作前提>)。

`search_api/read_api` 的成功 `result` 也按上述 JSON 口径限制为32 KiB，`budget.serialized_bytes` 包含计数字段本身。`limit` 默认20、允许1–100；它是条目上限，不保证一页能放下该数量。续页使用返回的 `next_offset`，不要按 `limit` 累加；整类读取还要兼顾下面的类链接游标。搜索按完整候选分页，读取按完整成员或其错误记录推进；`coverage.processed` 包含已经表达的读取错误，因此续页不能用成功成员数自行推算。`page_end_reason` 区分结果结束、条数上限、响应预算及越界起点。

整类读取还有正文引用链接：`next_offset` 对应成员列表，`links_next_offset` 对应类链接列表，两者共用输入 `offset`。两种游标同时非空时指向同一页边界；保持版本选择、类和成员筛选不变，将任一非空游标作为下一次 `offset`。某一列表已结束后，仍须根据另一游标继续。两者都为空只表示没有后续页，不抹去当前页的错误或正文摘录。

签名、版本、来源、继承组及错误不通过静默删除来压缩结果。最低一行连同上下文过大时，只对说明、注记正文、示例或弃用文字作明确摘录；类或各成员的 `content_truncations` 给出字段、原始与返回字符数及完整来源，`coverage.text_excerpted` 汇总正文是否有摘录。新增预算摘录的 `full_text_ref` 是相对当前 `result` 的 JSON Pointer，指向本页 `source` 或成员 `source`，不是外层协议封套；原类注记的 `full_text` 来源仍保留。摘录后的代码不是完整可执行示例。最低资料仍超预算时明确报错，不把它报告成无 API 或无法推进的空页。

分页、来源错误或摘录会体现在 `read_status/coverage` 中，原文未提供说明另看 `description_status`；`coverage.selection_complete` 描述本页是否包含整个候选选择，`coverage.truncated` 只描述对应候选列表后面是否还有条目，类链接另看 `links_coverage`。没有下一页不代表当前页就是完整资料。返回预算不限制索引全扫描与排序、整页 HTML 解析或缓存总内存；`budget.io_globally_bounded=false` 明示这一边界。

## 按需读取执行材料

`get_execution` 的 `artifacts` 列出固定材料的路径和可用状态，可读取项另带字节数与元数据版本；`artifact_reader` 给出读取方法及会话／请求参数。沿用这些参数的原有范围，不把返回的绝对会话位置改成另一个运行根下的短 ID。清单不重复塞入日志正文；已有会话和请求标识时，也可直接选择 `read_execution_artifact`，不必为了取日志重新执行任务。

| `artifact` | 材料 |
|---|---|
| `request` | 原请求快照，包括已冻结的源码与参数 |
| `compiler_log` | 编译日志 |
| `client_log` | 客户端执行日志 |
| `compilation` | 编译元数据原文 |
| `receipt` | 原始执行凭据文本，不代替 `get_execution` 的解析与状态判断 |

该方法不接受任意文件路径，只读取选定请求下的固定普通文件，不启动 STAR、不轮询进程、不接受或清除未知写入。`offset` 是零起始字节位置，不是字符或行号；`limit_bytes` 默认8192、允许4–65536，是单次原始读取上限。成功 `result` 另受32 KiB JSON预算，转义、来源元数据或无效字节材料可能让返回窗口小于读取上限；`io_bytes` 与 `range.bytes` 分别说明实际读入和返回的字节数。

普通前向读取使用 `next_offset` 继续，不自行累加文本字符数。遇到跨窗口的 UTF-8 字符时，未完整的末尾字节留到下一页。无效 UTF-8 或起点落在字符中间时，`encoding.status=replacement` 明示替代解码，`encoding.raw_base64` 保留返回范围的原字节；`range.sha256` 只针对该字节范围。`tail=true` 要求 `offset=0`，从观察到的文件尾部选窗口；预算缩小时仍保留已读窗口的后缀，不自动追踪后续追加。

前页或材料清单的 `version` 可作为 `expected_version` 传回；省略它不保证跨页来自同一版本。它绑定材料位置与文件元数据，不是内容哈希、事务快照或 `reconcile_execution` 的审阅 token。文件可打开但版本不符时返回 `version_mismatch`，不读取正文、不发出续页位置；应重新选择窗口，不能把不同版本直接拼接。读取期间会核对已打开文件及当前逻辑路径的版本，报告 `changed_during_read/current_version`；这不能证明所有并发改写都已被捕获。

检查 `read_status`、`coverage`、`encoding` 和变化诊断，而不只看外层 `ok`。缺失或不可读材料的正文为 `null`，不冒充实际空文件；异常零字节短读不会发出指向自身的空续页。`next_offset=null` 不能替代读取状态或完整性判断，版本不符、异常短读也会不提供续页；`coverage.whole_file` 描述本次是否覆盖整个观察文件，即使完整取得日志或 JSON 原文，也不证明宏的业务目标已经完成。

真实原生 MCP 已读取上轮清点任务的[715字节客户端日志](<../../outputs/requirements-first/artifact-reading/client_log.json>)、[实际空编译日志](<../../outputs/requirements-first/artifact-reading/compiler_log.json>)和[编译元数据](<../../outputs/requirements-first/artifact-reading/compilation.json>)，并取得原请求的[512字节首窗](<../../outputs/requirements-first/artifact-reading/request-head.json>)及[下一窗口](<../../outputs/requirements-first/artifact-reading/request-next.json>)。日志记录的是原任务的入口速度0.04 m/s、迭代5及变体文件存在但未重载，不是此次重新观察的 STAR 状态；这些材料读取没有新增 STAR 操作。当前源码也已在默认运行根配置下，通过绝对路径[查询另一运行根的原会话](<../../outputs/requirements-first/bounded-interface-a2nqrbgm/selected-runtime-execution.json>)，沿返回指引携带清单版本成功[读取同一日志](<../../outputs/requirements-first/bounded-interface-a2nqrbgm/selected-runtime-log.json>)，没有把范围换成当前运行根。原 `get_execution` 大凭据解析及全部业务响应尚无统一结果预算，不从本入口外推。尾窗裁减、UTF-8 跨字符续页及替代解码、并发替换和文件异常分支目前只有实现及静态复核，不冒充已实跑。

## 对象与属性调用

按类型查找的参数示例：

```json
{"session_id":"<returned session_id>","type_id":"region"}
```

从 `result.objects[]` 取得 `object_id`。查找该区域的边界时，使用 `type_id="boundary"`、`parent_id=<区域 ID>`。不知道目录类型时，可以从 `browse_tree` 根层或 `search_settings` 取得对象引用。树展开只接受树来源的引用；目录查找保留自身适配范围，不伪造树关系。

统一描述和读取参数：

```json
{"session_id":"<returned session_id>","object_id":"<returned object_id>"}
```

上面的参数用于 `describe_object`，再从返回的 `properties` 选择实际属性 ID：

```json
{"session_id":"<returned session_id>","object_id":"<returned object_id>","property_ids":["<returned property_id>"]}
```

上面的参数用于 `read_properties`。只消费 `status="ok"` 的 `value`；描述、搜索候选和支持标志不能代替当前值。属性结果中的单位、坐标关联、动态范围和局部错误保留各自含义，不由接口猜测。

修改使用 `modify_property`，将成功读取的完整 `value` 原样放入 `expected`，新值按描述中的 `write_contract.value_schema` 提供。新关联使用 `{"object_id":"<当前返回的 ID>"}`，可来自目录、运行时树或属性关系；具体允许来源与静态／查询格式仍由写入契约决定。通用 Bean selector 当前只接受静态新值，目录已适配的查询另按其契约执行；旧关联的 `expected` 仍保持完整读取结构。标签集合等数组值可直接作为 `value`，不需要外层请求版本或 `action`。

结构操作使用 `execute_operation`：从 `operations[id]` 取得 `state_property`，读取其完整值作为 `expected`；`arguments.method` 选实际可用的 `method_choices.id`。该结构化方法只执行目录对象已适配的操作；其他创建、执行或 Java 调用使用独立的[通用宏入口](<generic-execution.md>)，不混用属性赋值契约。

两种写入成功后均返回前后属性结果、必要关联项以及 `change` 标识；`before_complete` 说明前读完整性，`inspection_complete` 说明回读完整性。目录结果保留 `catalog_id/runtime` 供覆盖统计核对来源。`audit=true` 另附 `snapshot`、`snapshot_diff` 和 `property_diff`，普通赋值不强制比较全部 Inspector 字段。

## 分页、重定位与覆盖

对象查找与描述的 `limit` 默认 100、范围 1–500。`find_objects` 用 `next_offset`，保持类型、名称和父 ID，分页之间没有快照隔离。描述用 `next_cursor`，保持同一 `object_id/scope`；省略属性选择沿用前页。两种来源的描述均沿用同次观察，有效期 300 秒，过期重新描述，实际读写仍重新核对身份。

树展开默认最多观察 2000 个子项；搜索扩展默认最多访问 100 个节点、深度 4。`max_nodes` 上限 10000，搜索深度上限 32。Java 单次发现内部另有 30 秒上限；增加外层 `timeout` 不提高该上限。`scope=all` 可包含库资源，不表示遍历完整或允许写入资源。搜索翻页保持 query/scope 并设 `expand=false`；元数据改变后重新搜索。

跨加载调用 `relocate_object`，原样提供对象返回的 `locator`。目录 locator 含 `source="catalog"` 与完整 `target` 名称路径；树 locator 含 `source="runtime"` 与 `path` 数组。它们只是重定位材料，当前读写仍只接受 `object_id`。歧义和旧引用会被拒绝，不按名称猜测同一实例。

`next_cursor/next_offset` 非空表示尚有页面；分页结束、空搜索或顶层成功均不证明全算例覆盖。详细发现机制见[运行时发现](runtime-discovery.md)。

## 结果和失败恢复

MCP `content` 中只返回一份 Core JSON 文本，不重复提供 `structuredContent`。成功封套为 `{status:"ok",result:...}`；错误包含 `error`、可用会话状态及 `recovery`。协议错误不保证经过 Core 封套。API 资料或材料窗口的 `result.read_status=partial` 可以同时对应外层 `status=ok`，它与原宏的 `execution.status` 不是同一层状态。

| 状态 | 含义与后续动作 |
|---|---|
| `ok` | 调用完成，继续检查逐项错误与完整性 |
| `rejected` | 输入不合法或执行器确认写入前拒绝；重新读取或纠正输入 |
| `busy` | 请求仍在执行，查询状态并等待，不重复提交 |
| `uncertain` | 写入结果未确认；允许状态与只读核对，不自动重试、回滚或保存 |
| `error` | 其他执行或生命周期错误，结合状态和诊断判断 |
| `partial` | 通用宏有已完成步骤和失败／未知步骤；保留未开始项，不重复执行整组任务 |

会话一次只接受一个 Bridge 请求；状态查询可同时读取记录。只读成功不会解除既有 `uncertain_request`。结构化修改不保存；通用 Java 及 STAR 既有自动保存可能写文件，现成网格／求解方法会先检查。`save_session` 返回实际 `output` 和保存时的 `session_metadata`，不再附带全量 Inspector 快照；需要审查时单独 `inspect_session`。需要持久化验收时重新加载、定位和读取。保存后仍可能 `modified=true`，不能为关闭而擅自丢弃状态。

## 迁移与兼容边界

当前 MCP 默认列表改为三个稳定入口。原业务工具仍注册，原始 MCP `tools/call` 可以按旧名字调用，但客户端可能拒绝显示隐藏工具，或为隐藏名字额外请求工具列表；新接入应使用 `query/execute`，不依赖这种兼容方式。JSON CLI 的业务方法名和调用封套不变，结构化对象契约仍为 schema 2。`search_memory` 响应另有明确迁移：`candidates[].memory` 改为摘要、真实 ID／修订及 `full_record` 获取参数，完整材料通过 `get_memory` 取得；输入新增可选 `offset`，存储与完整读取格式未变。

此前的对象接口迁移将契约从 1 升至 2。移除 `describe_node`、`read_node_properties`、`modify_node_property`、`relocate_node` 和公开 `modify(request)`；旧参数 `node_id/target/properties/parent` 不再接受，分别使用统一对象、属性选择和父对象 ID。程序与 Skill 应一起更新。

旧 Runner 的 `set-scalar`、schema 1 修改及其 Inspector 结果投影已删除。对应的常量、表达式和标签能力均通过已有目录属性执行，迁移对应表见[旧修改入口迁移](modifier.md)。Inspector 快照继续作为按需审查结果保留。

独立文件 Runner 保留加载、另存、重载核对流程；它与会话 Runner 的底层目录请求仍使用内部 schema 1 读取、schema 2 属性修改及 schema 3 结构操作，用于开发与文件工作流，不再作为另一套 MCP 方法发布。

## 同源 JSON CLI

```bash
python3 starbridge.py contract
python3 starbridge.py read_properties --arguments /absolute/read-arguments.json
```

参数文件直接装工具参数对象，不加 `arguments` 外层。stdout 是 Core 封套，成功退出码 0，其他状态 1。旧方法和参数会被拒绝。

## 验证范围

历史运行材料见[MCP 验证记录](../evidence/mcp.md)。当前接口迁移和会话改造的验证范围、已有检查限制统一见[会话验证边界](bridge-session.md#验证边界)；历史三端安装结果不自动覆盖 schema 2 的完整算例工作流。
