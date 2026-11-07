"""管理会话标识与运行数据位置；项目目录只承载用户生成的报告和导出。"""

from pathlib import Path
import os
import re
import uuid


def runtime_root():
    """返回共享运行目录；可显式隔离开发环境，不因查询路径而创建目录。"""
    configured = os.environ.get('STARBRIDGE_HOME')
    if configured is not None:
        path = Path(configured)
        if not path.is_absolute():
            raise ValueError('STARBRIDGE_HOME must be an absolute path')
        return path.resolve()
    return Path.home() / '.starbridge'


def new_session_directory():
    """为新连接分配不可复用的标识，实际创建由会话执行器完成。"""
    return runtime_root() / 'sessions' / uuid.uuid4().hex


def session_directory(reference):
    """解析公开会话 ID；内部旧 Runner 的绝对目录在迁移期间仍可使用。"""
    if not isinstance(reference, (str, Path)) or not str(reference):
        raise ValueError('session_id must be a non-empty string')
    path = Path(reference)
    if path.is_absolute():
        return path.resolve()
    if re.fullmatch(r'[0-9a-f]{32}', str(reference)) is None:
        raise ValueError('Invalid session_id')
    return runtime_root() / 'sessions' / str(reference)


def session_version(state):
    """返回实际版本预期绑定，不把目录默认值或邻近版本当作当前安装。

    新会话使用 star_version；旧会话保留显式 catalog_target 的预期，实际请求仍须
    核对运行中服务器。显式损坏的新字段不回退；完全没有版本绑定时要求重新连接。
    """
    version = state['star_version'] if 'star_version' in state else state.get('catalog_target')
    if (not isinstance(version, dict) or set(version) != {'release', 'build'}
            or any(not isinstance(value, str) or not value.strip() for value in version.values())):
        raise ValueError('Session has no valid explicit STAR version binding; reconnect to inspect the selected installation')
    return dict(version)


def public_session(state):
    """返回连接所需的状态，实际版本与目录适配分别报告，不要求调用者管理内部进程。"""
    keys = ('session_id', 'state', 'ownership', 'star_version', 'version_source',
            'catalog_target', 'lifecycle_compilation', 'current_file',
            'project_dir', 'modified', 'session_token', 'server_alive', 'active_request',
            'last_request', 'last_request_status', 'recovery_required', 'uncertain_request',
            'last_reconciliation', 'pending_reconciliations')
    return {key: state[key] for key in keys if key in state}


def artifact_path(state, kind, filename, output=None):
    """在实际生成报告或导出时确定目的地，不在连接阶段创建项目隐藏目录。

    显式位置优先，其次沿用项目已有 reports/exports/analysis 目录，否则使用
    项目 .starbridge 中的对应目录。调用方写入前才创建返回路径的父目录。
    """
    if kind not in ('reports', 'exports') or Path(filename).name != filename:
        raise ValueError('Artifact requires a supported kind and a plain filename')
    if output is not None:
        path = Path(output)
        if not path.is_absolute():
            raise ValueError('Artifact output must be absolute')
        return path.resolve()
    project = Path(state['project_dir'])
    for name in (kind, 'analysis'):
        if (project / name).is_dir():
            return project / name / filename
    return project / '.starbridge' / kind / filename
