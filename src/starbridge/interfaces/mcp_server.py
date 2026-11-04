#!/usr/bin/env python3
"""通过官方 Python SDK 提供本机 stdio MCP，所有业务调用交给共享 Core。

stdout 仅用于 MCP 消息；STAR 的输出由原执行器写入请求日志。工具是同步函数，
SDK 在线程中执行，避免长时间 STAR 调用阻塞协议循环；同一会话仍由文件锁互斥。
"""

import json
from typing import Any

from mcp import types
from mcp.server import MCPServer
from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr
from jsonschema import Draft202012Validator

from starbridge import __version__
from starbridge.core.service import Service, contract
from starbridge.core.interface_contract import SERVER_INSTRUCTIONS, tool_input_schema, recovery_guidance


def tool_result(result):
    """单份 JSON 文本承载共享 Core 封套，不再复制一份相同的 structuredContent。"""
    return types.CallToolResult(
        content=[types.TextContent(text=json.dumps(result, ensure_ascii=False, allow_nan=False))],
        is_error=result['status'] != 'ok')


async def validate_arguments(context, call_next):
    """先按公开 JSON Schema 检查原始参数，防止 SDK 丢弃未知字段或将字符串隐式转成对象。"""
    if context.method == 'tools/call' and isinstance(context.params, dict):
        params = context.params
        for tool in await server.list_tools():
            if tool.name == params.get('name'):
                schema = tool_input_schema(tool.name.removeprefix('starbridge.'), tool.input_schema)
                error = next(Draft202012Validator(schema).iter_errors(params.get('arguments', {})), None)
                if error is not None:
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
    """直接返回单份 Core 状态封套，失败时设置 MCP 的 isError。"""
    result = service.call(method, arguments)
    return tool_result(result)


