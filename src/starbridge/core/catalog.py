"""加载、合并与比较版本目录；此模块只描述能力，不执行 Java API。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re


class CatalogError(ValueError):
    """目录格式、版本或人工映射不匹配，调用方必须停止使用该目录。"""


def _object(pairs):
    """拒绝重复键，避免目录或人工规则被静默覆盖。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f'Duplicate catalog key: {key}')
        result[key] = value
    return result


def _constant(value):
    """拒绝 JSON 标准之外的 NaN、Infinity 等数值常量。"""
    raise CatalogError(f'Invalid JSON constant: {value}')


def read_json(path):
    """读取标准 JSON；目录中的来源、约束和映射均作为数据处理。"""
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_object,
                      parse_constant=_constant)


def _require(condition, message):
    """将契约不满足统一报告为目录错误，防止调用方带着无效映射继续执行。"""
    if not condition:
        raise CatalogError(message)


def _keys(value, keys, where):
    """要求对象字段完整且没有额外字段，尽早发现格式版本或字段拼写错误。"""
    _require(isinstance(value, dict) and value.keys() == set(keys.split()),
             f'Invalid fields at {where}; expected {keys}')


def _strings(value, where):
    """校验引用、链接和枚举列表；允许空集合，但不允许空字符串条目。"""
    _require(isinstance(value, list) and all(isinstance(x, str) and x for x in value),
             f'Expected string list at {where}')


def _target(value):
    """独立校验产品版本与 Build，避免格式版本或数值转换混入版本身份。"""
    _keys(value, 'release build', 'target')
    _require(all(isinstance(x, str) and x.strip() for x in value.values()),
             'Target release and build must be non-empty strings')


def _source(value):
    """要求来源位于安装相对路径并附摘要，不将机器绝对路径写进目录。"""
    _keys(value, 'path sha256', 'source')
    _require(isinstance(value['path'], str) and bool(value['path'])
             and not Path(value['path']).is_absolute() and '..' not in Path(value['path']).parts,
             'Source path must be installation-relative')
    _require(isinstance(value['sha256'], str)
             and re.fullmatch(r'[a-f0-9]{64}', value['sha256']) is not None,
             'Source requires a SHA256 digest')


def validate(data):
    """校验 v1 完整目录及所有本地成员引用，不将未识别字段静默忽略。"""
    _keys(data, 'schema_version target generator sources scope types bindings', 'catalog')
    _require(type(data['schema_version']) is int and data['schema_version'] == 1,
             'Unsupported catalog schema_version')
    _target(data['target'])
    _require(data['generator'] == 'starbridge-javadoc-v1', 'Unsupported catalog generator')
    _require(isinstance(data['sources'], list) and bool(data['sources']), 'Missing sources')
    for source in data['sources']:
        _source(source)
    scope = data['scope']
    _keys(scope, 'roots indexed_types includes_inherited', 'scope')
    _strings(scope['roots'], 'scope.roots')
    _require(bool(scope['roots']) and len(scope['roots']) == len(set(scope['roots'])),
             'Scope roots must be non-empty and unique')
    _require(type(scope['indexed_types']) is int and scope['indexed_types'] > 0
             and scope['includes_inherited'] is True, 'Invalid discovery scope')
    types = data['types']
    _require(isinstance(types, dict) and bool(types), 'Catalog types must not be empty')
    _require(len(types) <= scope['indexed_types'], 'Included types exceed source index size')
    _require(set(scope['roots']) <= types.keys(), 'Missing root types')
    for name, entry in types.items():
        _keys(entry, 'java_class signature links source members property_candidates inherited_members status', name)
        _require(entry['java_class'] == name and isinstance(entry['signature'], str)
                 and bool(entry['signature']) and entry['status'] == 'discovered',
                 f'Invalid type declaration: {name}')
        _source(entry['source'])
        _strings(entry['links'], 'type.links')
        _require(isinstance(entry['members'], dict), f'Invalid members: {name}')
        for anchor, member in entry['members'].items():
            _keys(member, 'name signature return_type parameters modifiers annotations links', anchor)
            _strings(member['links'], 'member.links')
            _require(bool(anchor) and all(isinstance(v, str) for k, v in member.items() if k != 'links')
                     and bool(member['name']) and bool(member['signature']),
                     f'Invalid member declaration: {name}#{anchor}')
        _require(isinstance(entry['property_candidates'], dict), f'Invalid properties: {name}')
        for anchor, prop in entry['property_candidates'].items():
            _keys(prop, 'member metadata status adapter', anchor)
            _require(prop['member'] == anchor and anchor in entry['members']
                     and prop['metadata'] == entry['members'][anchor]['annotations']
                     and prop['status'] == 'discovered' and prop['adapter'] is None,
                     f'Invalid property candidate: {name}#{anchor}')
        _require(isinstance(entry['inherited_members'], list), f'Invalid inheritance: {name}')
        for ref in entry['inherited_members']:
            _keys(ref, 'type member', 'inherited member')
            _member(data, ref)
    _require(isinstance(data['bindings'], dict), 'Invalid bindings')
    for identifier, binding in data['bindings'].items():
        _binding(data, identifier, binding)
    return data


