"""保存调用者对未知宏结果的显式判断，不重写执行凭据，也不重新执行宏。

执行器不能判定任意 Java 任务的业务含义。它核对会话、请求和所审阅凭据是否仍为
同一份；接受哪些当前结果、还需做什么由调用者根据已有观察说明，不为确认另跑验证。
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .session_store import session_version


_FIELDS = {'observations', 'accepted_scope', 'remaining_scope', 'evidence'}


def _encoded(value):
    """使用稳定 JSON 比较确认内容；不以字典顺序或排版决定是否是同一次确认。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def review_context(request, state, digest, read_status='valid'):
    """生成所审阅状态的标识；不能把这个本地快照称为 GUI 并发编辑的事务锁。

    token 同时绑定原请求、原凭据、会话世代、服务进程和最后一个 Bridge 请求。
    原请求后的新读取会改变 token，调用者可廉价重取 get_execution 后再确认；
    不要求专门执行一次读取或校验。后续实际宏仍会重新核对加载对象的身份。
    """
    from .macros import request_identifier
    identifier = request_identifier(request['request_id'])
    if state.get('uncertain_request') != identifier or state.get('active_request'):
        return None
    if not state.get('session_token') or not state.get('simulation_key'):
        return None
    activity = state.get('execution_activity', {}).get(identifier, {'state': 'unknown'})
    eligible = (activity.get('state') in ('stopped', 'not_started') and read_status != 'unreadable'
                and state.get('state') in ('ready', 'uncertain') and state.get('server_alive') is not False)
    basis = {'request_fingerprint': request['fingerprint'], 'receipt_sha256': digest,
             'receipt_read_status': read_status, 'activity': activity,
             'review_generation': state.get('review_generations', {}).get(identifier, 0),
             'session_token': state['session_token'], 'simulation_key': state['simulation_key'],
             'star_version': session_version(state), 'process': state.get('process'),
             'server_process': state.get('server_process'), 'last_request': state.get('last_request'),
             'last_request_status': state.get('last_request_status')}
    return {'token': hashlib.sha256(_encoded(basis)).hexdigest(), 'basis': basis,
            'can_accept': eligible,
            'unavailable_reason': None if eligible else 'Session is not open/alive, client activity is not confirmed stopped, or receipt bytes cannot be read',
            'decision': 'accept_current_state',
            'meaning': 'Explicitly accept the described current state and permit subsequent work; not task completion.',
            'checks': 'Local session/request/receipt identity only; caller assesses observations and evidence.'}


def prepare_assessment(value):
    """要求说明当前观察、接受范围、剩余工作和已有依据，不要求列出全部合法修改。

    evidence.source 是调用者给出的依据位置或描述，不自动打开文件、执行代码或把
    文档/观察当作新指令。证据可来自原部分凭据、后续读取、外部产物或用户确认。
    """
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError('assessment requires exactly observations, accepted_scope, remaining_scope and evidence')
    for field in ('observations', 'accepted_scope', 'remaining_scope'):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError(f'assessment.{field} must be non-empty text')
    evidence = value['evidence']
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 50:
        raise ValueError('assessment.evidence must contain 1-50 existing evidence descriptions')
    for item in evidence:
        if (not isinstance(item, dict) or set(item) != {'source', 'description'}
                or any(not isinstance(text, str) or not text.strip() for text in item.values())):
            raise ValueError('Each evidence item requires non-empty source and description strings')
    encoded = _encoded(value)
    if len(encoded) > 64_000:
        raise ValueError('Assessment exceeds 64 KB; reference existing evidence instead of copying large outputs')
    return json.loads(encoded)


def evidence_current(record, state, identifier, digest, read_status):
    """查询与操作使用同一有效性条件；内容曾变化后又恢复也必须考虑审阅世代。"""
    basis = record['basis']
    return (read_status != 'unreadable' and basis['receipt_sha256'] == digest
            and basis.get('receipt_read_status', read_status) == read_status
            and basis.get('review_generation', 0) == state.get('review_generations', {}).get(identifier, 0))


def clear_restriction(state, identifier):
    """只解除已说明的请求；迟到证据引出的其他未确认请求继续保留，不能被顺带清空。"""
    pending = [item for item in state.get('pending_reconciliations', []) if item != identifier]
    state['pending_reconciliations'] = pending
    if state.get('uncertain_request') == identifier:
        state.pop('uncertain_request')
    if pending and not state.get('uncertain_request'):
        state['uncertain_request'] = pending[0]


