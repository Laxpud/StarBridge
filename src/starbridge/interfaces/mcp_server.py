#!/usr/bin/env python3
"""通过官方 Python SDK 提供本机 stdio MCP，所有业务调用交给共享 Core。

stdout 仅用于 MCP 消息；STAR 的输出由原执行器写入请求日志。工具是同步函数，
SDK 在线程中执行，避免长时间 STAR 调用阻塞协议循环；同一会话仍由文件锁互斥。
"""

import json

from mcp import types
from mcp.server import MCPServer
from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr
from jsonschema import Draft202012Validator

from starbridge import __version__
from starbridge.core.service import Service, contract
from starbridge.core.interface_contract import SERVER_INSTRUCTIONS, tool_input_schema, recovery_guidance


def tool_result(result):
    """所有 Core 与输入校验结果使用相同封套，兼容只支持文本结果的客户端。"""
    return types.CallToolResult(
        content=[types.TextContent(text=json.dumps(result, ensure_ascii=False, allow_nan=False))],
        structured_content=result, is_error=result['status'] != 'ok')


async def validate_arguments(context, call_next):
    """先按公开 JSON Schema 检查原始参数，防止 SDK 丢弃未知字段或将字符串隐式转成对象。"""
    if context.method == 'tools/call' and isinstance(context.params, dict):
        params = context.params
        for tool in await server.list_tools():
            if tool.name == params.get('name'):
                schema = tool_input_schema(tool.name.removeprefix('starbridge.'), tool.input_schema)
                error = next(Draft202012Validator(schema).iter_errors(params.get('arguments', {})), None)
                if error is not None:
                    # 修改请求按显式版本选择错误分支，避免把 schema 2 的字段缺失误报为“需要 schema 3”。
                    if error.validator == 'oneOf' and isinstance(error.instance, dict):
                        version = error.instance.get('schema_version')
                        for index, branch in enumerate(error.validator_value):
                            if branch.get('properties', {}).get('schema_version', {}).get('const') == version:
                                error = next((child for child in error.context
                                              if child.schema_path[0] == index), error)
                                break
                    return tool_result({'status': 'rejected', 'error': {
                        'type': 'ArgumentValidationError', 'message': error.message,
                        'argument_path': list(error.absolute_path)},
                        'recovery': recovery_guidance('rejected')})
                break
    result = await call_next(context)
    if context.method == 'tools/list' and isinstance(result, types.ListToolsResult):
        # 发布的格式与执行前检查同源；动态实例条件仍由 Core 验证。
        for tool in result.tools:
            tool.input_schema = tool_input_schema(tool.name.removeprefix('starbridge.'), tool.input_schema)
    elif context.method == 'tools/list' and isinstance(result, dict):
        # SDK 的协商版本也可能在中间件返回前已转成协议字典。
        for tool in result.get('tools', []):
            tool['inputSchema'] = tool_input_schema(tool['name'].removeprefix('starbridge.'), tool['inputSchema'])
    return result


server = MCPServer(
    'StarBridge', version=__version__,
    middleware=[validate_arguments],
    instructions=SERVER_INSTRUCTIONS,
)
service = Service()
READ = types.ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
WRITE = types.ToolAnnotations(read_only_hint=False, destructive_hint=True,
                              idempotent_hint=False, open_world_hint=False)


def call(method, arguments):
    """将 Core 状态同时放入结构化和文本结果，失败时设置 MCP 的 isError。"""
    result = service.call(method, arguments)
    return tool_result(result)


@server.tool(name='starbridge.get_contract', annotations=READ)
def get_contract() -> types.CallToolResult:
    """按需获取当前服务的完整调用契约；无需会话，不启动 STAR，也不是每次调用的前置步骤。

    result.usage 包含发现/目录两种流程、嵌套 target/request schema、结果字段位置、
    分页、保存重载及失败恢复规则；defaults 与 contract_scope 区分可覆盖默认值、当前上限和能力范围。
    与 starbridge://contract 资源内容相同，供只支持工具
    调用的客户端使用；属性的新值格式由 describe_node/describe_object 的 write_contract 提供。
    """
    return call('get_contract', {})


@server.tool(name='starbridge.get_capabilities', annotations=READ)
def get_capabilities(release: StrictStr | None = None, build: StrictStr | None = None) -> types.CallToolResult:
    """查询当前注册的离线能力；版本取自用户指定安装或 discover_installations，不选择固定默认版本。

    不传版本只列 supported_versions，不表示本机安装。给实际 release/Build 后检查 result.supported，
    未适配返回 supported=false 及原因，不冒用邻近版本；顶层 ok 只表示能力查询完成。
    仅给 release 时返回该 release 的登记 Build，不能据此认定实际安装匹配。
    types 给出目录类型和 parent_type；runtime_discovery.supported 决定是否可用发现入口。
    runtime_state=not_checked；读写实现、发现元数据和实测覆盖不可等同于当前实例可用。
    需要新会话时再 open_session，已有可用会话可直接沿用；完整调用格式可用 get_contract 取得。
    """
    return call('get_capabilities', locals())


