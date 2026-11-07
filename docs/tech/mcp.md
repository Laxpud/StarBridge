# MCP 与共享 Core API

[项目入口](../README.cn.md) · [技术文档](index.md) · [当前架构](architecture.md)

MCP 和 JSON CLI 共用 Core Service。正常任务以实际版本的 Java API／宏为主：按需取得资料和可靠代码，在同一已加载会话组织读取、判断、修改与回读，再检查逐步凭据和实际结果。结构化对象接口是可选辅助；它们使用契约 schema 2 的 `object_id` 与 `property_id`，结构操作有独立入口，不作为普通属性赋值。

版本仍由实际安装决定：目录支持 2602 Build `21.02.007` 和 2510 Build `20.06.007`，运行时发现仅登记前者。结构化接口仍有值类型和操作范围；新增的 `execute_macro` 可在同一会话使用完整 Java 宏 API，记忆接口帮助复用方法。具体契约与实际证据见[通用执行与工作记忆](<generic-execution.md>)；实现与真实 STAR 验证的区别见[验证边界](bridge-session.md#验证边界)。

## 安装与连接

三端使用[插件安装入口](../distribution.md#三端插件安装)，源码与通用 stdio 接入见[独立安装说明](../distribution.md#源码与通用接入)。stdout 仅承载协议消息；算例与输出路径均指 MCP 进程所在机器的绝对路径。

首次需要了解参数时调用 `get_contract` 或读取 `starbridge://contract`，无需先读文档或 Skill。已有有效会话、对象引用、资料和代码可以复用。初始化只提供简短能力说明；当前仍一次发布全部工具、返回完整契约，尚未实现按主题展开操作入口，不能将资料按需读取当成该要求已完成。`usage.workflow.task` 描述正常宏任务路径，`structured_read/structured_write` 只描述可选结构化流程。`usage.defaults` 来自 Core 方法签名；默认值是省略参数时的行为，可按任务覆盖。

安装未知时用 `discover_installations` 探测实际程序；用户已指定程序时可直接交给 `open_session`。`get_capabilities()` 的 `supported`、`catalog_supported` 和 `supported_versions` 只描述结构化目录，不能证明本机安装；通用生命周期与宏另见 `session_lifecycle`、`generic_execution`，发现另查 `runtime_discovery.supported`。顶层 `ok` 仅表示查询完成，不表示未知版本已经验证。

`open_session` 从所选程序检测版本，并核对可选的 `release/build` 预期；无法检测或不匹配时在加载前拒绝，不自动换安装。未登记版本可尝试独立通用路径，但须先用所选安装内 JDK／库编译最小生命周期模板，再核对实际 server 版本与加载对象；不借用邻近目录或系统 JDK。返回 `star_version`、`version_source`、编译凭据以及可为 `null` 的 `catalog_target`，不把成功接入推广成全部 API 已验证。需要运行时规则时，还要求已有精确适配与本机 Javadoc。接入、保存与关闭语义见[会话说明](<bridge-session.md>)。

## 工具与资源

工具前缀为 `starbridge.`，下表省略前缀。会话内操作需要 `session_id`；契约、安装发现、能力查询及工作记忆接口不需要。`timeout` 单位为秒，会话操作默认 180，安装发现默认 30；客户端超时应更长。超时或断开不证明 STAR 操作已取消。

| 工具 | 主要参数 | 结果与限制 |
|---|---|---|
| `get_contract` | 无 | schema 2 调用流程、默认值、结果位置与恢复约定 |
| `discover_installations` | `star` 或 `search_roots`，可选 `timeout` | 有界探测实际版本，不加载算例、不自动选择 |
| `get_capabilities` | 可选 `release/build` | 目录类型、执行和发现能力；不是当前实例条件 |
| `search_api` | `query`；`installation` 或 `session_id`，可选 `kind/offset/limit` | 官方类／成员索引候选及来源；不搜索正文，不连接 STAR |
| `read_api` | `java_class`；`installation` 或 `session_id`，可选 `member/offset/limit` | 签名、说明、文中代码及真实继承声明；检查 `read_status/coverage/next_offset`，见[资料使用](<generic-execution.md#按任务取得实际版本的-api-资料>) |
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
| `get_execution` | `request_id` | 原宏凭据、读取诊断、活动状态及可用的审阅 token；不重做操作 |
| `reconcile_execution` | `request_id/expected_review_token/assessment` | 根据已有依据显式接受当前状态；不重放、不保存、不追认旧任务完成，见[接受条件与边界](<generic-execution.md#根据已有观察接受当前状态>) |
| `search_memory` | `query`，可选 `context/limit/project_dir` | 返回需审查适用条件的经验与资料候选 |
| `get_memory` | `memory_id`，可选 `project_dir` | 完整做法、场景和证据范围 |
| `record_memory` | `entry`，可选 `project_dir` | 记录实际任务已有依据，不额外验证或执行方法 |
| `update_memory` | `memory_id/expected_revision/changes`，可选 `project_dir` | 乐观并发修订，保留例外与纠正 |
| `inspect_session` | 可选 `timeout` | Inspector 范围快照，不表示全算例导出 |
| `open_session` | `input`、`port+project_dir` 或 `create=true+project_dir` | 优先连接匹配算例；显式 create 从零创建空算例 |
| `session_status` | 无其他必填参数 | 状态、进程身份与未确认请求；不启动 Java 客户端 |
| `save_session` | 可选 `output` | 省略写回，给新路径另存；`output` 为实际绝对路径 |
| `close_session` | 可选 `discard` | 外部会话断开，自有服务检查修改状态后停止 |

资源 `starbridge://contract` 与 `get_contract.result` 同源，`starbridge://catalog/{release}` 与该 release 的能力查询同源。精确 Build 查询使用工具。

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

`limit` 默认 100、范围 1–500。`find_objects` 用 `next_offset`，保持类型、名称和父 ID，分页之间没有快照隔离。描述用 `next_cursor`，保持同一 `object_id/scope`；省略属性选择沿用前页。两种来源的描述均沿用同次观察，有效期 300 秒，过期重新描述，实际读写仍重新核对身份。

树展开默认最多观察 2000 个子项；搜索扩展默认最多访问 100 个节点、深度 4。`max_nodes` 上限 10000，搜索深度上限 32。Java 单次发现内部另有 30 秒上限；增加外层 `timeout` 不提高该上限。`scope=all` 可包含库资源，不表示遍历完整或允许写入资源。搜索翻页保持 query/scope 并设 `expand=false`；元数据改变后重新搜索。

跨加载调用 `relocate_object`，原样提供对象返回的 `locator`。目录 locator 含 `source="catalog"` 与完整 `target` 名称路径；树 locator 含 `source="runtime"` 与 `path` 数组。它们只是重定位材料，当前读写仍只接受 `object_id`。歧义和旧引用会被拒绝，不按名称猜测同一实例。

`next_cursor/next_offset` 非空表示尚有页面；分页结束、空搜索或顶层成功均不证明全算例覆盖。详细发现机制见[运行时发现](runtime-discovery.md)。

## 结果和失败恢复

MCP `content` 中只返回一份 Core JSON 文本，不重复提供 `structuredContent`。成功封套为 `{status:"ok",result:...}`；错误包含 `error`、可用会话状态及 `recovery`。协议错误不保证经过 Core 封套。

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

这是破坏性接口迁移，契约从 1 升至 2。移除 `describe_node`、`read_node_properties`、`modify_node_property`、`relocate_node` 和公开 `modify(request)`；旧参数 `node_id/target/properties/parent` 不再接受，分别使用统一对象、属性选择和父对象 ID。程序与 Skill 应一起更新。

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
