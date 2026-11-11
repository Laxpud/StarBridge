"""从已登记进程和会话记录解释驻留资源；不扫描全机、不启动 STAR 或执行清理。"""

from datetime import datetime, timezone
from pathlib import Path


def resource_summary(state):
    """为任务收尾提供本机观测与建议，身份不符或无法读取时保留未知，不猜零占用。

    RSS 只汇总登记且身份匹配的进程，可能重复计入共享页，也不覆盖未登记子进程。
    modified 与活动状态来自调用方提供的会话观察，不为本摘要重新访问 STAR；因此
    关闭建议不是安全授权，真正关闭仍由现有生命周期入口核对。
    """
    from starbridge.bridge.runner.session_bridge import process_identity

    request_id = state.get('active_request') or state.get('uncertain_request') or state.get('last_request')
    activity = state.get('execution_activity', {}).get(request_id, {'state': 'not_recorded'})
    client = state.get('client_process') or activity.get('client_process')
    records = []
    seen = set()
    references = [('server', state.get('server_process')), ('launcher', state.get('process')),
                  ('request_client', client)]
    references.extend(('owned_process', identity) for identity in state.get('owned_processes', []))
    for role, identity in references:
        if not isinstance(identity, dict) or type(identity.get('pid')) is not int:
            continue
        pid = identity['pid']
        if pid <= 0 or pid in seen:
            continue
        seen.add(pid)
        item = {'pid': pid, 'role': role, 'identity_status': 'unknown', 'rss_bytes': None}
        try:
            current = process_identity(pid)
            if current != identity:
                item['identity_status'] = 'not_running' if current is None else 'identity_changed'
            else:
                item['identity_status'] = 'matched'
                for line in Path(f'/proc/{pid}/status').read_text().splitlines():
                    if line.startswith('VmRSS:'):
                        item['rss_bytes'] = int(line.split()[1]) * 1024
                        break
                # 读取过程中 PID 可能退出或复用；无法重新确认时不能归属刚读到的内存。
                if process_identity(pid) != identity:
                    item.update(identity_status='changed_during_read', rss_bytes=None)
        except (OSError, ValueError, IndexError) as error:
            item.update(identity_status='unavailable', rss_bytes=None,
                        error={'type': type(error).__name__, 'message': str(error)})
        records.append(item)

    ownership = state.get('ownership')
    blockers = []
    if state.get('active_request') or state.get('state') == 'running':
        blockers.append('active_request_or_session_lock')
    if state.get('uncertain_request') or state.get('pending_reconciliations') or state.get('recovery_required'):
        blockers.append('unresolved_execution_or_recovery')
    if state.get('modified') is True:
        blockers.append('last_observed_modified')
    elif state.get('modified') is not False:
        blockers.append('modified_not_observed')
    if state.get('state') in ('stopped', 'disconnected', 'failed'):
        disposition = 'connection_closed; inspect registered_processes for remaining resources'
    elif ownership == 'external':
        disposition = 'external_server_retained; close_session only disconnects and does not stop active clients'
    elif ownership == 'owned' and blockers:
        disposition = 'owned_server_retained; review blockers and request user decision before saving or discarding'
    elif ownership == 'owned':
        disposition = 'owned_server_retained; explicit close_session still rechecks unsaved state'
    else:
        disposition = 'ownership_unknown; do not terminate processes'
    known = [item['rss_bytes'] for item in records if item['rss_bytes'] is not None]
    return {
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'registered_identity_matched_processes_only; RSS sum may double-count shared pages',
        'registered_processes': records,
        'observed_rss_bytes': sum(known) if known else None,
        'rss_coverage': 'complete_for_registered_records' if records and all(
            item['rss_bytes'] is not None or item['identity_status'] == 'not_running' for item in records) else 'partial_or_unknown',
        'ownership': ownership, 'state': state.get('state'),
        'modified': state.get('modified'),
        'modified_basis': 'last_recorded_STAR_observation; not refreshed by this summary',
        'active_request': state.get('active_request'), 'uncertain_request': state.get('uncertain_request'),
        'client_activity': {'request_id': request_id, 'recorded_state': activity.get('state', 'unknown'),
                            'basis': 'recorded_activity; process observation above does not prove a whole client group has stopped'},
        'disposition': disposition, 'close_considerations': blockers,
        'automatic_close': False, 'automatic_save': False,
        'notice': 'Task completion is not server shutdown. This observation does not authorize discard or prove the simulation file is unchanged.',
    }
