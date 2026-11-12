#!/usr/bin/env python3
"""通过官方 Python SDK 提供本机 stdio MCP，所有业务调用交给共享 Core。

stdout 仅用于 MCP 消息；STAR 的输出由原执行器写入请求日志。稳定入口异步转发，
原同步业务包装器仍由 SDK 在线程执行，避免 STAR 调用阻塞协议循环；会话由文件锁互斥。
"""

import json
from typing import Any

from mcp import types
from mcp.server import MCPServer
from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError
from mcp.server.mcpserver.exceptions import ToolError
from jsonschema import Draft202012Validator

from starbridge import __version__
from starbridge.core.service import METHODS, Service, contract
from starbridge.core.interface_contract import SERVER_INSTRUCTIONS, tool_input_schema, recovery_guidance
from starbridge.core.memory_safety import (
    MEMORY_WRITE_METHODS, MemorySensitiveDataError, ensure_safe_memory_data,
    sensitive_data_rejection, memory_argument_rejection, safe_field_path,
)
from starbridge.core.interface_exposure import (
    ENTRY_TOOLS, READ_METHODS, method_entry, validate_partition, expand as expand_contracts,
)

validate_partition(METHODS)


def tool_result(result):
    """单份 JSON 文本承载 Core 封套；恢复提示使用默认可见入口，不复制结果正文。"""
    recovery = result.get('recovery')
    if isinstance(recovery, dict):
        method = recovery.get('next_tool', '').removeprefix('starbridge.')
        if method == 'get_contract':
            # 无会话时 Core 的旧兜底是整份契约；MCP 改为按需入口，不因一次错误加载所有说明。
            result = {**result, 'recovery': {**recovery, 'next_tool': 'starbridge.expand_capabilities', 'arguments': {}}}
        elif method in METHODS:
            # 只改 MCP 路由，不改变 Core 的状态判断；缺少的业务参数仍须按原错误补充。
            arguments = {'method': method}
            if 'arguments' in recovery:
                arguments['arguments'] = recovery['arguments']
            result = {**result, 'recovery': {**recovery, 'next_tool': 'starbridge.' + method_entry(method),
                                           'method': method, 'arguments': arguments}}
    return types.CallToolResult(
        content=[types.TextContent(text=json.dumps(result, ensure_ascii=False, allow_nan=False))],
        is_error=result['status'] != 'ok')


def _memory_write_call(operation, arguments):
    """识别稳定转发和原业务注册的记忆写入，不将其他宏参数纳入此检查。"""
    if isinstance(operation, str) and operation in MEMORY_WRITE_METHODS:
        return True
    method = arguments.get('method') if isinstance(arguments, dict) else None
    return operation in ('execute', 'query') and isinstance(method, str) and method in MEMORY_WRITE_METHODS


async def validate_arguments(context, call_next):
    """记忆调用先做无原文安全检查，再校验结构，避免 SDK 错误回显未知键和值。"""
    if context.method == 'tools/call' and isinstance(context.params, dict):
        params = context.params
        operation = str(params.get('name', '')).removeprefix('starbridge.')
        raw = params.get('arguments', {})
        memory_write = _memory_write_call(operation, raw)
        if memory_write:
            try:
                ensure_safe_memory_data(raw)
            except MemorySensitiveDataError as error:
                return tool_result(sensitive_data_rejection(error))
        for tool in await server.list_tools():
            if tool.name == params.get('name'):
                schema = tool_input_schema(tool.name.removeprefix('starbridge.'), tool.input_schema)
                error = next(Draft202012Validator(schema).iter_errors(params.get('arguments', {})), None)
                if error is not None:
                    if memory_write:
                        return tool_result(memory_argument_rejection(error.absolute_path))
                    if tool.name.removeprefix('starbridge.') in ENTRY_TOOLS:
                        return entry_rejection(error.message, list(error.absolute_path))
                    return tool_result({'status': 'rejected', 'error': {
                        'type': 'ArgumentValidationError', 'message': error.message,
                        'argument_path': list(error.absolute_path)},
                        'recovery': recovery_guidance('rejected')})
                if operation == 'update_memory' and type(raw.get('expected_revision')) is not int:
                    return tool_result(memory_argument_rejection(['expected_revision']))
                break
    result = await call_next(context)
    if context.method == 'tools/list' and isinstance(result, types.ListToolsResult):
        # 默认仅发布稳定入口；完整业务注册表保留，按需展开才返回选中方法的格式。
        result.tools = [tool for tool in result.tools if tool.name.removeprefix('starbridge.') in ENTRY_TOOLS]
        for tool in result.tools:
            tool.input_schema = tool_input_schema(tool.name.removeprefix('starbridge.'), tool.input_schema)
    elif context.method == 'tools/list' and isinstance(result, dict):
        # 当前 SDK 通常已序列化；只过滤 tools，保留其协议版本及其他封套字段。
        result['tools'] = [tool for tool in result.get('tools', [])
                           if tool['name'].removeprefix('starbridge.') in ENTRY_TOOLS]
        for tool in result['tools']:
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
# 通用 Java 有完整宏权限，可能访问外部文件或资源，不能沿用结构化接口的封闭范围提示。
MACRO_WRITE = types.ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                    idempotent_hint=False, open_world_hint=True)