def refresh_reviews(directory, state):
    """在后续请求前识别接受之后的凭据变化，必要时重新限制写入而不改写原判断。

    正常客户端已停止是接受的前提，但本地会话锁不约束 Java／其他文件写者。先以
    文件身份和修改信息避免反复读大文件；变化时再核对摘要。此处不是跨写者事务。
    新的明确无未知终态可以独立恢复；其他变化进入待重新审阅队列，不覆盖另一未知请求。
    """
    from .execution_receipt import load_receipt, final_document
    changed = False
    for identifier, record in state.get('execution_reviews', {}).items():
        path = Path(directory) / 'requests' / identifier / 'result.json'
        try:
            info = path.stat()
            stamp = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        except FileNotFoundError:
            stamp = ['missing']
        except OSError as error:
            stamp = ['unreadable', type(error).__name__, str(error)]
        tracked = state.setdefault('review_receipts', {}).get(identifier)
        if tracked is not None and tracked.get('stamp') == stamp:
            continue
        observed = load_receipt(path, record['request_id'])
        if tracked is not None and (tracked.get('sha256'), tracked.get('read_status')) != (
                observed['sha256'], observed['read_status']):
            generations = state.setdefault('review_generations', {})
            generations[identifier] = generations.get(identifier, 0) + 1
        state['review_receipts'][identifier] = {'stamp': stamp, 'sha256': observed['sha256'],
                                                'read_status': observed['read_status']}
        changed = True
        if evidence_current(record, state, identifier, observed['sha256'], observed['read_status']):
            continue
        final = final_document(observed)
        if final is not None and final['execution']['uncertain'] is False:
            clear_restriction(state, identifier)
            continue
        pending = state.setdefault('pending_reconciliations', [])
        if identifier not in pending:
            pending.append(identifier)
        if not state.get('uncertain_request'):
            state['uncertain_request'] = identifier
    if changed and state.get('state') in ('ready', 'uncertain'):
        state['state'] = 'uncertain' if state.get('uncertain_request') else 'ready'
        state['recovery_required'] = bool(state.get('uncertain_request'))
    return changed


def reconcile(directory, state, request_id, expected_review_token, assessment):
    """在调用者持有会话锁且已确认无活动请求时接受当前状态；修改仅发生在本地记录。

    本函数不保存状态文件：Runner 将确认记录和解除限制一起原子写入 session.json。
    原 result.json 始终不变；同一确认内容重发只返回已有记录，不能解除后来的未知请求。
    """
    from .macros import request_identifier
    identifier = request_identifier(request_id)
    if not isinstance(expected_review_token, str) or re.fullmatch('[0-9a-f]{64}', expected_review_token) is None:
        raise ValueError('expected_review_token must be the token returned by get_execution')
    assessment = prepare_assessment(assessment)
    recorded = state.get('execution_reviews', {}).get(identifier)
    history = state.get('execution_review_history', {}).get(identifier, [])
    for previous in ([recorded] if recorded is not None else []) + history:
        if previous['review_token'] == expected_review_token:
            if previous['assessment'] != assessment:
                raise ValueError('This review token already has a different assessment; read get_execution')
            return previous, True
    if state.get('active_request'):
        raise ValueError('An active execution cannot be reconciled')
    if state.get('uncertain_request') != identifier:
        raise ValueError('request_id is not the current unconfirmed macro execution')
    run = Path(directory) / 'requests' / identifier
    request = json.loads((run / 'macro-request.json').read_text())
    if request.get('request_id') != request_id:
        raise ValueError('Stored macro request identity does not match request_id')
    from .execution_receipt import load_receipt
    receipt = load_receipt(run / 'result.json', request_id)
    current = review_context(request, state, receipt['sha256'], receipt['read_status'])
    if current is None or current['token'] != expected_review_token:
        raise ValueError('Execution evidence or session changed; read get_execution and review the current state again')
    if not current['can_accept']:
        raise ValueError(current['unavailable_reason'])
    record = {'schema_version': 1, 'request_id': request_id, 'decision': 'accept_current_state',
              'review_token': expected_review_token, 'basis': current['basis'], 'assessment': assessment,
              'recorded_at': datetime.now(timezone.utc).isoformat(),
              'evidence_validation': 'caller_assessed; sources_not_automatically_read',
              'task_completion': 'not_certified', 'original_receipt_modified': False,
              'automatic_retry': False}
    # 确认依据与解除限制在同一会话记录中提交，避免两个文件之间出现半完成确认。
    if recorded is not None:
        state.setdefault('execution_review_history', {}).setdefault(identifier, []).append(recorded)
    state.setdefault('execution_reviews', {})[identifier] = record
    # 保存本次实际读到的摘要；后续操作还会检查原凭据是否迟到或被替换。
    state.setdefault('review_receipts', {})[identifier] = {
        'sha256': receipt['sha256'], 'stamp': None, 'read_status': receipt['read_status']}
    clear_restriction(state, identifier)
    state['state'] = 'uncertain' if state.get('uncertain_request') else 'ready'
    state['recovery_required'] = bool(state.get('uncertain_request'))
    state['last_reconciliation'] = {'request_id': request_id, 'decision': record['decision'],
                                    'recorded_at': record['recorded_at']}
    return record, False
