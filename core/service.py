"""为 CLI 与 MCP 提供相同的目录能力、对象读写和显式会话生命周期。

服务只编排现有 Bridge，不接受 Java 代码，也不隐式保存、关闭或重试修改。
每次调用返回状态封套；局部属性错误仍放在原目录结果中，由调用者逐项处理。
"""

import inspect
import math
from pathlib import Path
import sys
from types import SimpleNamespace

from bridge.runner import session_bridge
from bridge.runner.modifier import ModificationRejected
from .catalog import read_json
from .catalog_bundle import BUNDLES, bundle_root, bundle_target, session_target
from .coverage import coverage
from .execution import prepare_find, prepare_modification_value, prepare_read_value
from .snapshot import prepare_snapshot


METHODS = (
    'get_capabilities', 'find_objects', 'describe_object', 'read_properties', 'modify',
    'inspect_session', 'open_session', 'session_status', 'save_session', 'close_session',
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
            directory = arguments.get('session_dir') if isinstance(arguments, dict) else None
            if isinstance(directory, str) and Path(directory).is_absolute():
                try:
                    state = read_json(Path(directory) / 'session.json')
                except (OSError, ValueError):
                    pass
            if isinstance(state, dict) and (state.get('state') == 'uncertain' or state.get('active_request')):
                status = 'uncertain'
            result = {'status': status, 'error': {'type': type(error).__name__, 'message': str(error)}}
            if isinstance(state, dict):
                result['session_state'] = {key: state.get(key) for key in
                                           ('state', 'active_request', 'last_request', 'last_request_status')}
            return result

    def get_capabilities(self, release):
        """读取精确版本的离线能力；不把具备实现解释为当前算例可写。"""
        root = bundle_root(bundle_target(release))
        report = coverage(root / 'generated' / 'catalog.json', execution_path=root / 'execution.json')
        rules = read_json(root / 'execution.json')
        return {
            'target': report['target'], 'catalog_id': report['catalog_id'],
            'supported_versions': [bundle_target(item) for item in BUNDLES],
            'runtime_state': 'not_checked', 'discovery': report['discovery'],
            'types': {name: {key: entry.get(key) for key in ('java_class', 'parent_type')}
                      for name, entry in rules['types'].items()},
            'execution': report['execution'], 'limitations': report['limitations'],
            'unavailable': ['mesh_generation', 'solver_execution', 'persistent_memory', 'gui_attachment'],
        }

    def _operate(self, session_dir, action, timeout=180, **values):
        """复用原会话执行器，保留互斥、进程身份、输入摘要与不确定状态处理。"""
        if not sys.platform.startswith('linux'):
            raise ValueError('Managed sessions currently support Linux only')
        directory = _path(session_dir, 'session_dir')
        args = SimpleNamespace(action=action, timeout=_timeout(timeout), **values)
        return session_bridge.operate(args, directory)

    def _catalog(self, session_dir, action, request, timeout):
        """用会话绑定版本准备请求；执行器持锁后再次核对，之后才设置活动标记。"""
        directory = _path(session_dir, 'session_dir')
        _timeout(timeout)
        root = bundle_root(session_target(read_json(directory / 'session.json')))
        paths = (root / 'generated' / 'catalog.json', root / 'execution.json')
        if action == 'modify':
            plan, prepared = prepare_modification_value(*paths, request)
        elif action == 'find':
            plan, prepared = prepare_find(*paths, request)
        else:
            plan, prepared = prepare_read_value(*paths, request, action)
        return self._operate(session_dir, action, timeout, catalog_plan=plan, catalog_request=prepared)

    def find_objects(self, session_dir, type_id, name=None, parent=None, offset=0, limit=100, timeout=180):
        """枚举目录类型，可按精确名称过滤；子类型要求 parent，单页最多 500 项。"""
        request = {'schema_version': 1, 'action': 'find', 'type': type_id, 'offset': offset, 'limit': limit}
        if name is not None:
            request['name'] = name
        if parent is not None:
            request['parent'] = parent
        return self._catalog(session_dir, 'find', request, timeout)

    def _read(self, session_dir, target, properties, action, timeout):
        """保留调用者选择的属性；省略表示该类型全部已映射属性。"""
        request = {'schema_version': 1, 'action': action, 'target': target}
        if properties is not None:
            request['properties'] = properties
        return self._catalog(session_dir, action, request, timeout)

    def describe_object(self, session_dir, target, properties=None, timeout=180):
        """描述属性、结构操作及当前已声明条件；不会预判尚未给出的新值。"""
        return self._read(session_dir, target, properties, 'describe', timeout)

    def read_properties(self, session_dir, target, properties=None, timeout=180):
        """返回逐属性值和错误，不把部分读取成功报告为完整设置导出。"""
        return self._read(session_dir, target, properties, 'read', timeout)

    def modify(self, session_dir, request, timeout=180):
        """提交一个 schema 2 属性修改或 schema 3 结构操作，保留 expected 核对与回读。"""
        return self._catalog(session_dir, 'modify', request, timeout)

    def inspect_session(self, session_dir, timeout=180):
        """读取既有 Inspector 快照范围；与按需属性读取共用目录，不表示全配置导出。"""
        return self._operate(session_dir, 'inspect', timeout)

    def open_session(self, input, session_dir, star='starccm+', release='2602', port=49001, timeout=180):
        """复制输入并启动独立后台会话，完成首个快照；不会连接现有 GUI。"""
        if not sys.platform.startswith('linux'):
            raise ValueError('Managed sessions currently support Linux only')
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('port must be between 1024 and 65535')
        if not isinstance(star, str) or not star:
            raise ValueError('star must be an executable name or path')
        args = SimpleNamespace(input=_path(input, 'input'), star=star, port=port,
                               timeout=_timeout(timeout), snapshot_plan=prepare_snapshot(bundle_target(release)))
        return session_bridge.start(args, _path(session_dir, 'session_dir'))

    def session_status(self, session_dir):
        """读取会话记录并检查进程身份，不启动 Java 客户端，也不重新核验 server Build。"""
        return self._operate(session_dir, 'status')

    def save_session(self, session_dir, output, timeout=180):
        """仅另存到尚不存在的 .sim 文件；不会覆盖输入，保存不自动关闭服务。"""
        return self._operate(session_dir, 'save', timeout, output=_path(output, 'output'))

    def close_session(self, session_dir, discard=False, timeout=180):
        """默认先核对修改标志；仅显式 discard 才放弃剩余内存状态并清理本次进程。"""
        if type(discard) is not bool:
            raise ValueError('discard must be a boolean')
        return self._operate(session_dir, 'stop', timeout, discard=discard)


def contract():
    """给客户端提供稳定的状态与恢复约定，供 CLI 和 MCP Resource 同源读取。"""
    return {
        'schema_version': 1, 'methods': list(METHODS), 'transport': 'local',
        'statuses': {
            'ok': 'Call completed; inspect property errors and inspection_complete for partial reads.',
            'rejected': 'Invalid input or confirmed rejection before mutation.',
            'uncertain': 'A request may have mutated the session. Check status and logs; do not retry.',
            'error': 'Call failed; inspect the error and session state before further actions.',
        },
        'session_lifetime': 'Explicit open/save/close; client exit does not close a session.',
        'identity': 'Object references belong to one session token; use full locators after reload.',
        'paths': 'All simulation, session and output paths must be absolute.',
        'request_schemas': {'read': 1, 'property_modification': 2, 'structural_operation': 3},
    }
