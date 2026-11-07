"""准备通用宏请求与读取执行凭据，不把结构化属性目录作为可操作能力的上限。

代码是调用者明确选择执行的程序，不是从算例名称、资料或记忆中自动执行的内容。
每个步骤记录独立范围、声明的影响和结果；声明只用于恢复判断，不构成 Java 沙箱。
"""

import hashlib
import json
import re
from pathlib import Path


IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}')


def request_identifier(value):
    """校验可用于持久凭据文件名的调用标识；同一标识不能用于另一份操作。"""
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ValueError('request_id must contain 1-80 ASCII letters, digits, underscores or hyphens')
    return 'macro-' + value


def prepare(request_id, steps, parameters=None, imports=None, declarations='', intent='execute',
            *, object_bindings=None):
    """校验并冻结有序 Java 步骤；参数作为数据注入，不对代码作字符串模板替换。

    code 是 execute 内的方法体，能访问 sim、parameters、shared 与 result。
    shared 只在本次步骤之间传递 Java 对象；result 只能存储明确的 JSON 值。
    declarations 支持共享方法、内部类和字段，imports 支持当前安装的任意宏 API。
    用户声明的初始化在身份与对象绑定通过后才开始，并单独记录 initialization；
    任一步声明 mutate 时整个初始化阶段按 mutate 处理，全 read 则初始化也声明只读。
    effect 覆盖全部用户源码，不是执行器自动检测出的权限或副作用保证。
    """
    request_identifier(request_id)
    if intent not in ('execute', 'explore'):
        raise ValueError('intent must be execute or explore')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 200:
        raise ValueError('steps must contain 1-200 explicit operations')
    seen = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) != {'id', 'code', 'effect', 'scope'}:
            raise ValueError('Each step requires exactly id, code, effect and scope')
        request_identifier(step['id'])
        if step['id'] in seen:
            raise ValueError('Step ids must be unique')
        seen.add(step['id'])
        if step['effect'] not in ('read', 'mutate'):
            raise ValueError('Step effect must be read or mutate; export, save and execution are mutations')
        for name in ('code', 'scope'):
            if not isinstance(step[name], str) or not step[name].strip():
                raise ValueError(f'Step {name} must be non-empty text')
    imports = [] if imports is None else imports
    if not isinstance(imports, list) or any(not isinstance(item, str) or re.fullmatch(
            r'(?:static )?[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:\.\*)?', item) is None
            for item in imports):
        raise ValueError('imports must contain Java qualified names without import or semicolon')
    if not isinstance(declarations, str):
        raise ValueError('declarations must be Java source text')
    parameters = {} if parameters is None else parameters
    if not isinstance(parameters, dict):
        raise ValueError('parameters must be a JSON object')
    request = dict(request_id=request_id, steps=steps, parameters=parameters,
                   imports=imports, declarations=declarations, intent=intent)
    # 空绑定不进入旧请求指纹，保持无对象参数的既有请求可重放。
    if object_bindings:
        if not isinstance(object_bindings, list):
            raise ValueError('Object bindings must be an array')
        for entry in object_bindings:
            if (not isinstance(entry, dict) or set(entry) != {'path', 'binding'}
                    or not isinstance(entry['path'], list) or not 1 <= len(entry['path']) <= 64
                    or any(type(part) not in (str, int) for part in entry['path'])
                    or not isinstance(entry['binding'], dict)):
                raise ValueError('Invalid internal object binding')
        request['object_bindings'] = object_bindings
    # JSON 往返同时拒绝非有限数和非数据类型；限制源请求而不限制 STAR 对象种类。
    try:
        encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError('Macro request must contain finite JSON data') from error
    if len(encoded.encode('utf-8')) > 2_000_000:
        raise ValueError('Macro request exceeds 2 MB; split independent work or use external data files')
    normalized = json.loads(encoded)
    # 在占用请求标识和启动客户端之前检查 Java 数据构造边界（例如 signed 64-bit 整数）。
    from starbridge.bridge.runner.modifier import java_literal
    java_literal(normalized['parameters'])
    normalized['fingerprint'] = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    return normalized


def execution_result(directory, request_id, state=None):
    """统一重放与查询的凭据语义，只有本请求仍活动时才报告 running。"""
    identifier = request_identifier(request_id)
    run = Path(directory) / 'requests' / identifier
    request = json.loads((run / 'macro-request.json').read_text())
    receipt = run / 'result.json'
    if state is None:
        state = json.loads((Path(directory) / 'session.json').read_text())
    # 会话层已核对活动进程；外部GUI断开后，原客户端仍可能执行，不能把断开当成停止。
    active = state.get('active_request') == identifier
    from .execution_receipt import load_receipt
    observed = load_receipt(receipt, request_id)
    # 原变更请求的未知影响属于历史执行结果，不能因接受当前状态继续而改成 false。
    mutating = any(step['effect'] == 'mutate' for step in request['steps'])
    if observed['read_status'] == 'valid':
        data = observed['document']
        execution = data['execution']
        if execution['status'] == 'running' and not active:
            execution = {**execution, 'status': 'uncertain',
                         'uncertain': mutating,
                         'steps': [{**step, 'status': 'uncertain'} if step.get('status') == 'running' else step
                                   for step in execution.get('steps', [])],
                         'reason': 'No confirmed final receipt; completed steps remain recorded, do not infer rollback'}
            if execution.get('initialization', {}).get('status') == 'running':
                execution['initialization'] = {**execution['initialization'], 'status': 'uncertain'}
    else:
        execution = {'status': 'running' if active else 'uncertain', 'steps': [],
                     'uncertain': mutating,
                     'reason': 'No valid execution receipt; inspect receipt_read and session status before any retry'}
    from .execution_review import review_context, evidence_current
    digest = observed['sha256']
    result = {'request_id': request_id, 'fingerprint': request['fingerprint'],
              'execution': execution, 'receipt': str(receipt), 'receipt_sha256': digest,
              'request_activity': state.get('execution_activity', {}).get(identifier, {'state': 'unknown'}),
              'receipt_read': {key: value for key, value in observed.items() if key != 'document'}}
    review = review_context(request, state, digest, observed['read_status'])
    if review is not None:
        result['review'] = review
    recorded = state.get('execution_reviews', {}).get(identifier)
    if recorded is not None:
        # 历史未知结果保持原样；确认只是接受当前状态继续，不将旧任务追认成 completed。
        result['reconciliation'] = {**recorded,
            'evidence_current': evidence_current(recorded, state, identifier, digest, observed['read_status'])}
        result['previous_reconciliation_count'] = len(state.get('execution_review_history', {}).get(identifier, []))
    # 本次读取成功不等于先前写入已确认；重放与新调用都显式保留当前会话的限制。
    for key in ('active_request', 'uncertain_request'):
        if state.get(key):
            result[key] = state[key]
    return result
