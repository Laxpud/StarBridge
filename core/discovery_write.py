"""为发现属性组合受控赋值计划；规则证据与运行时元数据分别校验。

本模块不执行 setter。调用方须通过现有修改事务保留完整快照、Diff、
单次尝试和显式保存；这里返回的 writer 不能用于独立反射调用。
"""

from copy import deepcopy

from .catalog import CatalogError


# 只允许下列完整规则进入单次赋值事务；实例条件仍需每次准备及 setter 前检查。
WRITING_ENABLED = True

# 安装库资源可在 all 范围描述，但不属于算例普通赋值的影响范围。
RESOURCE_OWNERS = {'star.material.MaterialDataBaseManager'}


def _resource_node(node):
    """根据已验证的类型路径区分库资源，避免依赖本地化显示名称。"""
    return any(step.get('java_class') in RESOURCE_OWNERS for step in node.get('path', []))

# 每个族固定读取表示、参数来源和最终方法形状；调用方不能从请求传方法。
FAMILIES = {
    'scalar_value': ('quantity', ['double', 'star.common.Units'], ['number', 'units']),
    'vector_value': ('vector', ['double', 'double', 'double', 'star.common.Units'],
                     ['x', 'y', 'z', 'units']),
    'enum': ('enum', ['java.lang.Enum'], ['value']),
    'primitive': ('primitive', None, ['value']),
}


def capability(reason, *, supported=False):
    """描述规则支持，不把尚未执行的实例及新值条件冒充满足。"""
    return {'write_support': 'supported' if supported else 'unsupported',
            'write_enabled': supported and WRITING_ENABLED, 'write_reason': reason,
            'target_conditions': 'not_checked', 'value_conditions': 'not_checked'}


def attach_writer(entry, descriptor, contract):
    """把已核验的族规则附加到已编译读取项，返回新项和能力说明。

    contract 由服务内部规则产生，包含 family、evidence、pipeline、guards、
    conditions_complete、impact_scope；不得直接接受请求传入。pipeline 中的方法
    必须先经 execution._member 验证版本、签名和指纹。禁止和特殊规则优先，
    有 setter、读取成功或缺少约束均不能代替 conditions_complete 的证明。
    """
    result = deepcopy(entry)
    result.pop('write', None)
    result['writable'] = False
    if descriptor.get('forbidden'):
        return result, capability('Explicit deny rule')
    if descriptor.get('hidden') or descriptor.get('read_only') or descriptor.get('readOnly'):
        return result, capability('Hidden or read-only property')
    if not contract:
        return result, capability('No accepted assignment rule')
    if descriptor.get('special_rule') and not contract.get('special'):
        return result, capability('Special rule takes precedence')
    family = contract.get('family')
    if family not in FAMILIES:
        return result, capability('Structural or unsupported assignment family')
    if not contract.get('evidence') or contract.get('conditions_complete') is not True:
        return result, capability('Assignment conditions lack evidence')
    if contract.get('impact_scope') != 'target_and_snapshot':
        return result, capability('Assignment impact scope is not established')
    adapter, parameters, arguments = FAMILIES[family]
    if entry.get('adapter') != adapter:
        raise CatalogError('Assignment family and reader do not agree')
    pipeline = deepcopy(contract.get('pipeline', {}))
    steps = pipeline.get('steps', [])
    if pipeline.get('root') != 'object' or not steps:
        raise CatalogError('Assignment requires an object-rooted pipeline')
    if any(step.get('effect') != 'read' for step in steps[:-1]):
        raise CatalogError('Assignment prefix must be read-only')
    setter = steps[-1]
    if setter.get('effect') != 'write':
        raise CatalogError('Assignment requires a final setter')
    if parameters is None:
        types = setter.get('parameter_types', [])
        if len(types) != 1 or types[0] not in ('boolean', 'byte', 'short', 'int', 'long', 'float', 'double'):
            raise CatalogError('Primitive assignment requires a boolean or numeric setter')
    elif setter.get('parameter_types') != parameters:
        raise CatalogError('Assignment setter parameters do not match the family')
    if setter.get('arguments') != [{'context': name} for name in arguments]:
        raise CatalogError('Assignment parameter bindings do not match the family')
    writer = {'adapter': family, 'pipeline': pipeline,
              'guards': deepcopy(contract.get('guards', [])),
              'preserved_properties': list(contract.get('preserved_properties', []))}
    if 'bounds' in contract:
        if family != 'scalar_value':
            raise CatalogError('Runtime bounds require a scalar assignment')
        writer['bounds'] = deepcopy(contract['bounds'])
    result.update(writable=True, write=writer)
    return result, capability(str(contract['evidence']), supported=True)


