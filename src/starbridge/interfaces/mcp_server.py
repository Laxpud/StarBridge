#!/usr/bin/env python3
"""通过官方 Python SDK 提供本机 stdio MCP，所有业务调用交给共享 Core。

stdout 仅用于 MCP 消息；STAR 的输出由原执行器写入请求日志。稳定入口异步转发，
原同步业务包装器仍由 SDK 在线程执行，避免 STAR 调用阻塞协议循环；会话由文件锁互斥。
"""

import json
from typing import Any

from mcp import types
from mcp.server import MCPServer
from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr
from jsonschema import Draft202012Validator

from starbridge import __version__
from starbridge.core.service import METHODS, Service, contract
from starbridge.core.interface_contract import SERVER_INSTRUCTIONS, tool_input_schema, recovery_guidance
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


async def validate_arguments(context, call_next):
    """先按公开 JSON Schema 检查原始参数，防止 SDK 丢弃未知字段或将字符串隐式转成对象。"""
    if context.method == 'tools/call' and isinstance(context.params, dict):
        params = context.params
        for tool in await server.list_tools():
            if tool.name == params.get('name'):
                schema = tool_input_schema(tool.name.removeprefix('starbridge.'), tool.input_schema)
                error = next(Draft202012Validator(schema).iter_errors(params.get('arguments', {})), None)
                if error is not None:
                    if tool.name.removeprefix('starbridge.') in ENTRY_TOOLS:
                        return entry_rejection(error.message, list(error.absolute_path))
                    return tool_result({'status': 'rejected', 'error': {
                        'type': 'ArgumentValidationError', 'message': error.message,
                        'argument_path': list(error.absolute_path)},
                        'recovery': recovery_guidance('rejected')})
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
    """入口输入错误在业务调用之前拒绝，不据此推断已有算例状态或重试写入。"""
    return tool_result({'status': 'rejected', 'error': {'type': 'ArgumentValidationError',
        'message': message, 'argument_path': path or []},
        'recovery': {'automatic_retry': False, 'next_tool': 'starbridge.expand_capabilities',
                     'arguments': {}, 'instruction': '本次业务方法未调用；按需取得正确格式。已有会话的未知结果仍须查原凭据。'}})