def call(method, arguments):
    """直接返回单份 Core 状态封套，失败时设置 MCP 的 isError。"""
    result = service.call(method, arguments)
    return tool_result(result)


async def method_catalog():
    """通过 SDK 公开注册接口取同源签名；不经过出站列表过滤，也不读取业务资料。"""
    result = {}
    for tool in await server.list_tools():
        method = tool.name.removeprefix('starbridge.')
        if method in METHODS:
            expected_read = method in READ_METHODS
            if tool.annotations is None or tool.annotations.read_only_hint is not expected_read:
                raise RuntimeError(f'Method impact annotation disagrees with its entrypoint: {method}')
            result[method] = {'description': tool.description or '',
                              'input_schema': tool_input_schema(method, tool.input_schema)}
    if set(result) != set(METHODS):
        raise RuntimeError('Registered business tools and Core methods must agree')
    return result


@server.tool(name='starbridge.expand_capabilities', annotations=READ)
async def expand_capabilities(capabilities: list[StrictStr] | None = None,
                              methods: list[StrictStr] | None = None,
                              offset: StrictInt = 0, limit: StrictInt = 16) -> types.CallToolResult:
    """主动选择任务相关能力或已知方法，取得说明、参数格式和调用入口。

    省略选择只返回简短索引。按 next_offset 继续，schema不截断；不调用STAR、不读API正文或记忆。
    这不是STAR功能支持清单，也不会自动授予写入权限；已有有效格式可直接复用。
    """
    try:
        result = expand_contracts(await method_catalog(), capabilities, methods, offset, limit)
        return tool_result({'status': 'ok', 'result': result})
    except ValueError as error:
        return entry_rejection(str(error))


def entry_rejection(message, path=None):
    """入口错误不代表算例失败；诊断本身若含认证格式，也不能向客户端回显。"""
    try:
        ensure_safe_memory_data({'message': message, 'path': path})
    except MemorySensitiveDataError:
        message = 'Tool arguments were rejected; validation content is omitted.'
        path = safe_field_path(path or [])
    return tool_result({'status': 'rejected', 'error': {'type': 'ArgumentValidationError',
        'message': message, 'argument_path': path or []},
        'recovery': {'automatic_retry': False, 'next_tool': 'starbridge.expand_capabilities',
                     'arguments': {}, 'instruction': '本次业务方法未调用；按需取得正确格式。已有会话的未知结果仍须查原凭据。'}})


