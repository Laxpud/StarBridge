"""为 CLI 与 MCP 提供相同的目录能力、对象读写和显式会话生命周期。

服务只编排现有 Bridge，不接受 Java 代码，也不隐式保存、关闭或重试修改。
每次调用返回状态封套；局部属性错误仍放在原目录结果中，由调用者逐项处理。
"""

import inspect
import math
from pathlib import Path
import sys
from types import SimpleNamespace

from starbridge.bridge.runner import session_bridge
from starbridge.bridge.runner.modifier import ModificationRejected
from .catalog import read_json
from .catalog_bundle import BUNDLES, bundle_root, bundle_target, session_target
from .coverage import coverage
from .execution import prepare_find, prepare_modification_value, prepare_read_value
from .snapshot import prepare_snapshot
from .session_store import new_session_directory, session_directory, public_session


METHODS = (
    'get_contract', 'discover_installations', 'get_capabilities', 'find_objects', 'describe_object', 'read_properties', 'modify',
    'inspect_session', 'open_session', 'session_status', 'save_session', 'close_session',
    'browse_tree', 'describe_node', 'read_node_properties', 'search_settings',
    'relocate_node', 'modify_node_property',
)


def _path(value, field):
    """将调用者明确给出的绝对路径规范化，避免 MCP 的工作目录决定目标算例。"""
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError(f'{field} must be an absolute path')
    return Path(value).resolve()


def _timeout(value):
    """拒绝布尔值、非有限数和非正超时；单位为秒。"""
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('timeout must be positive and finite')
    return value


