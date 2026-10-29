"""校验人工执行映射并裁剪读写计划，供文件与会话入口共用。

候选目录证明成员声明存在，人工映射说明如何访问对象及读取值。只有两者
版本、签名和指纹一致时才输出 Java 可执行计划；请求本身不能提供 Java 调用。
"""

import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from .catalog import CatalogError, _keys, _pinned_member, _require, load, read_json


ADAPTERS = {'primitive', 'reference', 'collection', 'quantity', 'vector', 'enum', 'query',
            'name', 'type_name', 'names', 'enum_name', 'presence', 'java_class',
            'tensor_profile', 'tensor_basis', 'tensor_method_state',
            'tensor_components', 'tensor_method_basis', 'tensor_layout_valid'}
WRITE_ADAPTERS = {
    'primitive': {'value'},
    'field_definition': {'value'},
    'enum': {'value'},
    'scalar_expression': {'definition', 'units'},
    'scalar_value': {'number', 'units'},
    'vector_expression': {'definition', 'units'},
    'vector_value': {'x', 'y', 'z', 'units'},
    'reference': {'value'},
    'object_selection': {'value'},
    'user_tags': {'value'},
}
# 结构操作的参数只用于其最终调用，不能混入普通属性 writer 的契约。
OPERATION_ADAPTERS = {'profile_method': {'method'}}
JAVA_TYPE = re.compile(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:\[\])*\Z')
PRIMITIVES = {'boolean', 'byte', 'char', 'short', 'int', 'long', 'float', 'double'}
QUERY_OPERATORS = {
    'name': {'Contains', 'DoesNotContain', 'Matches', 'DoesNotMatch', 'StartsWith',
             'DoesNotStartWith', 'EndsWith', 'DoesNotEndWith', 'RegexContains', 'RegexDoesNotContain'},
    'java_type': {'Is', 'IsNot'},
    'compound': {'And', 'Or'},
    'tag': {'Contains', 'DoesNotContain', 'ContainsInherited', 'DoesNotContainInherited'},
}


def _text(value, where):
    """要求标识符或名称是非空字符串，避免把 null 或数值隐式转成定位文本。"""
    _require(isinstance(value, str) and bool(value), f'Expected non-empty string: {where}')


def _literal(value):
    """初版调用参数只接受 JSON 标量；数组、对象和引用需有明确的类型适配器。"""
    _require(value is None or type(value) in (str, bool, int, float),
             'Pipeline literals must be JSON scalars')
    if type(value) is float:
        _require(math.isfinite(value), 'Pipeline literals must be finite')
    if type(value) is int:
        _require(-(2 ** 63) <= value < 2 ** 63, 'Pipeline integer is outside signed 64-bit range')


def _binary_class(catalog, name):
    """按类型页文件名识别嵌套类，将 Javadoc 的点号名称转成 JVM 的美元符号名称。"""
    _require(name in catalog['types'], f'Unknown Java class: {name}')
    stem = Path(catalog['types'][name]['source']['path']).stem
    _require(name.endswith('.' + stem), f'Type source does not match class name: {name}')
    return name[:-len(stem)] + stem.replace('.', '$')


def _parameter_type(catalog, declaration, name):
    """只解析材料能证明的参数类型；裸类型变量 T 不会被当成可加载类。"""
    suffix = ''
    while name.endswith('[]'):
        name, suffix = name[:-2], suffix + '[]'
    if name in PRIMITIVES:
        return name + suffix
    if name in catalog['types']:
        return _binary_class(catalog, name) + suffix
    # 标准库类不在 STAR 类型表中，使用当前成员的官方 Javadoc 类型链接证明来源。
    for link in declaration['links']:
        path = urlsplit(link).path
        if '/api/' not in path or not path.endswith('.html'):
            continue
        parts = path.split('/api/', 1)[1].split('/')
        if '.' in parts[0]:  # Java 9+ 的第一段是 java.base 等模块名。
            parts = parts[1:]
        canonical = '.'.join(parts)[:-5]
        if canonical == name:
            return '.'.join(parts[:-1] + [parts[-1][:-5].replace('.', '$')]) + suffix
    raise CatalogError(f'Unresolved reflection parameter type: {name}')