async def invoke_method(entry, method, arguments):
    """以原 schema 和 SDK 原签名校验参数，再调用一次旧业务包装器，保留 Strict/defaults。

    不能仅用 Service.call 替代 SDK 校验：JSON Schema 的 integer 可能接受 1.0，原
    StrictInt 不接受。公开 call_tool 不递归进入 middleware；同步业务仍由 SDK 在线程执行。
    记忆输入在 Schema/SDK 之前检查，不能让校验错误将检测到的认证值带回响应。
    """
    memory_write = isinstance(method, str) and method in MEMORY_WRITE_METHODS
    if memory_write:
        try:
            ensure_safe_memory_data(arguments)
        except MemorySensitiveDataError as error:
            return tool_result(sensitive_data_rejection(error))
    try:
        expected = method_entry(method)
    except ValueError as error:
        return entry_rejection(str(error), ['method'])
    if expected != entry:
        return entry_rejection(f'{method} requires starbridge.{expected}; no business method was called', ['method'])
    arguments = {} if arguments is None else arguments
    catalog = await method_catalog()
    error = next(Draft202012Validator(catalog[method]['input_schema']).iter_errors(arguments), None)
    if error is not None:
        if memory_write:
            return tool_result(memory_argument_rejection(error.absolute_path))
        return entry_rejection(error.message, ['arguments', *error.absolute_path])
    if method == 'update_memory' and type(arguments.get('expected_revision')) is not int:
        return tool_result(memory_argument_rejection(['expected_revision']))
    # 仅允许既有业务名称，不能转发回 query/execute/expand 形成递归。CallToolResult 原样返回，
    # 保留 Core partial/uncertain 与 is_error，不再次包一层 JSON 或复制 structuredContent。
    try:
        return await server.call_tool('starbridge.' + method, arguments)
    except ToolError as error:
        if not memory_write:
            raise
        if isinstance(error.__cause__, ValidationError):
            return tool_result(memory_argument_rejection())
        # 非参数错误不能声称从未执行；省略底层异常，核对修订后人工处理。
        return tool_result({'status': 'error', 'error': {'type': 'MemoryWriteError',
                            'message': 'Memory write dispatch failed; underlying error content is omitted.'},
                            'recovery': {'automatic_retry': False, 'next_tool': 'starbridge.get_memory',
                                         'instruction': '先核对相同范围的当前修订，不自动重放或重做算例。'}})


@server.tool(name='starbridge.query', annotations=READ)
async def query(method: StrictStr, arguments: dict | None = None) -> types.CallToolResult:
    """调用已知只读方法，按需展开取得 method 与 arguments_schema。

    只接受既有读取方法，不接收用户Java或记忆写入，也不请求算例修改／会话启停；这些动作另用execute。
    返回原业务状态与覆盖信息；只读成功不解除此前未知写入。
    """
    return await invoke_method('query', method, arguments)