class Service:
    """无会话缓存的本机服务；每次读盘和 Bridge 锁共同维护当前会话身份。"""

    def call(self, method, arguments):
        """校验公开方法和参数后执行，区分确定拒绝、结果不确定及其他错误。

        uncertain 以 Bridge 写入的状态为依据，不根据异常文本猜测 setter 是否执行。
        即使 MCP 客户端断开，管理会话仍存在；恢复时必须先查询状态，不能重发修改。
        """
        try:
            if method not in METHODS or not isinstance(arguments, dict):
                raise ValueError('Unknown service method or invalid arguments')
            operation = getattr(self, method)
            try:
                inspect.signature(operation).bind(**arguments)
            except TypeError as error:
                raise ValueError(str(error)) from error
            result = operation(**arguments)
            return {'status': 'ok', 'result': result}
        except Exception as error:
            status = 'rejected' if isinstance(error, (ModificationRejected, ValueError)) else 'error'
            state = None
            # 错误封套仅查看本次显式目标，不扫描用户会话，也不修改恢复状态。
            directory = arguments.get('session_id') if isinstance(arguments, dict) else None
            if isinstance(directory, str):
                try:
                    state = read_json(session_directory(directory) / 'session.json')
                except (OSError, ValueError):
                    pass
            if isinstance(error, session_bridge.OperationUncertain) or (
                    status != 'rejected' and isinstance(state, dict)
                    and state.get('state') == 'uncertain'):
                status = 'uncertain'
            result = {'status': status, 'error': {'type': type(error).__name__, 'message': str(error)}}
            if isinstance(state, dict):
                result['session_state'] = {key: state.get(key) for key in
                                           ('state', 'active_request', 'last_request', 'last_request_status')}
            # 失败恢复信息与错误一起返回，客户端不必先翻项目文档；不根据错误猜测是否已执行 setter。
            from .interface_contract import recovery_guidance
            result['recovery'] = recovery_guidance(status, directory, state)
            return result

    def get_contract(self):
        """不连接 STAR，返回与 MCP Resource 相同的自说明调用契约。"""
        return contract()

    def discover_installations(self, star=None, search_roots=None, timeout=30):
        """探测用户指定程序或有界环境候选的实际版本；不加载算例、不自动选择安装。"""
        from .environment import discover_installations
        return discover_installations(star, search_roots, _timeout(timeout))

    def get_capabilities(self, release=None, build=None):
        """查询注册能力，版本由调用者或安装探测提供；未知版本作为查询结果返回。

        省略版本时只列支持范围，不选择默认版本。给出 release 但未给 Build 时，
        返回该 release 的已登记目录，不代表本机安装或用户算例已匹配。
        """
        from .discovery_policy import TARGET, PROVIDERS, READ_RULES
        from .discovery_write import WRITING_ENABLED
        versions = [bundle_target(item) for item in BUNDLES]
        if release is None:
            if build is not None:
                raise ValueError('build requires release')
            return {'query_scope': 'registry', 'supported_versions': versions,
                    'runtime_discovery_versions': [dict(TARGET)], 'runtime_state': 'not_checked',
                    'selection_required': True,
                    'next_step': '需要选择安装时使用用户指定程序，或 discover_installations 获取实际 version；不能把支持列表当成本机安装列表。已有可用会话可沿用。'}
        if not isinstance(release, str) or not release or (build is not None and
                (not isinstance(build, str) or not build)):
            raise ValueError('release and optional build must be non-empty strings')
        if release not in BUNDLES or (build is not None and BUNDLES[release] != build):
            return {'query_scope': 'target', 'target': {'release': release, 'build': build},
                    'supported': False,
                    'support_status': 'unsupported_release' if release not in BUNDLES else 'unsupported_build',
                    'supported_versions': versions, 'runtime_state': 'not_checked',
                    'types': {}, 'execution': {},
                    'runtime_discovery': {'supported': False, 'write_enabled': False},
                    'limitations': ['当前未登记此版本的可执行适配；检测到安装不代表能够读取或修改其算例。'],
                    'next_step': '报告实际版本与缺少的适配；不要冒用邻近版本、自动切换安装或转换算例。'}
        root = bundle_root(bundle_target(release))
        report = coverage(root / 'generated' / 'catalog.json', execution_path=root / 'execution.json')
        rules = read_json(root / 'execution.json')
        return {
            'query_scope': 'target', 'supported': True, 'support_status': 'registered',
            'version_selection': 'exact_query' if build is not None else 'registered_build_for_release',
            'target': report['target'], 'catalog_id': report['catalog_id'],
            'supported_versions': versions,
            'runtime_state': 'not_checked', 'discovery': report['discovery'],
            'usage': {'contract_tool': 'starbridge.get_contract', 'contract_resource': 'starbridge://contract',
                      'next_step': '需要新会话时 open_session，已有可用会话直接沿用；按当前版本和目标选择发现或目录接口，types 不是当前算例实例。'},
            'types': {name: {key: entry.get(key) for key in ('java_class', 'parent_type')}
                      for name, entry in rules['types'].items()},
            'execution': report['execution'], 'limitations': report['limitations'],
            'runtime_discovery': {
                'supported': report['target'] == TARGET, 'target': TARGET,
                'providers': PROVIDERS, 'read_rules': READ_RULES,
                'write_enabled': WRITING_ENABLED and report['target'] == TARGET,
                'write_scope': 'Accepted special assignments and constant bounded-scalar/vector rules',
                'requirements': [
                    'Linux 管理会话，精确匹配已支持 Build。',
                    'open_session.star 解析后须位于对应安装目录内；不解析外部包装脚本。',
                    '可执行文件的某个父目录下须有本机 doc/client/html/type-search-index.js。',
                ],
                'instance_conditions': 'not_checked'},
            'unavailable': ['mesh_generation', 'solver_execution', 'persistent_memory'],
        }

    def _operate(self, session_id, action, timeout=180, **values):
        """复用原会话执行器，保留互斥、进程身份与不确定状态处理。"""
        if not sys.platform.startswith('linux'):
            raise ValueError('Managed sessions currently support Linux only')
        directory = session_directory(session_id)
        args = SimpleNamespace(action=action, timeout=_timeout(timeout), **values)
        return session_bridge.operate(args, directory)

    def _catalog(self, session_id, action, request, timeout):
        """用会话绑定版本准备请求；执行器持锁后再次核对，之后才设置活动标记。"""
        directory = session_directory(session_id)
        _timeout(timeout)
        root = bundle_root(session_target(read_json(directory / 'session.json')))
        paths = (root / 'generated' / 'catalog.json', root / 'execution.json')
        if action == 'modify':
            plan, prepared = prepare_modification_value(*paths, request)
        elif action == 'find':
            plan, prepared = prepare_find(*paths, request)
        else:
            plan, prepared = prepare_read_value(*paths, request, action)
        result = self._operate(session_id, action, timeout, catalog_plan=plan, catalog_request=prepared)
        if action == 'describe':
            # 将准备阶段生成的新值格式放回同一属性描述；不改动 Java 的条件检查及现有字段。
            entries = plan['properties'][prepared['target']['type']]
            for identifier, description in result.get('catalog', {}).get('properties', {}).items():
                description['write_contract'] = entries[identifier].get('write_contract')
        return result

    def find_objects(self, session_id, type_id, name=None, parent=None, offset=0, limit=100, timeout=180):
        """枚举目录类型，可按精确名称过滤；子类型要求 parent，单页最多 500 项。"""
        request = {'schema_version': 1, 'action': 'find', 'type': type_id, 'offset': offset, 'limit': limit}
        if name is not None:
            request['name'] = name
        if parent is not None:
            request['parent'] = parent
        return self._catalog(session_id, 'find', request, timeout)

    def _read(self, session_id, target, properties, action, timeout):
        """保留调用者选择的属性；省略表示该类型全部已映射属性。"""
        request = {'schema_version': 1, 'action': action, 'target': target}
        if properties is not None:
            request['properties'] = properties
        return self._catalog(session_id, action, request, timeout)

    def describe_object(self, session_id, target, properties=None, timeout=180):
        """描述属性、结构操作及当前已声明条件；不会预判尚未给出的新值。"""
        return self._read(session_id, target, properties, 'describe', timeout)

    def read_properties(self, session_id, target, properties=None, timeout=180):
        """返回逐属性值和错误，不把部分读取成功报告为完整设置导出。"""
        return self._read(session_id, target, properties, 'read', timeout)

    def modify(self, session_id, request, timeout=180):
        """提交一个 schema 2 属性修改或 schema 3 结构操作，保留 expected 核对与回读。"""
        return self._catalog(session_id, 'modify', request, timeout)

    def browse_tree(self, session_id, node_id=None, cursor=None, offset=0, limit=100,
                    scope='simulation', max_nodes=2000, timeout=180):
        """从根或已发现节点读取一层对象；游标绑定本次关系集合，不递归扫描。"""
        from .discovery import browse_tree
        return browse_tree(session_id, node_id=node_id, cursor=cursor, offset=offset,
                           limit=limit, scope=scope, max_nodes=max_nodes,
                           timeout=_timeout(timeout), operate=self._operate)

    def describe_node(self, session_id, node_id=None, scope='simulation', timeout=180,
                      property_ids=None, cursor=None, limit=100):
        """描述当前节点的属性及规则支持状态；不会隐式读取全部属性值。"""
        from .discovery import describe_node, page_description, _state
        from .discovery_write import describe_write_support
        description = describe_node(session_id, node_id=node_id, scope=scope,
                                    timeout=_timeout(timeout), operate=self._operate)
        state = _state(session_id)
        description = describe_write_support(session_id, description, state)
        return page_description(description, state, property_ids=property_ids, cursor=cursor, limit=limit)

    def read_node_properties(self, session_id, node_id, property_ids, timeout=180):
        """重新核对引用和实际描述符，再执行明确选择的属性读取计划。"""
        from .discovery import read_node_properties
        return read_node_properties(session_id, node_id=node_id, property_ids=property_ids,
                                    timeout=_timeout(timeout), operate=self._operate)

    def relocate_node(self, session_id, locator, timeout=180):
        """在新加载中按结构化路径唯一定位对象，返回当前会话的新引用。"""
        from .discovery import relocate_node
        return relocate_node(session_id, locator=locator, timeout=_timeout(timeout),
                             operate=self._operate)

    def modify_node_property(self, session_id, node_id, property_id, expected, value, timeout=180):
        """按受控规则修改单个发现属性；保留旧状态、完整快照和回读，不自动保存。"""
        from .discovery_write import modify_node_property
        return modify_node_property(session_id, node_id=node_id, property_id=property_id,
                                    expected=expected, value=value, timeout=_timeout(timeout),
                                    operate=self._operate)

    def search_settings(self, session_id, query, expand=False, max_nodes=100, max_depth=4,
                        scope='simulation', timeout=180, limit=100, cursor=None):
        """搜索已有发现范围；只有显式 expand 才按节点、深度和耗时预算继续发现。"""
        from .discovery import search_settings
        return search_settings(session_id, query=query, expand=expand, max_nodes=max_nodes,
                               max_depth=max_depth, scope=scope, timeout=_timeout(timeout),
                               operate=self._operate, limit=limit, cursor=cursor)

    def inspect_session(self, session_id, timeout=180):
        """读取既有 Inspector 快照范围；与按需属性读取共用目录，不表示全配置导出。"""
        return self._operate(session_id, 'inspect', timeout)

    def open_session(self, input=None, star='starccm+', release=None, port=None, timeout=180, build=None,
                     project_dir=None, debug=False):
        """先检测所选程序版本，优先连接匹配的本机会话；没有匹配时直接加载输入。

        用户给出的 release/Build 作为预期值核对。未知版本、Build 或预期不符时，
        在创建会话目录和加载算例前拒绝；实际 server 的版本仍由初始只读请求再核验。
        """
        from .environment import inspect_installation
        if not sys.platform.startswith('linux'):
            raise ValueError('Managed sessions currently support Linux only')
        if port is not None and (type(port) is not int or not 1024 <= port <= 65535):
            raise ValueError('port must be between 1024 and 65535')
        if not isinstance(star, str) or not star:
            raise ValueError('star must be an executable name or path')
        source = _path(input, 'input') if input is not None else None
        project = _path(project_dir, 'project_dir') if project_dir is not None else None
        if project is not None and not project.is_dir():
            raise ValueError('project_dir must be an existing directory')
        if source is None and (port is None or project is None):
            raise ValueError('Without input, specify port and project_dir for an existing session')
        if type(debug) is not bool:
            raise ValueError('debug must be a boolean')
        directory = new_session_directory()
        timeout = _timeout(timeout)
        for name, value in (('release', release), ('build', build)):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f'{name} must be a non-empty string when provided')
        detected = inspect_installation(star, min(timeout, 30))
        if detected['status'] != 'ok':
            raise ValueError(f'Cannot determine STAR version: {detected.get("reason")}; use discover_installations')
        target = detected['version']
        if (release is not None and release != target['release']) or (build is not None and build != target['build']):
            raise ValueError(f'STAR version does not match the requested release/build: requested '
                             f'{release}/{build}, detected {target}; no installation was substituted')
        if not detected['catalog_supported']:
            raise ValueError(f'No registered catalog for detected STAR version {target}; '
                             'query get_capabilities for support; no session was created')
        args = SimpleNamespace(input=source, star=detected['executable'], port=port,
                               timeout=timeout, snapshot_plan=prepare_snapshot(target),
                               project_dir=project, debug=debug)
        return public_session(session_bridge.connect(args, directory))

    def session_status(self, session_id):
        """读取会话记录并检查进程身份，不启动 Java 客户端，也不重新核验 server Build。"""
        return public_session(self._operate(session_id, 'status'))

    def save_session(self, session_id, output=None, timeout=180):
        """省略 output 保存当前路径；给出新路径则另存为，保存不自动关闭服务。"""
        return self._operate(session_id, 'save', timeout, output=_path(output, 'output') if output is not None else None)

    def close_session(self, session_id, discard=False, timeout=180):
        """外部会话只断开；自有服务默认检查未保存修改，显式 discard 才放弃内存状态。"""
        if type(discard) is not bool:
            raise ValueError('discard must be a boolean')
        return public_session(self._operate(session_id, 'stop', timeout, discard=discard))


