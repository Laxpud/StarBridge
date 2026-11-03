"""管理会话标识与运行数据位置；项目目录只承载用户生成的报告和导出。"""

from pathlib import Path
import re
import uuid


def runtime_root():
    """返回当前用户的运行目录；不因查询路径而创建任何目录。"""
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


def public_session(state):
    """返回连接所需的状态，避免让调用者管理内部进程、日志和客户端目录。"""
    keys = ('session_id', 'state', 'ownership', 'catalog_target', 'current_file',
            'project_dir', 'modified', 'session_token', 'server_alive', 'active_request',
            'last_request', 'last_request_status', 'recovery_required')
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
