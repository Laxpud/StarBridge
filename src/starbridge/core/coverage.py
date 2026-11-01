"""分别报告静态发现、执行实现及已有运行结果中的成功观察，不连接算例。"""

from collections import Counter
import hashlib
import json
from pathlib import Path

from .catalog import CatalogError, _constant, _object, _require, load
from .execution import _operation_request, _target, load_execution


def _locator(value):
    """移除会话引用后比较定位路径；重载后的 token/key 不承担永久身份。"""
    return {key: _locator(item) if key == 'parent' else item
            for key, item in value.items() if key != 'reference'}


def _read_result(value, plan):
    """核对读取结果的目录、版本和属性身份，返回成功与错误的逐项观察。

    此处只认 status=ok 且存在 value 的读取结果，describe 的适配器描述
    不算读取成功。局部错误不影响其他属性已返回的值，但仍保留错误明细。
    """
    _require(isinstance(value, dict), 'Missing catalog read result')
    _require(value.get('catalog_id') == plan['catalog_id'], 'Stale execution catalog_id')
    runtime = value.get('runtime')
    _require(isinstance(runtime, dict) and
             {k: runtime.get(k) for k in ('release', 'build')} == plan['target'],
             'Runtime version does not match the execution catalog')
    target = value.get('target')
    _require(isinstance(target, dict) and isinstance(target.get('locator'), dict),
             'Read result is missing its target locator')
    locator = target['locator']
    _target(plan, locator)
    _require(target.get('type') == locator['type'] and target.get('name') == locator['name'],
             'Read result target and locator do not agree')
    entries = value.get('properties')
    _require(isinstance(entries, dict) and bool(entries), 'Read result has no properties')
    _require(entries.keys() <= plan['properties'][locator['type']].keys(),
             'Read result contains unknown mapped properties')
    successful, errors = [], []
    for name, entry in entries.items():
        _require(isinstance(entry, dict) and entry.get('status') in ('ok', 'error'),
                 'Expected property read status; descriptions are not read evidence')
        if entry['status'] == 'ok':
            _require('value' in entry and 'error' not in entry, 'Successful read is missing its value')
            successful.append(name)
        else:
            errors.append({'property': name, 'error': entry.get('error')})
    _require(type(value.get('inspection_complete')) is bool and
             value['inspection_complete'] == (not errors), 'Read completeness contradicts property results')
    return locator, successful, errors


def _no_observations():
    """为未接收的证据返回各类空观察，不在属性与操作之间共用可变列表。"""
    return {key: [] for key in ('observed_read', 'observed_write', 'file_reload',
                               'observed_execute', 'operation_file_reload')}


def _file_reload(data, file_result):
    """确认本例的双层重载与原文件保护标志；不将一次保存推广为其他分支已验证。"""
    if (file_result and data.get('reopened_catalog_match') is True
            and data.get('reopened_snapshot_match') is True):
        _require(isinstance(data.get('output'), str) and data['output'] != data.get('input'),
                 'File reload evidence is missing a distinct output')
        return True
    return False


