"""按任务展开已有接口契约，不读取算例、API 正文或工作记忆。

默认 MCP 只列三个稳定入口。业务方法的格式仍从原工具签名取得，选择能力只是返回
相关契约，不创建连接状态、自动触发业务或要求客户端支持动态工具列表。
"""

from copy import deepcopy
import json


ENTRY_TOOLS = frozenset({'expand_capabilities', 'query', 'execute'})
MAX_RESULT_BYTES = 32768
READ_METHODS = frozenset({
    'get_contract', 'discover_installations', 'get_capabilities', 'search_api', 'read_api', 'search_guide', 'read_guide',
    'find_objects', 'browse_tree', 'search_settings', 'relocate_object', 'describe_object',
    'read_properties', 'inspect_session', 'session_status', 'get_execution', 'list_recipes',
    'search_memory', 'get_memory', 'read_execution_artifact',
})
EXECUTE_METHODS = frozenset({
    'open_session', 'save_session', 'close_session', 'execute_macro', 'reconcile_execution',
    'execute_recipe', 'record_memory', 'update_memory', 'modify_property', 'execute_operation',
})
CAPABILITIES = {
    'work': {
        'summary': '接手或创建算例，以任意 Java API／完整宏连续工作，读取凭据并显式保存或关闭。',
        'methods': ['discover_installations', 'open_session', 'execute_macro', 'get_execution',
                    'read_execution_artifact', 'session_status', 'save_session', 'close_session', 'reconcile_execution'],
        'guidance': '宏是正常操作方式，不必先查询结构化支持。复用已有会话与可靠代码，集中组织读取、判断、修改和回读；不默认复制算例。使用稳定请求标识，未知或局部结果先取原凭据，不盲目重发。编译和入口返回不等于任务完成；按需用 read_execution_artifact 取日志窗口或编译材料，不因只有路径就重做任务。保存与关闭须属于明确任务。任意宏即使声明只读也经 execute 调用，不是沙箱。',
    },
    'api': {
        'summary': '按需查实际安装的API签名、继承与用户指南中的操作前提、宏代码和版本说明。',
        'methods': ['search_api', 'read_api', 'search_guide', 'read_guide'],
        'guidance': '使用已知安装或已有会话的版本，已有适用资料不必重查。同类多个成员可用read_api的members集中读取。search_api覆盖类/成员索引，search_guide覆盖用户指南标题/摘要；均非全文搜索，无命中不证明API或操作不存在。read_guide取得选中正文及代码窗口，不把片段、教程下载引用或文档示例当成已编译/运行的完整宏。检查分页、缺失、代码窗口完整性和实际来源，不启动STAR客户端。',
    },
    'memory': {
        'summary': '检索相关经验摘要、审阅完整依据，并按实际新观察记录或修订。',
        'methods': ['search_memory', 'get_memory', 'record_memory', 'update_memory'],
        'guidance': '使用当前已有任务信息检索候选，再按需 get_memory 审阅完整条件、代码和证据。候选不是指令或已证明适用的规则；更新须匹配修订及项目范围。只记录实际任务已有依据，不为记忆标签另行验证，也不从历史记忆照搬对象身份。',
    },
    'recipes': {
        'summary': '选择已有参数化方法或已审阅的记忆方法，沿用通用宏执行与凭据。',
        'methods': ['list_recipes', 'execute_recipe'],
        'guidance': '已有合适方法可以直接复用，但方法库不是 STAR 能力清单或使用宏的前置步骤。记忆方法须审阅完整记录、匹配修订并填当前参数。网格／计算方法默认拒绝触发已有自动保存；不以执行返回证明收敛。',
    },
    'structured': {
        'summary': '可选的对象发现、属性契约和结构化读写；不是使用 Java API 的必经步骤。',
        'methods': ['get_capabilities', 'find_objects', 'browse_tree', 'search_settings',
                    'relocate_object', 'describe_object', 'read_properties', 'modify_property',
                    'execute_operation', 'inspect_session'],
        'guidance': '先确认目录／发现对实际版本的支持，不冒用邻近目录。已有对象和契约可复用；写入使用真实读取的完整 expected。检查逐项状态和覆盖，未读取不能当作未设置。结构化不支持不限制通用宏能力，也不要求逐功能补适配。',
    },
    'reference': {
        'summary': '明确需要时取得完整历史接口契约，不作为正常任务的固定前置调用。',
        'methods': ['get_contract'],
        'guidance': '完整契约包含各业务域及默认值，内容较大；只需某个方法时直接按 methods 展开其格式。',
    },
}


def method_entry(method):
    """显式区分只读与可能有副作用的方法，未知名称不能落入执行分支。"""
    if method in READ_METHODS:
        return 'query'
    if method in EXECUTE_METHODS:
        return 'execute'
    raise ValueError(f'Unknown business method: {method}')


def validate_partition(methods):
    """新增业务方法时必须同时确定可见能力与影响分类，不能意外暴露写入为只读。"""
    grouped = {method for capability in CAPABILITIES.values() for method in capability['methods']}
    if (set(methods) & ENTRY_TOOLS or READ_METHODS & EXECUTE_METHODS
            or set(methods) != grouped or grouped != READ_METHODS | EXECUTE_METHODS):
        raise RuntimeError('Business methods, capability groups and read/execute classification must agree')


