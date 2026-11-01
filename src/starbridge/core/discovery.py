"""编排会话对象树发现、签名引用、按需属性读取与有界文本搜索。"""

import base64
import hashlib
import hmac
import json
import fcntl
import os
import secrets
import stat
import tempfile
from pathlib import Path
import time
from datetime import datetime, timezone

from .catalog import read_json
from .catalog_bundle import session_target
from .discovery_rules import RULE_VERSION, _write, build_read_plan, digest, property_id, select_rule
from .execution import prepare_read_value
from .discovery_policy import TARGET, rule_evidence

ALIASES = {'松弛': ['relaxation'], '压力': ['pressure'], '速度': ['velocity'],
           '时间步': ['time step', 'timestep'], '网格': ['mesh'], '求解器': ['solver'],
           '停止': ['stopping'], '温度': ['temperature'], '密度': ['density'],
           '粘度': ['viscosity'], '湍流': ['turbulence'], '边界': ['boundary'],
           '区域': ['region'], '连续体': ['continuum', 'continua'], '参数': ['parameter'], 'urf': ['relaxation', '松弛']}


def _state(session_dir):
    """所有缓存按当前会话 token 隔离；精确版本不支持时在启动客户端前拒绝。"""
    directory = Path(session_dir)
    if not directory.is_absolute():
        raise ValueError('session_dir must be absolute')
    state = read_json(directory / 'session.json')
    if session_target(state) != TARGET:
        raise ValueError('Runtime discovery is unsupported for this exact version')
    if not state.get('session_token'):
        raise ValueError('Session has no identity token')
    state['_discovery_secret'] = _reference_secret(directory)
    return state


