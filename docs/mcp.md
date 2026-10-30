# MCP 与共享 Core API

[返回项目入口](README.cn.md)

StarBridge 提供本机 stdio MCP 接口。Agent 可以查询版本目录、查找对象、描述与读取属性、提交单项修改，以及显式打开、保存和关闭后台会话。所有工具调用 [Core Service](../core/service.py)，与新的 JSON CLI 使用相同参数和结果；已有文件和会话 CLI 继续保留，并复用相同目录、类型适配器与 Bridge 执行器。

当前支持 Linux 管理会话和随附的精确版本目录：2602 Build `21.02.007`、2510 Build `20.06.007`。两版的实际适配范围见[版本说明](catalog-versions.md)。新增运行时发现仅支持 2602 Build `21.02.007`，与既有目录能力分开计量，见[发现契约](runtime-discovery.md)。网格生成、求解执行、GUI 接入和持久化工作记忆尚未提供工具；后续发现与写入扩展见[路线图](roadmap.md#后续里程碑)，覆盖缺口及版本核验见[覆盖范围与版本验证](roadmap.md#覆盖范围与版本验证)。

## 安装与连接

Core 和既有 CLI 只使用 Python 标准库。MCP 额外使用[官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)，本次固定为 `mcp==2.3.0`。在仓库根目录创建独立环境：

```bash
python3 -m venv .venv-mcp
.venv-mcp/bin/python -m pip install -r interfaces/requirements.txt
```

在 MCP 客户端配置一个 stdio 服务，填写以下两个字段，将 `/absolute/StarBridge` 替换为实际仓库路径：

```json
{
  "command": "/absolute/StarBridge/.venv-mcp/bin/python",
  "args": ["/absolute/StarBridge/interfaces/mcp_server.py"]
}
```

客户端外层配置格式依其实现而定。无需启动 HTTP 服务。stdout 仅传输协议消息，STAR 输出留在会话请求目录；这是 [MCP stdio 传输约定](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#stdio)。工具运行权限与启动它的本机进程相同，路径必须是绝对路径，STAR 安装与许可证沿用本机配置。

MCP 客户端的请求超时应大于工具的 `timeout`，并为服务启动、宏编译和清理留出余量。`timeout` 单位为秒，默认 `180`。客户端取消、断开或超时不证明 STAR 操作已撤销；重新连接后先查询状态，不能自动重发修改。

## 工具与资源

工具名统一使用 `starbridge.` 前缀。下面表格省略此前缀。除目录能力查询外，算例调用都明确指定 `session_dir`；未知顶层参数和不符合 JSON Schema 的类型在调用 Core 前拒绝。

| 工具 | 主要参数 | 结果与约束 |
|---|---|---|
| `get_capabilities` | `release` | 离线目录类型、属性、操作、读写实现及覆盖限制；不检查当前实例或可写条件 |
| `find_objects` | `session_dir`、`type_id`，可选 `name`、`parent`、`offset`、`limit` | 按目录定位管线枚举实例；`name` 为精确匹配，子对象必须提供完整父路径 |
| `describe_object` | `session_dir`、`target`，可选 `properties` | 属性与结构操作描述，以及已声明目标条件的实际结果 |
| `read_properties` | `session_dir`、`target`，可选 `properties` | 逐属性值和错误；省略属性列表表示该类型全部已映射属性 |
| `modify` | `session_dir`、`request` | 原样使用 schema 2 属性修改或 schema 3 结构操作契约；必须提供实际读取的 `expected` |
| `browse_tree` | `session_dir`，可选 `node_id`、`cursor`、`offset`、`limit`、`scope`、`max_nodes` | 展开真实对象的一层；不读取属性值，分页游标绑定列表指纹 |
| `describe_node` | `session_dir`，可选 `node_id`、`scope`、`property_ids`、`cursor`、`limit` | 描述真实 Bean 属性及规则支持；支持属性选择和指纹绑定分页 |
| `read_node_properties` | `session_dir`、`node_id`、非空 `property_ids` | 刷新身份和描述符后读取显式选择的属性；局部错误独立返回 |
| `search_settings` | `session_dir`、`query`，可选 `expand`、`max_nodes`、`max_depth`、`scope`、`limit`、`cursor` | 默认搜索已发现元数据；扩展必须显式给出，返回覆盖与截断 |
| `relocate_node` | `session_dir`、`locator` | 按完整名称/类型路径重建新会话引用；不继承旧对象身份 |
| `modify_node_property` | `session_dir`、`node_id`、`property_id`、`expected`、`value` | 已接入契约，当前发现写入开关关闭，调用明确拒绝 |
| `inspect_session` | `session_dir` | 既有 Inspector 快照范围；不是全部算例设置导出 |
| `open_session` | `input`、`session_dir`，可选 `star`、`release`、`port`、`timeout` | 从输入复制工作文件后启动独立后台服务；目录必须不存在，默认端口 `49001` |
| `session_status` | `session_dir` | 会话记录及进程身份检查；不启动 Java 客户端，不重新核对 server Build |
| `save_session` | `session_dir`、`output` | 另存到尚不存在且父目录已存在的 `.sim` 文件；不覆盖原输入 |
| `close_session` | `session_dir`，可选 `discard` | 默认检查修改标志；仅显式 `discard: true` 才放弃剩余内存状态 |

`open_session` 的 `star` 默认 `starccm+`，`release` 默认 `2602`。选择 2510 时同时提供对应安装的可执行程序，后续调用使用会话保存的 release/Build 绑定。客户端退出不会关闭后台服务，关闭必须明确调用 `close_session`。

资源提供相同契约与离线能力，不扫描磁盘上的其他会话：

| URI | 内容 |
|---|---|
| `starbridge://contract` | Core 方法、状态封套、路径及恢复约定 |
| `starbridge://catalog/2602` | 2602 能力，与 `get_capabilities` 同源 |
| `starbridge://catalog/2510` | 2510 能力，与 `get_capabilities` 同源 |

版本资源以 `starbridge://catalog/{release}` 模板发布，未知版本明确失败。离线结果中的 `runtime_state: not_checked` 和缺失实测证据不可解读为当前算例读写成功或失败。

## 从实际对象树发现设置

发现入口使用 `node_id` 与 `property_ids`，不要求先知道人工目录的 `type_id`。顺序为 `browse_tree` → 选择返回节点 → `describe_node` → `read_node_properties`；也可先调用 `search_settings`，确认命中的路径上下文后再描述和读取。参数示例、结果 schema、缓存及重定位方式见[运行时发现说明](runtime-discovery.md)。

```json
{"session_dir": "/absolute/new-session", "limit": 100}
```

把上述参数交给 `starbridge.browse_tree` 即可读取根层。浏览默认一页 100 项、最多观察 2000 个子项；搜索默认 `expand=false`，显式扩展默认最多访问 100 个节点、深度 4，结果一页 100 项。两者 `limit` 上限 500，`max_nodes` 上限 10000；搜索深度上限 32。所有默认 `timeout` 为 180 秒。`scope` 默认为 `simulation`，`all` 可纳入材料数据库资源。

描述能力与读取当前值是分开的；`read_node_properties` 不接受省略属性列表来读取全部属性。搜索命中是带观察时间的缓存候选，必须重新描述或读取以核对当前身份。未知代理不返回可用 `node_id`。`modify_node_property` 当前总开关 `WRITING_ENABLED=False`，新写入须启用并完成真实验收后才开放；既有目录 `modify` 继续遵循下面的原契约。

## 查找、读取与修改

先查询明确版本的能力，再打开会话。以下为工具参数示例；路径与对象名需要替换为实际值：

```json
{
  "input": "/absolute/case.sim",
  "session_dir": "/absolute/new-session",
  "star": "/absolute/STAR-CCM+/star/bin/starccm+",
  "release": "2602"
}
```

调用 `find_objects` 时可先枚举根类型，例如：

```json
{"session_dir": "/absolute/new-session", "type_id": "region", "limit": 100}
```

查找结果位于 `result.catalog`，包含 `objects`、`total`、`offset` 和 `next_offset`。每页默认 100 项，最多 500 项；非空 `next_offset` 表示还有下一页。分页按名称和会话 key 排序，但不同请求之间没有快照隔离，其他客户端的修改可能改变分页结果。

每项对象返回 `type`、`name`、`java_class`、`locator`、`reference` 和 `locator_unique`。读取或修改的 `target` 可由 `locator` 加上 `reference` 组成。子类型继续把父对象目标放入 `parent`；例如查找边界时指定 `type_id: boundary` 和已查得的区域作为 `parent`。同名歧义以 `locator_unique: false` 显示，后续唯一定位仍会拒绝，不会任意选择一个对象。

`read_properties` 返回的属性值可直接用作 `expected`。以下 Python 片段说明单个标量常量修改请求的组成，`read_result` 为先前工具的 Core 封套：

```python
catalog = read_result["result"]["catalog"]
target = dict(catalog["target"]["locator"], reference=catalog["target"]["reference"])
quantity = catalog["properties"]["quantity_value"]["value"]
request = {
    "schema_version": 2,
    "action": "modify",
    "target": target,
    "property": "quantity_value",
    "expected": quantity,
    "value": {"value": 12.5, "unit": quantity["unit"]},
}
```

将该 `request` 和 `session_dir` 传给 `modify`。其他值类型、单位、查询规则、对象引用和结构操作的精确契约见[目录修改](catalog-modifier.md)。`describe_object` 的 `writable` 仅表示写入实现；最终条件、旧值和关联身份仍在修改准备阶段及 setter 前检查。

成功修改只更新内存，并返回回读结果、目录 Diff 与已有快照 Diff。随后明确 `save_session`；保存不包含独立重载验收。如需确认持久化，用新会话重新打开输出并读取，或使用[文件修改入口](catalog-modifier.md)。新会话不能复用旧 `reference`，应通过完整 `locator` 重新查找。STAR 保存后仍可能报告 `modified: true`，关闭时仍需显式决定是否放弃剩余内存状态。

## 结果和失败恢复

Core 封套位于 MCP 的 `structuredContent`，同样的 JSON 也放在文本内容中。工具错误设置 `isError: true`。

| `status` | 含义 | 下一步 |
|---|---|---|
| `ok` | 调用完成 | 继续核对 `inspection_complete`、逐属性错误和回读值 |
| `rejected` | 输入不合法，或执行器确认写入前拒绝 | 根据错误重新读取或修正请求；不把拒绝当作已修改 |
| `uncertain` | 本次执行结果未确认，或之前的请求仍有未解决结果，可能已写入 | 查询状态与请求日志，不自动重试；必要时显式放弃并重新打开 |
| `error` | 其他执行、文件或生命周期错误 | 结合错误和会话状态判断；例如未保存状态导致默认关闭失败 |

未知 MCP 方法或资源、协议结构错误可能由 SDK 直接返回协议错误，不保证包含 Core 封套。属性局部错误保留在成功封套中，通过 `inspection_complete: false` 和逐属性 `status: error` 表示。

会话一次只接受一个 Bridge 请求。未取得会话锁的忙碌请求在执行前返回 `rejected`，不把另一请求的活动标记当成本次未知写入。已停止或结果不确定的会话不会静默启动另一操作。`session_status` 也使用同一把锁，忙碌时可能被拒绝；这不授权自动重试修改。后台会话和请求目录中的 `session.json`、`result.json`、命令及日志是恢复依据。

## 同源 JSON CLI

从仓库根目录运行，方法名与 MCP 去掉 `starbridge.` 前缀后的名称相同：

```bash
python3 starbridge.py contract
python3 starbridge.py get_capabilities --arguments /absolute/capabilities.json
python3 starbridge.py read_properties --arguments /absolute/read-arguments.json
```

`capabilities.json` 的内容例如 `{"release": "2602"}`。参数文件直接装工具参数对象，不添加额外 `arguments` 外层。stdout 为一个 Core JSON 封套；`ok` 返回退出码 0，其他状态返回 1。参数解析错误仍由 CLI 显示用法并退出。原有 `bridge/runner/file_bridge.py`、`session_bridge.py` 的命令及结果形式保持可用。

## 验证范围

以下记录是既有目录与生命周期入口的验收，不能推广为新增发现接口的全量验收。发现实现与已知限制见[专门说明](runtime-discovery.md)，完成情况以当前任务的实际验证记录为准。

已用官方 SDK 的独立 stdio 客户端核对工具发现、资源读取、两个版本的离线能力及未知版本拒绝。2602 真实工作副本已完成分页、精确名称与空结果、单对象管理器和父上下文查找、描述与读取、标量修改、过时旧值及跨会话引用拒绝、另存和显式关闭；客户端退出后重新连接仍可使用原后台会话。

2602 另存文件在新 MCP 会话中独立重载后，完整既有快照和所选目录属性均匹配，原输入摘要未变。一次受控的短客户端超时返回 `uncertain`，后续读操作被拒绝且没有新请求落盘，显式放弃关闭可完成清理。该检查验证保守恢复行为，不证明超时能撤销已执行的 setter。

2510 已通过 `initialize` 握手路径下的工具与资源发现、会话打开、对象查找、描述、读取、标量修改、过时请求拒绝、快照、另存和关闭。MCP 保存的文件再由原文件 CLI 独立加载，所选目录属性一致，输入摘要未变。JSON CLI 与 MCP 目录资源的能力结果一致。参数验收包含未知字段、错误基础类型和把对象误传为 JSON 字符串的拒绝。

该验收只说明这些代表性调用通过，不扩展[目录修改验证](catalog-modifier.md#验证范围与迁移边界)中的类型和分支覆盖，也不验证 CFD 物理合理性。HTTP 传输、远程多用户服务和 GUI 共享会话不在当前实现范围内。