def _member(catalog, identifier, entry):
    """核对人工指定的 public 实例方法及反射参数；泛型擦除不明确时拒绝猜测。"""
    _keys(entry, 'type member signature fingerprint parameter_types effect', identifier)
    ref = {key: entry[key] for key in ('type', 'member', 'signature', 'fingerprint')}
    _pinned_member(catalog, ref)
    declaration = catalog['types'][ref['type']]['members'][ref['member']]
    modifiers = declaration['modifiers'].split()
    _require('public' in modifiers and 'static' not in modifiers,
             f'Execution requires a public instance method: {identifier}')
    anchor = ref['member']
    _require('(' in anchor and anchor.endswith(')') and not anchor.startswith('<'),
             f'Execution requires a method, not a field or constructor: {identifier}')
    _require(entry['effect'] in ('read', 'write'), f'Unknown method effect: {identifier}')
    parameters = entry['parameter_types']
    _require(isinstance(parameters, list)
             and all(isinstance(x, str) and JAVA_TYPE.fullmatch(x) for x in parameters),
             f'Invalid reflection parameter types: {identifier}')
    documented = anchor.partition('(')[2][:-1]
    # 枚举 setter 的 T 擦除为首个上界 Enum；只对已确认的声明应用此规则。
    # 类声明和官方类型链接必须同时证明上界，其他泛型仍拒绝猜测。
    if ref['type'] == 'star.common.EnumeratedOption' and anchor == 'setSelected(T)':
        owner = catalog['types'][ref['type']]
        _require('EnumeratedOption<T extends Enum<T> & Localizable & SerializableEnum>' in owner['signature'],
                 'Unconfirmed EnumeratedOption generic bound')
        expected = [_parameter_type(catalog, owner, 'java.lang.Enum')]
    else:
        expected = [_parameter_type(catalog, declaration, name)
                    for name in documented.split(',')] if documented else []
    _require(parameters == expected, f'Unresolved or mismatched method parameters: {identifier}')
    return {'owner': _binary_class(catalog, ref['type']),
            'name': declaration['name'], 'parameter_types': parameters, 'effect': entry['effect']}


def _pipeline(catalog, methods, pipeline, where, *, write_adapter=None):
    """将已核对的方法 ID 编译为调用序列；每一步的接收对象来自上一步结果。"""
    _keys(pipeline, 'root steps', where)
    _require(pipeline['root'] in ('simulation', 'object', 'parent'), f'Invalid pipeline root: {where}')
    # 只读空管线返回根对象本身，供 Profile 等值适配器读取已经定位的对象。
    # 写入仍必须包含显式 setter，不能把恒等读取误当作修改成功。
    _require(isinstance(pipeline['steps'], list) and (write_adapter is None or bool(pipeline['steps'])),
             f'Pipeline steps must be a list; write pipelines cannot be empty: {where}')
    compiled = []
    for index, step in enumerate(pipeline['steps']):
        _keys(step, 'member arguments', where)
        _text(step['member'], 'step.member')
        _require(step['member'] in methods, f'Unknown execution member: {step["member"]}')
        member = methods[step['member']]
        is_final_write = write_adapter is not None and index == len(pipeline['steps']) - 1
        _require(member['effect'] == ('write' if is_final_write else 'read'),
                 f'Only the last call of a write pipeline may mutate: {where}')
        arguments = step['arguments']
        _require(isinstance(arguments, list) and len(arguments) == len(member['parameter_types']),
                 f'Wrong argument count: {step["member"]}')
        compiled_arguments = []
        for arg in arguments:
            _require(isinstance(arg, dict) and len(arg) == 1, 'Arguments require exactly one source')
            if 'class' in arg:
                _text(arg['class'], 'argument.class')
                _require(arg['class'] in catalog['types'], f'Unknown class argument: {arg["class"]}')
                arg = {'class': _binary_class(catalog, arg['class'])}
            elif 'literal' in arg:
                _literal(arg['literal'])
            elif 'context' in arg:
                contexts = {**WRITE_ADAPTERS, **OPERATION_ADAPTERS}
                allowed = {'object', 'parent'} | (contexts[write_adapter] if is_final_write else set())
                _require(isinstance(arg['context'], str) and arg['context'] in allowed,
                         'Unsupported argument context')
            else:
                raise CatalogError('Unknown argument source')
            compiled_arguments.append(arg)
        compiled.append({**member, 'arguments': compiled_arguments})
    return {'root': pipeline['root'], 'steps': compiled}


def _guards(catalog, methods, source, *, has_parent):
    """编译目标或关联对象的只读条件，逐项核对标识、值及父路径是否可用。"""
    guards = []
    _require(isinstance(source, list), 'Write guards must be a list')
    for guard in source:
        _keys(guard, 'id read adapter expected message', 'write guard')
        _text(guard['id'], 'guard.id')
        _text(guard['message'], 'guard.message')
        _require(guard['id'] not in {g['id'] for g in guards}, 'Duplicate write guard')
        _require(isinstance(guard['adapter'], str) and guard['adapter'] in ADAPTERS,
                 'Unsupported guard adapter')
        _json_value(guard['expected'])
        read = _pipeline(catalog, methods, guard['read'], 'guard.' + guard['id'])
        _require(read['root'] != 'parent' or has_parent, 'Guard has no parent context')
        guards.append({**guard, 'read': read})
    return guards