@server.tool(name='starbridge.discover_installations', annotations=READ)
def discover_installations(star: StrictStr | None = None, search_roots: list[StrictStr] | None = None,
                           timeout: StrictFloat = 30) -> types.CallToolResult:
    """从用户指定启动器或有界本机环境取得实际 STAR release/Build，不加载算例。

    给 star 时只执行该程序的 -version；否则检查 PATH 的 starccm+ 与安装根目录，
    默认根为 /opt/Siemens 和 /opt/siemens，可用 search_roots 替换，空数组表示只查 PATH。
    当前实现最多探测 20 个不同调用路径；这些路径和预算不是用户安装位置或数量的限制。
    result.installations[] 含 executable、实际 version、适配标志、Javadoc 路径及探测错误。
    未适配版本也原样报告；没有命中或预算截断不表示整机未安装。安装支持不证明许可证可用。
    按用户任务选择程序，再 get_capabilities(release,build)；多个版本无法确定时询问用户，不自动换版本。
    """
    return call('discover_installations', locals())


@server.tool(name='starbridge.find_objects', annotations=READ)
def find_objects(session_id: StrictStr, type_id: StrictStr, name: StrictStr | None = None,
                 parent: dict | None = None, offset: StrictInt = 0, limit: StrictInt = 100,
                 timeout: StrictFloat = 180) -> types.CallToolResult:
    """按已适配目录类型枚举当前实例；未知对象类型在发现能力可用时先沿对象树导航。

    从 get_capabilities 选择 type_id；子类型必须传完整 parent，name 为精确匹配。
    result.catalog.objects[] 返回 locator/reference/locator_unique；将 locator 加上 reference
    作为后续 target。非空 catalog.next_offset 继续翻页；名称歧义不得任取一项。
    需要属性契约时 describe_object，需要当前值时 read_properties；可复用有效描述，列表不提供当前属性值。
    """
    return call('find_objects', locals())


@server.tool(name='starbridge.describe_object', annotations=READ)
def describe_object(session_id: StrictStr, target: dict, properties: list[StrictStr] | None = None,
                    timeout: StrictFloat = 180) -> types.CallToolResult:
    """描述已定位目录对象的属性、写入格式和结构操作；不读取全部当前值。

    result.catalog.properties[id].write_contract 提供新值 schema 和约束；adapter 是读取格式，
    不可据它猜测写入格式。检查 target_condition_status、guard_checks 和 inspection_complete；
    writable 只代表实现。operations[id] 含 state_property、method_choices 及影响范围。
    需要当前值时 read_properties：属性修改取该属性 value；结构操作取 state_property 的完整 value。
    """
    return call('describe_object', locals())


@server.tool(name='starbridge.read_properties', annotations=READ)
def read_properties(session_id: StrictStr, target: dict, properties: list[StrictStr] | None = None,
                    timeout: StrictFloat = 180) -> types.CallToolResult:
    """读取目录属性的当前值；properties 省略表示该类型全部已映射属性，不代表全算例。

    result.catalog.properties[id] 为 {status,value} 或错误；只有 status=ok 才消费 value，
    同时检查 catalog.inspection_complete。修改前把该完整 value 原样作为 expected，
    不含 status 外壳，也不删除单位、定义或关联字段。新值格式从 describe_object 取得。
    """
    return call('read_properties', locals())


@server.tool(name='starbridge.modify', annotations=WRITE)
def modify(session_id: StrictStr, request: dict, timeout: StrictFloat = 180) -> types.CallToolResult:
    """修改一个已描述的目录属性或执行一个已发布的结构操作，只改变内存。

    属性 request={schema_version:2,action:'modify',target,property,expected,value}；
    结构操作 request={schema_version:3,action:'modify',target,operation,expected,arguments:{method}}。
    expected 取当前读取 value；属性 value 遵循 write_contract，method 取可用 method_choices.id。
    result.catalog 是回读，catalog_diff/snapshot_diff 为核验差异；成功后按任务显式 save_session。
    uncertain 时停止并查询 session_status，不重试、不回滚、不保存。详细格式见 get_contract。
    """
    return call('modify', locals())