class AcceptedWriteRules:
    """把已有版本写入语义迁移到发现属性，不将任意 setter 当作授权。

    按读取管线的完整声明身份匹配既有已维护规则，复用其条件、范围和
    保持项。发现节点定位来自实际对象树，不再要求旧目录的手工定位路径。
    新声明没有接受依据时保持只读；模型、方法、选择器等操作不迁移。
    """

    def __init__(self, target):
        from .catalog_bundle import bundle_root
        from .catalog import read_json
        self.source = read_json(bundle_root(target) / 'execution.json')

    def _signature(self, pipeline):
        """用完整 owner/name/参数序列标识同一读取过程。"""
        return tuple((self.source['members'][step['member']]['type'],
                      self.source['members'][step['member']]['member'])
                     for step in pipeline['steps'])

    @staticmethod
    def _canonical_signature(signature):
        """仅归一化已确认的全局参数数量访问，不推断其他 input 的所有权。

        Scalar/VectorGlobalParameter 的 quantity input 是其自身 quantity 的
        编辑表示；Java 写前仍核对最终 setter 接收数量与读取数量的 CSO key。
        """
        for owner in ('star.common.ScalarGlobalParameter', 'star.common.VectorGlobalParameter'):
            if signature == ((owner, 'getQuantityInput()'),
                             ('star.common.CompiledValueFunctionInput', 'getQuantity()')):
                return ((owner, 'getQuantity()'),)
        return signature

    def _matching_entries(self, selected):
        """按首个真实 getter 缩小特殊规则候选，完整管线仍在 attach 核对。"""
        getters = {(p['getter']['owner'].replace('$', '.'), p['getter']['name'] + '()')
                   for p in selected.values()}
        for owner in ('star.common.ScalarGlobalParameter', 'star.common.VectorGlobalParameter'):
            if (owner, 'getQuantityInput()') in getters:
                getters.add((owner, 'getQuantity()'))
        for entries in self.source['properties'].values():
            for original in entries.values():
                steps = original.get('read', {}).get('steps', [])
                if not steps or not original.get('write'):
                    continue
                declaration = self.source['members'][steps[0]['member']]
                if (declaration['type'], declaration['member']) in getters:
                    yield original, entries

    def required_classes(self, selected):
        """只加入匹配规则及保持项实际引用的成员声明，避免全目录编译。"""
        classes = set()
        def collect(value):
            if isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, dict):
                if 'member' in value:
                    declaration = self.source['members'][value['member']]
                    classes.add(declaration['type'])
                    classes.update(t for t in declaration['parameter_types']
                                   if t.startswith('star.'))
                for item in value.values():
                    collect(item)
        for original, entries in self._matching_entries(selected):
            collect(original)
            for name in original['write'].get('preserved_properties', []):
                collect(entries[name]['read'])
            for entry in entries.values():
                if entry['adapter'] not in ('quantity', 'vector'):
                    collect(entry['read'])
        return classes

    def attach(self, catalog, rules, selected, type_id, member):
        """按已接受管线匹配、复制完整语义，再交回统一编译器校验。"""
        def signature(pipeline):
            return tuple((rules['members'][step['member']]['type'],
                          rules['members'][step['member']]['member'])
                         for step in pipeline['steps'])

        def translate(value):
            if isinstance(value, list):
                return [translate(item) for item in value]
            if not isinstance(value, dict):
                return value
            if 'member' in value:
                identifier = value['member']
                declaration = self.source['members'][identifier]
                new_id = 'accepted_' + identifier
                rules['members'][new_id] = deepcopy(declaration)
                return {**deepcopy(value), 'member': new_id}
            return {key: translate(item) for key, item in value.items()}

        entries = rules['properties'][type_id]
        for identifier, descriptor in selected.items():
            entry = entries[identifier]
            if descriptor.get('hidden') or descriptor.get('forbidden'):
                continue
            matches = []
            for legacy_type, legacy_entries in self.source['properties'].items():
                for legacy_name, original in legacy_entries.items():
                    writer = original.get('write', {})
                    if writer.get('adapter') not in FAMILIES:
                        continue
                    if original['read']['root'] != 'object' or not original['read']['steps']:
                        continue
                    if self._canonical_signature(self._signature(original['read'])) == self._canonical_signature(signature(entry['read'])):
                        matches.append((legacy_type, legacy_name, original))
            # 多个上下文规则不能靠任意选第一个消除歧义。
            if len(matches) != 1:
                continue
            legacy_type, legacy_name, original = matches[0]
            writer = original['write']
            # 父级条件依赖旧定位结构，不能移植到新对象树的不同父节点。
            if any(isinstance(v, dict) and v.get('root') == 'parent'
                   for v in [writer.get('pipeline', {}), writer.get('bounds', {})]
                   + [g['read'] for g in writer.get('guards', [])]):
                continue
            old_entries = self.source['properties'][legacy_type]
            preserved = writer.get('preserved_properties', [])
            if any(old_entries[name]['read']['root'] != 'object' for name in preserved):
                continue
            prefix = 'preserved_' + identifier + '_'
            # 保持项作为内部读取项迁移；最终请求仍仅暴露发现属性 ID。
            for name in preserved:
                copied = translate(old_entries[name])
                copied.pop('write', None)
                copied['writable'] = False
                entries[prefix + name] = copied
            copied_writer = translate(writer)
            copied_writer['preserved_properties'] = [prefix + name for name in preserved]
            if self._signature(original['read']) != signature(entry['read']):
                # alias 保留旧目标的完整只读状态，排除数量的两个等价表示。
                for name, original_property in old_entries.items():
                    if original_property['adapter'] in ('quantity', 'vector') or name in ('definition', 'unit'):
                        # 定义和单位是本次赋值的结果，不能同时声明为保持项。
                        continue
                    if original_property['read']['root'] != 'object':
                        continue
                    copied = translate(original_property)
                    copied.pop('write', None)
                    copied['writable'] = False
                    entries[prefix + name] = copied
                    if prefix + name not in copied_writer['preserved_properties']:
                        copied_writer['preserved_properties'].append(prefix + name)

            entry.update(writable=True, write=copied_writer,
                         reason='按完整读取声明复用已接受赋值规则及其条件：' + legacy_type + '.' + legacy_name)