def _operations(catalog, methods, source, types, properties):
    """编译结构操作及其影响范围，确保操作使用独立的读取集合和最终调用。

    Profile 方法切换可能改变分量组织，不能强制读取当前方法不存在的矩阵属性。
    read_properties 显式声明修改前后必须完整读取的状态，preserved_properties
    声明应保持不变的字段；状态属性自身允许随方法改变，但必须能完整回读。
    """
    _require(isinstance(source, dict) and source.keys() == types.keys(),
             'Operations must describe every execution type exactly once')
    operations = {}
    for type_id, entries in source.items():
        _require(isinstance(entries, dict), f'Invalid operations: {type_id}')
        operations[type_id] = {}
        for name, entry in entries.items():
            _text(name, 'operation ID')
            where = type_id + '.' + name
            _keys(entry, 'adapter reason read_properties state_property methods available write guards '
                         'impacts preserved_properties', where)
            _require(entry['adapter'] == 'profile_method', f'Unsupported operation adapter: {where}')
            _text(entry['reason'], 'operation.reason')
            for key in ('read_properties', 'preserved_properties'):
                value = entry[key]
                _require(isinstance(value, list) and bool(value)
                         and all(isinstance(item, str) and item in properties[type_id] for item in value)
                         and len(value) == len(set(value)), f'Invalid operation {key}: {where}')
            state = entry['state_property']
            _require(isinstance(state, str) and state in entry['read_properties'],
                     f'Operation state property must be read: {where}')
            _require(properties[type_id][state]['adapter'] == 'tensor_method_state',
                     f'Profile method operation requires tensor_method_state: {where}')
            _require(set(entry['preserved_properties']) <= set(entry['read_properties'])
                     and state not in entry['preserved_properties'],
                     f'Operation preserved properties must exclude its mutable state: {where}')

            # 1. 方法 ID 只映射目录内的已知类；请求不能指定任意 Java 类。
            choices = entry['methods']
            _require(isinstance(choices, dict) and bool(choices), f'Missing operation methods: {where}')
            compiled_choices = {}
            for method_id, java_class in choices.items():
                _text(method_id, 'method ID')
                _require(isinstance(java_class, str) and java_class in catalog['types'],
                         f'Unknown operation method class: {where}.{method_id}')
                compiled_choices[method_id] = _binary_class(catalog, java_class)
            _require(len(set(compiled_choices.values())) == len(compiled_choices),
                     f'Duplicate operation method classes: {where}')

            # 2. 可选方法只能只读枚举；最终 setter 仅消费运行时选中的方法对象。
            available = _pipeline(catalog, methods, entry['available'], where + '.available')
            write = _pipeline(catalog, methods, entry['write'], where + '.write',
                              write_adapter=entry['adapter'])
            _require(available['root'] == 'object' and write['root'] == 'object',
                     f'Profile method operations must start at the target object: {where}')
            _require(write['steps'][-1]['arguments'] == [{'context': 'method'}]
                     and write['steps'][-1]['parameter_types'] == ['star.common.ProfileMethod'],
                     f'Profile method setter must consume exactly one ProfileMethod: {where}')
            guards = _guards(catalog, methods, entry['guards'],
                             has_parent=types[type_id]['parent_type'] is not None)
            _require(isinstance(entry['impacts'], list) and bool(entry['impacts']),
                     f'Operation requires affected-object descriptions: {where}')
            scopes = set()
            for impact in entry['impacts']:
                _keys(impact, 'scope description', 'operation impact')
                _require(impact['scope'] in ('target', 'owned_objects') and impact['scope'] not in scopes,
                         f'Unsupported or duplicate operation impact scope: {where}')
                scopes.add(impact['scope'])
                _text(impact['description'], 'impact.description')
            _require('target' in scopes, f'Operation must describe its target impact: {where}')
            operations[type_id][name] = {**entry, 'methods': compiled_choices, 'available': available,
                                         'write': write, 'guards': guards}
    return operations