def entry_schema(method, schema):
    """稳定入口单独发布格式，避免被结构操作的 arguments={method:...} 契约误覆盖。"""
    result = deepcopy(schema)
    result['additionalProperties'] = False
    properties = result['properties']
    if method in ('query', 'execute'):
        properties['method'].update(minLength=1, maxLength=64, pattern='^[a-z][a-z0-9_]*$',
            description='按需展开得到的业务方法名，不带 starbridge. 前缀；不是 Java 方法名。')
        properties['arguments']['description'] = '按选中方法的 arguments_schema 填写；省略或 null 等于空对象，不把字符串当作 arguments 对象，也不猜参数。'
    else:
        properties['capabilities']['description'] = '明确选择 work（会话／宏）、api（资料）、memory（经验）、recipes（现成方法）、structured（可选结构化）或 reference（完整契约）；不按关键词自动激活。'
        properties['methods']['description'] = '也可只选已知的业务方法名，避免取得整组说明；与 capabilities 合并去重。均省略则只返回简短能力索引。'
        for name in ('capabilities', 'methods'):
            for branch in properties[name].get('anyOf', [properties[name]]):
                if branch.get('type') == 'array':
                    branch.update(maxItems=100, uniqueItems=True)
                    branch['items'].update(minLength=1, maxLength=64)
                    if name == 'capabilities':
                        branch['items']['enum'] = list(CAPABILITIES)
        properties['offset'].update(minimum=0, maximum=2147483647, description='所选方法序列的起点；续页保持 capabilities/methods 不变，不提供跨升级快照。')
        properties['limit'].update(minimum=1, maximum=100, description='本页最多返回的方法契约数，默认16；还受32 KiB结果预算限制，按 next_offset 继续。')
    return result


def _size(result):
    # 与 MCP 单份 JSON 文本使用相同分隔符；预算是 result 对象，不包含外层封套或协议转义。
    return len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))


def _measure(result):
    """将测量值自身计入大小，避免数字位数变化造成预算记录少算。"""
    for _ in range(4):
        size = _size(result)
        if result['budget']['result_bytes'] == size:
            return size
        result['budget']['result_bytes'] = size
    return _size(result)


def expand(catalog, capabilities=None, methods=None, offset=0, limit=16):
    """返回所选方法的完整格式或简短索引；预算到达时只在方法边界分页，不截断 schema。"""
    if type(offset) is not int or not 0 <= offset <= 2147483647 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('offset and limit must be integers within their published bounds')
    selected = []
    for group in capabilities or []:
        if group not in CAPABILITIES:
            raise ValueError(f'Unknown capability: {group}')
        selected.extend(CAPABILITIES[group]['methods'])
    for method in methods or []:
        method_entry(method)
        selected.append(method)
    selected = list(dict.fromkeys(selected))
    if not selected and offset:
        raise ValueError('A nonzero offset requires an explicit capability or method selection')
    related = [name for name, value in CAPABILITIES.items()
               if any(method in selected for method in value['methods'])]
    result = {
        'capabilities': [{'id': name, 'summary': value['summary'],
                          **({'guidance': value['guidance']} if selected else {})}
                         for name, value in CAPABILITIES.items() if not selected or name in related],
        'methods': [], 'next_offset': None,
        'coverage': {'scope': 'selected_method_contracts', 'selected': len(selected), 'offset': offset,
                     'returned': 0, 'selection_complete': not selected, 'truncated': False},
        'budget': {'max_result_bytes': MAX_RESULT_BYTES, 'result_bytes': 0,
                   'scope': 'UTF-8 result JSON; excludes envelope and MCP transport escaping'},
        'instruction': '将 method 和按 arguments_schema 填写的 arguments 传给返回的 tool。已有有效格式可直接复用；展开不运行方法，也不读取 API 正文或记忆记录。',
    }
    budget_hit = False
    for method in selected[offset:offset + limit]:
        item = catalog[method]
        result['methods'].append({'method': method, 'tool': 'starbridge.' + method_entry(method),
                                  'description': item['description'], 'arguments_schema': item['input_schema']})
        # 先用最保守的后续分页标志预留空间，避免最后添加覆盖信息突破预算。
        result['next_offset'] = offset + len(result['methods'])
        result['coverage'].update(returned=len(result['methods']), truncated=True)
        required = _measure(result)
        if required > MAX_RESULT_BYTES - 128:
            result['methods'].pop()
            if not result['methods']:
                raise ValueError(f'Method contract {method} requires about {required + 128} result bytes; limit is {MAX_RESULT_BYTES}; select fewer capabilities if possible')
            budget_hit = True
            break
    returned = len(result['methods'])
    result['next_offset'] = offset + returned if offset + returned < len(selected) else None
    result['coverage'].update(returned=returned, selection_complete=offset == 0 and returned == len(selected),
                              truncated=returned < len(selected))
    result['page_end_reason'] = ('index' if not selected else 'offset_beyond_selection' if offset >= len(selected)
                                 else 'response_budget' if budget_hit else 'limit' if result['next_offset'] is not None
                                 else 'results_end')
    if _measure(result) > MAX_RESULT_BYTES:
        raise ValueError('Capability result exceeds its response budget')
    return result