def _evidence(path, plan):
    """读取单个 Runner 结果并分类；文件摘要固定本次观察所用的原始材料。

    支持宏 result.json、文件 Runner summary.json 和会话命令响应。只把
    成功的 schema 2 修改视为属性写入观察，schema 3 修改另计结构操作执行。
    旧 schema 的兼容结果不猜测属性映射。
    结果来自调用方提供的本地文件，摘要保证可追溯，不构成来源真实性认证。
    """
    path = Path(path)
    raw = path.read_bytes()
    record = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
    data = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    _require(isinstance(data, dict), 'Evidence must be a result object')
    if data.get('status') in ('rejected', 'error'):
        return {**record, 'status': data['status'], 'reason': data.get('error'),
                **_no_observations()}
    catalog = data.get('catalog')
    if isinstance(catalog, dict) and catalog.get('catalog_id') != plan['catalog_id']:
        return {**record, 'status': 'stale', 'reason': 'Execution catalog_id differs',
                'catalog_id': catalog.get('catalog_id'),
                **_no_observations()}
    try:
        # 1. 限定为当前 Runner 的成功封套；裸 catalog 或任意描述不能冒充执行结果。
        _require('status' not in data or data['status'] == 'ok', 'Result status is not successful')
        macro = data.get('status') == 'ok'
        file_result = data.get('action') in ('read', 'modify') and data.get('input_unchanged') is True
        session_result = isinstance(data.get('request_result'), str) and isinstance(data.get('session'), str)
        _require(macro or file_result or session_result, 'Unsupported or unsuccessful result envelope')
        locator, reads, errors = _read_result(catalog, plan)
        type_id = locator['type']
        writes, reloads = [], []
        executes, operation_reloads = [], []
        operation_observation = {}
        request = data.get('catalog_request', data.get('modification'))
        # 2. 写入必须在同一成功结果中带有请求及完整前后读取，不能从值变化推断 setter 成功。
        if (isinstance(request, dict) and type(request.get('schema_version')) is int
                and request['schema_version'] == 2 and request.get('action') == 'modify'):
            _require(request.keys() == {'schema_version', 'action', 'target', 'property', 'expected', 'value'},
                     'Invalid modification evidence request')
            _target(plan, request['target'])
            _require(_locator(request['target']) == _locator(locator), 'Modification target differs from read target')
            before_locator, before_reads, before_errors = _read_result(data.get('catalog_before'), plan)
            _require(_locator(before_locator) == _locator(locator), 'Modification before/after targets differ')
            name = request['property']
            _require(isinstance(name, str) and name in reads and name in before_reads,
                     'Modified property is missing from successful readback')
            _require(plan['properties'][type_id][name]['writable'], 'Modified property has no writer')
            _require(not errors and not before_errors, 'Modification readback is incomplete')
            _require(set(reads) == set(before_reads) == plan['properties'][type_id].keys(),
                     'Modification readback omits mapped properties')
            writes.append(name)
            if _file_reload(data, file_result):
                reloads.append(name)
        # 3. 结构操作只要求该操作承诺的回读范围；方法切换后部分旧分量已不适用，
        # 不能要求整个目标类型的所有属性都可读，也不能把操作算成普通属性 setter。
        elif (isinstance(request, dict) and type(request.get('schema_version')) is int
              and request['schema_version'] == 3 and request.get('action') == 'modify'):
            # 复用实际请求入口的旧状态、方法参数及目标契约，避免报告另造较宽松的格式。
            request = _operation_request(plan, request)
            _require(_locator(request['target']) == _locator(locator), 'Operation target differs from read target')
            identifier = request['operation']
            operation = plan['operations'][type_id][identifier]
            _require(isinstance(operation.get('write'), dict), 'Operation has no execution implementation')
            before_locator, before_reads, before_errors = _read_result(data.get('catalog_before'), plan)
            _require(_locator(before_locator) == _locator(locator), 'Operation before/after targets differ')
            _require(not errors and not before_errors, 'Operation readback is incomplete')
            _require(set(reads) == set(before_reads) == set(operation['read_properties']),
                     'Operation readback does not match its declared properties')
            executes.append(identifier)
            operation_observation = {'operation': {'id': identifier, 'arguments': request['arguments']}}
            if _file_reload(data, file_result):
                operation_reloads.append(identifier)
        return {**record, 'status': 'accepted', 'target': locator,
                'runtime': {k: catalog['runtime'][k] for k in ('release', 'build')},
                'observed_read': reads, 'observed_write': writes, 'file_reload': reloads,
                'observed_execute': executes, 'operation_file_reload': operation_reloads,
                'property_errors': errors, **operation_observation}
    except (CatalogError, KeyError, TypeError) as error:
        return {**record, 'status': 'not_accepted', 'reason': str(error),
                **_no_observations()}