def load_execution(catalog_path, execution_path):
    """加载共享候选目录及人工执行映射，返回已校验的完整运行时目录。

    不访问安装或算例；运行 server 版本检查由 Java 在第一次目录调用前执行。
    catalog_id 覆盖执行映射和版本；成员声明另外由映射中的指纹锁定。
    """
    catalog = load(catalog_path)
    rules = read_json(execution_path)
    _require(isinstance(rules, dict), 'Execution rules must be an object')
    _require(type(rules.get('schema_version')) is int and rules['schema_version'] in (1, 2, 3, 4, 5),
             'Unsupported execution schema_version')
    _keys(rules, 'schema_version target members types properties'
          + (' operations' if rules['schema_version'] >= 5 else ''), 'execution')
    _require(rules['target'] == catalog['target'], 'Execution catalog version mismatch')
    _require(isinstance(rules['members'], dict) and bool(rules['members']), 'Missing execution members')
    methods = {}
    for identifier, member in rules['members'].items():
        _text(identifier, 'member ID')
        methods[identifier] = _member(catalog, identifier, member)
        _require(rules['schema_version'] >= 2 or methods[identifier]['effect'] == 'read',
                 'Execution schema 1 cannot contain write methods')

    # 1. 先校验全部类型和定位管线，再核对父类型引用与循环。
    _require(isinstance(rules['types'], dict) and bool(rules['types']), 'Missing execution types')
    types = {}
    for identifier, entry in rules['types'].items():
        _text(identifier, 'type ID')
        _keys(entry, 'java_class parent_type locate', identifier)
        _text(entry['java_class'], 'java_class')
        _require(entry['java_class'] in catalog['types'], f'Unknown Java type: {identifier}')
        _require(entry['parent_type'] is None or isinstance(entry['parent_type'], str),
                 f'Invalid parent type: {identifier}')
        locate = _pipeline(catalog, methods, entry['locate'], identifier + '.locate')
        expected_root = 'simulation' if entry['parent_type'] is None else 'parent'
        _require(locate['root'] == expected_root, f'Locator must start at {expected_root}: {identifier}')
        types[identifier] = {**entry, 'java_class': _binary_class(catalog, entry['java_class']),
                             'locate': locate}
    for identifier in types:
        visited = set()
        current = identifier
        while current is not None:
            _require(current in types, f'Unknown parent type: {current}')
            _require(current not in visited, f'Cyclic parent types: {identifier}')
            visited.add(current)
            current = types[current]['parent_type']

    # 2. 读写管线分别检查；读取不能混入 setter，写入只能在最后一步改变状态。
    _require(isinstance(rules['properties'], dict) and rules['properties'].keys() == types.keys(),
             'Properties must describe every execution type exactly once')
    properties = {}
    for identifier, entries in rules['properties'].items():
        _require(isinstance(entries, dict) and bool(entries), f'Missing properties: {identifier}')
        properties[identifier] = {}
        for name, entry in entries.items():
            _text(name, 'property ID')
            fields = 'adapter read writable reason' + (' write' if 'write' in entry else '')
            _keys(entry, fields, identifier + '.' + name)
            _require(isinstance(entry['adapter'], str) and entry['adapter'] in ADAPTERS,
                     f'Unsupported read adapter: {identifier}.{name}')
            _require(type(entry['writable']) is bool and entry['writable'] == ('write' in entry),
                     'Writable state must match an explicit write contract')
            _text(entry['reason'], 'property.reason')
            read = _pipeline(catalog, methods, entry['read'], identifier + '.' + name)
            _require(read['root'] != 'parent' or types[identifier]['parent_type'] is not None,
                     f'Property has no parent context: {identifier}.{name}')
            properties[identifier][name] = {**entry, 'read': read}
            if 'write' in entry:
                _require(rules['schema_version'] >= 2, 'Writes require execution schema 2 or later')
                write = entry['write']
                _require(isinstance(write, dict), 'Write contract must be an object')
                selection = write.get('adapter') == 'object_selection'
                related = selection or write.get('adapter') == 'reference'
                fields = 'adapter ' + ('pipelines' if selection else 'pipeline')
                fields += ' value_types' if related else ''
                fields += ' value_guards' if write.get('adapter') == 'reference' else ''
                fields += ' guards' if 'guards' in write else ''
                _keys(write, fields, identifier + '.' + name + '.write')
                _require(not related or rules['schema_version'] >= 4,
                         'Reference and selection writers require execution schema 4')
                if rules['schema_version'] == 2:
                    _require('guards' not in write and write['adapter'] in
                             ('primitive', 'scalar_expression', 'scalar_value', 'user_tags'),
                             'Typed writers and guards require execution schema 3')
                    # schema 2 的 primitive 专指场函数定义，升级不能放宽旧契约。
                    if write['adapter'] == 'primitive':
                        write = {**write, 'adapter': 'field_definition'}
                _require(isinstance(write['adapter'], str) and write['adapter'] in WRITE_ADAPTERS,
                         'Unsupported write adapter')
                expected_reader = {'primitive': 'primitive', 'field_definition': 'primitive',
                                   'scalar_expression': 'quantity', 'scalar_value': 'quantity',
                                   'vector_expression': 'vector', 'vector_value': 'vector',
                                   'enum': 'enum', 'user_tags': 'collection', 'reference': 'reference',
                                   'object_selection': 'query'}[write['adapter']]
                _require(entry['adapter'] == expected_reader, 'Read and write adapters do not agree')
                # 静态选择和动态规则各有一个终点；每个请求只选择一个 setter。
                pipelines = write['pipelines'] if selection else {'single': write['pipeline']}
                if selection:
                    _keys(pipelines, 'static query', 'selection pipelines')
                compiled = {}
                for mode, pipeline in pipelines.items():
                    compiled[mode] = _pipeline(catalog, methods, pipeline,
                                              identifier + '.' + name + '.write.' + mode,
                                              write_adapter=write['adapter'])
                    _require(compiled[mode]['root'] != 'parent' or types[identifier]['parent_type'] is not None,
                             f'Write property has no parent context: {identifier}.{name}')
                guards = _guards(catalog, methods, write.get('guards', []),
                                 has_parent=types[identifier]['parent_type'] is not None)
                writer = {**write, 'guards': guards}
                writer.update({'pipelines': compiled} if selection else {'pipeline': compiled['single']})
                if related:
                    _require(isinstance(write['value_types'], list) and bool(write['value_types'])
                             and all(isinstance(t, str) and t in types for t in write['value_types'])
                             and len(set(write['value_types'])) == len(write['value_types']),
                             'Writer value_types must be unique mapped types')
                if write['adapter'] == 'reference':
                    writer['value_guards'] = _guards(catalog, methods, write['value_guards'], has_parent=all(
                        types[t]['parent_type'] is not None for t in write['value_types']))
                    properties[identifier][name]['value_guards'] = [
                        {key: g[key] for key in ('id', 'expected', 'message')} for g in writer['value_guards']]
                if related:
                    properties[identifier][name]['value_types'] = write['value_types']
                properties[identifier][name]['write'] = writer
                # describe 去除执行管线后仍可展示前提；不把描述当作已完成运行检查。
                properties[identifier][name]['guards'] = [
                    {key: guard[key] for key in ('id', 'expected', 'message')} for guard in guards]
    operations = _operations(catalog, methods, rules.get('operations', {name: {} for name in types}),
                             types, properties)
    fingerprint = json.dumps(rules, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return {'schema_version': 1, 'target': catalog['target'],
            'catalog_id': hashlib.sha256(fingerprint.encode('utf-8')).hexdigest(),
            'types': types, 'properties': properties, 'operations': operations}


def _target(plan, target, depth=0):
    """校验明确的层级定位与可选会话引用；文件重载应使用不带 reference 的定位。"""
    _require(depth < 16, 'Target nesting exceeds supported depth')
    _require(isinstance(target, dict) and {'type', 'name'} <= target.keys()
             and target.keys() <= {'type', 'name', 'parent', 'reference'}, 'Invalid target fields')
    _text(target['type'], 'target.type')
    _text(target['name'], 'target.name')
    _require(target['type'] in plan['types'], f'Unknown target type: {target["type"]}')
    parent_type = plan['types'][target['type']]['parent_type']
    if parent_type is None:
        _require('parent' not in target, 'Target type does not accept a parent')
    else:
        _require('parent' in target, f'Target requires parent type: {parent_type}')
        _target(plan, target['parent'], depth + 1)
        _require(target['parent']['type'] == parent_type, f'Target requires parent type: {parent_type}')
    if 'reference' in target:
        _keys(target['reference'], 'session_token key', 'reference')
        _text(target['reference']['session_token'], 'reference.session_token')
        _text(target['reference']['key'], 'reference.key')


def prepare_read(catalog_path, execution_path, request_path, action):
    """校验 describe/read 请求并返回裁剪计划与原请求，不创建运行目录或活动标记。

    计划只包含请求目标及其父类型的定位和选定属性，避免把全量 API 放入宏常量。
    describe 另保留目标条件的只读管线；新关联条件需要输入值，仍只提供摘要。
    未映射属性立即拒绝，不因为候选目录中存在 getter 就猜测运行方式。
    """
    _require(action in ('describe', 'read'), 'Unsupported catalog read action')
    plan = load_execution(catalog_path, execution_path)
    request = read_json(request_path)
    _require(isinstance(request, dict)
             and {'schema_version', 'action', 'target'} <= request.keys()
             and request.keys() <= {'schema_version', 'action', 'target', 'properties'},
             'Invalid catalog request fields')
    _require(type(request['schema_version']) is int and request['schema_version'] == 1,
             'Unsupported catalog request schema_version')
    _require(request['action'] == action, 'Catalog request action does not match command')
    _target(plan, request['target'])
    identifier = request['target']['type']
    names = request.get('properties', list(plan['properties'][identifier]))
    _require(isinstance(names, list) and bool(names)
             and all(isinstance(name, str) and name for name in names)
             and len(names) == len(set(names)), 'Properties must be unique non-empty IDs')
    _require(set(names) <= plan['properties'][identifier].keys(),
             f'Unknown or unmapped properties: {sorted(set(names) - plan["properties"][identifier].keys())}')
    required = {}
    current = identifier
    while current is not None:
        required[current] = plan['types'][current]
        current = plan['types'][current]['parent_type']
    # 不向读取宏发送任何 setter；条件只使用加载时已验证 effect=read 的管线。
    properties = {}
    for name in names:
        source = plan['properties'][identifier][name]
        entry = {key: value for key, value in source.items() if key != 'write'}
        if action == 'describe':
            entry['condition_reads'] = source.get('write', {}).get('guards', [])
        properties[name] = entry
    operations = {identifier: {name: {key: value for key, value in entry.items() if key != 'write'}
                              for name, entry in plan['operations'][identifier].items()}}
    return ({**plan, 'types': required, 'properties': {identifier: properties},
             'operations': operations if action == 'describe' else {}}, request)


def _json_value(value):
    """检查预期值中的所有标量，避免非有限数值或超范围整数进入 Java 常量。"""
    if isinstance(value, dict):
        for item in value.values():
            _json_value(item)
    elif isinstance(value, list):
        for item in value:
            _json_value(item)
    else:
        _literal(value)


def _reference_state(value):
    """保留旧关联的名称与实际类；会话引用不作为跨加载的旧状态前提。"""
    if value is None:
        return None
    _require(isinstance(value, dict) and value.keys() in (
        {'name', 'java_class'}, {'name', 'java_class', 'reference'}), 'Invalid expected object reference')
    _text(value['name'], 'reference.name')
    _text(value['java_class'], 'reference.java_class')
    if 'reference' in value:
        _keys(value['reference'], 'session_token key', 'expected object reference')
        _text(value['reference']['session_token'], 'expected reference token')
        _text(value['reference']['key'], 'expected reference key')
    return {key: value[key] for key in ('name', 'java_class')}


def _selection_value(plan, writer, value, *, expected=False):
    """校验完整静态选择或动态规则；新引用保留定位路径，旧引用去掉会话元数据。

    动态规则不在本地求值。类型谓词只能使用写映射允许的类，标签谓词只解析
    已映射的用户标签；两种参数都不能变成调用者提供的任意 Java 类加载。
    """
    _require(isinstance(value, dict), 'Object selection must be an object')
    mode = value.get('mode')
    if mode == 'static':
        _keys(value, 'mode objects', 'static selection')
        _require(isinstance(value['objects'], list), 'Static objects must be a list')
        if expected:
            objects = [_reference_state(item) for item in value['objects']]
            _require(all(item is not None for item in objects), 'Selected objects cannot be null')
            # 保留同名同类项的数量，不能把不同父对象下的同名边界合并成一项。
            objects.sort(key=lambda item: (item['name'], item['java_class']))
            return {**value, 'objects': objects}
        for target in value['objects']:
            _target(plan, target)
            _require(target['type'] in writer['value_types'], 'Unsupported selected object type')
        return value
    _require(mode == 'query', 'Unsupported object selection mode')
    _keys(value, 'mode predicate modifiers', 'query selection')
    modifiers = value['modifiers']
    _require(isinstance(modifiers, list) and all(m == 'PrefilterNamedObjects' for m in modifiers)
             and len(modifiers) == len(set(modifiers)), 'Unsupported or duplicate query modifiers')
    count = 0

    def predicate(rule, depth=0):
        """根节点深度为零；限制边数和总节点数，避免任意深递归进入宏编译或执行。"""
        nonlocal count
        count += 1
        _require(depth <= 16 and count <= 256, 'Query exceeds depth or node limit')
        _require(isinstance(rule, dict), 'Query predicate must be an object')
        kind = rule.get('type')
        _require(isinstance(kind, str) and kind in QUERY_OPERATORS, 'Unsupported query predicate')
        _keys(rule, 'type operator ' + ('predicates' if kind == 'compound' else 'value'), 'predicate')
        _require(isinstance(rule['operator'], str) and rule['operator'] in QUERY_OPERATORS[kind],
                 'Unsupported query operator')
        if kind == 'compound':
            _require(isinstance(rule['predicates'], list), 'Compound predicates must be a list')
            return {**rule, 'predicates': [predicate(p, depth + 1) for p in rule['predicates']]}
        if kind == 'tag':
            if expected:
                tag = _reference_state(rule['value'])
                _require(tag is not None, 'Tag predicate requires a tag')
                return {**rule, 'value': tag}
            _target(plan, rule['value'])
            _require(rule['value']['type'] == 'user_tag', 'Tag predicate requires a user_tag target')
        else:
            _require(isinstance(rule['value'], str), 'Predicate value must be a string')
            if kind == 'java_type':
                _require(bool(JAVA_TYPE.fullmatch(rule['value'])), 'Invalid predicate Java class')
                if not expected:
                    classes = {plan['types'][t]['java_class'] for t in writer['value_types']}
                    _require(rule['value'] in classes, 'Query type is outside writer value_types')
        return rule

    return {**value, 'predicate': predicate(value['predicate']), 'modifiers': sorted(modifiers)}


def _operation_request(plan, request):
    """检查结构操作请求并规范方向引用；保留完整旧状态供 server 严格相等比较。

    方向对象的会话引用不承担跨文件加载身份；只按已有引用契约移除这两个明确
    字段的 reference。其他旧状态字段不删除、不补默认值，不能掩盖缺失设置。
    """
    _keys(request, 'schema_version action target operation expected arguments', 'operation request')
    _require(type(request['schema_version']) is int and request['schema_version'] == 3,
             'Structural operations require schema_version 3')
    _require(request['action'] == 'modify', 'Structural operation action must be modify')
    _target(plan, request['target'])
    type_id = request['target']['type']
    _text(request['operation'], 'operation ID')
    _require(request['operation'] in plan['operations'].get(type_id, {}), 'Unknown structural operation')
    operation = plan['operations'][type_id][request['operation']]
    _keys(request['arguments'], 'method', 'operation arguments')
    _text(request['arguments']['method'], 'operation method')
    _require(request['arguments']['method'] in operation['methods'], 'Unknown or unsupported profile method')
    _json_value(request['expected'])
    expected = request['expected']
    _keys(expected, 'java_class method dimensions is_3d shape storage coordinate_system local_orientation components',
          'expected tensor method state')
    for field in ('java_class', 'method', 'dimensions', 'storage'):
        _text(expected[field], 'expected.' + field)
    _require(expected['method'] in operation['methods'].values(), 'Expected method is outside the operation mapping')
    # shape 表示二维或三维二阶张量；布尔维度标志和整数矩阵尺寸必须一致。
    dimension = 3 if expected['is_3d'] is True else 2
    _require(type(expected['is_3d']) is bool and isinstance(expected['shape'], list)
             and all(type(size) is int for size in expected['shape'])
             and expected['shape'] == [dimension, dimension],
             'Expected tensor state requires a boolean is_3d and matching 2D or 3D shape')
    _require(isinstance(expected['components'], list) and bool(expected['components'])
             and all(isinstance(component, dict) for component in expected['components']),
             'Expected method state requires its component settings')
    expected = {**expected, **{key: _reference_state(expected[key])
                              for key in ('coordinate_system', 'local_orientation')}}
    return {**request, 'expected': expected}


def _prepare_operation(plan, request):
    """仅保留选定操作及其完整读取集合；其他属性和操作的 setter 不进入宏。"""
    request = _operation_request(plan, request)
    type_id = request['target']['type']
    operation = plan['operations'][type_id][request['operation']]
    required = {}
    current = type_id
    while current is not None:
        required[current] = plan['types'][current]
        current = plan['types'][current]['parent_type']
    properties = {name: {key: value for key, value in plan['properties'][type_id][name].items()
                         if key != 'write'} for name in operation['read_properties']}
    return ({**plan, 'types': required, 'properties': {type_id: properties},
             'operations': {type_id: {request['operation']: operation}}}, request)


def prepare_modification(catalog_path, execution_path, request_path):
    """校验属性或结构操作请求并裁剪写入计划；旧状态和实际可写条件在 server 再核对。

    修改请求格式与旧 Modifier 分开版本化。新值在本地按适配器检查，最终方法和
    参数在 Java 准备阶段解析；活动请求标记之前不会启动客户端或尝试 setter。
    """
    plan = load_execution(catalog_path, execution_path)
    request = read_json(request_path)
    if isinstance(request, dict) and type(request.get('schema_version')) is int and request['schema_version'] == 3:
        return _prepare_operation(plan, request)
    _keys(request, 'schema_version action target property expected value', 'modification')
    _require(type(request['schema_version']) is int and request['schema_version'] == 2,
             'Catalog modification requires schema_version 2')
    _require(request['action'] == 'modify', 'Catalog modification action must be modify')
    _target(plan, request['target'])
    identifier = request['target']['type']
    _text(request['property'], 'property ID')
    properties = plan['properties'][identifier]
    _require(request['property'] in properties, 'Unknown modification property')
    prop = properties[request['property']]
    _require('write' in prop and prop['writable'], 'Property has no write implementation')
    _json_value(request['expected'])
    _json_value(request['value'])
    adapter, value = prop['write']['adapter'], request['value']
    if adapter == 'reference':
        _target(plan, value)
        _require(value['type'] in prop['write']['value_types'], 'Unsupported reference value type')
        request = {**request, 'expected': _reference_state(request['expected'])}
    elif adapter == 'object_selection':
        request = {**request,
                   'value': _selection_value(plan, prop['write'], value),
                   'expected': _selection_value(plan, prop['write'], request['expected'], expected=True)}
    elif adapter == 'field_definition':
        _require(isinstance(value, str) and bool(value.strip()), 'Definition must be a non-empty string')
        _require(isinstance(request['expected'], str), 'Expected definition must be a string')
    elif adapter == 'primitive':
        old = request['expected']
        _require(type(value) in (str, bool, int, float), 'Primitive value must be a JSON scalar')
        _require(type(old) is type(value) or
                 (type(old) in (int, float) and type(value) in (int, float)),
                 'Primitive value must match the expected JSON scalar type')
    elif adapter == 'enum':
        _text(value, 'enum value')
        _keys(request['expected'], 'selected allowed', 'expected enum')
        old = request['expected']
        _require(isinstance(old['allowed'], list) and all(isinstance(v, str) and v for v in old['allowed'])
                 and len(old['allowed']) == len(set(old['allowed'])), 'Invalid expected enum choices')
        _require(old['selected'] is None or old['selected'] in old['allowed'], 'Invalid expected enum selection')
        _require(value in old['allowed'], 'Enum value is not among expected allowed choices')
    elif adapter in ('vector_expression', 'vector_value'):
        field = 'definition' if adapter == 'vector_expression' else 'components'
        _keys(value, field + ' unit', 'vector value')
        _require(isinstance(value['unit'], str), 'Vector unit must be a string')
        if field == 'definition':
            _require(isinstance(value[field], str) and bool(value[field].strip()),
                     'Vector definition must be a non-empty string')
        else:
            _require(isinstance(value[field], list) and len(value[field]) == 3
                     and all(type(v) in (int, float) and math.isfinite(v) for v in value[field]),
                     'Vector components must contain three finite numbers')
        old = request['expected']
        _keys(old, 'definition unit components', 'expected vector')
        _require(isinstance(old['definition'], str) and isinstance(old['unit'], str),
                 'Expected vector requires definition and unit')
        _require(isinstance(old['components'], list) and len(old['components']) == 3
                 and all((type(v) in (int, float) and math.isfinite(v)) or
                         (isinstance(v, str) and v in ('NaN', 'Infinity', '-Infinity'))
                         for v in old['components']), 'Invalid expected vector components')
    elif adapter in ('scalar_expression', 'scalar_value'):
        field = 'definition' if adapter == 'scalar_expression' else 'value'
        _keys(value, field + ' unit', 'scalar value')
        _require(isinstance(value['unit'], str), 'Scalar unit must be a string')
        if field == 'definition':
            _require(isinstance(value[field], str) and bool(value[field].strip()),
                     'Scalar definition must be a non-empty string')
        else:
            _require(type(value[field]) in (int, float) and math.isfinite(value[field]),
                     'Scalar value must be a finite number')
        _keys(request['expected'], 'definition unit si_unit raw_value si_value', 'expected quantity')
        _require(all(isinstance(request['expected'][k], str) for k in ('definition', 'unit', 'si_unit')),
                 'Expected quantity requires definition and units')
        for key in ('raw_value', 'si_value'):
            old = request['expected'][key]
            _require((type(old) in (int, float) and math.isfinite(old))
                     or (isinstance(old, str) and old in ('NaN', 'Infinity', '-Infinity')),
                     'Expected quantity values must preserve numeric or non-finite readback types')
    else:
        _require(isinstance(value, list) and all(isinstance(v, str) and v for v in value)
                 and len(value) == len(set(value)), 'Tags must be unique non-empty names')
        _require(isinstance(request['expected'], list), 'Expected tags must be the previous read value')
        expected, seen = [], set()
        for tag in request['expected']:
            _require(isinstance(tag, dict)
                     and tag.keys() in ({'name', 'java_class'}, {'name', 'java_class', 'reference'}),
                     'Expected tags require name, java_class and an optional reference')
            _text(tag['name'], 'expected tag name')
            _text(tag['java_class'], 'expected tag Java class')
            _require(tag['name'] not in seen, 'Duplicate expected tag name')
            seen.add(tag['name'])
            if 'reference' in tag:
                _keys(tag['reference'], 'session_token key', 'expected tag reference')
                _text(tag['reference']['session_token'], 'expected tag session token')
                _text(tag['reference']['key'], 'expected tag key')
            # 关联集合按名称和实际类型核对，引用元数据不跨文件加载作为身份前提。
            # 规范化请求显式移除这些元数据，不宣称仍比较了已移除的 token/key。
            expected.append({'name': tag['name'], 'java_class': tag['java_class']})
        request = {**request, 'value': sorted(value), 'expected': sorted(expected, key=lambda item: item['name'])}
    # 所有本类型读取都留在计划中，用于修改前完整性检查与修改后差异；只保留一个写入。
    required = {}
    needed = [identifier]
    if adapter in ('reference', 'object_selection'):
        needed += prop['write']['value_types']
        if adapter == 'object_selection' and 'user_tag' in plan['types']:
            needed.append('user_tag')
    for current in needed:
        while current is not None:
            required[current] = plan['types'][current]
            current = plan['types'][current]['parent_type']
    clipped = {name: {key: item for key, item in value.items()
                      if key != 'write' or name == request['property']}
               for name, value in properties.items()}
    return ({**plan, 'types': required, 'properties': {identifier: clipped}, 'operations': {}}, request)


def prepare_legacy(modification=None):
    """为旧修改入口加载随仓库分发的 2602 目录，保留原请求与结果契约。

    调用方应先用旧请求校验器检查 modification；None 表示 set-scalar。
    这里只选择调用能力，不读取算例或合成预期状态。Java 在同一次宏中读取
    目录与旧快照，核对旧 expected 及两种读取的一致性，再交给统一修改器。
    旧数值入口仍无外部 expected。
    固定目录不表示其他 STAR 版本兼容，实际 server 必须通过精确版本检查。
    """
    root = Path(__file__).resolve().parents[1] / 'catalogs' / '2602'
    plan = load_execution(root / 'generated' / 'catalog.json', root / 'execution.json')
    if modification is None:
        identifier, property_name = 'scalar_parameter', 'quantity_value'
    elif modification['operation'] == 'set-definition':
        identifier, property_name = {
            'parameter': ('scalar_parameter', 'quantity'),
            'field_function': ('user_field_function', 'definition'),
        }[modification['target']['kind']]
    else:
        identifier = {'parameter': 'global_parameter', 'field_function': 'field_function',
                      'region': 'region', 'boundary': 'boundary'}[modification['target']['kind']]
        property_name = 'tags'
    required = {}
    current = identifier
    while current is not None:
        required[current] = plan['types'][current]
        current = plan['types'][current]['parent_type']
    # 只把本次需要的 setter 留给兼容层，其余属性用于完整回读和身份核对。
    properties = {name: {key: value for key, value in entry.items()
                         if key != 'write' or name == property_name}
                  for name, entry in plan['properties'][identifier].items()}
    return {**plan, 'types': required, 'properties': {identifier: properties}, 'operations': {}}