class GenericWriteRules(AcceptedWriteRules):
    """优先保留特殊已接受规则，再生成普通常量数量赋值规则。

    标量只接受具有实际范围的 BoundedScalarInput，沿原 input 在执行前
    检查范围和单位。向量保留原坐标约定；带未知范围、关联和编辑器的
    描述符拒绝。两个族都禁止覆盖表达式，并保留同节点其他读取结果。
    """

    def __init__(self, target, descriptors=None):
        super().__init__(target)
        self.descriptors = descriptors

    def required_classes(self, selected):
        return super().required_classes(selected) | {
            'star.common.ScalarPhysicalQuantity', 'star.common.VectorPhysicalQuantity',
            'star.common.Units'}

    def attach(self, catalog, rules, selected, type_id, member):
        # 已有特殊规则即使因为上下文或歧义不能迁移，也必须阻止通用回退。
        special_getters = {self._signature(original['read'])[0]
                           for original, _ in self._matching_entries(selected)}
        # 特殊语义的 input alias 同样保留优先级；迁移失败不能退回通用族。
        for owner in ('star.common.ScalarGlobalParameter', 'star.common.VectorGlobalParameter'):
            if (owner, 'getQuantity()') in special_getters:
                special_getters.add((owner, 'getQuantityInput()'))
        super().attach(catalog, rules, selected, type_id, member)
        entries = rules['properties'][type_id]
        for identifier, descriptor in selected.items():
            entry = entries[identifier]
            if entry.get('writable') or descriptor.get('hidden') or descriptor.get('forbidden'):
                continue
            getter = descriptor['getter']
            if (getter['owner'].replace('$', '.'), getter['name'] + '()') in special_getters:
                continue
            annotations = {a['type']: a.get('values', {})
                           for a in descriptor.get('getter', {}).get('annotations', [])}
            bean = annotations.get('star.locale.annotation.StarBeanProperty', {})
            if bean.get('readOnly') is not False or descriptor.get('constrained'):
                continue
            # 自链接仅表示本属性的通知关联，不证明完整物理依赖已覆盖。
            # 跨属性或格式未知的关联缺少保持依据，不能自动开放。
            links = [bean.get('link', []), descriptor.get('attributes', {}).get('link', [])]
            if any(not isinstance(link, list) or any(item != descriptor.get('name') for item in link)
                   for link in links):
                continue
            editor = bean.get('editor', {})
            if descriptor.get('editor_class') or editor not in ({}, {'class': 'java.beans.PropertyEditor'}):
                continue
            # 未知注解可能施加模型或范围条件，不能由通用规则忽略。
            if any(name != 'star.locale.annotation.StarBeanProperty' for name in annotations):
                continue
            kind = descriptor.get('property_type')
            if kind == 'star.common.BoundedScalarInput':
                family, owner, setter = 'scalar_value', 'star.common.ScalarPhysicalQuantity', 'setValueAndUnits'
            elif kind == 'star.common.VectorPhysicalQuantityInput':
                # 完整描述符中存在坐标、方向或模型方法上下文时，当前值编码
                # 不能证明关联身份保持；缺少完整描述符同样拒绝通用向量。
                if self.descriptors is None:
                    continue
                context_words = ('coordinate', 'orientation', 'referenceframe', 'direction', 'axis', 'method', 'model')
                contexts = [p for p in self.descriptors if p is not descriptor
                            and any(word in (p.get('name', '') + p.get('property_type', '')).lower()
                                    for word in context_words)]
                if contexts:
                    continue
                family, owner, setter = 'vector_value', 'star.common.VectorPhysicalQuantity', 'setComponentsAndUnits'
            else:
                continue
            _, parameters, arguments = FAMILIES[family]
            final = member(owner, setter, parameters, effect='write')
            final['arguments'] = [{'context': name} for name in arguments]
            writer = {'adapter': family, 'constant_only': True,
                      'pipeline': {'root': 'object', 'steps': deepcopy(entry['read']['steps']) + [final]},
                      'guards': [], 'preserved_properties': [name for name in entries if name != identifier]}
            if family == 'scalar_value':
                writer['bounds'] = {'root': 'object', 'steps': deepcopy(entry['read']['steps'][:1])}
            entry.update(writable=True, write=writer,
                         reason='普通常量数量赋值：固定类型 setter、运行时单位/范围检查、完整节点保持和旧快照验证')