def contract():
    """给客户端提供稳定的状态与恢复约定，供 CLI 和 MCP Resource 同源读取。"""
    from .interface_contract import usage_contract
    from .discovery_policy import TARGET
    return {
        'schema_version': 1, 'methods': list(METHODS), 'transport': 'local',
        'statuses': {
            'ok': 'Call completed; inspect property errors and inspection_complete for partial reads.',
            'rejected': 'Invalid input or confirmed rejection before assignment; lifecycle setup may have created files.',
            'uncertain': 'A request may have mutated the session. Check status and logs; do not retry.',
            'error': 'Call failed; inspect the error and session state before further actions.',
        },
        'session_lifetime': 'Explicit open/save/close; client exit does not close a session.',
        'identity': 'Object references belong to one session token; use full locators after reload.',
        'paths': 'Simulation, project and output paths must be absolute; session_id is returned by open_session.',
        'request_schemas': {'read': 1, 'property_modification': 2, 'structural_operation': 3,
                            'discovery': 1},
        'runtime_discovery': {
            'versions': [dict(TARGET)],
            'navigation': 'Browse one level, describe, then read explicit property_ids.',
            'search': 'Cached scope by default; expand uses explicit node, depth and time budgets.',
            'references': 'Opaque node_id and property_id; re-describe after identity or rule changes.',
        },
        'usage': usage_contract(),
    }
