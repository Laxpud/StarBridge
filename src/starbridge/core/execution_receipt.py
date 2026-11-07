"""读取宏凭据并区分完整数据、缺失、损坏和无法访问，不把读取失败当作执行成功。

宏入口原子替换 result.json；读取器从一次打开的文件取得摘要与正文。大凭据只流式
计算摘要，不无限制解析到内存；调用者可按返回路径查看完整材料，不能据此宣称结果为空。
"""

import hashlib
import json
from pathlib import Path


MAX_PARSE_BYTES = 32 * 1024 * 1024
FINAL_STATUSES = {'completed', 'partial', 'failed', 'uncertain', 'rejected'}


def _validate(data, expected_request_id):
    """只检查执行状态投影所需的固定字段；步骤输出仍是宏提供的任意 JSON 数据。"""
    if not isinstance(data, dict) or data.get('status') not in {'ok', 'rejected', 'partial', 'uncertain', 'error', 'running'}:
        raise ValueError('Invalid receipt envelope')
    execution, after = data.get('execution'), data.get('after')
    if not isinstance(execution, dict) or execution.get('status') not in FINAL_STATUSES | {'running'}:
        raise ValueError('Invalid execution status')
    if (not isinstance(execution.get('request_id'), str)
            or expected_request_id is not None and execution['request_id'] != expected_request_id):
        raise ValueError('Receipt request identity does not match')
    if type(execution.get('uncertain')) is not bool:
        raise ValueError('Execution uncertainty is not explicitly recorded')
    steps = execution.get('steps')
    if not isinstance(steps, list) or any(not isinstance(step, dict) or step.get('status') not in
            {'not_started', 'running', 'completed', 'failed', 'uncertain'} for step in steps):
        raise ValueError('Invalid execution steps')
    initialization = execution.get('initialization')
    if initialization is not None and (not isinstance(initialization, dict) or initialization.get('status') not in
            {'not_started', 'running', 'completed', 'failed', 'uncertain'}):
        raise ValueError('Invalid initialization status')
    status = execution['status']
    observed_unknown = any(step['status'] == 'uncertain' for step in steps) or (
        initialization is not None and initialization['status'] == 'uncertain')
    if (status == 'uncertain' or observed_unknown) and not execution['uncertain']:
        raise ValueError('Receipt contradicts its recorded uncertainty')
    if status == 'completed' and (not steps or execution['uncertain'] or any(step['status'] != 'completed' for step in steps)
            or initialization is not None and initialization['status'] != 'completed'):
        raise ValueError('Completed receipt contains unfinished work')
    if status == 'rejected' and (execution['uncertain'] or any(step['status'] != 'not_started' for step in steps)
            or initialization is not None and initialization['status'] != 'not_started'):
        raise ValueError('Rejected receipt contains started user work')
    if status in FINAL_STATUSES and (any(step['status'] == 'running' for step in steps)
            or initialization is not None and initialization['status'] == 'running'):
        raise ValueError('Final receipt still contains running user work')
    if status in {'failed', 'partial', 'uncertain'}:
        states = [step['status'] for step in steps]
        init_status = initialization['status'] if initialization is not None else None
        if init_status in {'failed', 'uncertain'}:
            if status != init_status or any(item != 'not_started' for item in states):
                raise ValueError('Initialization failure conflicts with step outcomes')
        else:
            failure = next((index for index, item in enumerate(states) if item in {'failed', 'uncertain'}), None)
            if (failure is None or any(item != 'completed' for item in states[:failure])
                    or any(item != 'not_started' for item in states[failure + 1:])
                    or (status == 'partial') != (failure > 0)
                    or status != 'partial' and status != states[failure]
                    or init_status not in (None, 'completed')):
                raise ValueError('Failure receipt has inconsistent completed, failed or unstarted steps')
        if status == 'failed' and execution['uncertain']:
            raise ValueError('Read failure receipt contains unconfirmed mutation')
    expected_envelope = {'completed': 'ok', 'rejected': 'rejected', 'partial': 'partial',
                         'failed': 'error', 'uncertain': 'uncertain', 'running': 'running'}
    if data['status'] != expected_envelope[status]:
        raise ValueError('Receipt envelope and execution status disagree')
    if (not isinstance(after, dict) or 'session_path' not in after
            or after['session_path'] is not None and not isinstance(after['session_path'], str)
            or type(after.get('modified')) is not bool):
        raise ValueError('Receipt has no valid final session metadata')


def _reject_constant(value):
    """Java 凭据只允许有限 JSON 数值；不能把损坏文件中的 NaN/Infinity 当成有效结果。"""
    raise ValueError(f'Non-finite JSON number in receipt: {value}')


def load_receipt(path, expected_request_id=None):
    """返回同一份文件的摘要和结构化诊断；损坏文件不改写、不删除，保留显式恢复依据。"""
    path = Path(path)
    result = {'path': str(path), 'read_status': 'missing', 'sha256': None}
    digest, size, chunks = hashlib.sha256(), 0, []
    try:
        with path.open('rb') as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                if size <= MAX_PARSE_BYTES:
                    chunks.append(chunk)
    except FileNotFoundError:
        return result
    except OSError as error:
        return {**result, 'read_status': 'unreadable', 'error': {'type': type(error).__name__, 'message': str(error)}}
    result.update(sha256=digest.hexdigest(), bytes=size)
    if size > MAX_PARSE_BYTES:
        return {**result, 'read_status': 'too_large', 'parse_limit_bytes': MAX_PARSE_BYTES,
                'error': {'type': 'ReceiptSizeLimit', 'message': 'Receipt exceeds the parsing budget; full artifact remains available'}}
    try:
        data = json.loads(b''.join(chunks), parse_constant=_reject_constant)
        _validate(data, expected_request_id)
    except (ValueError, TypeError, RecursionError) as error:
        return {**result, 'read_status': 'malformed', 'error': {'type': type(error).__name__, 'message': str(error)}}
    return {**result, 'read_status': 'valid', 'document': data}


def final_document(receipt):
    """只有结构有效的明确终态可用于自动恢复；中间或损坏凭据始终返回 None。"""
    data = receipt.get('document')
    if (receipt.get('read_status') == 'valid' and data['execution']['status'] in FINAL_STATUSES
            and data['status'] != 'running'):
        return data
    return None
