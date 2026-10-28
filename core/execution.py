"""校验人工执行映射并裁剪只读计划，供文件与会话入口共用。

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


ADAPTERS = {'primitive', 'reference', 'collection', 'quantity', 'vector', 'enum', 'query'}
JAVA_TYPE = re.compile(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:\[\])*\Z')
PRIMITIVES = {'boolean', 'byte', 'char', 'short', 'int', 'long', 'float', 'double'}


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
    _require(entry['effect'] == 'read', f'Only reviewed read methods are supported: {identifier}')
    parameters = entry['parameter_types']
    _require(isinstance(parameters, list)
             and all(isinstance(x, str) and JAVA_TYPE.fullmatch(x) for x in parameters),
             f'Invalid reflection parameter types: {identifier}')
    documented = anchor.partition('(')[2][:-1]
    expected = [_parameter_type(catalog, declaration, name)
                for name in documented.split(',')] if documented else []
    # 这里只接收可直接对应的声明，不把类型变量 T 自动当 Object。
    # 需要泛型擦除、静态工厂或写入方法时必须扩展契约并重新验证。
    _require(parameters == expected, f'Unresolved or mismatched method parameters: {identifier}')
    return {'owner': _binary_class(catalog, ref['type']),
            'name': declaration['name'], 'parameter_types': parameters}


def _pipeline(catalog, methods, pipeline, where):
    """将已核对的方法 ID 编译为调用序列；每一步的接收对象来自上一步结果。"""
    _keys(pipeline, 'root steps', where)
    _require(pipeline['root'] in ('simulation', 'object', 'parent'), f'Invalid pipeline root: {where}')
    _require(isinstance(pipeline['steps'], list) and bool(pipeline['steps']),
             f'Pipeline requires at least one call: {where}')
    compiled = []
    for step in pipeline['steps']:
        _keys(step, 'member arguments', where)
        _text(step['member'], 'step.member')
        _require(step['member'] in methods, f'Unknown execution member: {step["member"]}')
        member = methods[step['member']]
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
                _require(arg['context'] in ('object', 'parent'), 'Unsupported argument context')
            else:
                raise CatalogError('Unknown argument source')
            compiled_arguments.append(arg)
        compiled.append({**member, 'arguments': compiled_arguments})
    return {'root': pipeline['root'], 'steps': compiled}


def load_execution(catalog_path, execution_path):
    """加载共享候选目录及人工执行映射，返回已校验的完整只读运行时目录。

    不访问安装或算例；运行 server 版本检查由 Java 在第一次目录调用前执行。
    catalog_id 覆盖执行映射和版本；成员声明另外由映射中的指纹锁定。
    """
    catalog = load(catalog_path)
    rules = read_json(execution_path)
    _keys(rules, 'schema_version target members types properties', 'execution')
    _require(type(rules['schema_version']) is int and rules['schema_version'] == 1,
             'Unsupported execution schema_version')
    _require(rules['target'] == catalog['target'], 'Execution catalog version mismatch')
    _require(isinstance(rules['members'], dict) and bool(rules['members']), 'Missing execution members')
    methods = {}
    for identifier, member in rules['members'].items():
        _text(identifier, 'member ID')
        methods[identifier] = _member(catalog, identifier, member)

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

    # 2. 属性只声明读取适配；写入能力必须由后续完整修改契约提供。
    _require(isinstance(rules['properties'], dict) and rules['properties'].keys() == types.keys(),
             'Properties must describe every execution type exactly once')
    properties = {}
    for identifier, entries in rules['properties'].items():
        _require(isinstance(entries, dict) and bool(entries), f'Missing properties: {identifier}')
        properties[identifier] = {}
        for name, entry in entries.items():
            _text(name, 'property ID')
            _keys(entry, 'adapter read writable reason', identifier + '.' + name)
            _require(isinstance(entry['adapter'], str) and entry['adapter'] in ADAPTERS,
                     f'Unsupported read adapter: {identifier}.{name}')
            _require(entry['writable'] is False, 'Read contracts cannot claim writable properties')
            _text(entry['reason'], 'property.reason')
            read = _pipeline(catalog, methods, entry['read'], identifier + '.' + name)
            _require(read['root'] != 'parent' or types[identifier]['parent_type'] is not None,
                     f'Property has no parent context: {identifier}.{name}')
            properties[identifier][name] = {**entry, 'read': read}
    fingerprint = json.dumps(rules, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return {'schema_version': 1, 'target': catalog['target'],
            'catalog_id': hashlib.sha256(fingerprint.encode('utf-8')).hexdigest(),
            'types': types, 'properties': properties}


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
    return ({**plan, 'types': required,
             'properties': {identifier: {name: plan['properties'][identifier][name] for name in names}}},
            request)