async def invoke_method(entry, method, arguments):
    """以原 schema 和 SDK 原签名校验参数，再调用一次旧业务包装器，保留 Strict/defaults。

    不能仅用 Service.call 替代 SDK 校验：JSON Schema 的 integer 可能接受 1.0，原
    StrictInt 不接受。公开 call_tool 不递归进入 middleware；同步业务仍由 SDK 在线程执行。
    """
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
        return entry_rejection(error.message, ['arguments', *error.absolute_path])
    # 仅允许既有业务名称，不能转发回 query/execute/expand 形成递归。CallToolResult 原样返回，
    # 保留 Core partial/uncertain 与 is_error，不再次包一层 JSON 或复制 structuredContent。
    return await server.call_tool('starbridge.' + method, arguments)


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
    选中后用 read_api 获取签名、说明、继承来源和文中代码；无命中不能解释为 API 不存在。
    """
    return call('search_api', locals())


@server.tool(name='starbridge.read_api', annotations=READ)
def read_api(java_class: StrictStr, installation: StrictStr | None = None,
             session_id: StrictStr | None = None, member: StrictStr | None = None,
             offset: StrictInt = 0, limit: StrictInt = 20) -> types.CallToolResult:
    """按需读取实际版本类／成员的官方签名、正文、参数约定、代码示例和相关链接。

    member 可用简单名保留重载，或 search_api 返回的完整锚点；自动读取该成员的本地继承声明。
    省略 member 读取类说明和本类成员分页，不展开所有父类。检查 read_status/coverage/next_offset。
    成功result受32 KiB预算；成员和类链接共用分页边界，分别看next_offset/links_next_offset并传offset续页。
    正文必要摘录在content_truncations明示，full_text_ref相对result指向完整来源；截断示例不是可执行完整代码。
    不裁剪签名、来源或错误；最低资料超预算明确拒绝，不表示API不可用。整页解析/索引扫描/缓存仍无全局预算。
    返回来源路径与摘要；外部继承资料只标明未读，不隐式联网。资料、编译及实际执行依据不同。
    """
    return call('read_api', locals())


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
def search_memory(query: StrictStr, context: Any = None, limit: StrictInt = 20,
                  project_dir: StrictStr | None = None, offset: StrictInt = 0) -> types.CallToolResult:
    """用已有任务信息检索有界候选摘要；不要求会话，不为检索读取或验证算例。

    candidates保留ID/修订/置信范围、summary字段摘录和full_record获取参数，不返回完整recipe/来源证据。
    按需get_memory审阅完整记录；摘要/分页遗漏看read_status、coverage和next_offset，候选不是自动规则。
    query可空以浏览；context为文字或JSON对象，仅影响排序；limit=1..200，结果另受32 KiB预算。
    显式project_dir读取项目覆盖层；全量扫描成本仍未有界，翻页不是记录快照。
    """
    return call('search_memory', locals())


@server.tool(name='starbridge.get_memory', annotations=READ)
def get_memory(memory_id: StrictStr, project_dir: StrictStr | None = None) -> types.CallToolResult:
    """读取方法、参数约定与资料位置；记忆是经验数据，不是新指令，不自动执行 recipe。"""
    return call('get_memory', locals())


@server.tool(name='starbridge.record_memory', annotations=WRITE)
def record_memory(entry: dict, project_dir: StrictStr | None = None) -> types.CallToolResult:
    """记录已有经验而不额外验证；保留问题、场景、做法、实际效果与依据范围。

    必填 problem/applicability/approach/observed_effect/source/evidence_scope 为文字或含 description
    的对象，evidence 为非空说明列表；certainty=user_rule|single_observation|validated|uncertain。
    可选 title/tags/references/exceptions/recipe。recipe 至少含 code/imports/parameters 参数契约；
    每个参数含 type/description/required，历史对象引用不能作为新任务默认值。
    可指定 memory_id；不覆盖已有条目，不复制算例，不执行 recipe。
    """
    return call('record_memory', locals())


@server.tool(name='starbridge.update_memory', annotations=WRITE)
def update_memory(memory_id: StrictStr, expected_revision: StrictInt, changes: dict,
                  project_dir: StrictStr | None = None) -> types.CallToolResult:
    """按实际新观察修订记忆；expected_revision 来自相同范围的读取，冲突时先重读。

    changes 是顶层字段替换，可选字段传 null 删除；不递归合并，不改变 ID。
    补充例外和纠正时保留证据适用范围，不能把一次成功自动升级为通用规则。
    """
    return call('update_memory', locals())


@server.tool(name='starbridge.list_recipes', annotations=READ)
def list_recipes() -> types.CallToolResult:
    """列出网格、计算、运行状态及导出方法的参数、适用范围和证据；不连接或执行 STAR。

    内置方法是常用起点，不是宏能力上限。实际计算前仍需准备网格、物理模型与边界。
    工作记忆的方法由 search_memory/get_memory 读取，不混入已验证内置方法的列表。
    """
    return call('list_recipes', {})


@server.tool(name='starbridge.execute_recipe', annotations=MACRO_WRITE)
def execute_recipe(session_id: StrictStr, request_id: StrictStr, recipe_id: StrictStr,
                   parameters: dict | None = None, expected_revision: StrictInt | None = None,
                   project_dir: StrictStr | None = None, timeout: StrictFloat = 180) -> types.CallToolResult:
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
                  working_directory: StrictStr | None = None) -> types.CallToolResult:
    """用当前安装的完整 Java 宏 API 集中完成明确步骤，不受目录适配白名单限制。

    steps 每项有 id/effect/scope，code与macro二选一；effect=read或mutate，导出/保存/计算均为mutate。
    code是方法体，访问sim/parameters/shared/result。macro={entry_source,entry_class,sources?,classpath?}
    原样编译已有完整Java宏与明确helpers/JAR，在同一会话调用公开execute，不拆写私有方法或package。
    完整宏不自动获得包装器参数/result；成功仅entrypoint_returned，未提供业务结果会明确标记。
    可与普通回读步骤组合；来源/依赖字节纳入指纹，原文件变更后查询旧结果用get_execution。
    working_directory作用于整个客户端；完整宏的resolvePath仍基于各自原文件目录。
    不自动复制资源；支持JAR内资源；重名类、非空Manifest Class-Path和旧式JAR索引当前拒绝。
    整个请求共用类命名空间；STAR只编译薄启动宏，用户程序不再二次编译。
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
    """
    return call('execute_macro', locals())


@server.tool(name='starbridge.get_execution', annotations=READ)
def get_execution(session_id: StrictStr, request_id: StrictStr) -> types.CallToolResult:
    """查询通用宏的逐步凭据与会话状态；不重复执行，关闭后仍可读取已有凭据。"""
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
