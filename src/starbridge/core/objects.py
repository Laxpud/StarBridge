"""统一公开对象引用与属性结果，目录和运行时规则只作为内部能力来源。

对象 ID 绑定当前会话世代；稳定 locator 只用于重新查找，不能代替当前身份。
本模块不推测类型适配、不补写 expected，也不改变执行器的版本和写入边界。
"""

from copy import deepcopy

from . import discovery


def resolve(session_id, object_id):
    """从引用表解析已返回的对象；目录句柄携带完整父路径和首次观察的身份。"""
    state = discovery.reference_state(session_id)
    if isinstance(object_id, str) and object_id.startswith(('n_', 'r_')):
        kind = 'node' if object_id.startswith('n_') else 'related_object'
        discovery._decode(object_id, state, kind)
        return {'source': 'runtime', 'node_id': object_id}
    saved = discovery._decode(object_id, state, 'catalog_object')
    return {'source': 'catalog', **saved['object']}


def catalog_target(session_id, object_id):
    """为目录定位和新关联取回实际查得的目标；不能把树节点猜成目录类型。"""
    saved = resolve(session_id, object_id)
    if saved['source'] != 'catalog':
        raise ValueError('This operation requires an object returned by find_objects')
    return {**saved['locator'], 'reference': saved['reference']}


def catalog_object(session_id, item):
    """登记目录实际返回的对象，并隐藏内部 reference/target 双重表达。"""
    state = discovery.reference_state(session_id)
    identifier = discovery._remember_reference({'kind': 'catalog_object', 'object': item}, state)
    return {'object_id': identifier, 'name': item['name'], 'java_class': item['java_class'],
            'type_id': item['type'], 'kind': 'object',
            'locator': {'source': 'catalog', 'target': item['locator']},
            'locator_unique': item.get('locator_unique', True)}


def runtime_object(node):
    """树节点只公开一种对象 ID；代理保持无引用，路径仅作为定位与上下文。"""
    result = {key: value for key, value in node.items()
              if key not in ('node_id', 'path', 'key', 'parent_key', 'locator', 'binding')}
    result['object_id'] = node.get('node_id')
    if 'locator' in node:
        result['locator'] = {'source': 'runtime', 'path': node['locator']}
    return result


def runtime_result(result):
    """在边界处统一对象字段；属性 value 和错误内容原样保留，避免改写业务数据。"""
    result = dict(result)
    if 'node' in result:
        result['object'] = runtime_object(result.pop('node'))
    if 'children' in result:
        result['objects'] = [runtime_object(node) for node in result.pop('children')]
    if 'matches' in result:
        result['matches'] = [{**{k: v for k, v in match.items() if k != 'node'},
                              'object': runtime_object(match['node'])} for match in result['matches']]
    if isinstance(result.get('properties'), list):
        result['properties'] = {entry['property_id']: entry for entry in result['properties']}
    if 'coverage' in result:
        coverage = dict(result['coverage'])
        coverage['unsupported'] = [runtime_object(node) if 'node_id' in node else node
                                   for node in coverage.get('unsupported', [])]
        result['coverage'] = coverage
    result.update(schema_version=2, schema_id='starbridge.objects')
    return public_write_contracts(result)


def catalog_result(result, obj):
    """移除目录外壳，只保留一次属性结果；修改返回 before/properties 及可选审查。"""
    catalog = result['catalog']
    payload = {key: value for key, value in catalog.items()
               if key not in ('schema_version', 'target', 'action')}
    payload.update({key: value for key, value in result.items()
                    if key not in ('catalog', 'catalog_before', 'modification', 'catalog_diff')})
    if 'catalog_before' in result:
        payload['before'] = result['catalog_before']['properties']
        payload['before_complete'] = result['catalog_before']['inspection_complete']
        request = result['modification']
        payload['change'] = ({'kind': 'property', 'property_id': request['property']}
                             if request['schema_version'] == 2 else
                             {'kind': 'operation', 'operation_id': request['operation'],
                              'arguments': request['arguments']})
    if 'catalog_diff' in result:
        payload['property_diff'] = result['catalog_diff']
    observed = catalog.get('target', {})
    obj = {**obj, **{key: observed[key] for key in ('name', 'java_class') if key in observed}}
    payload.update(schema_version=2, schema_id='starbridge.objects', object=obj)
    return public_write_contracts(payload)


def public_write_contracts(result):
    """把新关联的输入格式改为 object_id；旧值保留执行器实际读取的原始结构。"""
    result = deepcopy(result)
    for identifier, entry in result.get('properties', {}).items():
        entry.setdefault('property_id', identifier)
        if 'writable' in entry:
            entry['write_enabled'] = entry.pop('writable')
        contract = entry.get('write_contract')
        if not contract:
            continue
        definitions = contract.get('value_schema', {}).get('$defs', {})
        if 'catalog_target' in definitions:
            definitions['catalog_target'] = {
                'type': 'object', 'properties': {'object_id': {'type': 'string', 'minLength': 1}},
                'required': ['object_id'], 'additionalProperties': False}
            contract['constraints'] = [text for text in contract['constraints']
                                       if '目录 target' not in text and '改写成 target' not in text]
            contract['constraints'].append(
                '新关联使用 find_objects 返回的 {object_id: ...}；expected 原样复制读取值。')
    return result