def _member(data, ref):
    """解析声明类和成员锚点，拒绝引用不存在的声明。"""
    _require(isinstance(ref.get('type'), str) and isinstance(ref.get('member'), str),
             'Member reference requires type and member strings')
    entry = data['types'].get(ref['type'])
    _require(isinstance(entry, dict) and ref['member'] in entry.get('members', {}),
             f'Unknown catalog member: {ref}')
    return entry['members'][ref['member']]


def _binding(data, identifier, binding):
    """校验人工语义及签名锁定；v1 尚无执行器，不接受把能力标记成已实现。"""
    _keys(binding, 'type kind value_type parameters access read write adapter constraints verification evidence status', identifier)
    _require(isinstance(binding['type'], str) and binding['type'] in data['types'],
             f'Unknown binding type: {identifier}')
    _require(binding['kind'] in ('property', 'operation'), f'Invalid binding kind: {identifier}')
    _value_type(binding['value_type'])
    _require(isinstance(binding['parameters'], dict), 'Invalid operation parameters')
    _require(binding['kind'] == 'operation' or not binding['parameters'],
             'Property bindings cannot declare operation parameters')
    for name, value in binding['parameters'].items():
        _require(bool(name), 'Empty parameter name')
        _value_type(value)
    _keys(binding['access'], 'description members', 'access')
    _require(isinstance(binding['access']['description'], str), 'Invalid access description')
    for group in (binding['access']['members'], binding['read'], binding['write']):
        _require(isinstance(group, list), f'Member references must be lists: {identifier}')
        for ref in group:
            _pinned_member(data, ref)
    _require(binding['adapter'] is None, 'Executable adapters are not supported by catalog v1 yet')
    _require(isinstance(binding['constraints'], list), 'Invalid constraints')
    for constraint in binding['constraints']:
        _keys(constraint, 'description runtime_check', 'constraint')
        _require(isinstance(constraint['description'], str) and bool(constraint['description'])
                 and constraint['runtime_check'] is None, 'Invalid or unsupported runtime check')
    _keys(binding['verification'], 'description members', 'verification')
    _require(isinstance(binding['verification']['description'], str), 'Invalid verification description')
    _require(isinstance(binding['verification']['members'], list), 'Invalid verification members')
    for ref in binding['verification']['members']:
        _pinned_member(data, ref)
    _strings(binding['evidence'], 'evidence')
    _require(bool(binding['evidence']), 'Binding requires evidence')
    _require(isinstance(binding['status'], dict)
             and all(type(value) is bool for value in binding['status'].values())
             and binding['status'] == {'discovered': True, 'read_implemented': False,
                                   'write_implemented': False, 'verified': False},
             'Catalog-only bindings cannot claim implemented or verified execution')


def _value_type(value):
    """描述属性值或操作参数；未知单位与量纲用 null，不冒充无量纲。"""
    _keys(value, 'kind unit dimensions enum_values reference_type', 'value_type')
    _require(value['kind'] in ('number', 'boolean', 'string', 'enum', 'quantity',
                             'expression', 'vector', 'tensor', 'reference',
                             'collection', 'query', 'void'), 'Unsupported value kind')
    for key in ('unit', 'dimensions', 'reference_type'):
        _require(value[key] is None or isinstance(value[key], str), f'Invalid {key}')
    _strings(value['enum_values'], 'value_type.enum_values')