def _reference_secret(directory):
    """在独立 0600 文件中保管签名密钥，公开会话 token 只标识世代。

    文件锁串行化首次初始化，原子替换保证其他进程只观察到完整密钥；
    密钥仅注入当前内存 state，不写入可返回给客户端的 session.json。
    """
    key_path = directory / '.discovery-reference-key'
    lock_path = directory / '.discovery-reference-key.lock'
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not key_path.exists():
            with tempfile.NamedTemporaryFile(dir=directory, prefix='.discovery-key-', delete=False) as stream:
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            temporary.replace(key_path)
        key_fd = os.open(key_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(key_fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
                raise ValueError('Discovery signing key requires an owner-only regular file')
            key = stream.read(33)
        if len(key) != 32:
            raise ValueError('Invalid discovery signing key')
        return key


def _sign(payload, state):
    """句柄内容由 Core 签名，调用者不能替换路径中的对象 key 或类。"""
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip('=')
    signature = hmac.new(state['_discovery_secret'], raw, hashlib.sha256).hexdigest()
    return encoded + '.' + signature


def _decode(value, state, kind):
    """先核验签名再解析身份；跨加载旧 token 生成的句柄明确失效。"""
    if not isinstance(value, str):
        raise ValueError('Discovery reference must be an opaque string')
    try:
        encoded, signature = value.rsplit('.', 1)
        raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        expected = hmac.new(state['_discovery_secret'], raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError('Stale or invalid discovery reference')
        payload = json.loads(raw)
        if payload['kind'] != kind or payload['session_token'] != state['session_token']:
            raise ValueError('Discovery reference kind or session mismatch')
        return payload
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeError) as error:
        raise ValueError('Invalid discovery reference') from error


def _invoke(session_dir, request, timeout, operate):
    """延迟导入服务以避免循环依赖，同时允许服务传入同一 transport 回调。"""
    if operate is None:
        from .service import Service
        operate = Service()._operate
    result = operate(str(session_dir), 'discovery', timeout, discovery_request=request)
    return result.get('discovery', result)


def _cache_path(session_dir, state):
    """元数据索引绑定版本、会话和规则，旧会话文件不会成为当前搜索依据。"""
    path = Path(session_dir) / 'discovery-cache' / digest([state['session_token'], session_target(state), RULE_VERSION])
    path.mkdir(parents=True, exist_ok=True)
    return path


def _decorate(node, state):
    """返回不透明句柄及可审阅的稳定路径，路径只是重定位材料而非当前身份。"""
    result = dict(node)
    if node.get('kind') == 'proxy':
        return {**result, 'node_id': None, 'breadcrumbs': node['path']}
    result['breadcrumbs'] = [{'name': p['name'], 'java_class': p['java_class']} for p in node['path']]
    result['node_id'] = _sign({'kind': 'node', 'session_token': state['session_token'], 'path': node['path']}, state)
    result['locator'] = [{'name': p['name'], 'java_class': p['java_class']} for p in node['path']]
    return result


def _remember(session_dir, state, node, properties=None, **coverage):
    """每个节点单独落盘；描述结果覆盖该节点旧 schema，当前值从不写入索引。"""
    path = _cache_path(session_dir, state) / (digest(node['path']) + '.json')
    previous = read_json(path) if path.is_file() else {}
    now = time.time()
    entry = {**previous, 'node': node, 'node_observed_at': now, **coverage}
    scope = coverage.get('scope', 'simulation')
    entry['scopes'] = sorted(set(previous.get('scopes', [previous.get('scope')] if previous.get('scope') else [])) | {scope})
    # 两类观察分别按范围保存；展开 children 不会刷新旧属性的时间或覆盖其错误。
    for kind in ('children', 'property'):
        key = kind + '_coverage'
        if key in coverage:
            entry[key] = {**previous.get(key, {}), scope: {**coverage[key], 'observed_at': now}}
    if properties is not None:
        entry['properties'] = properties
        entry['properties_observed_at'] = now
    _write(path, entry)


def _target(node_id, state):
    """只有 Core 已签名的路径可进入运行时；根节点允许省略。"""
    if node_id is None:
        return None
    return {'session_token': state['session_token'], 'path': _decode(node_id, state, 'node')['path']}


def _budget(value, name, maximum):
    """限制客户端可请求的遍历规模，布尔值不作为整数接受。"""
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError(f'{name} must be between 1 and {maximum}')
    return value


def browse_tree(session_dir, node_id=None, cursor=None, offset=0, limit=100, scope='simulation',
                max_nodes=2000, timeout=180, operate=None):
    """展开一个真实节点；分页游标绑定父节点和当前子列表指纹。"""
    state = _state(session_dir)
    _budget(limit, 'limit', 500)
    _budget(max_nodes, 'max_nodes', 10000)
    if scope not in ('simulation', 'all'):
        raise ValueError('Unsupported discovery scope')
    if type(offset) is not int or offset < 0:
        raise ValueError('offset must be non-negative')
    saved = _decode(cursor, state, 'cursor') if cursor is not None else None
    if saved:
        if node_id is None:
            node_id = saved['node_id']
        if saved['node_id'] != node_id or saved['scope'] != scope:
            raise ValueError('Cursor belongs to another node or scope')
        offset = saved['offset']
    request = {'action': 'browse', 'offset': offset, 'limit': limit, 'max_nodes': max_nodes,
               'scope': scope, 'timeout_ms': max(1, min(30000, int(timeout * 1000)))}
    target = _target(node_id, state)
    if target is not None:
        request['target'] = target
    result = _invoke(session_dir, request, timeout, operate)
    if saved and saved['fingerprint'] != result.get('fingerprint'):
        raise ValueError('Discovery pagination invalidated by tree change')
    if 'node' not in result:
        return result
    node = _decorate(result['node'], state)
    children = [_decorate(n, state) for n in result.get('children', [])]
    _remember(session_dir, state, node, children_state=result.get('state'), scope=scope,
              fingerprint=result.get('fingerprint'), next_offset=result.get('next_offset'),
              children_coverage={'state': result.get('state'), 'next_offset': result.get('next_offset'),
                  'errors': result.get('errors', []), 'truncations': result.get('truncations', []),
                  'unsupported': [n for n in children if n.get('kind') == 'proxy']})
    for child in children:
        if child.get('node_id') is None:
            continue
        _remember(session_dir, state, child, scope=scope)
    next_cursor = None
    if result.get('next_offset') is not None:
        next_cursor = _sign({'kind': 'cursor', 'session_token': state['session_token'],
            'node_id': node['node_id'], 'scope': scope, 'offset': result['next_offset'],
            'fingerprint': result.get('fingerprint')}, state)
    return {**result, 'schema_version': 1, 'node': node, 'children': children,
            'next_cursor': next_cursor, 'cache_state': 'refreshed', 'scope': scope}


def describe_node(session_dir, node_id=None, scope='simulation', timeout=180, operate=None):
    """刷新实例描述符，未知类型保留完整元数据和不可执行原因。"""
    state = _state(session_dir)
    if scope not in ('simulation', 'all'):
        raise ValueError('Unsupported discovery scope')
    request = {'action': 'describe', 'scope': scope, 'limit': 500, 'max_nodes': 10000, 'timeout_ms': max(1, min(30000, int(timeout * 1000)))}
    target = _target(node_id, state)
    if target is not None:
        request['target'] = target
    started = time.monotonic()
    result = _invoke(session_dir, request, timeout, operate)
    while result.get('next_offset') is not None and time.monotonic() - started < timeout:
        page = _invoke(session_dir, {**request, 'offset': result['next_offset']},
                       max(0.1, timeout - (time.monotonic() - started)), operate)
        if page.get('fingerprint') != result.get('fingerprint'):
            raise ValueError('Property schema changed during pagination')
        result['properties'].extend(page.get('properties', []))
        result['next_offset'] = page.get('next_offset')
        result.setdefault('errors', []).extend(page.get('errors', []))
        result.setdefault('truncations', []).extend(page.get('truncations', []))
        if page.get('state') != 'complete':
            result['state'] = 'partial'
    if result.get('next_offset') is not None:
        result['state'] = 'partial'
    if 'node' not in result:
        return result
    node = _decorate(result['node'], state)
    properties, seen = [], set()
    for descriptor in result.get('properties', []):
        identifier = property_id(descriptor)
        if identifier in seen:
            continue
        seen.add(identifier)
        rule, reason = select_rule(descriptor)
        properties.append({**descriptor, 'property_id': identifier,
            'readable': rule is not None, 'read_state': 'candidate_requires_plan_validation' if rule else 'unsupported',
            'read_reason': reason, 'writable': False, 'write_state': 'requires_verified_write_rule',
            'discovered': True, 'read_support': 'unknown' if rule else 'unsupported',
            'setter_present': descriptor.get('setter') is not None, 'write_support': 'unknown',
            'write_enabled': False, 'target_conditions': 'not_checked', 'value_conditions': 'not_checked',
            'evidence': {'descriptor_sources': descriptor.get('sources', []), 'rule_version': RULE_VERSION,
                         'member_validation': 'pending_read_plan',
                         'mechanism': rule_evidence(rule[0]) if rule else None},
            'range_state': 'not_checked'})
    _remember(session_dir, state, node, properties, property_state=result.get('state'), scope=scope,
              descriptor_fingerprint=result.get('fingerprint'),
              property_coverage={'state': result.get('state'), 'errors': result.get('errors', []),
                  'truncations': result.get('truncations', []), 'next_offset': result.get('next_offset')})
    return {**result, 'schema_version': 1, 'node': node, 'properties': properties,
            'cache_state': 'refreshed', 'rule_version': RULE_VERSION}


def page_description(description, state, property_ids=None, cursor=None, limit=100):
    """对已完整准备的描述结果选择和分页，不裁剪内部编译或写入保持范围。

    游标绑定节点、全部属性描述指纹和选择顺序。服务每次先刷新完整描述，
    再调用本函数；返回的页面不改变原始观察的 complete/partial 状态。
    """
    _budget(limit, 'limit', 500)
    if 'node' not in description:
        return description
    saved = _decode(cursor, state, 'description_cursor') if cursor is not None else None
    if property_ids is None and saved is not None:
        property_ids = saved['selection']
    if property_ids is not None and (not isinstance(property_ids, list)
            or not 1 <= len(property_ids) <= 500
            or any(not isinstance(identifier, str) or not identifier for identifier in property_ids)
            or len(property_ids) != len(set(property_ids))):
        raise ValueError('property_ids must contain 1 to 500 unique non-empty IDs')
    properties = description.get('properties', [])
    by_id = {prop['property_id']: prop for prop in properties}
    if property_ids is not None and not set(property_ids) <= by_id.keys():
        raise ValueError('Unknown or stale property ID in description selection')
    selected = properties if property_ids is None else [by_id[identifier] for identifier in property_ids]
    node_id = description['node']['node_id']
    fingerprint = digest(properties)
    offset = 0
    if saved is not None:
        if (saved['node_id'] != node_id or saved['fingerprint'] != fingerprint
                or saved['selection'] != property_ids):
            raise ValueError('Description cursor invalidated by node, schema or selection change')
        offset = saved['offset']
    end = offset + limit
    next_offset = end if end < len(selected) else None
    next_cursor = None if next_offset is None else _sign({
        'kind': 'description_cursor', 'session_token': state['session_token'],
        'node_id': node_id, 'fingerprint': fingerprint,
        'selection': property_ids, 'offset': next_offset}, state)
    return {**description, 'properties': selected[offset:end], 'offset': offset,
            'total_count': len(selected), 'descriptor_total_count': len(properties),
            'next_cursor': next_cursor, 'next_offset': next_offset,
            'descriptor_next_offset': description.get('next_offset'),
            'selection': property_ids}


def prepare_node_read(session_dir, node_id, property_ids, timeout=180, operate=None, writer_hook=None):
    """读取前刷新描述符与对象身份，并对显式属性集合生成校验后的计划。"""
    if (not isinstance(property_ids, list) or not 1 <= len(property_ids) <= 500
            or any(not isinstance(p, str) or not p for p in property_ids)
            or len(set(property_ids)) != len(property_ids)):
        raise ValueError('property_ids must contain 1 to 500 unique non-empty IDs')
    started = time.monotonic()
    description = describe_node(session_dir, node_id, timeout=timeout, operate=operate)
    if 'node' not in description:
        raise ValueError('Discovery node is unavailable')
    descriptors = {p['property_id']: p for p in description['properties']}
    if not set(property_ids) <= descriptors.keys():
        raise ValueError('Unknown or stale property ID')
    unsupported = [p for p in property_ids if not descriptors[p]['readable']]
    supported = [descriptors[p] for p in property_ids if p not in unsupported]
    state = _state(session_dir)
    plans, compilation_errors = [], []
    if supported:
        try:
            plans.append(build_read_plan(session_dir, description['node'], supported, state, writer_hook=writer_hook))
        except (ValueError, KeyError, OSError) as combined_error:
            # 单个声明缺失不能取消其他属性读取；写入仍必须完整规划，不能使用此降级结果。
            if writer_hook is not None:
                raise ValueError('Write planning requires complete property validation') from combined_error
            for descriptor in supported:
                if time.monotonic() - started >= timeout:
                    compilation_errors.append({'property_id': descriptor['property_id'], 'reason': 'time_budget'})
                    continue
                try:
                    plans.append(build_read_plan(session_dir, description['node'], [descriptor], state))
                except (ValueError, KeyError, OSError) as error:
                    compilation_errors.append({'property_id': descriptor['property_id'],
                        'reason': 'plan_validation_failed', 'message': str(error)})
    return {'prepared': plans[0] if len(plans) == 1 else None, 'prepared_plans': plans,
            'description': description, 'unsupported': unsupported, 'compilation_errors': compilation_errors}


def read_node_properties(session_dir, node_id, property_ids, timeout=180, operate=None):
    """只读取显式选择的属性；不支持项单独报告，不把部分成功当成完整结果。"""
    started = time.monotonic()
    context = prepare_node_read(session_dir, node_id, property_ids, timeout, operate)
    errors = ([{'property_id': p, 'reason': 'unsupported_property'} for p in context['unsupported']]
              + context['compilation_errors'])
    outcomes, values = [], {}
    if operate is None:
        from .service import Service
        operate = Service()._operate
    for prepared in context['prepared_plans']:
        selected = list(prepared['property_map'])
        if time.monotonic() - started >= timeout:
            errors.extend({'property_id': p, 'reason': 'time_budget'} for p in selected)
            continue
        request = {'schema_version': 1, 'action': 'read', 'target': prepared['target'],
            'properties': selected + [extra for p in selected for extra in prepared.get('supplemental', {}).get(p, [])]}
        plan, request = prepare_read_value(prepared['catalog_path'], prepared['execution_path'], request, 'read')
        # 实例绑定不进入可重用类缓存；每次执行重新检查实际父关系和导航路径。
        plan['discovery_binding'] = prepared['binding']
        outcome = operate(str(session_dir), 'read', max(0.1, timeout - (time.monotonic() - started)),
                          catalog_plan=plan, catalog_request=request)
        outcomes.append(outcome)
        values.update(outcome.get('catalog', {}).get('properties', {}))
    complete = bool(outcomes) and all(o.get('catalog', {}).get('inspection_complete', False) for o in outcomes)
    result = outcomes[0] if len(outcomes) == 1 else {
        'requests': outcomes, 'catalog': {'properties': values, 'inspection_complete': complete}}
    properties = {}
    for identifier in property_ids:
        if identifier in context['unsupported']:
            properties[identifier] = {'status': 'unsupported', 'reason': 'unsupported_property'}
            continue
        failure = next((e for e in errors if e['property_id'] == identifier), None)
        value = dict(values.get(identifier, {'status': 'error', 'error': failure or 'Missing runtime property result'}))
        # 辅助管线结果与主值分开表达，保留动态范围错误和关联身份，不从值猜测单位。
        for suffix, field in (('_relation', 'relation'), ('_range', 'range')):
            auxiliary = identifier + suffix
            if auxiliary in values:
                value[field] = values[auxiliary]
        value.setdefault('range', {'status': 'not_supported', 'reason': 'No verified range provider'})
        properties[identifier] = value
    node = dict(context['description']['node'])
    # 数量/选项关联来自实际解包对象；它不一定属于 getChildren 的导航树。
    node['relations'] = list(node.get('relations', [])) + [
        {'kind': 'input_backing_object', 'property_id': identifier,
         'target_reference': entry['relation']['value'],
         'navigation': 'through_property_read'}
        for identifier, entry in properties.items()
        if entry.get('relation', {}).get('status') == 'ok']
    return {'schema_version': 1, 'schema_id': 'starbridge.discovery',
            'node': node, 'property_ids': property_ids,
            'properties': properties,
            'result': result, 'errors': errors, 'inspection_complete': not errors and complete,
            'observed_at': datetime.now(timezone.utc).isoformat(), 'value_source': 'runtime',
            'validity': 'Observed during this request; external changes require a new read'}


def search_settings(session_dir, query, expand=False, max_nodes=100, max_depth=4, scope='simulation',
                    timeout=180, operate=None, limit=100, cursor=None):
    """搜索已发现元数据，或在节点、深度及墙钟预算内扩展实际树。

    空命中只说明当前覆盖范围没有匹配；未展开、截断和错误在 coverage 中保留。
    """
    state = _state(session_dir)
    if not isinstance(query, str) or not query.strip():
        raise ValueError('query must be non-empty')
    if type(expand) is not bool:
        raise ValueError('expand must be boolean')
    _budget(max_nodes, 'max_nodes', 10000)
    _budget(max_depth, 'max_depth', 32)
    if scope not in ('simulation', 'all'):
        raise ValueError('Unsupported discovery scope')
    _budget(limit, 'limit', 500)
    started, visited, errors, truncations = time.monotonic(), 0, [], []
    unsupported = []
    if expand:
        queue = [(None, 0)]
        seen_nodes = set()
        while queue and visited < max_nodes and time.monotonic() - started < timeout:
            identifier, depth = queue.pop(0)
            remaining = max(0.1, timeout - (time.monotonic() - started))
            try:
                description = describe_node(session_dir, identifier, scope, remaining, operate)
                visited += 1
                if 'node' not in description:
                    errors.append(description)
                    continue
                actual = description['node']['node_id']
                identity = description['node']['key']
                if identity in seen_nodes:
                    continue
                seen_nodes.add(identity)
                if depth >= max_depth:
                    truncations.append({'node_id': actual, 'reason': 'max_depth'})
                    continue
                if time.monotonic() - started >= timeout:
                    truncations.append({'node_id': actual, 'reason': 'time_budget_before_browse'})
                    break
                page = browse_tree(session_dir, actual, limit=min(500, max_nodes), scope=scope,
                                   max_nodes=max_nodes, timeout=max(0.1, timeout - (time.monotonic() - started)), operate=operate)
                queue.extend((n['node_id'], depth + 1) for n in page.get('children', []) if n.get('node_id'))
            except (ValueError, OSError, RuntimeError) as error:
                errors.append({'node_id': identifier, 'message': str(error)})
        if queue:
            truncations.append({'reason': 'max_nodes_or_timeout', 'pending_nodes': len(queue)})
    terms = {query.strip().casefold()}
    for chinese, english in ALIASES.items():
        if chinese.casefold() in query.casefold() or any(word.casefold() in query.casefold() for word in english):
            terms.update([chinese, *english])
    matches, indexed, unexpanded, undescribed = [], 0, 0, 0
    matched_identities, covered_observations = set(), set()
    entries = [read_json(path) for path in sorted(_cache_path(session_dir, state).glob('*.json'))]
    # 路径中已发现的资源管理器使整个资源分支排除；不用英文显示名称分类。
    resource_type = 'star.material.MaterialDataBaseManager'
    resource_keys = {entry['node'].get('key') for entry in entries
                     if resource_type in entry['node'].get('hierarchy', [])
                     or entry['node'].get('java_class') == resource_type}
    for entry in entries:
        node = entry['node']
        scopes = entry.get('scopes', [entry.get('scope')])
        if scope == 'simulation' and ('simulation' not in scopes or any(
                part.get('key') in resource_keys or part.get('java_class') == resource_type for part in node['path'])):
            continue
        indexed += 1
        observations = {}
        for kind in ('children', 'property'):
            available = entry.get(kind + '_coverage', {})
            observation = available.get(scope)
            if observation is None and available:
                observation = max(available.values(), key=lambda item: item.get('observed_at', 0))
            observations[kind] = observation
            if observation is None:
                continue
            context = {'observation_node_id': node.get('node_id'), 'observation': kind,
                       'observed_at': observation.get('observed_at'), 'validity': 'cached_may_be_stale'}
            for field, destination in (('errors', errors), ('truncations', truncations), ('unsupported', unsupported)):
                for item in observation.get(field, []):
                    identity = digest([node.get('key'), kind, field, item])
                    if identity not in covered_observations:
                        covered_observations.add(identity)
                        destination.append({**item, **context})
            if observation.get('state') == 'partial':
                truncations.append({**context, 'reason': 'partial_' + kind + '_observation'})
            if observation.get('next_offset') is not None:
                truncations.append({**context, 'reason': kind + '_page_limit'})
        children_observation = observations['children'] or {}
        if children_observation.get('state') != 'complete' or children_observation.get('next_offset') is not None:
            unexpanded += 1
        if 'properties' not in entry:
            undescribed += 1
        fields = {'name': node.get('name', ''), 'path': ' / '.join(p['name'] for p in node['path']),
                  'java_class': node.get('java_class', '')}
        for prop in [None, *entry.get('properties', [])]:
            searchable = dict(fields)
            if prop:
                searchable.update({key: str(prop.get(key, '')) for key in ('name', 'display_name', 'description', 'short_description', 'property_type')})
                getter = prop.get('getter') or {}
                searchable['getter'] = str(getter.get('owner', '')) + '#' + str(getter.get('name', '')) + '(' + ','.join(getter.get('parameter_types', [])) + ')'
            evidence = [{'field': key, 'term': term} for key, value in searchable.items()
                        for term in terms if term in value.casefold()]
            identity = (node.get('key'), prop.get('property_id') if prop else None)
            if evidence and identity not in matched_identities:
                matched_identities.add(identity)
                matches.append({'node': node, 'property': prop, 'matched_by': evidence,
                                'observed_at': entry.get('properties_observed_at') if prop else entry.get('node_observed_at'),
                                'validity': 'cached_may_be_stale', 'requires_revalidation': True,
                                'revalidation': 'describe_node/read_node_properties re-resolve identity and refresh descriptors'})
    fingerprint = digest(matches)
    offset = 0
    if cursor is not None:
        saved = _decode(cursor, state, 'search_cursor')
        if saved['query'] != query or saved['scope'] != scope or saved['fingerprint'] != fingerprint:
            raise ValueError('Search cursor invalidated by query or metadata change')
        offset = saved['offset']
    next_offset = offset + limit
    next_cursor = _sign({'kind': 'search_cursor', 'session_token': state['session_token'],
        'query': query, 'scope': scope, 'fingerprint': fingerprint, 'offset': next_offset}, state) if next_offset < len(matches) else None
    return {'schema_version': 1, 'query': query, 'matches': matches[offset:next_offset],
            'next_cursor': next_cursor, 'total_matches': len(matches), 'coverage': {
        'scope': scope, 'mode': 'budgeted_expansion' if expand else 'cached_only', 'indexed_nodes': indexed,
        'visited_nodes': visited, 'unexpanded_nodes': unexpanded, 'undescribed_nodes': undescribed, 'errors': errors, 'truncations': truncations,
        'unsupported': unsupported,
        'max_nodes': max_nodes, 'max_depth': max_depth, 'elapsed_seconds': time.monotonic() - started,
        'cache_state': 'session_metadata_values_not_cached', 'whole_simulation_complete': False}}


def relocate_node(session_dir, locator, timeout=180, operate=None):
    """用结构化名称和类型路径重新绑定当前会话；每层唯一性由运行时检查。

    locator 不包含可调用成员，旧 key 和旧 token 不参与身份继承。成功结果是新引用，
    不能被解释为保存前后仍为同一 Java 实例。
    """
    state = _state(session_dir)
    if not isinstance(locator, list) or not locator or len(locator) > 64:
        raise ValueError('locator must be a non-empty path of at most 64 elements')
    for step in locator:
        if not isinstance(step, dict) or set(step) != {'name', 'java_class'} or any(
                not isinstance(step[k], str) or not step[k] for k in step):
            raise ValueError('locator elements require name and java_class')
    result = _invoke(session_dir, {'action': 'describe', 'relocate': True,
        'target': {'path': locator}, 'limit': 500,
        'timeout_ms': max(1, min(30000, int(timeout * 1000)))}, timeout, operate)
    if 'node' not in result:
        return result
    node = _decorate(result['node'], state)
    _remember(session_dir, state, node, scope='simulation')
    return {'schema_version': 1, 'node': node, 'identity_state': 'relocated_new_session_reference',
            'errors': result.get('errors', []), 'state': result.get('state')}