def assignment_value(session_id, value, *, runtime=False):
    """只展开新值中明确的对象 ID；通用赋值不再要求对象必须来自旧目录。"""
    if isinstance(value, dict):
        if set(value) == {'object_id'}:
            return ({'runtime_reference': object_binding(session_id, value['object_id'])} if runtime
                    else catalog_target(session_id, value['object_id']))
        if {'type', 'name'} <= value.keys() or 'runtime_reference' in value:
            raise ValueError('New references require object_id, not an internal target')
        return {key: assignment_value(session_id, item, runtime=runtime) for key, item in value.items()}
    if isinstance(value, list):
        return [assignment_value(session_id, item, runtime=runtime) for item in value]
    return value


def object_binding(session_id, object_id):
    """把服务器已经登记的对象转换成当前会话绑定，调用者不能直接传入裸 key。"""
    state = discovery.reference_state(session_id)
    source = resolve(session_id, object_id)
    if source['source'] == 'runtime':
        return discovery._target(object_id, state)
    return {'session_token': state['session_token'], 'simulation_key': state['simulation_key'],
            'object_key': source['reference']['key'], 'java_class': source['java_class']}


def link_references(session_id, result):
    """给实际读到的关联分配可操作 ID；登记失败不掩盖已经完成的读取或修改。

    只处理属性值及前读中的 STAR reference，不扫描任意宏输出，不创造不存在的对象。
    这些 ID 尚未重新求值；后续使用时由 STAR registry 核对 key、类型及当前 Simulation 归属。
    """
    result = deepcopy(result)
    candidates = []

    def collect(value):
        if isinstance(value, dict):
            reference = value.get('reference')
            if (isinstance(reference, dict) and set(reference) == {'session_token', 'key'}
                    and isinstance(reference.get('key'), str) and reference['key']):
                candidates.append(value)
            for key, child in value.items():
                if key != 'reference':
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for field in ('properties', 'before'):
        collect(result.get(field))
    if not candidates:
        return result
    try:
        state = discovery.reference_state(session_id)
        payloads = []
        for item in candidates:
            if item['reference']['session_token'] != state['session_token']:
                raise ValueError('Observed reference belongs to another session')
            binding = {'session_token': state['session_token'], 'simulation_key': state['simulation_key'],
                       'object_key': item['reference']['key'], 'java_class': item.get('java_class')}
            payloads.append({'kind': 'related_object', 'binding': binding, 'name': item.get('name')})
        identifiers = discovery._remember_references(payloads, state)
        for item, identifier in zip(candidates, identifiers):
            item['object_id'] = identifier
        result['reference_registration'] = {'status': 'ok', 'count': len(set(identifiers))}
    except (OSError, ValueError, KeyError, discovery.sqlite3.Error) as error:
        result['reference_registration'] = {'status': 'error', 'error': str(error)}
    return result


def parameter_reference_paths(parameters, names):
    """显式选中的宏参数中，只有精确的 {object_id} 包装会转换成 STAR 对象。"""
    if names is None:
        return []
    if (not isinstance(parameters, dict) or not isinstance(names, list)
            or any(not isinstance(name, str) or name not in parameters for name in names)
            or len(set(names)) != len(names)):
        raise ValueError('object_parameters must contain unique existing parameter names')
    paths = []

    def visit(value, path):
        if len(path) > 64:
            raise ValueError('Object parameter nesting exceeds 64 levels')
        if isinstance(value, dict):
            if set(value) == {'object_id'}:
                paths.append(path)
            else:
                for key in sorted(value):
                    visit(value[key], [*path, key])
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, [*path, index])

    for name in sorted(names):
        visit(parameters[name], [name])
    return paths


def bind_parameters(session_id, parameters, paths):
    """冻结声明为对象参数的引用路径；实际对象在用户步骤开始前一次性解析。"""
    bindings = []
    for path in paths:
        value = parameters
        for part in path:
            value = value[part]
        if not isinstance(value, dict) or set(value) != {'object_id'}:
            raise ValueError('Object reference parameters require exactly object_id')
        bindings.append({'path': path, 'binding': object_binding(session_id, value['object_id'])})
    return bindings


def expected_value(session_id, value):
    """剥离由 Core 追加的导航 ID，保留 STAR 的原始值；ID 与原 reference 不符则拒绝。"""
    if isinstance(value, dict):
        if 'object_id' in value and isinstance(value.get('reference'), dict):
            binding = object_binding(session_id, value['object_id'])
            key = binding.get('object_key') or binding['path'][-1]['key']
            if value['reference'] != {'session_token': binding['session_token'], 'key': key}:
                raise ValueError('Expected object_id and reference disagree')
            value = {key: item for key, item in value.items() if key != 'object_id'}
        return {key: expected_value(session_id, item) for key, item in value.items()}
    if isinstance(value, list):
        return [expected_value(session_id, item) for item in value]
    return value


def selection(property_ids):
    """所有读取显式选择属性，避免两个能力来源有不同的省略语义。"""
    if (not isinstance(property_ids, list) or not 1 <= len(property_ids) <= 500
            or any(not isinstance(item, str) or not item for item in property_ids)
            or len(property_ids) != len(set(property_ids))):
        raise ValueError('property_ids must contain 1 to 500 unique non-empty IDs')
    return property_ids