@server.tool(name='starbridge.get_contract', annotations=READ)
def get_contract() -> types.CallToolResult:
    """按需获取当前服务的完整调用契约；无需会话，不启动 STAR，也不是每次调用的前置步骤。

    result.usage 包含统一对象流程、locator schema、结果字段位置、
    分页、保存重载及失败恢复规则；defaults 与 contract_scope 区分可覆盖默认值、当前上限和能力范围。
    与 starbridge://contract 资源内容相同，供只支持工具
    调用的客户端使用；属性的新值格式由 describe_object 的 write_contract 提供。
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
                 parent_id: StrictStr | None = None, offset: StrictInt = 0,
                 limit: StrictInt = 100, timeout: StrictFloat = 180) -> types.CallToolResult:
    """按目录类型查找真实对象；返回 result.objects[] 的 object_id 与稳定 locator。

    子类型用父对象查找结果的 parent_id。名称精确匹配，分页用 next_offset。
    引用用于统一 describe_object/read_properties/modify_property；跨会话须 relocate_object。
    """
    return call('find_objects', locals())


@server.tool(name='starbridge.describe_object', annotations=READ)
def describe_object(session_id: StrictStr, object_id: StrictStr | None = None,
                    property_ids: list[StrictStr] | None = None, cursor: StrictStr | None = None,
                    limit: StrictInt = 100, scope: StrictStr = 'simulation',
                    timeout: StrictFloat = 180) -> types.CallToolResult:
    """描述查找或浏览所得对象，统一返回 result.properties[id]，不读取全部当前值。

    属性给出 write_enabled/write_contract；operations[id] 给出已适配结构操作。
    支持标志不证明实例或新值可写；写前读取完整 value 用作 expected。
    省略 object_id 只表示运行时树根。翻页保持 object_id/scope；property_ids 可省略沿用。
    检查 inspection_complete、state、errors 和 next_cursor；描述分页不消除底层缺口。
    """
    return call('describe_object', locals())


@server.tool(name='starbridge.read_properties', annotations=READ)
def read_properties(session_id: StrictStr, object_id: StrictStr, property_ids: list[StrictStr],
                    timeout: StrictFloat = 180) -> types.CallToolResult:
    """读取显式选择的属性，目录对象和树节点使用相同参数与 result.properties[id]。

    只消费 status=ok 的 value；检查 inspection_complete 和逐属性错误。
    relation/range 各有独立状态；不支持范围读取不代表没有限制。
    expected 必须原样复制完整 value；已有有效引用与属性契约可直接复用。
    """
    return call('read_properties', locals())


@server.tool(name='starbridge.modify_property', annotations=WRITE)
def modify_property(session_id: StrictStr, object_id: StrictStr, property_id: StrictStr,
                    expected: Any, value: Any, timeout: StrictFloat = 180,
                    audit: StrictBool = False) -> types.CallToolResult:
    """按当前 write_contract 修改单个属性，只改变内存，不自动保存或重试。

    expected 使用 read_properties 的完整 value；value 可为契约允许的标量、数组或对象。
    新关联使用 find_objects 返回的 {object_id: ...}，不构造 Java 引用或目录 target。
    result.before/properties 为前后属性结果，setter_attempts 记录尝试；audit=true 附快照与 Diff。
    uncertain 时查询状态并只读核对，不重试、回滚或保存。
    """
    return call('modify_property', locals())


@server.tool(name='starbridge.execute_operation', annotations=WRITE)
def execute_operation(session_id: StrictStr, object_id: StrictStr, operation_id: StrictStr,
                      expected: Any, arguments: dict, timeout: StrictFloat = 180,
                      audit: StrictBool = False) -> types.CallToolResult:
    """执行 describe_object.operations 中已适配的结构操作，不把方法切换当成普通赋值。

    expected 从 state_property 指定的属性读取；arguments.method 取可用的 method_choices.id。
    result.before/properties 返回前后属性结果；实例和关联条件由执行器重新核对。
    仅适用于 find_objects 返回的目录对象；不会自动保存或重试。
    """
    return call('execute_operation', locals())


@server.tool(name='starbridge.inspect_session', annotations=READ)
def inspect_session(session_id: StrictStr, timeout: StrictFloat = 180) -> types.CallToolResult:
    """按需读取已适配 Inspector 快照范围；不是全算例导出，也不是普通赋值前提。"""
    return call('inspect_session', locals())


@server.tool(name='starbridge.browse_tree', annotations=READ)
def browse_tree(session_id: StrictStr, object_id: StrictStr | None = None,
                cursor: StrictStr | None = None, offset: StrictInt = 0, limit: StrictInt = 100,
                scope: StrictStr = 'simulation', max_nodes: StrictInt = 2000,
                timeout: StrictFloat = 180) -> types.CallToolResult:
    """展开实际树的一层，返回 result.object 与 objects[]，不读取属性值。

    仅在 runtime_discovery.supported=true 时可用；省略 object_id 从根开始。
    后续展开沿用树结果的 object_id，目录查找不提供树关系。代理 object_id 为空。
    翻页用 next_cursor，检查 errors/truncations，不将一次展开当成全树覆盖。
    """
    return call('browse_tree', locals())


@server.tool(name='starbridge.search_settings', annotations=READ)
def search_settings(session_id: StrictStr, query: StrictStr, expand: StrictBool = False,
                    max_nodes: StrictInt = 100, max_depth: StrictInt = 4,
                    scope: StrictStr = 'simulation', timeout: StrictFloat = 180,
                    limit: StrictInt = 100, cursor: StrictStr | None = None) -> types.CallToolResult:
    """搜索缓存元数据；result.matches[].object/property 用于统一描述和读取。

    需要新发现才显式 expand=true；覆盖受节点、深度和时间预算限制。
    空命中不证明目标不存在。检查 coverage、errors/truncations 和分页。
    翻页保持 query/scope 并设 expand=false；缓存变化可使游标失效。
    """
    return call('search_settings', locals())


@server.tool(name='starbridge.relocate_object', annotations=READ)
def relocate_object(session_id: StrictStr, locator: dict,
                    timeout: StrictFloat = 180) -> types.CallToolResult:
    """按对象结果的 locator 在当前会话重新定位，返回 result.object.object_id。

    locator 原样传入，内部按来源使用目录路径或树路径；不接受旧引用代替定位。
    同名歧义拒绝；重定位不证明仍是原 Java 实例，须重新描述读取。
    """
    return call('relocate_object', locals())


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
    执行中也可查询状态；state=running 表示请求未结束，uncertain_request 标识未确认写入。此工具不重试操作。
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