def describe_write_support(session_dir, description, state):
    """用实际编译结果标记支持；条件仍在写前检查，不宣称实例已满足。"""
    from .discovery_rules import build_read_plan
    from .catalog_bundle import session_target
    result = deepcopy(description)
    properties = result.get('properties', [])
    if _resource_node(result.get('node', {})):
        for prop in properties:
            prop.update(capability('Library resources are outside the assignment scope'))
            prop['writable'] = False
        return result
    readable = [p for p in properties if p.get('readable')]
    if not readable:
        return result
    try:
        prepared = build_read_plan(session_dir, result['node'], readable, state,
                                   writer_hook=GenericWriteRules(session_target(state), properties))
        entries = prepared['plan']['properties'][prepared['target']['type']]
    except (ValueError, KeyError, CatalogError) as error:
        # 写入需要完整保持范围；组合计划失败不能用单属性成功冒充可写。
        # 节点和原始描述符仍返回，读取入口可以独立隔离属性编译错误。
        for prop in properties:
            prop.update(capability('Complete write verification plan unavailable: ' + str(error)))
            prop['writable'] = False
        result['write_plan_error'] = str(error)
        return result
    for prop in properties:
        entry = entries.get(prop['property_id'], {})
        if entry:
            prop['read_support'] = 'supported'
            prop.setdefault('evidence', {})['member_validation'] = 'validated'
        supported = bool(entry.get('writable') and entry.get('write'))
        prop.update(capability(entry.get('reason', 'No accepted assignment rule'), supported=supported))
        prop['writable'] = supported
    return result


def modify_node_property(session_dir, node_id, property_id, expected, value, timeout=180, operate=None):
    """刷新目标并生成完整节点写计划，然后进入保留旧快照的统一修改事务。

    规划失败发生在 setter 之前，由共享服务返回 rejected。执行器启动后的异常和
    uncertain 结果原样传播，不自动重试，也不隐式保存。影响范围仅涵盖
    目标节点全部已支持读取项及旧快照覆盖范围，不宣称覆盖完整物理依赖。
    """
    from .discovery import describe_node, _state
    from .discovery_rules import build_read_plan
    from .catalog_bundle import session_target
    from .execution import prepare_modification_value
    from bridge.runner.modifier import ModificationRejected
    if not WRITING_ENABLED:
        raise ModificationRejected('Runtime-discovered writing is not enabled in this release')
    if operate is None:
        from .service import Service
        operate = Service()._operate
    try:
        description = describe_node(session_dir, node_id, timeout=timeout, operate=operate)
        if 'node' not in description:
            raise CatalogError('Discovery node is unavailable')
        if _resource_node(description['node']):
            raise CatalogError('Library resources are outside the assignment scope')
        if description.get('state') != 'complete' or description.get('errors') or description.get('write_plan_error'):
            raise CatalogError('Complete descriptor and verification scope is required for modification')
        descriptors = description.get('properties', [])
        selected = next((p for p in descriptors if p['property_id'] == property_id), None)
        if selected is None or not selected.get('readable'):
            raise CatalogError('Unknown, stale or unsupported property ID')
        state = _state(session_dir)
        prepared = build_read_plan(session_dir, description['node'],
            [p for p in descriptors if p.get('readable')], state,
            writer_hook=GenericWriteRules(session_target(state), descriptors))
        request = {'schema_version': 2, 'action': 'modify', 'target': prepared['target'],
                   'property': property_id, 'expected': expected, 'value': value}
        plan, request = prepare_modification_value(prepared['catalog_path'], prepared['execution_path'], request)
        plan['discovery_binding'] = prepared['binding']
    except (ValueError, KeyError, CatalogError) as error:
        # 交给统一状态封套，不能把内部 rejected 包装成外层 ok。
        raise ModificationRejected(str(error)) from error
    return operate(str(session_dir), 'modify', timeout, catalog_plan=plan, catalog_request=request)
