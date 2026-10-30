"""将实际 Bean 元数据与本机 Javadoc 组合为经过成员指纹校验的读取计划。"""

import hashlib
import json
from pathlib import Path

from .catalog import member_fingerprint, validate, read_json
from .catalog_bundle import session_target
from .execution import load_execution
from tools.catalog.javadoc import generate

from .discovery_policy import POLICY_VERSION, TARGET, PRIMITIVES, INPUTS, INPUT_RECEIVER_TYPES, DENY, DYNAMIC_RANGES

RULE_VERSION = 'discovery-read-v4-' + POLICY_VERSION


def digest(value):
    """使用确定性 JSON 摘要区分方法签名和规则版本。"""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def property_id(prop):
    """锁定声明和安全相关绑定上下文，不因显示名称或翻译说明变化而换 ID。"""
    context = {key: prop.get(key) for key in (
        'setter', 'hidden', 'expert', 'bound', 'constrained', 'editor_class', 'attributes')}
    return 'property_' + digest({'rule': RULE_VERSION, 'getter': prop.get('getter'),
                               'type': prop.get('property_type'), 'name': prop.get('name'), 'context': context})[:24]


def select_rule(prop):
    """禁止项优先；未知或隐藏描述符保留元数据而不调用 getter。"""
    getter = prop.get('getter') or {}
    if (DENY['descriptor_forbidden'] and prop.get('forbidden') or
            getter.get('owner') in DENY['owners'] or
            (getter.get('owner'), getter.get('name')) in DENY['members']):
        return None, 'explicit_deny_rule'
    if not getter.get('public') or getter.get('static') or getter.get('parameter_types'):
        return None, 'unsupported_getter'
    annotations = {a['type']: a.get('values') for a in getter.get('annotations', [])}
    if DENY['hidden'] and prop.get('hidden'):
        return None, 'hidden_property_metadata_only'
    if any(a.rsplit('.', 1)[-1] in DENY['annotation_names'] for a in annotations):
        return None, 'internal_or_deprecated'
    if 'star.locale.annotation.StarBeanProperty' not in annotations:
        return None, 'no_property_annotation'
    kind = prop.get('property_type')
    if kind in PRIMITIVES:
        return ('primitive', None, None), None
    if kind in INPUTS:
        return INPUTS[kind], None
    return None, 'unsupported_value_type'


def _write(path, value):
    """以同目录原子替换保存缓存，避免中断留下半份 JSON。"""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        temporary = Path(stream.name)
    temporary.replace(path)


def installation(state):
    """从会话绑定的真实可执行文件向上寻找同一安装的官方文档。"""
    executable = Path(state['star']).resolve()
    for parent in executable.parents:
        if (parent / 'doc/client/html/type-search-index.js').is_file():
            return parent
    raise ValueError('STAR installation Javadoc is unavailable')


