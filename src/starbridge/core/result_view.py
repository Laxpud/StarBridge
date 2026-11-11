"""精简宏结果的传输视图，不修改磁盘凭据、执行状态或请求指纹。"""

from copy import deepcopy
import json


RESULT_BUDGET_BYTES = 16384


def validate_result_view(result_view):
    """在派发前拒绝未知视图，避免宏已经执行后才发现展示参数无效。"""
    if result_view not in ('compact', 'full'):
        raise ValueError('result_view must be compact or full')


def project_execution(result, result_view, session_id, request_id):
    """保留全部步骤状态；超出合计预算的业务结果整项省略，并给出原凭据读取入口。

    预算只覆盖 steps[].result，不是整个响应大小上限。任意业务 JSON 内可能含局部
    错误，因此省略不表示成功、空值或完整读取；不能用执行 completed 代替审阅正文。
    full 返回同一结构化凭据的完整业务结果，不重新运行宏，也不改写原始凭据。
    """
    validate_result_view(result_view)
    projected = deepcopy(result)
    remaining = RESULT_BUDGET_BYTES
    omitted = []
    for index, step in enumerate(projected.get('execution', {}).get('steps', [])):
        if 'result' not in step or result_view == 'full':
            continue
        payload = step['result']
        size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        if size <= remaining:
            remaining -= size
            continue
        # 不用 null 或假摘要替换真实值；结果缺席与明确的省略清单共同表达传输范围。
        del step['result']
        omitted.append({'step_id': step.get('id'), 'path': f'/execution/steps/{index}/result',
                        'json_bytes': size, 'reason': 'business_result_budget',
                        'business_status': 'not_assessed; omitted data may contain partial reads or errors'})
    projected['result_projection'] = {
        'view': result_view,
        'business_results_complete': not omitted and result.get('receipt_read', {}).get('read_status') == 'valid',
        'business_result_budget_bytes': RESULT_BUDGET_BYTES if result_view == 'compact' else None,
        'omitted': omitted,
    }
    if omitted:
        projected['result_projection'].update(
            full_result={'method': 'get_execution', 'arguments': {
                'session_id': str(session_id), 'request_id': request_id, 'result_view': 'full'}},
            notice='Inspect omitted results before claiming task completion. Use the existing artifact_reader for receipt windows; do not rerun the macro.')
    return projected
