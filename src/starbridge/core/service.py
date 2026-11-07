"""为 CLI 与 MCP 提供相同的目录能力、对象读写和显式会话生命周期。

结构化对象接口与通用 Java 步骤共享会话，不自动关闭或重试修改。
结构化修改不保存；通用 Java 及 STAR 既有自动保存可能写文件，须按实际任务判断。
每次调用返回状态封套；局部属性错误和逐步执行状态均保留，不能把调用结束当成任务完成。
"""

import inspect
import math
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from starbridge.bridge.runner import session_bridge
from starbridge.bridge.runner.modifier import ModificationRejected
from .catalog import read_json
from .catalog_bundle import BUNDLES, bundle_root, bundle_target, session_target
from .coverage import coverage
from .execution import prepare_find, prepare_modification_value, prepare_read_value
from . import objects
from .session_store import new_session_directory, session_directory, public_session


METHODS = (
    'get_contract', 'discover_installations', 'get_capabilities', 'search_api', 'read_api',
    'find_objects', 'browse_tree', 'search_settings', 'relocate_object',
    'describe_object', 'read_properties', 'modify_property', 'execute_operation',
    'inspect_session', 'open_session', 'session_status', 'save_session', 'close_session',
    'execute_macro', 'get_execution', 'read_execution_artifact', 'reconcile_execution', 'list_recipes', 'execute_recipe',
    'search_memory', 'get_memory', 'record_memory', 'update_memory',
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


def source_object(source):
    """提取引用表原始对象记录，避免把内部能力来源写入对象身份。"""
    return {key: value for key, value in source.items() if key != 'source'}


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
            execution_status = result.get('execution', {}).get('status') if isinstance(result, dict) else None
            status = {'partial': 'partial', 'failed': 'error', 'uncertain': 'uncertain',
                      'rejected': 'rejected', 'running': 'busy'}.get(execution_status, 'ok')
            return {'status': status, 'result': result}
        except Exception as error:
            status = 'rejected' if isinstance(error, (ModificationRejected, ValueError)) else 'error'
            from .memory import MemoryStoreError, MemoryConflictError, MemoryBusyError, MemoryPersistenceError
            if isinstance(error, MemoryStoreError):
                # 记忆写入不是算例操作；尤其提交结果未知时不能建议重新执行 STAR 任务。
                status = ('rejected' if isinstance(error, MemoryConflictError) else
                          'busy' if isinstance(error, MemoryBusyError) else
                          'uncertain' if isinstance(error, MemoryPersistenceError) and error.may_have_committed else 'error')
                return {'status': status, 'error': {'type': type(error).__name__, 'message': str(error)},
                        'recovery': {'automatic_retry': False, 'next_tool': 'starbridge.get_memory',
                                     'instruction': '先读取相同范围的记忆核对修订；不得因此重做已完成的算例操作。'}}
            state = None
            # 错误封套仅查看本次显式目标，不扫描用户会话，也不修改恢复状态。
            directory = arguments.get('session_id') if isinstance(arguments, dict) else None
            if isinstance(directory, str):
                try:
                    state = read_json(session_directory(directory) / 'session.json')
                except (OSError, ValueError):
                    pass
            if isinstance(error, session_bridge.OperationBusy):
                status = 'busy'
            elif isinstance(error, session_bridge.OperationUncertain):
                status = 'uncertain'
            result = {'status': status, 'error': {'type': type(error).__name__, 'message': str(error)}}
            if isinstance(state, dict):
                result['session_state'] = {key: state.get(key) for key in
                                           ('state', 'active_request', 'last_request', 'last_request_status',
                                            'uncertain_request')}
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

    def search_api(self, query, installation=None, session_id=None, kind='all', offset=0, limit=20):
        """在所选安装的官方索引中找类／成员，不要求目录适配或运行 STAR。"""
        from .api_docs import documentation
        return documentation(installation, session_id).search(query, kind, offset, limit)

    def read_api(self, java_class, installation=None, session_id=None, member=None, offset=0, limit=20):
        """按需读取签名、说明、文中代码及继承来源，缺失资料不是 API 不存在。"""
        from .api_docs import documentation
        return documentation(installation, session_id).read(java_class, member, offset, limit)

    def get_capabilities(self, release=None, build=None):
        """查询注册能力，版本由调用者或安装探测提供；未知版本作为查询结果返回。

        省略版本时只列支持范围，不选择默认版本。给出 release 但未给 Build 时，
        返回该 release 的已登记目录，不代表本机安装或用户算例已匹配。
        """
        from .discovery_policy import TARGET, PROVIDERS, READ_RULES
        from .discovery_write import WRITING_ENABLED
        versions = [bundle_target(item) for item in BUNDLES]
        # 注册表只证明结构化适配存在；通用入口始终单列，并明确仍需安装编译与运行时身份检查。
        general = {
            'support_scope': 'structured_catalog',
            'session_lifecycle': {'entry_points_available': True, 'methods': ['open_session', 'save_session', 'close_session'],
                'compatibility': 'requires_selected_installation_compile_and_runtime_identity_check',
                'runtime_state': 'not_checked', 'registered_catalog_required': False},
            'generic_execution': {'method': 'execute_macro', 'entry_point_available': True,
                'coverage': 'Caller-selected STAR Java macro API', 'compatibility': 'per_request_compilation_required',
                'runtime_state': 'not_checked', 'registered_catalog_required': False,
                'session_reuse': True, 'ordered_steps': True, 'durable_receipts': True,
                'scope': 'Caller-selected code; compilation is not behavior validation or a code sandbox',
                'completion': 'Step returned and JSON result recorded; not CFD validity'},
            'prepared_methods': {'discovery_method': 'list_recipes', 'execution_method': 'execute_recipe',
                'scope': 'Explicit parameterized methods; inspect applicability and evidence before execution'},
            'working_memory': {'supported': True, 'methods': ['search_memory', 'get_memory',
                'record_memory', 'update_memory'], 'activation': 'Review candidates against current task context',
                'verification': 'Record existing evidence only; do not run additional validation for memory'},
        }
        if release is None:
            if build is not None:
                raise ValueError('build requires release')
            return {**general, 'query_scope': 'registry', 'supported_versions': versions,
                    'runtime_discovery_versions': [dict(TARGET)], 'runtime_state': 'not_checked',
                    'selection_required': True,
                    'next_step': '需要选择安装时使用用户指定程序，或 discover_installations 获取实际 version；不能把支持列表当成本机安装列表。已有可用会话可沿用。'}
        if not isinstance(release, str) or not release or (build is not None and
                (not isinstance(build, str) or not build)):
            raise ValueError('release and optional build must be non-empty strings')
        if release not in BUNDLES or (build is not None and BUNDLES[release] != build):
            return {**general, 'query_scope': 'target', 'target': {'release': release, 'build': build},
                    'supported': False, 'catalog_supported': False,
                    'support_status': 'unsupported_release' if release not in BUNDLES else 'unsupported_build',
                    'supported_versions': versions, 'runtime_state': 'not_checked',
                    'types': {}, 'execution': {},
                    'runtime_discovery': {'supported': False, 'write_enabled': False},
                    'limitations': ['当前未登记此版本的结构化目录或发现适配；通用入口可用不等于该版本全部API已经验证。'],
                    'next_step': '可用实际检测安装尝试通用会话预编译与身份握手；结构化接口仍不可用，不冒用邻近目录、切换安装或转换算例。'}
        root = bundle_root(bundle_target(release))
        report = coverage(root / 'generated' / 'catalog.json', execution_path=root / 'execution.json')
        rules = read_json(root / 'execution.json')
        return {
            **general,
            'query_scope': 'target', 'supported': True, 'catalog_supported': True, 'support_status': 'registered',
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
            'unavailable': [],
        }

    def _operate(self, session_id, action, timeout=180, **values):
        """复用原会话执行器，保留互斥、进程身份与不确定状态处理。"""
        if not sys.platform.startswith('linux'):
            raise ValueError('Managed sessions currently support Linux only')
        directory = session_directory(session_id)
        args = SimpleNamespace(action=action, timeout=_timeout(timeout), **values)
        return session_bridge.operate(args, directory)

    def _catalog(self, session_id, action, request, timeout, audit=False):
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
        result = self._operate(session_id, action, timeout, catalog_plan=plan, catalog_request=prepared, audit=audit)
        if action == 'describe':
            # 将准备阶段生成的新值格式放回同一属性描述；不改动 Java 的条件检查及现有字段。
            entries = plan['properties'][prepared['target']['type']]
            for identifier, description in result.get('catalog', {}).get('properties', {}).items():
                description['write_contract'] = entries[identifier].get('write_contract')
        return result

    def find_objects(self, session_id, type_id, name=None, parent_id=None, offset=0, limit=100, timeout=180):
        """按已适配类型查找，返回统一对象引用；子类型的 parent_id 来自父对象查找。"""
        request = {'schema_version': 1, 'action': 'find', 'type': type_id, 'offset': offset, 'limit': limit}
        if name is not None:
            request['name'] = name
        if parent_id is not None:
            request['parent'] = objects.catalog_target(session_id, parent_id)
        outcome = self._catalog(session_id, 'find', request, timeout)
        result = {key: value for key, value in outcome['catalog'].items()
                  if key not in ('schema_version', 'catalog_id', 'action')}
        result['objects'] = [objects.catalog_object(session_id, item) for item in result['objects']]
        result.update({key: value for key, value in outcome.items() if key != 'catalog'})
        return {**result, 'schema_version': 2, 'schema_id': 'starbridge.objects'}

    def _read(self, session_id, target, properties, action, timeout):
        """把统一属性选择交给目录编译器；这里不建立第二套对外读取契约。"""
        request = {'schema_version': 1, 'action': action, 'target': target}
        if properties is not None:
            request['properties'] = properties
        return self._catalog(session_id, action, request, timeout)

    def describe_object(self, session_id, object_id=None, property_ids=None, cursor=None,
                        limit=100, scope='simulation', timeout=180):
        """描述对象的属性与结构操作；目录和运行时结果共用 properties[id]。

        首次调用观察对象，翻页沿用同一次描述。只读值不会缓存为写入前提；
        后续读取和修改仍由实际执行器刷新对象身份及属性状态。
        """
        from . import discovery
        discovery._budget(limit, 'limit', 500)
        if scope not in ('simulation', 'all'):
            raise ValueError('Unsupported discovery scope')
        if property_ids is not None:
            objects.selection(property_ids)
        _timeout(timeout)
        # 1. 引用表决定能力来源；调用者不需要切换两套描述方法。
        source = objects.resolve(session_id, object_id) if object_id is not None else {'source': 'runtime'}
        if source['source'] == 'runtime':
            result = discovery.describe_page(session_id, node_id=object_id, scope=scope,
                property_ids=property_ids, cursor=cursor, limit=limit, timeout=timeout, operate=self._operate)
            return objects.runtime_result(result)
        # 2. 目录描述同样按一次观察分页，不为后续页面重新访问 STAR。
        state = discovery.reference_state(session_id)
        if cursor is None:
            outcome = self._read(session_id, objects.catalog_target(session_id, object_id),
                                 property_ids, 'describe', timeout)
            description = objects.catalog_result(outcome, objects.catalog_object(session_id, source_object(source)))
            saved = {'kind': 'catalog_cursor', 'object_id': object_id, 'scope': scope,
                     'selection': property_ids, 'description': description, 'expires_at': time.time() + 300,
                     'property_order': list(description['properties']), 'offset': 0}
        else:
            saved = discovery._decode(cursor, state, 'catalog_cursor')
            if (saved['object_id'] != object_id or saved['scope'] != scope
                    or (property_ids is not None and property_ids != saved['selection'])):
                raise ValueError('Description cursor belongs to another object, scope or selection')
            if saved['expires_at'] < time.time():
                raise ValueError('Description snapshot expired; describe again')
            description = saved['description']
        # 3. 游标绑定原对象与选择；完整性沿用原观察，不由页面大小推断。
        # 引用表按键排序序列化 JSON；单独记录顺序，防止翻页后属性重新排序。
        entries = [(identifier, description['properties'][identifier]) for identifier in saved['property_order']]
        offset = saved['offset']
        end = offset + limit
        next_offset = end if end < len(entries) else None
        next_cursor = None if next_offset is None else discovery._remember_reference(
            {**saved, 'offset': next_offset}, state)
        return {**description, 'properties': dict(entries[offset:end]), 'offset': offset,
                'total_count': len(entries), 'next_offset': next_offset, 'next_cursor': next_cursor,
                'value_source': 'descriptor_snapshot'}

    def read_properties(self, session_id, object_id, property_ids, timeout=180):
        """显式读取一组属性；两种来源均返回 properties[id] 的状态与原始 value。"""
        objects.selection(property_ids)
        source = objects.resolve(session_id, object_id)
        if source['source'] == 'runtime':
            from .discovery import read_node_properties
            return objects.link_references(session_id, objects.runtime_result(
                read_node_properties(session_id, object_id, property_ids,
                    timeout=_timeout(timeout), operate=self._operate)))
        result = self._read(session_id, objects.catalog_target(session_id, object_id),
                            property_ids, 'read', timeout)
        return objects.link_references(session_id, objects.catalog_result(
            result, objects.catalog_object(session_id, source_object(source))))

    def modify_property(self, session_id, object_id, property_id, expected, value, timeout=180, audit=False):
        """按当前完整旧值修改一个属性；版本规则、条件和回读仍由原执行器核验。"""
        if type(audit) is not bool:
            raise ValueError('audit must be a boolean')
        objects.selection([property_id])
        source = objects.resolve(session_id, object_id)
        expected = objects.expected_value(session_id, expected)
        value = objects.assignment_value(session_id, value, runtime=source['source'] == 'runtime')
        if source['source'] == 'runtime':
            from .discovery_write import modify_node_property
            # 关联对象不伪造可跨加载导航的树路径；写后实际身份由执行器返回。
            binding = objects.object_binding(session_id, object_id)
            identity = binding['path'][-1] if 'path' in binding else binding
            obj = {'object_id': object_id, 'name': identity.get('name'),
                   'java_class': identity.get('java_class'), 'kind': 'object'}
            if 'path' in binding:
                obj['locator'] = {'source': 'runtime', 'path': [
                    {'name': item['name'], 'java_class': item['java_class']} for item in binding['path']]}
            result = modify_node_property(session_id, object_id, property_id, expected, value,
                timeout=_timeout(timeout), operate=self._operate, audit=audit)
        else:
            request = {'schema_version': 2, 'action': 'modify',
                       'target': objects.catalog_target(session_id, object_id), 'property': property_id,
                       'expected': expected, 'value': value}
            obj = objects.catalog_object(session_id, source_object(source))
            result = self._catalog(session_id, 'modify', request, timeout, audit=audit)
        return objects.link_references(session_id, objects.catalog_result(result, obj))

    def execute_operation(self, session_id, object_id, operation_id, expected, arguments,
                          timeout=180, audit=False):
        """执行已描述的结构操作，保留独立于普通赋值的参数与影响范围。"""
        if type(audit) is not bool:
            raise ValueError('audit must be a boolean')
        source = objects.resolve(session_id, object_id)
        target = objects.catalog_target(session_id, object_id)
        request = {'schema_version': 3, 'action': 'modify', 'target': target,
                   'operation': operation_id, 'expected': objects.expected_value(session_id, expected),
                   'arguments': arguments}
        obj = objects.catalog_object(session_id, source_object(source))
        result = self._catalog(session_id, 'modify', request, timeout, audit=audit)
        return objects.catalog_result(result, obj)

    def browse_tree(self, session_id, object_id=None, cursor=None, offset=0, limit=100,
                    scope='simulation', max_nodes=2000, timeout=180):
        """展开实际对象树的一层，返回与类型查找相同的 object_id 字段。"""
        if object_id is not None and objects.resolve(session_id, object_id)['source'] != 'runtime':
            raise ValueError('Tree browsing requires an object returned by browse_tree or search_settings')
        from .discovery import browse_tree
        return objects.runtime_result(browse_tree(session_id, node_id=object_id, cursor=cursor, offset=offset,
            limit=limit, scope=scope, max_nodes=max_nodes, timeout=_timeout(timeout), operate=self._operate))

    def relocate_object(self, session_id, locator, timeout=180):
        """重载后按返回的 locator 唯一查找；不继承旧世代引用或猜测同名对象。"""
        if not isinstance(locator, dict):
            raise ValueError('locator must be an object returned by an object lookup')
        if locator.get('source') == 'runtime' and set(locator) == {'source', 'path'}:
            from .discovery import relocate_node
            return objects.runtime_result(relocate_node(session_id, locator['path'],
                timeout=_timeout(timeout), operate=self._operate))
        if locator.get('source') != 'catalog' or set(locator) != {'source', 'target'}:
            raise ValueError('Invalid object locator')
        # 名称定位只接受不含 reference 的完整路径；本次读取生成新的实际引用。
        target = locator['target']
        current = target
        depth = 0
        while isinstance(current, dict):
            if not {'type', 'name'} <= current.keys() or set(current) - {'type', 'name', 'parent'}:
                raise ValueError('Catalog locator must contain only type, name and optional parent')
            depth += 1
            if depth > 16:
                raise ValueError('Catalog locator is too deep')
            current = current.get('parent')
        if current is not None or depth == 0:
            raise ValueError('Invalid catalog locator parent')
        result = self._read(session_id, target, None, 'describe', timeout)
        return {'schema_version': 2, 'schema_id': 'starbridge.objects',
                'object': objects.catalog_object(session_id, result['catalog']['target'])}

    def search_settings(self, session_id, query, expand=False, max_nodes=100, max_depth=4,
                        scope='simulation', timeout=180, limit=100, cursor=None):
        """搜索元数据并返回统一对象引用；命中值仍须显式重新读取。"""
        from .discovery import search_settings
        return objects.runtime_result(search_settings(session_id, query=query, expand=expand,
            max_nodes=max_nodes, max_depth=max_depth, scope=scope, timeout=_timeout(timeout),
            limit=limit, cursor=cursor, operate=self._operate))

    def search_memory(self, query, context=None, limit=20, project_dir=None, offset=0):
        """用已有任务信息检索有界经验摘要；按需另读完整记录，不为检索验证 STAR。"""
        from .memory import search_memory
        return search_memory(query, context, limit,
                             str(_path(project_dir, 'project_dir')) if project_dir is not None else None,
                             offset=offset)

    def get_memory(self, memory_id, project_dir=None):
        """读取方法、参数约定、资料位置和证据范围，结果是经验而非当前用户指令。"""
        from .memory import get_memory
        return get_memory(memory_id, str(_path(project_dir, 'project_dir')) if project_dir is not None else None)

    def record_memory(self, entry, project_dir=None):
        """记录实际任务已有经验，保留来源、适用条件和观察效果，不额外验证或执行方法。"""
        from .memory import record_memory
        return record_memory(entry, str(_path(project_dir, 'project_dir')) if project_dir is not None else None)

    def update_memory(self, memory_id, expected_revision, changes, project_dir=None):
        """依据实际新观察更新指定修订，避免覆盖另一客户端刚写入的纠正。"""
        from .memory import update_memory
        return update_memory(memory_id, expected_revision, changes,
                             str(_path(project_dir, 'project_dir')) if project_dir is not None else None)

    def list_recipes(self):
        """列出可直接使用的参数化方法、证据与完成边界，不连接 STAR 或自动选择方法。"""
        from .recipes import list_recipes
        return list_recipes()

    def execute_recipe(self, session_id, request_id, recipe_id, parameters=None,
                       expected_revision=None, project_dir=None, timeout=180):
        """执行显式选中的内置方法或 memory:ID，复用同一宏通道的逐步凭据。

        记忆必须先审阅且提供当前修订；检索本身从不执行方法。未声明影响时按 mutate
        保守处理，不把来源或一次成功当成当前适用性证明。已有输出不影响旧请求重放。
        """
        from .recipes import prepare_recipe, validate_recipe, validate_parameters, object_reference_paths
        binding_paths = []
        if not isinstance(recipe_id, str) or not recipe_id:
            raise ValueError('recipe_id must be non-empty text')
        parameters = {} if parameters is None else parameters
        if recipe_id.startswith('memory:'):
            if type(expected_revision) is not int or expected_revision < 1:
                raise ValueError('Memory recipe execution requires the reviewed expected_revision')
            memory = self.get_memory(recipe_id[len('memory:'):], project_dir)
            if memory['revision'] != expected_revision:
                raise ValueError('Memory recipe revision changed; review it again before execution')
            recipe = validate_recipe(memory.get('recipe'))
            prepared = {'steps': [{'id': 'recipe', 'code': recipe['code'],
                         'effect': recipe.get('effect', 'mutate'),
                         'scope': recipe.get('scope', 'Explicitly selected memory recipe')
                                  + f' [{recipe_id}, revision {expected_revision}]'}],
                        'imports': recipe['imports'], 'declarations': recipe.get('declarations', ''),
                        'parameters': validate_parameters(recipe['parameters'], parameters)}
            binding_paths = object_reference_paths(recipe['parameters'], prepared['parameters'])
            provenance = {'recipe_id': recipe_id, 'memory_revision': expected_revision,
                          'applicability': memory['applicability'], 'evidence_scope': memory['evidence_scope']}
        else:
            if expected_revision is not None or project_dir is not None:
                raise ValueError('expected_revision and project_dir apply only to memory recipes')
            prepared = prepare_recipe(recipe_id, parameters)
            # 内置方法也可能包含嵌套 object_reference，不能把其 JSON 包装原样交给 Java 方法体。
            binding_paths = prepared['object_parameter_paths']
            provenance = {key: value for key, value in prepared.items()
                          if key not in ('steps', 'imports', 'declarations', 'parameters', 'object_parameter_paths')}
        result = self._execute_bound_macro(session_id, request_id, timeout=timeout,
                    binding_paths=binding_paths,
                    **{key: prepared[key] for key in ('steps', 'imports', 'declarations', 'parameters')})
        return {**result, 'recipe': provenance}

    def execute_macro(self, session_id, request_id, steps, parameters=None, imports=None,
                      declarations='', intent='execute', timeout=180, object_parameters=None,
                      working_directory=None):
        """一次连接组合代码方法体和原样完整宏，返回持久逐步凭据；相同标识不重复执行。

        macro 步骤显式选择入口、辅助源码及 JAR，保持原宏自身上下文与路径语义；
        working_directory 作用于整个客户端，不自动复制工程或把来源文件当作数据目录快照。
        方法体可访问 sim、parameters、shared、result；imports 和 declarations 允许
        使用当前 STAR 宏 API 的完整能力。effect 和 scope 是调用者的影响及读取范围声明，
        不是代码沙箱或自动覆盖保证。explore 不授予试改当前用户算例的额外权限。
        """
        parameters = {} if parameters is None else parameters
        paths = objects.parameter_reference_paths(parameters, object_parameters)
        return self._execute_bound_macro(session_id, request_id, steps, parameters, imports,
                                         declarations, intent, timeout, paths, working_directory)

    def _execute_bound_macro(self, session_id, request_id, steps, parameters=None, imports=None,
                             declarations='', intent='execute', timeout=180, binding_paths=None,
                             working_directory=None):
        """统一准备参数绑定及请求凭据；本地 ID 校验不执行 STAR，实际解析先于所有用户步骤。"""
        from .macros import prepare
        bindings = objects.bind_parameters(session_id, parameters, binding_paths or [])
        request = prepare(request_id, steps, parameters, imports, declarations, intent,
                          object_bindings=bindings, working_directory=working_directory)
        return self._operate(session_id, 'macro', _timeout(timeout), macro_request=request)

    def get_execution(self, session_id, request_id):
        """读取宏执行凭据和当前会话状态，断开后仍可查询，不启动客户端或重复执行。"""
        from .macros import execution_result
        state = self._operate(session_id, 'status')
        result = execution_result(session_directory(session_id), request_id, state)
        result['session_state'] = public_session(state)
        return result

    def read_execution_artifact(self, session_id, request_id, artifact, offset=0, limit_bytes=8192,
                                tail=False, expected_version=None):
        """按需读取明确请求的固定材料，不轮询进程、不解析整份凭据或解除未知状态。"""
        from .execution_artifacts import read_artifact
        return read_artifact(session_directory(session_id), request_id, artifact, offset, limit_bytes,
                             tail, expected_version)

    def reconcile_execution(self, session_id, request_id, expected_review_token, assessment):
        """根据调用者对已有依据的判断接受当前状态，不重做宏、不改变原任务完成状态。

        token 来自 get_execution；新请求、迟到凭据或会话变化后必须重新审阅。
        仅处理当前未确认的通用宏；活动请求、版本/身份不明及历史不同确认均拒绝。
        """
        return self._operate(session_id, 'reconcile', request_id=request_id,
                             expected_review_token=expected_review_token, assessment=assessment)

    def inspect_session(self, session_id, timeout=180):
        """读取既有 Inspector 快照范围；与按需属性读取共用目录，不表示全配置导出。"""
        return self._operate(session_id, 'inspect', timeout)

    def open_session(self, input=None, star='starccm+', release=None, port=None, timeout=180, build=None,
                     project_dir=None, debug=False, create=False):
        """先检测所选程序版本，优先复用输入算例；create 显式新建空算例，不复制已有文件。

        用户给出的 release/Build 作为预期值核对。无法实际检测或预期不符时先拒绝；
        未登记版本可走独立生命周期预编译和身份握手，但不获得目录／发现适配。
        所选安装JDK预编译在加载前完成；实际server版本仍由初始只读请求核验。
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
        if type(create) is not bool:
            raise ValueError('create must be a boolean')
        if create and (source is not None or project is None):
            raise ValueError('Creating an empty simulation requires project_dir and no input')
        if not create and source is None and (port is None or project is None):
            raise ValueError('Without input, specify port and project_dir, or create=true with project_dir')
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
        from starbridge.bridge.runner import lifecycle_execution
        # 无目录不代表通用生命周期不可用；但必须在加载原算例前证明最小模板可由所选JDK编译。
        compilation = lifecycle_execution.prepare(detected['executable'], target, min(timeout, 90))
        args = SimpleNamespace(input=source, star=detected['executable'], port=port,
                               timeout=timeout, star_version=target, lifecycle_compilation=compilation,
                               project_dir=project, debug=debug, create=create)
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
        'schema_version': 2, 'methods': list(METHODS), 'transport': 'local',
        'statuses': {
            'ok': 'Call completed; inspect property errors and inspection_complete for partial reads.',
            'rejected': 'Invalid input or confirmed rejection before assignment; lifecycle setup may have created files.',
            'busy': 'A request is still running; query status without repeating the operation.',
            'uncertain': 'A request may have mutated the session. Check status and logs; do not retry.',
            'error': 'Call failed; inspect the error or execution steps and session state before further actions.',
            'partial': 'Some steps completed; inspect each step and execution.uncertain. Do not repeat the whole request.',
        },
        'session_lifetime': 'Explicit open/save/close; client exit does not close a session.',
        'identity': 'Object references belong to one session token; use full locators after reload.',
        'paths': 'Simulation, project and output paths must be absolute; session_id is returned by open_session.',
        'object_schema': 'starbridge.objects/2',
        'runtime_discovery': {
            'versions': [dict(TARGET)],
            'navigation': 'Browse one level, describe, then read explicit property_ids.',
            'search': 'Cached scope by default; expand uses explicit node, depth and time budgets.',
            'references': 'Opaque object_id and property_id; re-describe after identity or rule changes.',
        },
        'usage': usage_contract(),
    }