@server.tool(name='starbridge.inspect_session', annotations=READ)
def inspect_session(session_id: StrictStr, timeout: StrictFloat = 180) -> types.CallToolResult:
    """获取已有 Inspector 布局的概览，result.snapshot 含参数、场函数、区域、边界等。

    快照仅覆盖已有布局，缺少字段不表示 STAR 没有此设置，也不是完整依赖检查。
    需要快照外的值或写入契约时按需通过发现或目录接口定位、描述和读取目标；request_result 指向请求记录。
    """
    return call('inspect_session', locals())


@server.tool(name='starbridge.browse_tree', annotations=READ)
def browse_tree(session_id: StrictStr, node_id: StrictStr | None = None,
                cursor: StrictStr | None = None, offset: StrictInt = 0, limit: StrictInt = 100,
                scope: StrictStr = 'simulation', max_nodes: StrictInt = 2000,
                timeout: StrictFloat = 180) -> types.CallToolResult:
    """发现能力可用时，展开根或 node_id 的一层实际对象，不隐式读取属性或扫描全树。

    result.children[] 的 node_id 可用于继续浏览或 describe_node；kind=proxy 且 node_id=null
    的项不可当作可调用节点。检查 state/errors/truncations；next_cursor 非空时传回并保持 scope。
    complete 仅指本次层级观察，未展开不表示没有子对象。保存 locator 供新会话重定位。
    limit、max_nodes、scope 和 timeout 可按任务调整；当前允许范围见参数 schema。
    """
    return call('browse_tree', locals())


@server.tool(name='starbridge.describe_node', annotations=READ)
def describe_node(session_id: StrictStr, node_id: StrictStr | None = None,
                  scope: StrictStr = 'simulation', timeout: StrictFloat = 180,
                  property_ids: list[StrictStr] | None = None, cursor: StrictStr | None = None,
                  limit: StrictInt = 100) -> types.CallToolResult:
    """发现能力可用时，描述实际节点属性和已接受的写入格式，不返回全部当前属性值。

    result.properties[] 含 property_id、名称/说明、read_support、write_enabled、write_contract。
    可读候选仍须 read_node_properties 核验；write_enabled 不代表实例或新值条件已通过。
    property_ids 省略描述全部已观察属性；next_cursor 翻页保持 node_id/scope，可省略选择以沿用。
    检查 state/errors/descriptor_next_offset，分页完成不消除底层 partial 状态。
    """
    return call('describe_node', locals())


@server.tool(name='starbridge.read_node_properties', annotations=READ)
def read_node_properties(session_id: StrictStr, node_id: StrictStr, property_ids: list[StrictStr],
                         timeout: StrictFloat = 180) -> types.CallToolResult:
    """发现能力可用时，用返回的节点和属性 ID 读取明确选择的当前值，必须传非空 property_ids。

    result.properties[id] 的 status=ok 才能消费 value；整体检查 inspection_complete/errors。
    relation/range 各有独立 status；range 不支持不表示没有上下限。
    修改时把完整 value 原样用作 expected，新值按 describe_node.write_contract；不推测旧状态。
    """
    return call('read_node_properties', locals())


@server.tool(name='starbridge.search_settings', annotations=READ)
def search_settings(session_id: StrictStr, query: StrictStr, expand: StrictBool = False,
                    max_nodes: StrictInt = 100, max_depth: StrictInt = 4,
                    scope: StrictStr = 'simulation', timeout: StrictFloat = 180,
                    limit: StrictInt = 100, cursor: StrictStr | None = None) -> types.CallToolResult:
    """发现能力可用时，搜索名称、说明、程序标识与中英文术语，返回缓存候选，不返回当前属性值。

    默认 expand=false 只搜已有索引，新会话可能零命中；需要新发现时设 expand=true 并调整预算。
    当前扩展每次从根开始，不保证断点续扫或全树穷尽；扩大预算也须核对覆盖结果。
    result.matches[] 的 node/property 用于 describe_node 和 read_node_properties 重新核验。
    必须检查 coverage 的 errors/truncations/unexpanded_nodes；空命中不能证明全算例不存在目标。
    翻页保持 query/scope 并设 expand=false；缓存变化会使 next_cursor 失效。
    """
    return call('search_settings', locals())


@server.tool(name='starbridge.relocate_node', annotations=READ)
def relocate_node(session_id: StrictStr, locator: list[dict],
                  timeout: StrictFloat = 180) -> types.CallToolResult:
    """发现能力可用时，在保存重载或新会话后，按之前节点的 locator 名称/类型路径重新定位。

    返回 result.node.node_id 作为新引用；检查 state/errors，再 describe_node/read_node_properties。
    locator 是数组，不是目录 target；不携带旧 key/token。同名歧义拒绝，不宣称仍为原 Java 实例。
    """
    return call('relocate_node', locals())