def coverage(catalog_path, *, execution_path=None, overrides=None, results=(), release=None, build=None):
    """返回分项覆盖报告，按不同统计基数保留发现、实现和实测观察。

    catalog_path 必需；execution_path 可省略，此时执行能力为 not_supplied，
    不能由候选 getter 推断实现。results 是已有 Runner JSON 路径序列，必须
    同时提供 execution_path。证据缺失不等于能力失败，成功样例也不等于全部
    分支通过。该函数只读取材料，不启动 STAR 或判断当前算例是否可写。
    """
    catalog = load(catalog_path, overrides=overrides, release=release, build=build)
    _require(execution_path is not None or not results, 'Result evidence requires --execution')
    plan = load_execution(catalog_path, execution_path) if execution_path is not None else None
    # 1. 发现数量以声明位置去重；继承引用不重复计入成员或属性候选总数。
    discovery = {'indexed_types': catalog['scope']['indexed_types'],
                 'root_types': len(catalog['scope']['roots']),
                 'included_types': len(catalog['types']),
                 'declared_members': sum(len(t['members']) for t in catalog['types'].values()),
                 'property_candidates': sum(len(t['property_candidates']) for t in catalog['types'].values()),
                 'semantic_properties': sum(b['kind'] == 'property' for b in catalog['bindings'].values()),
                 'semantic_operations': sum(b['kind'] == 'operation' for b in catalog['bindings'].values())}
    evidence = [_evidence(path, plan) for path in results]
    observations = {}
    for index, record in enumerate(evidence):
        if record['status'] != 'accepted':
            continue
        type_id = record['target']['type']
        for kind in ('observed_read', 'observed_write', 'file_reload',
                     'observed_execute', 'operation_file_reload'):
            for name in record[kind]:
                observations.setdefault((type_id, name, kind), []).append(index)
    # 2. 实现数量以 type ID + property ID 为基数，不能除以注解候选数宣称全 API 覆盖率。
    entries = []
    for type_id, properties in sorted(plan['properties'].items()) if plan else []:
        for name, prop in sorted(properties.items()):
            records = {kind: observations.get((type_id, name, kind), [])
                       for kind in ('observed_read', 'observed_write', 'file_reload')}
            missing = []
            if not prop['writable']:
                missing.append({'code': 'write_not_implemented', 'reason': prop['reason']})
            if not records['observed_read']:
                missing.append({'code': 'read_evidence_missing', 'reason': 'No accepted successful read result'})
            if prop['writable'] and not records['observed_write']:
                missing.append({'code': 'write_evidence_missing', 'reason': 'No accepted successful modification result'})
            if prop['writable'] and not records['file_reload']:
                missing.append({'code': 'file_reload_evidence_missing', 'reason': 'No accepted file reload result'})
            entries.append({'type': type_id, 'property': name,
                            'java_class': plan['types'][type_id]['java_class'],
                            'read_implemented': True, 'write_implemented': prop['writable'],
                            'read_adapter': prop['adapter'],
                            'write_adapter': prop.get('write', {}).get('adapter'),
                            'conditions': prop.get('guards', []),
                            'value_conditions': prop.get('value_guards', []),
                            'value_bounds': prop.get('value_bounds', False),
                            'preserved_properties': prop.get('preserved_properties', []),
                            'runtime_state': 'not_checked', 'full_branch_verification': 'not_assessed',
                            'evidence': records, 'missing': missing})
    counts = {'mapped_types': len(plan['types']) if plan else 0, 'mapped_properties': len(entries),
              'read_implemented': len(entries),
              'write_implemented': sum(e['write_implemented'] for e in entries)}
    for kind in ('observed_read', 'observed_write', 'file_reload'):
        counts[kind] = sum(bool(e['evidence'][kind]) for e in entries)
    # 3. 操作以 type ID + operation ID 为独立基数，属性同名也不会合并证据。
    operations = []
    for type_id, descriptors in sorted(plan.get('operations', {}).items()) if plan else []:
        for identifier, operation in sorted(descriptors.items()):
            records = {'observed_execute': observations.get((type_id, identifier, 'observed_execute'), []),
                       'file_reload': observations.get((type_id, identifier, 'operation_file_reload'), [])}
            implemented = isinstance(operation.get('write'), dict)
            missing = []
            if not implemented:
                missing.append({'code': 'execute_not_implemented', 'reason': operation['reason']})
            if implemented and not records['observed_execute']:
                missing.append({'code': 'execute_evidence_missing', 'reason': 'No accepted successful operation result'})
            if implemented and not records['file_reload']:
                missing.append({'code': 'file_reload_evidence_missing', 'reason': 'No accepted operation file reload result'})
            observed_methods = {evidence[i]['operation']['arguments']['method']
                                for i in records['observed_execute']}
            operations.append({'type': type_id, 'operation': identifier,
                               'java_class': plan['types'][type_id]['java_class'],
                               'execute_implemented': implemented, 'adapter': operation['adapter'],
                               'reason': operation['reason'],
                               'read_properties': operation['read_properties'],
                               'state_property': operation['state_property'],
                               'methods': operation['methods'],
                               'observed_methods': sorted(observed_methods),
                               'unobserved_methods': sorted(operation['methods'].keys() - observed_methods),
                               'conditions': [{k: guard[k] for k in ('id', 'expected', 'message')}
                                              for guard in operation.get('guards', [])],
                               'impacts': operation['impacts'],
                               'preserved_properties': operation['preserved_properties'],
                               'runtime_state': 'not_checked', 'full_branch_verification': 'not_assessed',
                               'evidence': records, 'missing': missing})
    operation_counts = {'mapped_operations': len(operations),
                        'execute_implemented': sum(o['execute_implemented'] for o in operations)}
    for kind in ('observed_execute', 'file_reload'):
        operation_counts[kind] = sum(bool(o['evidence'][kind]) for o in operations)
    # 4. 候选与执行属性没有一对一语义映射，保留逐候选材料及未判定原因。
    # 管线可能读取中间对象或由适配器拆成多个字段，成员被调用不能冒充整个候选已覆盖。
    candidates = [{'type': type_id, 'member': member, 'status': 'discovered',
                   'adaptation': 'not_assessed',
                   'reason': 'No one-to-one candidate-to-property semantic mapping'}
                  for type_id, entry in sorted(catalog['types'].items())
                  for member in sorted(entry['property_candidates'])]
    return {'schema_version': 1, 'target': catalog['target'],
            'catalog_id': plan['catalog_id'] if plan else None,
            'scope': catalog['scope'], 'discovery': discovery,
            'execution': {'status': 'loaded' if plan else 'not_supplied', 'counts': counts,
                          'read_adapters': dict(sorted(Counter(e['read_adapter'] for e in entries).items())),
                          'write_adapters': dict(sorted(Counter(e['write_adapter'] for e in entries
                                                               if e['write_implemented']).items())),
                          'properties': entries, 'operation_counts': operation_counts,
                          'operations': operations},
            'candidates': candidates, 'evidence': evidence,
            'evidence_counts': dict(sorted(Counter(e['status'] for e in evidence).items())),
            'runtime_state': 'not_checked', 'full_branch_verification': 'not_assessed',
            'limitations': ['Discovery and execution use different denominators; no global coverage percentage is inferred.',
                            'Observed success applies only to the supplied result targets and values, not every branch.',
                            'Result digests identify local evidence files; they do not authenticate their producer.',
                            'Current model/method conditions and CFD physical validity are not assessed offline.']}
