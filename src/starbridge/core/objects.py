"""统一公开对象引用与属性结果，目录和运行时规则只作为内部能力来源。

对象 ID 绑定当前会话世代；稳定 locator 只用于重新查找，不能代替当前身份。
本模块不推测类型适配、不补写 expected，也不改变执行器的版本和写入边界。
"""

from copy import deepcopy

from . import discovery


def resolve(session_id, object_id):
    """从引用表解析已返回的对象；目录句柄携带完整父路径和首次观察的身份。"""
    state = discovery.reference_state(session_id)
    if isinstance(object_id, str) and object_id.startswith('n_'):
        discovery._decode(object_id, state, 'node')
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
              if key not in ('node_id', 'path', 'key', 'parent_key', 'locator')}
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


def assignment_value(session_id, value):
    """只展开新值中明确的对象引用；执行器继续校验值类型、关系和单位。"""
    if isinstance(value, dict):
        if set(value) == {'object_id'}:
            return catalog_target(session_id, value['object_id'])
        if {'type', 'name'} <= value.keys():
            raise ValueError('New references require object_id, not a catalog target')
        return {key: assignment_value(session_id, item) for key, item in value.items()}
    if isinstance(value, list):
        return [assignment_value(session_id, item) for item in value]
    return value


def selection(property_ids):
    """所有读取显式选择属性，避免两个能力来源有不同的省略语义。"""
    if (not isinstance(property_ids, list) or not 1 <= len(property_ids) <= 500
            or any(not isinstance(item, str) or not item for item in property_ids)
            or len(property_ids) != len(set(property_ids))):
        raise ValueError('property_ids must contain 1 to 500 unique non-empty IDs')
    return property_ids