@server.tool(name='starbridge.execute', annotations=MACRO_WRITE)
async def execute(method: StrictStr, arguments: dict | None = None) -> types.CallToolResult:
    """调用明确选定的宏、生命周期、记忆写入或结构化修改方法，不根据关键词选择动作。

    使用展开取得的格式和已有授权范围；宏有完整Java权限，即使声明只读也走此入口。
    原请求标识、逐步结果和恢复规则不变，失败或超时不自动重发。
    """
    return await invoke_method('execute', method, arguments)


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

    supported_versions、supported、catalog_supported只描述结构化目录，不表示本机安装或通用宏兼容。
    未适配仍返回supported=false；session_lifecycle/generic_execution另列通用入口及编译/身份要求，顶层ok只表示查询完成。
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
    按用户任务选择程序；仅选用结构化接口时再查 get_capabilities。多个版本无法确定时询问用户，不自动换版本。
    """
    return call('discover_installations', locals())


@server.tool(name='starbridge.search_api', annotations=READ)
def search_api(query: StrictStr, installation: StrictStr | None = None,
               session_id: StrictStr | None = None, kind: StrictStr = 'all',
               offset: StrictInt = 0, limit: StrictInt = 20) -> types.CallToolResult:
    """按实际安装的官方索引搜索类和成员，不连接 STAR，不受结构化适配名单限制。

    installation 与 session_id 二选一；关键词按空白分词且全部匹配，可组合类名和方法名。
    只搜索索引标签，不全文检索文档或外部宏库。read_status/coverage 区分缺失索引和空命中。
    成功result受32 KiB UTF-8 JSON预算，完整条目按next_offset续页；不是索引扫描或缓存内存预算。
    只在定位未知类或成员时搜索；已知完整类名可直接read_api，有把握的宏可直接编写。
    需要进一步解决具体疑问时再读正文，不要求搜索后固定再读；无命中不证明API不存在。
    """
    return call('search_api', locals())


@server.tool(name='starbridge.read_api', annotations=READ)
def read_api(java_class: StrictStr, installation: StrictStr | None = None,
             session_id: StrictStr | None = None, member: StrictStr | None = None,
             offset: StrictInt = 0, limit: StrictInt = 20,
             members: list[StrictStr] | None = None) -> types.CallToolResult:
    """按需读取实际版本类／成员的官方签名、正文、参数约定、代码示例和相关链接。

    已知完整类名/成员可直接读取，无需先search_api；只补查当前疑问，已有资料不重读。
    member可用已知简单名保留重载或完整锚点；自动读取该成员的本地继承声明。
    也可用members一次选择同类至多32个成员，共享类资料；与member互斥，检查每个selector的缺失和覆盖。
    两者均省略则读取类说明和本类成员分页，不展开所有父类。检查 read_status/coverage/next_offset。
    成功result受32 KiB预算；成员和类链接共用分页边界，分别看next_offset/links_next_offset并传offset续页。
    正文必要摘录在content_truncations明示，full_text_ref相对result指向完整来源；截断示例不是可执行完整代码。
    不裁剪签名、来源或错误；最低资料超预算明确拒绝，不表示API不可用。整页解析/索引扫描/缓存仍无全局预算。
    返回来源路径与摘要；外部继承资料只标明未读，不隐式联网。资料、编译及实际执行依据不同。
    """
    return call('read_api', locals())


@server.tool(name='starbridge.search_guide', annotations=READ)
def search_guide(query: StrictStr, installation: StrictStr | None = None,
                 session_id: StrictStr | None = None, language: StrictStr = 'en',
                 offset: StrictInt = 0, limit: StrictInt = 20) -> types.CallToolResult:
    """按任务搜索实际安装用户指南的标题／摘要，找到操作前提、宏示例和版本迁移资料。

    installation与session_id二选一，language是安装文档目录语言代号，不自动翻译或切换版本。
    关键词按空白分词且全部匹配；ASCII字母/数字开头的词从词首匹配，非ASCII词按子串，精确标题优先。
    支持英文词尾延伸，但不是词干还原、全文、语义或已下载教程库搜索；正文用read_guide另读。
    复用官方索引，不遍历全部HTML；索引输入上限8MiB，结果32KiB，完整条目按next_offset续页。
    read_status/coverage区分资料不可用、索引部分识别与无命中；无命中不能证明操作不可用。
    """
    return call('search_guide', locals())


@server.tool(name='starbridge.read_guide', annotations=READ)
def read_guide(topic: StrictStr, installation: StrictStr | None = None,
               session_id: StrictStr | None = None, language: StrictStr = 'en',
               offset: StrictInt = 0, limit_chars: StrictInt = 12000,
               link_offset: StrictInt = 0, link_limit: StrictInt = 20,
               expected_sha256: StrictStr | None = None) -> types.CallToolResult:
    """定向读取用户指南主题正文与发布时代码，不执行脚本、联网或自动执行宏。

    topic取search_guide或已有主题links返回的HTML名称，不接受任意路径。核对安装和指南包版本。
    offset以渲染正文Unicode码点计，不是HTML字节；按next_offset续读，并用source.sha256作expected_sha256。
    说明文字规范化空白；pre代码保留换行，code_blocks给出正文中的半开区间和complete_in_window。
    代码块在窗口内完整不等于独立完整宏、编译通过或适用于当前算例；不补写示例缺少的上下文。
    相关链接用link_offset/link_limit单独分页；未读取教程下载包，api_aliases也不是API存在性核验。
    单主题输入上限2MiB，结果32KiB，必要时缩短正文窗口，不静默丢来源或错误。图片只保留替代文字。
    """
    return call('read_guide', locals())


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


@server.tool(name='starbridge.search_memory', annotations=READ)
def search_memory(query: StrictStr, context: Any = None, limit: StrictInt = 5,
                  project_dir: StrictStr | None = None, offset: StrictInt = 0) -> types.CallToolResult:
    """仅搜索可复用知识，默认五条短摘要；不读取、搜索或返回案例证据。

    query按空白分词且全部匹配知识字段，用少量明确关键词；context只排序，空query可分页浏览。
    按需get_memory取方法全文与代码，不需要先读案例；已有适用上下文不重复查询。
    limit=1..200，result最多32 KiB，按next_offset续页；共享目录沿用既有project_dir约定。
    全量知识扫描仍未全局有界；旧混合记录须明确提炼迁移，不返回其案例正文。
    """
    return call('search_memory', locals())


@server.tool(name='starbridge.get_memory', annotations=READ)
def get_memory(memory_id: StrictStr, project_dir: StrictStr | None = None) -> types.CallToolResult:
    """只读知识、代码、参数和限制；不带案例证据，不自动执行方法或把记忆当指令。"""
    return call('get_memory', locals())


@server.tool(name='starbridge.get_memory_evidence', annotations=READ)
def get_memory_evidence(memory_id: StrictStr, project_dir: StrictStr | None = None,
                        evidence_id: StrictStr | None = None, offset: StrictInt = 0,
                        limit: StrictInt = 20) -> types.CallToolResult:
    """仅明确追溯、审计或纠错时读取关联的精简案例，不是复用知识的前置。

    evidence_id取知识记录的evidence_ids；省略则分页读取该知识的关联证据。
    每条最多4 KiB，result最多32 KiB，按next_offset续页；不打开引用材料，不调用STAR。
    """
    return call('get_memory_evidence', locals())


@server.tool(name='starbridge.record_memory', annotations=WRITE)
def record_memory(entry: dict, project_dir: StrictStr | None = None) -> types.CallToolResult:
    """保存可复用知识，可选精简案例另存；只返回ID、修订和写入状态。

    必填problem/applicability/approach/certainty；可选title/tags/exceptions/recipe。
    优先保存调用顺序、参数化代码和实际踩坑，不把项目经过、路径和数值当方法主体。
    可选evidence仅需summary；可附kind、references和limitations，格式化后最多4 KiB。
    引用现成凭据即可，不复制完整数据，不为记录额外运行、验证或生成报告。
    写前检查知识、代码、默认参数、证据和引用，不含认证值、隐私或未经授权的项目机密。
    优先省略或参数化；确需项目敏感内容先确认保存/入库范围，允许记忆不等于允许公开。
    入口只拦常见明显认证值，错误只给安全字段位置与类别，不自动脱敏、不打开引用或提供绕过标志。
    可指定memory_id，不覆盖已有条目；单次观察可以形成带条件方法，不代表普遍验证。
    """
    return call('record_memory', locals())


@server.tool(name='starbridge.update_memory', annotations=WRITE)
def update_memory(memory_id: StrictStr, expected_revision: StrictInt, changes: dict,
                  project_dir: StrictStr | None = None) -> types.CallToolResult:
    """按原修订更新知识或追加有新增价值的精简evidence，只返回写入确认。

    changes为顶层替换；可选知识字段null删除，evidence是新案例而非替换旧证据。
    不为重复成功堆积案例。旧格式迁移须显式提供四个知识必填字段，原记录另存legacy备份。
    写前同样检查知识、代码、默认值、证据和引用的隐私及项目授权；只检查拟写内容。
    新输入、沿用知识及将要复制的旧备份若含明显认证值则拒绝，不自动改写原材料或绕过检查。
    错误只给安全字段位置和类别；冲突先重读修订，不要求看案例或为迁移重新运行STAR。
    """
    return call('update_memory', locals())


@server.tool(name='starbridge.list_recipes', annotations=READ)
def list_recipes(recipe_id: StrictStr | None = None,
                 include_source: StrictBool = False) -> types.CallToolResult:
    """默认返回方法短索引；给 recipe_id 读取参数、条件与证据，不连接 STAR。

    选定方法后 include_source=true 可取原始 steps/imports/declarations 供直接复用，
    不必重新研究或从结果反推源码；合并时须处理步骤名、helper 和 shared 冲突。
    参数契约不是绑定值。原样执行优先 execute_recipe；记忆方法另经 get_memory 审阅。
    方法库不是能力清单，不要求通用宏先经过此入口。
    """
    return call('list_recipes', locals())


@server.tool(name='starbridge.execute_recipe', annotations=MACRO_WRITE)
def execute_recipe(session_id: StrictStr, request_id: StrictStr, recipe_id: StrictStr,
                   parameters: dict | None = None, expected_revision: StrictInt | None = None,
                   project_dir: StrictStr | None = None, timeout: StrictFloat = 180,
                   result_view: StrictStr = 'compact') -> types.CallToolResult:
    """执行明确选中的参数化方法，沿用宏的稳定请求标识和逐步凭据，不自动执行检索候选。

    内置 ID 与参数来自 list_recipes。memory:ID 执行先前审阅的记忆方法，必须提供对应
    expected_revision 和同一 project_dir 范围；未声明影响按 mutate 处理。契约中的
    object_reference 参数传 {object_id:当前ID}，会在用户步骤前解析为当前 STAR 对象；
    支持嵌套对象/数组，不复用跨会话旧引用，普通 JSON 字段不会自动转换。
    网格/计算不显式保存或改变 AutoSave；已有自动保存默认在 preflight 拒绝，任务授权时
    才传 allow_existing_autosave=true。内置导出只创建新文件；记忆中的任意代码不受此保护。
    方法源码和参数不变时，相同 request_id 返回旧凭据。记忆修订或方法库改变后用
    get_execution 查询旧结果，不改写旧请求。operation_returned 不证明收敛或物理正确；检查每个步骤、状态读取完整性和实际输出。
    """
    return call('execute_recipe', locals())


@server.tool(name='starbridge.execute_macro', annotations=MACRO_WRITE)
def execute_macro(session_id: StrictStr, request_id: StrictStr, steps: list[dict],
                  parameters: dict | None = None, imports: list[StrictStr] | None = None,
                  declarations: StrictStr = '', intent: StrictStr = 'execute',
                  timeout: StrictFloat = 180,
                  object_parameters: list[StrictStr] | None = None,
                  working_directory: StrictStr | None = None,
                  result_view: StrictStr = 'compact') -> types.CallToolResult:
    """用当前安装的完整 Java 宏 API 集中完成明确步骤，不受目录适配白名单限制。

    steps 每项有 id/effect/scope，code与macro二选一；effect=read或mutate，导出/保存/计算均为mutate。
    仅不改算例仍不够声明read：用户宏创建诊断JSON/CSV等外部文件也须mutate，并用scope限定输出及不改动范围。
    code是方法体，访问sim/parameters/shared/result。macro={entry_source,entry_class,sources?,classpath?}
    原样编译已有完整Java宏与明确helpers/JAR，在同一会话调用公开execute，不拆写私有方法或package。
    完整宏不自动获得包装器参数/result；成功仅entrypoint_returned，未提供业务结果会明确标记。
    可与普通回读步骤组合；来源/依赖字节纳入指纹，原文件变更后查询旧结果用get_execution。
    working_directory作用于整个客户端；完整宏的resolvePath仍基于各自原文件目录。
    不自动复制资源；支持JAR内资源；重名类、非空Manifest Class-Path和旧式JAR索引当前拒绝。
    整个请求共用类命名空间；安装JDK预编译成功后，两类请求都只让STAR编译薄启动，复用用户class。
    仅纯code在无法定位安装JDK时保留STAR源码编译；预编译失败不回退重试，完整源码仍须安装JDK。
    外部javac使用独立空processorpath；STAR使用空用户classpath，入口编译后再加载冻结依赖。
    cwd中已有javac Plugin服务描述符时拒绝派发；安装/配置/目录仍可信，不防同权限并发篡改。
    运行期类/资源与SPI可使用该加载器，不保证嵌套STAR源码编译继承依赖或异步任务已结束。
    object_parameters 显式列出需绑定的参数名；其中精确的 {object_id:当前ID}（含嵌套数组）
    在全部步骤前替换为 STAR 对象，其他参数仍为 JSON。绑定失败拒绝整个请求，不执行用户步骤。
    imports 是不含 import/分号的类或通配名称，declarations 可定义字段、辅助方法与内部类。
    身份与全部绑定通过后才初始化用户声明，execution.initialization 单独记录；任一步mutate则初始化
    也按mutate声明，全read则初始化也声明只读。声明覆盖全部代码，不是自动检测。
    result.execution.steps 保留完成、失败、未知和未开始项；completed 只证明步骤返回且结果可序列化，
    不证明物理有效性或自动验证读取范围。代码有完整宏权限，effect 是声明而非沙箱。
    request_id 须为稳定任务标识：重发同一内容只返回原凭据，变更内容须新标识。
    超时或部分完成先 get_execution，不盲目重试。explore 仅标记探索，不授权试改或自动复制。
    result_view=compact 只对 steps[].result 使用合计16 KiB预算；超出的整项结果显式省略，
    不裁剪步骤状态/错误。用 get_execution(result_view=full) 取正文，不重新执行。
    完成时说明 session_state.resources 的驻留资源和关闭边界，不自动保存或丢弃。
    """
    return call('execute_macro', locals())


@server.tool(name='starbridge.get_execution', annotations=READ)
def get_execution(session_id: StrictStr, request_id: StrictStr,
                  result_view: StrictStr = 'compact') -> types.CallToolResult:
    """查询已有逐步凭据和资源摘要；compact 明示省略大业务结果，full 返回完整业务正文。

    状态、错误和原始凭据不改写；省略正文可能包含局部读取错误，不能据 completed 宣称任务完整。
    不重复执行，关闭后仍可读取已有凭据；大日志或凭据也可用 read_execution_artifact 定向取窗口。
    """
    return call('get_execution', locals())


@server.tool(name='starbridge.read_execution_artifact', annotations=READ)
def read_execution_artifact(session_id: StrictStr, request_id: StrictStr, artifact: StrictStr,
                            offset: StrictInt = 0, limit_bytes: StrictInt = 8192,
                            tail: StrictBool = False, expected_version: StrictStr | None = None) -> types.CallToolResult:
    """按任务读取固定执行材料的头部、尾部或字节窗口，不启动STAR或重复执行。

    artifact选request/compiler_log/client_log/compilation/receipt，不接受任意文件路径。
    默认最多读取8192原始字节，成功result另受32 KiB JSON预算；不会一次加载完整大日志再截断。
    tail=true从观察到的文件尾部读取，此时offset须为0。否则用零起始字节offset与next_offset续读。
    可携带version作expected_version，变化后拒绝混页；它是文件元数据版本，不是内容哈希或恢复token。
    检查read_status、coverage、changed_during_read和encoding，不把缺失／错误当成空文件。
    无效UTF-8或窗口从半字符开始时说明替代解码并保留raw_base64；原字节摘要只覆盖返回窗口。
    只读到末尾不等于读完整文件；日志文本或原始JSON片段也不是验证后的执行结果，仍以get_execution判断。
    """
    return call('read_execution_artifact', locals())


@server.tool(name='starbridge.reconcile_execution', annotations=WRITE)
def reconcile_execution(session_id: StrictStr, request_id: StrictStr,
                        expected_review_token: StrictStr, assessment: dict) -> types.CallToolResult:
    """显式接受已观察到的当前状态并允许继续；不重放宏、不保存、不把旧结果改成完成。

    先审阅 get_execution 的原结果、当前会话和 review；token 必须仍匹配。
    assessment 说明 observations/accepted_scope/remaining_scope，以及已有 evidence 的 source/description。
    依据可来自原部分凭据或已有观察，不要求为确认额外验证；来源文字不自动读取或执行。
    活动或活动状态未知的请求不能接受。只支持通用宏；相同确认重发不再次解除后来的限制。
    """
    return call('reconcile_execution', locals())


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
                 project_dir: StrictStr | None = None, debug: StrictBool = False,
                 create: StrictBool = False) -> types.CallToolResult:
    """优先连接匹配的本机 STAR GUI／服务器，否则直接加载原算例启动自有后台服务。

    input 是算例绝对路径；不指定 input 时给已有服务的 port 和 project_dir，
    或 create=true 加 project_dir 从零创建空算例（不保存、不复用其他会话）。
    star为用户选定安装程序；release/build是可选预期，不符时拒绝。未登记版本可尝试通用预编译和身份握手，目录/发现仍不支持。
    加载前须使用所选安装内JDK编译最小生命周期模板；包装脚本无法定位工具链时拒绝，不换安装或系统JDK。
    自动发现限于同用户、同安装且 /proc 可见的本机服务，初始请求核对版本与加载对象。
    多个会话加载相同文件时用 port 选择；未指定 port 且需要启动时自动分配空闲端口。
    返回session_id、实际star_version及可为空的catalog_target；生命周期编译/身份成功不代表任意宏API已验证。
    后续原样传回session_id；运行目录由服务管理，项目默认采用算例所在目录。
    不复制算例、不自动保存。debug=true 保留详细请求文件；外部会话关闭时只断开连接。
    """
    return call('open_session', locals())


@server.tool(name='starbridge.session_status', annotations=READ)
def session_status(session_id: StrictStr) -> types.CallToolResult:
    """查询已知 session_id 的记录和当前进程存活情况，不启动 Java 或重新核对 Build。

    result 包含 state、server_alive、active_request、last_request、last_request_status（字段可缺省）。
    resources 列出身份匹配的登记进程、RSS观测和保留/关闭说明；不扫描全机，不自动清理。
    modified 是最近成功请求的观察，不为摘要刷新STAR；RSS合计可能重复计算共享页且不覆盖未登记子进程。
    用于任务收尾、断开、超时或 uncertain 后排查；ready 不等于上次修改成功，需结合请求结果。
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