def member_fingerprint(member):
    """锁定签名、注解和类型链接；同名异包的类型变化也会使人工规则失效。"""
    text = json.dumps(member, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _pinned_member(data, ref):
    """核对人工引用的可读签名和完整声明指纹，任一变化都要求重新确认映射。"""
    _keys(ref, 'type member signature fingerprint', 'binding member')
    member = _member(data, ref)
    _require(member['signature'] == ref['signature']
             and member_fingerprint(member) == ref['fingerprint'],
             f'Stale mapping signature: {ref["type"]}#{ref["member"]}')


def load(path, *, release=None, build=None, overrides=None):
    """返回经校验的独立目录；提供运行版本时必须同时提供 release 和 Build 并精确匹配。"""
    data = validate(read_json(path))
    if release is not None or build is not None:
        _require(release is not None and build is not None, 'Both release and build are required')
        _require(data['target'] == {'release': release, 'build': build},
                 f'Catalog version mismatch: expected {release}/{build}, got {data["target"]}')
    if overrides is None:
        return data
    rules = read_json(overrides)
    _keys(rules, 'schema_version target bindings', 'overrides')
    _require(type(rules['schema_version']) is int and rules['schema_version'] == 1,
             'Unsupported overrides schema_version')
    _target(rules['target'])
    _require(rules['target'] == data['target'], 'Overrides version mismatch')
    _require(isinstance(rules['bindings'], dict), 'Invalid overrides bindings')
    # 合并只增加人工语义，不允许篡改候选事实。重复规则 ID 必须由维护者先处理。
    merged = deepcopy(data)
    _require(not (merged['bindings'].keys() & rules['bindings'].keys()), 'Duplicate binding IDs')
    merged['bindings'].update(rules['bindings'])
    return validate(merged)


def describe(data, name):
    """返回类型声明及人工属性/操作映射；不宣称对象存在于当前算例。"""
    _require(name in data['types'], f'Unknown catalog type: {name}')
    return {'target': data['target'], 'type': data['types'][name],
            'bindings': {k: v for k, v in data['bindings'].items() if v['type'] == name},
            'runtime_state': 'not_checked'}


def summary(data):
    """按明确范围统计发现和映射数量，执行覆盖始终与静态发现分开。"""
    return {'target': data['target'], 'root_types': len(data['scope']['roots']),
            'indexed_types': data['scope']['indexed_types'], 'included_types': len(data['types']),
            'declared_members': sum(len(t['members']) for t in data['types'].values()),
            'property_candidates': sum(len(t['property_candidates']) for t in data['types'].values()),
            'semantic_bindings': len(data['bindings']),
            'read_implemented': 0, 'write_implemented': 0, 'verified': 0,
            'runtime_state': 'not_checked'}


def compare(before, after):
    """比较同范围目录的声明和语义变化；改名仅报告候选，不建立自动兼容映射。"""
    changes = []
    for name in sorted(before['types'].keys() | after['types'].keys()):
        old, new = before['types'].get(name), after['types'].get(name)
        if old is None or new is None:
            changes.append({'type': name, 'kind': 'type_added' if old is None else 'type_removed'})
            continue
        for field in ('signature', 'links', 'property_candidates', 'inherited_members'):
            if old[field] != new[field]:
                changes.append({'type': name, 'kind': field + '_changed',
                                'before': old[field], 'after': new[field]})
        removed = old['members'].keys() - new['members'].keys()
        added = new['members'].keys() - old['members'].keys()
        for member in sorted(old['members'].keys() | new['members'].keys()):
            a, b = old['members'].get(member), new['members'].get(member)
            if a != b:
                kind = 'member_added' if a is None else 'member_removed' if b is None else 'member_changed'
                changes.append({'type': name, 'member': member, 'kind': kind, 'before': a, 'after': b})
        # 相同参数与返回类型、不同名称只能提示人工核对，重载/泛型变化不自动兼容。
        for a in sorted(removed):
            for b in sorted(added):
                left, right = old['members'][a], new['members'][b]
                if ('(' in a and '(' in b and left['name'] != right['name']
                        and a[a.index('('):] == b[b.index('('):]
                        and left['return_type'] == right['return_type']):
                    changes.append({'type': name, 'kind': 'rename_candidate',
                                    'before': a, 'after': b, 'requires_confirmation': True})
    for key in sorted(before['bindings'].keys() | after['bindings'].keys()):
        a, b = before['bindings'].get(key), after['bindings'].get(key)
        if a != b:
            changes.append({'binding': key, 'kind': 'binding_changed', 'before': a, 'after': b})
    return {'before_target': before['target'], 'after_target': after['target'],
            'same_roots': before['scope']['roots'] == after['scope']['roots'],
            'changes': changes, 'compatibility': 'not_assessed'}