def build_read_plan(session_dir, node, properties, state, *, writer_hook=None):
    """为当前节点生成计划；每次生成校验安装 Build 和所有用到的成员声明。

    返回目录路径、已编译计划、带会话身份的 target 和 descriptor 映射。
    writer_hook 仅供内部规则扩展；外部请求不能提供方法或执行步骤。
    """
    target_version = session_target(state)
    if target_version != TARGET:
        raise ValueError('Runtime discovery is unsupported for this exact version')
    selected = {property_id(p): p for p in properties if select_rule(p)[0] is not None}
    if not selected:
        raise ValueError('No supported readable properties on node')
    classes = {'star.base.neo.ClientServerObject', 'star.common.Simulation'}
    classes.update(s['java_class'].replace('$', '.') for s in node['path'])
    for prop in selected.values():
        classes.add(prop['getter']['owner'].replace('$', '.'))
        adapter, owner, name = select_rule(prop)[0]
        if owner:
            classes.add(owner)
            classes.update(INPUT_RECEIVER_TYPES[adapter])
    if writer_hook is not None:
        classes.update(writer_hook.required_classes(selected))
    root = installation(state)
    metadata = Path(session_dir) / 'discovery-cache' / 'metadata'
    metadata.mkdir(parents=True, exist_ok=True)
    cached = metadata / (digest([str(root), target_version, RULE_VERSION, sorted(classes)]) + '.json')
    catalog = read_json(cached) if cached.is_file() else None
    # 源文件内容摘要同时覆盖版本材料和类页面；文件变化时重新解析注解与继承链。
    sources = [] if catalog is None else catalog['sources'] + [v['source'] for v in catalog['types'].values()]
    valid = catalog is not None and all((root / item['path']).is_file() and
        hashlib.sha256((root / item['path']).read_bytes()).hexdigest() == item['sha256'] for item in sources)
    if not valid:
        catalog = validate(generate(root, sorted(classes)))
        _write(cached, catalog)
    else:
        catalog = validate(catalog)
    if catalog['target'] != target_version:
        raise ValueError('Installation and session Build differ')
    rules = {'schema_version': 8, 'target': target_version, 'members': {},
             'types': {}, 'properties': {}, 'operations': {}}

    def member(owner, name, parameter_types=None, effect='read'):
        """只有官方目录中存在的精确声明才进入执行成员表。"""
        owner = owner.replace('$', '.')
        parameters = parameter_types or []
        anchor = name + '(' + ','.join(parameters) + ')'
        declaration = catalog['types'][owner]['members'][anchor]
        identifier = 'm_' + digest([owner, anchor])[:24]
        rules['members'][identifier] = {'type': owner, 'member': anchor,
            'signature': declaration['signature'], 'fingerprint': member_fingerprint(declaration),
            'parameter_types': parameters, 'effect': effect}
        return {'member': identifier, 'arguments': []}

    children = member('star.base.neo.ClientServerObject', 'getChildren')
    presentation = member('star.base.neo.ClientServerObject', 'getPresentationName')
    parent = parent_type = None
    # 根节点使用恒等单对象定位；后续节点沿真实 CSO 父子关系逐级校验身份。
    for index, step in enumerate(node['path']):
        type_id = 'node_' + digest([s['java_class'] for s in node['path'][:index + 1]])[:24]
        rules['types'][type_id] = {'java_class': step['java_class'].replace('$', '.'),
            'parent_type': parent_type, 'locate_kind': 'object' if index == 0 else 'collection',
            'locate': {'root': 'simulation' if index == 0 else 'parent', 'steps': [] if index == 0 else [children]}}
        rules['properties'][type_id] = {'name': {'adapter': 'primitive',
            'read': {'root': 'object', 'steps': [presentation]}, 'writable': False, 'reason': '对象身份读取'}}
        rules['operations'][type_id] = {}
        current = {'type': type_id, 'name': step['name'],
                   'reference': {'session_token': state['session_token'], 'key': step['key']}}
        if parent is not None:
            current['parent'] = parent
        parent, parent_type = current, type_id
    supplemental = {}
    for identifier, prop in selected.items():
        adapter, owner, name = select_rule(prop)[0]
        steps = [member(prop['getter']['owner'], prop['getter']['name'])]
        if owner:
            # 属性声明只描述静态返回类型。实际 input 必须先匹配登记的精确类，
            # 再执行解包；关联读取和复制此管线的 writer 自动保留同一约束。
            unwrap = member(owner, name)
            unwrap['receiver_types'] = list(INPUT_RECEIVER_TYPES[adapter])
            steps.append(unwrap)
        rules['properties'][type_id][identifier] = {'adapter': adapter,
            'read': {'root': 'object', 'steps': steps}, 'writable': False, 'reason': '已核对描述符和官方成员声明的通用只读规则'}
        # input 的真实数量或选项对象作为关联返回，不把临时 input 包装器伪装成 CSO。
        if owner:
            relation_id = identifier + '_relation'
            rules['properties'][type_id][relation_id] = {'adapter': 'reference',
                'read': {'root': 'object', 'steps': steps}, 'writable': False, 'reason': 'input 包装的实际对象身份'}
            supplemental.setdefault(identifier, []).append(relation_id)
        bounded = next((a.get('values', {}) for a in prop['getter'].get('annotations', [])
                        if a['type'].endswith('.StarBeanBounded')), None)
        range_steps = None
        if bounded and bounded.get('dynamic') is True and bounded.get('rangeMethod'):
            range_name = bounded['rangeMethod']
            declaration = catalog['types'][prop['getter']['owner'].replace('$', '.')]['members'].get(range_name + '()')
            if (prop['getter']['owner'], range_name) in DYNAMIC_RANGES and declaration and 'ScalarRange' in declaration['signature']:
                range_steps = [member(prop['getter']['owner'], range_name)]
                range_adapter = 'scalar_range'
        elif prop.get('property_type') == 'star.common.BoundedScalarInput':
            range_steps = steps[:1]
            range_adapter = 'scalar_bounds'
        if range_steps:
            range_id = identifier + '_range'
            rules['properties'][type_id][range_id] = {'adapter': range_adapter,
                'read': {'root': 'object', 'steps': range_steps}, 'writable': False,
                'reason': '已核验有界 input 或显式动态范围声明的只读范围'}
            supplemental.setdefault(identifier, []).append(range_id)
    if writer_hook is not None:
        writer_hook.attach(catalog, rules, selected, type_id, member)
    cache = Path(session_dir) / 'discovery-cache' / 'plans' / digest([RULE_VERSION, catalog, rules])
    cache.mkdir(parents=True, exist_ok=True)
    cp, ep = cache / 'catalog.json', cache / 'execution.json'
    _write(cp, catalog)
    _write(ep, rules)
    return {'catalog_path': cp, 'execution_path': ep, 'plan': load_execution(cp, ep),
            'target': parent, 'property_map': selected, 'supplemental': supplemental,
            'binding': {'session_token': state['session_token'], 'path': node['path']}}