@server.tool(name='starbridge.modify_node_property', annotations=WRITE)
def modify_node_property(session_id: StrictStr, node_id: StrictStr, property_id: StrictStr,
                         expected: dict | StrictStr | StrictBool | StrictInt | StrictFloat,
                         value: dict | StrictStr | StrictBool | StrictInt | StrictFloat,
                         timeout: StrictFloat = 180) -> types.CallToolResult:
    """发现写入能力可用时，按当前描述的 write_contract 修改一个支持的发现属性，只改变内存。

    使用当前有效 describe_node 契约，并从 read_node_properties 取得完整 value 用作 expected。
    常量标量新值如 {value:0.001,unit:'m'}，向量如 {components:[0,0,0.125],unit:'m'}，
    仅在该属性契约允许时适用；不要照抄示例单位或假设任意 setter 都可执行。
    result 含 catalog 回读、catalog_diff、snapshot_diff、snapshot_scope 和 setter_attempts。
    任务要求持久化时另行 save_session；uncertain 时停止并查询 session_status，不重试、不回滚、不保存。
    """
    return call('modify_node_property', locals())


@server.tool(name='starbridge.open_session', annotations=WRITE)
def open_session(input: StrictStr | None = None, star: StrictStr = 'starccm+',
                 release: StrictStr | None = None, port: StrictInt | None = None,
                 timeout: StrictFloat = 180, build: StrictStr | None = None,
                 project_dir: StrictStr | None = None, debug: StrictBool = False) -> types.CallToolResult:
    """优先连接匹配的本机 STAR GUI／服务器，否则直接加载原算例启动自有后台服务。

    input 是算例绝对路径；不指定 input 时必须给已有服务的 port 和 project_dir。
    star 为用户指定或实际探测的安装程序；release/build 是可选预期，未适配版本拒绝连接。
    自动发现限于同用户、同安装且 /proc 可见的本机服务，初始请求核对版本与加载对象。
    多个会话加载相同文件时用 port 选择；未指定 port 且需要启动时自动分配空闲端口。
    返回 session_id，后续原样传回；运行目录由服务管理。项目默认采用算例所在目录。
    不复制算例、不自动保存。debug=true 保留详细请求文件；外部会话关闭时只断开连接。
    """
    return call('open_session', locals())


@server.tool(name='starbridge.session_status', annotations=READ)
def session_status(session_id: StrictStr) -> types.CallToolResult:
    """查询已知 session_id 的记录和当前进程存活情况，不启动 Java 或重新核对 Build。

    result 包含 state、server_alive、active_request、last_request、last_request_status（字段可缺省）。
    用于断开、超时或 uncertain 后排查；ready 不等于上次修改成功，需结合请求结果。
    同会话正在执行时状态查询也可能因锁而拒绝；此工具不会取消、恢复或重试操作。
    """
    return call('session_status', locals())


@server.tool(name='starbridge.save_session', annotations=WRITE)
def save_session(session_id: StrictStr, output: StrictStr | None = None, timeout: StrictFloat = 180) -> types.CallToolResult:
    """按明确保存指令写回当前算例；提供 output 时另存为新的绝对 .sim 路径。

    新路径的父目录必须存在；无保存路径的 GUI 算例必须指定 output。
    result.output 返回实际绝对路径；不自动关闭或重新加载，也不自动生成备份。
    """
    return call('save_session', locals())


@server.tool(name='starbridge.close_session', annotations=WRITE)
def close_session(session_id: StrictStr, discard: StrictBool = False,
                  timeout: StrictFloat = 180) -> types.CallToolResult:
    """外部会话只断开连接；自有后台服务才停止进程，均不隐式保存。

    外部会话返回 state=disconnected，用户 STAR 和内存修改仍保留。
    自有服务默认拒绝丢弃未保存修改；discard=true 只用于已授权放弃内存状态的任务。
    """
    return call('close_session', locals())


@server.resource('starbridge://contract', mime_type='application/json')
def service_contract() -> str:
    """按需读取当前调用流程、默认值、嵌套 schema、返回字段和恢复约定；也可调用 get_contract，无需算例。"""
    return json.dumps(contract(), ensure_ascii=False, allow_nan=False)


@server.resource('starbridge://catalog/{release}', mime_type='application/json')
def catalog_capabilities(release: str) -> str:
    """读取版本目录能力；与 get_capabilities 同源，未适配版本返回 supported=false，目录损坏报错。"""
    return json.dumps(service.get_capabilities(release), ensure_ascii=False, allow_nan=False)


if __name__ == '__main__':
    server.run(transport='stdio')
