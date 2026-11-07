"""保存带场景和依据的工作记忆，检索只返回候选，不替调用者决定或执行操作。

默认读取、写入 session_store.runtime_root()/memory；显式传入 project_dir 时，
项目 .starbridge/memory 覆盖同 ID 的用户记录，用户记录再覆盖内置种子。写入目标是
显式选择的项目或用户目录；更新继承的记录会在目标目录保存新修订，不修改其来源。
读取不会创建目录，种子也不因读取而落盘。文件锁只协调使用本模块的写入者。
"""

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import errno
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid

from .session_store import runtime_root


SCHEMA_VERSION = 1
MAX_RECORD_BYTES = 2_000_000
_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')
_PARAMETER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_CERTAINTIES = {'user_rule', 'single_observation', 'validated', 'uncertain'}
_REQUIRED = {'problem', 'applicability', 'approach', 'observed_effect',
             'source', 'evidence', 'evidence_scope', 'certainty'}
_OPTIONAL = {'title', 'tags', 'references', 'recipe', 'exceptions'}
_METADATA = {'schema_version', 'memory_id', 'revision', 'created_at', 'updated_at'}
_NOTICE = ('Matching memories are candidates, not automatically applicable rules. '
           'Review the current context, evidence scope and exceptions before use. '
           'No additional verification or STAR operation is performed by this module.')
_RECIPE_NOTICE = ('Recipes are inert source data. Resolve current objects and supply '
                  'parameters explicitly; never reuse or automatically replace prior object IDs.')


class MemoryStoreError(RuntimeError):
    """工作记忆存储失败；不得将这些异常转换成“没有相关记忆”。"""


class MemoryCorruptionError(MemoryStoreError):
    """已有文件无法读取、解析或通过结构校验；保留原文件供调用者诊断。"""


class MemoryNotFoundError(MemoryStoreError):
    """指定 ID 在本次读取范围内不存在。"""


class MemoryConflictError(MemoryStoreError):
    """创建 ID 已存在，或预期修订与当前修订不一致。"""

    def __init__(self, memory_id, expected_revision, actual_revision):
        self.memory_id = memory_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(f'Memory {memory_id!r} revision conflict: '
                         f'expected {expected_revision!r}, found {actual_revision!r}')


class MemoryBusyError(MemoryStoreError):
    """其他写入者持有锁；本次未写入，可重新读取后决定是否重试。"""


class MemoryPersistenceError(MemoryStoreError):
    """持久化失败；may_have_committed 为真时必须先读取，不能盲目重放。"""

    def __init__(self, message, *, may_have_committed=False):
        self.may_have_committed = may_have_committed
        super().__init__(message)


def _seed():
    """返回独立的内置记录；用户规则不是本模块另行验证的软件行为。"""
    return {
        'schema_version': SCHEMA_VERSION,
        'memory_id': 'starccm-unit-expression',
        'revision': 1,
        'created_at': '2026-11-05T00:00:00+08:00',
        'updated_at': '2026-11-05T00:00:00+08:00',
        'title': 'STAR-CCM+ 表达式中带单位数值的写法',
        'problem': '编写参数或场函数表达式时，需要直接输入带单位的数值。',
        'applicability': '适用于上述 STAR-CCM+ 表达式输入场景；不推断其他软件、API 或文件格式。',
        'approach': '用户明确规则：写成 <1 deg>，不要写成 1 <deg>。',
        'observed_effect': '需求文档记录了用户给出的正确与错误示例；本次未另行运行软件观察效果。',
        'source': {'description': '用户在需求讨论中明确提供的规则与纠正。',
                   'location': 'StarBridge.md#已讨论的经验示例'},
        'evidence': [{'description': '需求文档明确列出正确示例 <1 deg> 和错误示例 1 <deg>。',
                      'location': 'StarBridge.md#已讨论的经验示例'}],
        'evidence_scope': '依据仅为需求文档中的用户规则；没有独立软件验证、版本覆盖或普遍性证明。',
        'certainty': 'user_rule',
        'tags': ['STAR-CCM+', '单位', '表达式', '参数', '场函数', 'units', 'expression', 'deg'],
        'references': [{'description': '工作记忆要求及用户提供的单位表达式示例。',
                        'location': 'StarBridge.md#工作记忆'}],
    }


def _identifier(value):
    """限制 ID 为单个安全文件名，避免把用户输入解释成目录路径。"""
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError('memory_id must contain 1-128 ASCII letters, digits, underscores or hyphens')
    return value


def _json_copy(value):
    """复制严格 JSON 数据，拒绝 NaN、非字符串键与隐式类型转换。"""
    def check(item):
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float) and math.isfinite(item):
            return
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for child in item.values():
                check(child)
            return
        raise ValueError('Memory data must contain only finite JSON values with string object keys')

    try:
        check(value)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode('utf-8')) > MAX_RECORD_BYTES:
            raise ValueError('Memory data exceeds 2 MB')
        return json.loads(encoded)
    except (RecursionError, UnicodeError) as error:
        raise ValueError('Memory data is too deeply nested or contains invalid Unicode') from error


def _text(value, name):
    """要求调用者明确说明内容；未知的效果或范围也必须用文字明确表达。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be non-empty text')


def _description(value, name):
    """接受文字或带 description 的结构化说明，保留来源位置和具体条件等元数据。"""
    if isinstance(value, dict):
        _text(value.get('description'), f'{name}.description')
    else:
        _text(value, name)


def _recipe(value):
    """校验可复用方法的数据契约，不解释代码，不生成参数值，也不调用 STAR。

    parameters 是“参数名 -> 契约”的对象，每份契约至少包含 type、description 和
    required。object_reference 表示必须在当前算例重新定位的对象，禁止为其保存默认
    对象 ID；其他参数可携带 JSON 默认值、单位和约束，但本模块不替执行方验证绑定。
    """
    if not isinstance(value, dict):
        raise ValueError('recipe must be a JSON object')
    _text(value.get('code'), 'recipe.code')
    imports = value.get('imports')
    if not isinstance(imports, list):
        raise ValueError('recipe.imports must be a list of source import strings')
    for item in imports:
        _text(item, 'recipe.imports item')
    parameters = value.get('parameters')
    if not isinstance(parameters, dict):
        raise ValueError('recipe.parameters must map names to explicit parameter contracts')
    kinds = {'string', 'number', 'integer', 'boolean', 'object', 'array', 'object_reference'}
    for name, contract in parameters.items():
        if _PARAMETER.fullmatch(name) is None or not isinstance(contract, dict):
            raise ValueError('Recipe parameter names must be identifiers with object contracts')
        if not isinstance(contract.get('type'), str) or contract['type'] not in kinds:
            raise ValueError(f'Unsupported parameter type for {name!r}')
        _text(contract.get('description'), f'recipe.parameters.{name}.description')
        if not isinstance(contract.get('required'), bool):
            raise ValueError(f'recipe.parameters.{name}.required must be boolean')
        if contract['type'] == 'object_reference' and 'default' in contract:
            raise ValueError('Object references must be resolved for the current case, not defaulted')
    if 'language' in value:
        _text(value['language'], 'recipe.language')


def _validate(record):
    """同时校验新记录与磁盘记录，避免损坏数据被当作可信的旧修订继续覆盖。"""
    if not isinstance(record, dict):
        raise ValueError('Memory must be a JSON object')
    missing = (_REQUIRED | _METADATA) - record.keys()
    unknown = record.keys() - (_REQUIRED | _OPTIONAL | _METADATA)
    if missing or unknown:
        raise ValueError(f'Invalid memory fields: missing={sorted(missing)}, unknown={sorted(unknown)}')
    if type(record['schema_version']) is not int or record['schema_version'] != SCHEMA_VERSION:
        raise ValueError('Unsupported memory schema_version')
    _identifier(record['memory_id'])
    if type(record['revision']) is not int or record['revision'] < 1:
        raise ValueError('Memory revision must be a positive integer')
    for name in ('created_at', 'updated_at'):
        _text(record[name], name)
        try:
            timestamp = datetime.fromisoformat(record[name])
        except ValueError as error:
            raise ValueError(f'{name} must be an ISO 8601 timestamp') from error
        if timestamp.tzinfo is None:
            raise ValueError(f'{name} must include a time zone')
    for name in ('problem', 'applicability', 'approach', 'observed_effect', 'source', 'evidence_scope'):
        _description(record[name], name)
    if not isinstance(record['certainty'], str) or record['certainty'] not in _CERTAINTIES:
        raise ValueError('certainty must be user_rule, single_observation, validated or uncertain')
    if not isinstance(record['evidence'], list) or not record['evidence']:
        raise ValueError('evidence must include at least one explicit description of the available basis')
    for item in record['evidence']:
        _description(item, 'evidence item')
    for name in ('references', 'exceptions'):
        if name in record:
            if not isinstance(record[name], list):
                raise ValueError(f'{name} must be a list')
            for item in record[name]:
                _description(item, f'{name} item')
    if 'title' in record:
        _text(record['title'], 'title')
    if 'tags' in record:
        if not isinstance(record['tags'], list):
            raise ValueError('tags must be a list')
        for item in record['tags']:
            _text(item, 'tags item')
    if 'recipe' in record:
        _recipe(record['recipe'])
    return record


def _roots(project_dir):
    """构造低到高优先级的读取位置；项目扩展必须显式指定现有项目目录。"""
    user = (runtime_root() / 'memory').resolve()
    roots = [('user', user)]
    if project_dir is not None:
        if not isinstance(project_dir, (str, os.PathLike)) or not str(project_dir).strip():
            raise ValueError('project_dir must identify an existing directory')
        project = Path(project_dir).expanduser().resolve()
        if not project.is_dir():
            raise ValueError('project_dir must identify an existing directory')
        local = (project / '.starbridge' / 'memory').resolve()
        if local != user:
            roots.append(('project', local))
    return roots


def _pairs(items):
    """拒绝重复 JSON 键，避免解析器静默采用后一个值而掩盖文件损坏。"""
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key!r}')
        result[key] = value
    return result


def _read_record(path):
    """读取完整记录；权限错误、坏 JSON、非法字段和文件名不一致均明确失败。"""
    try:
        if path.is_symlink():
            raise ValueError('Memory record must not be a symbolic link')
        with path.open('rb') as handle:
            raw = handle.read(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError('Memory file exceeds 2 MB')
        record = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)
        record = _validate(_json_copy(record))
        if path.stem != record['memory_id']:
            raise ValueError('Memory filename and memory_id differ')
        return record
    except (OSError, ValueError, TypeError, RecursionError) as error:
        raise MemoryCorruptionError(f'Cannot read memory record {path}: {error}') from error


def _check_root(root):
    """不存在的目录表示尚未写入；已有但不可读取的目录不能表示空存储。"""
    try:
        root.stat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise MemoryCorruptionError(f'Cannot inspect memory directory {root}: {error}') from error
    if not root.is_dir():
        raise MemoryCorruptionError(f'Memory storage path is not a directory: {root}')
    return True


def _get(memory_id, roots):
    """逐层读取并覆盖，连被高优先级遮盖的损坏记录也不会静默跳过。"""
    seed = _seed()
    record = seed if memory_id == seed['memory_id'] else None
    for _, root in roots:
        if not _check_root(root):
            continue
        path = root / f'{memory_id}.json'
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise MemoryCorruptionError(f'Cannot inspect memory record {path}: {error}') from error
        record = _read_record(path)
    if record is None:
        raise MemoryNotFoundError(f'Memory {memory_id!r} was not found in the selected scope')
    return record


@contextmanager
def _lock(root):
    """通过操作系统锁保护修订比较和替换；锁文件永久保留，避免删锁产生双写窗口。

    POSIX 使用 flock，Windows 使用 msvcrt 单字节锁；进程退出后由系统释放。
    采用非阻塞获取，竞争时明确返回 busy，而不是无限等待或回收仍活跃的“过期锁”。
    """
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        handle = (root / '.write.lock').open('a+b')
    except OSError as error:
        raise MemoryPersistenceError(f'Cannot open memory write lock in {root}: {error}') from error
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b'\0')
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise MemoryBusyError(f'Memory store is busy: {root}') from error
            raise MemoryPersistenceError(f'Cannot lock memory store {root}: {error}') from error
        yield
    finally:
        # 关闭本次独占打开的句柄即释放操作系统锁，不删除共享锁文件。
        handle.close()


@contextmanager
def _write_scope(roots):
    """按固定路径顺序锁住所有读取层，保护从用户记录派生项目修订时的比较。"""
    with ExitStack() as stack:
        for root in sorted({root for _, root in roots}, key=str):
            stack.enter_context(_lock(root))
        yield roots[-1][1]


def _persist(root, record):
    """同目录临时文件先 fsync 再原子替换，读者只会得到完整的旧记录或新记录。"""
    payload = json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + '\n'
    if len(payload.encode('utf-8')) > MAX_RECORD_BYTES:
        raise ValueError('Formatted memory record exceeds 2 MB')
    temporary = None
    committed = False
    try:
        descriptor, name = tempfile.mkstemp(prefix=f'.{record["memory_id"]}.', suffix='.tmp', dir=root)
        temporary = Path(name)
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / f'{record["memory_id"]}.json')
        committed = True
        # POSIX 还同步目录项；Windows 标准库没有通用目录 fsync 接口。
        if os.name != 'nt':
            directory = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except OSError as error:
        state = 'Commit may already be visible; read the record before retrying.' if committed else 'No record committed.'
        raise MemoryPersistenceError(f'Cannot persist memory {record["memory_id"]!r}: {error}. {state}',
                                     may_have_committed=committed) from error
    finally:
        if temporary is not None and not committed:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # 残留临时文件不是正式记录，不覆盖原始写入错误，也不参与检索。
                pass


def get_memory(memory_id, project_dir=None):
    """返回指定记忆的完整记录；找不到抛 MemoryNotFoundError，损坏抛 MemoryCorruptionError。

    project_dir 启用项目覆盖层；未指定时只有用户层和内置种子。revision 是更新所需的
    乐观并发令牌，应连同相同 project_dir 一起使用；不得跨读取范围复用修订号。
    """
    return _get(_identifier(memory_id), _roots(project_dir))


def record_memory(entry, project_dir=None):
    """创建修订 1 的记忆并返回完整记录，现有 ID 绝不覆盖。

    必填 problem、applicability、approach、observed_effect、source、evidence_scope 可为
    非空文字，或包含非空 description 的 JSON 对象；evidence 为至少一项同类说明的
    列表。未知效果或缺少独立验证必须如实填写，不能留空或为记录另行启动验证。
    certainty 为 user_rule / single_observation / validated / uncertain，分别代表用户
    规则、单次观察、已有验证和不确定；本模块只保存声明，绝不认证其真实性或通用性。

    可选 title、tags（字符串列表）、references / exceptions（说明列表）、recipe。
    recipe 至少含 code、imports（字符串列表）、parameters（参数名到契约的对象）；
    每份参数契约至少包含 type、description、required，可附加单位、条件等 JSON 数据。
    可指定 memory_id，否则生成 UUID；其余系统字段由本模块维护，不接受调用者赋值。
    """
    data = _json_copy(entry)
    if not isinstance(data, dict):
        raise ValueError('entry must be a JSON object')
    if (set(data) & _METADATA) - {'memory_id'}:
        raise ValueError('System metadata cannot be supplied when recording a memory')
    memory_id = _identifier(data.pop('memory_id', uuid.uuid4().hex))
    now = datetime.now(timezone.utc).isoformat()
    record = _validate(dict(data, schema_version=SCHEMA_VERSION, memory_id=memory_id,
                            revision=1, created_at=now, updated_at=now))
    roots = _roots(project_dir)
    with _write_scope(roots) as root:
        try:
            current = _get(memory_id, roots)
        except MemoryNotFoundError:
            pass
        else:
            raise MemoryConflictError(memory_id, None, current['revision'])
        _persist(root, record)
    return record


def update_memory(memory_id, expected_revision, changes, project_dir=None):
    """比较修订后更新，返回新修订；旧修订抛 MemoryConflictError，禁止丢失更新。

    changes 是顶层字段替换而非递归合并；必填字段不可删除。可选字段用 null 删除，
    其余字段仍按完整契约校验。不得修改 ID、revision、schema_version 或时间戳。
    更新种子或用户层继承的记忆时，在本次写入目标创建覆盖记录，revision 加一。
    """
    memory_id = _identifier(memory_id)
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError('expected_revision must be a positive integer')
    delta = _json_copy(changes)
    if not isinstance(delta, dict) or not delta:
        raise ValueError('changes must be a non-empty JSON object')
    if set(delta) - (_REQUIRED | _OPTIONAL):
        raise ValueError('changes may contain only editable memory fields')
    roots = _roots(project_dir)
    with _write_scope(roots) as root:
        current = _get(memory_id, roots)
        if current['revision'] != expected_revision:
            raise MemoryConflictError(memory_id, expected_revision, current['revision'])
        updated = dict(current)
        for key, value in delta.items():
            if key in _OPTIONAL and value is None:
                updated.pop(key, None)
            else:
                updated[key] = value
        updated['revision'] += 1
        updated['updated_at'] = datetime.now(timezone.utc).isoformat()
        _validate(updated)
        _persist(root, updated)
    return updated


def _tokens(text):
    """用英文词和中文双字片段做确定性词法召回，不冒充语义适用性判断。"""
    terms = set()
    for word in re.findall(r'[a-z0-9_]+|[\u3400-\u9fff]+', text.casefold()):
        terms.add(word)
        if len(word) > 1 and '\u3400' <= word[0] <= '\u9fff':
            terms.update(word[index:index + 2] for index in range(len(word) - 1))
    if not terms and text.strip():
        terms.add(text.strip().casefold())
    return terms


def search_memory(query, context=None, limit=20, project_dir=None):
    """按关键词返回候选信封，候选内 memory 可直接供 get/update 的调用者使用。

    query 为文字，空字符串用于浏览；context 可为文字或 JSON 对象，只参与排序，
    不作为“条件已满足”的证明。limit 为 1..200。结果包含总匹配数、截断状态和
    读取范围；每个候选都带 requires_context_review=True 与 recipe_usage 警告。
    任一正式 JSON 记录损坏会使本次检索明确失败，而不是略过后返回误导性空结果。
    多记录读取不是事务快照；更新前必须携带所读修订，竞争更新仍会受到保护。
    """
    if not isinstance(query, str) or len(query) > 4000:
        raise ValueError('query must be text of at most 4000 characters')
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('limit must be an integer from 1 to 200')
    if context is not None and not isinstance(context, (str, dict)):
        raise ValueError('context must be text, a JSON object or null')
    context = _json_copy(context)
    roots = _roots(project_dir)
    seed = _seed()
    records = {seed['memory_id']: (seed, 'builtin')}
    # 1. 完整读取各层再检索；高层覆盖不能掩盖低层已知文件的损坏。
    for scope, root in roots:
        if not _check_root(root):
            continue
        try:
            paths = sorted(root.iterdir())
        except OSError as error:
            raise MemoryCorruptionError(f'Cannot enumerate memory directory {root}: {error}') from error
        for path in paths:
            if path.suffix == '.json':
                record = _read_record(path)
                records[record['memory_id']] = (record, scope)
    # 2. query 必须产生文本匹配，context 只提升排序；空 query 则允许浏览全部记录。
    query_terms = _tokens(query)
    context_terms = _tokens(context if isinstance(context, str) else
                            json.dumps(context, ensure_ascii=False) if context is not None else '')
    weights = {'title': 5, 'problem': 5, 'tags': 4, 'applicability': 3, 'approach': 3,
               'observed_effect': 1, 'source': 1, 'evidence': 1, 'evidence_scope': 1,
               'references': 1, 'exceptions': 1, 'recipe': 1}
    candidates = []
    for record, scope in records.values():
        fields = {key: json.dumps(record[key], ensure_ascii=False).casefold()
                  for key in weights if key in record}
        matches = {key: sorted(term for term in query_terms if term in value)
                   for key, value in fields.items()}
        matched = sorted({term for terms in matches.values() for term in terms})
        if query_terms and not matched:
            continue
        score = sum(weights[key] * len(terms) * 10 for key, terms in matches.items())
        score += sum(weights[key] * sum(term in value for term in context_terms)
                     for key, value in fields.items())
        candidates.append({'memory': record, 'storage_scope': scope,
                           'match': {'score': score, 'matched_terms': matched,
                                     'matched_fields': sorted(key for key, terms in matches.items() if terms)},
                           'requires_context_review': True, 'recipe_usage': _RECIPE_NOTICE})
    # 3. 稳定排序不因“已验证”或“用户规则”的标签而自动提升适用性。
    candidates.sort(key=lambda candidate: (-candidate['match']['score'], candidate['memory']['memory_id']))
    return {'kind': 'memory_match_candidates', 'application': 'review_required', 'notice': _NOTICE,
            'query': query, 'context': context, 'candidates': candidates[:limit],
            'total_matches': len(candidates), 'returned': min(len(candidates), limit),
            'truncated': len(candidates) > limit, 'read_status': 'complete',
            'read_scope': {'builtin': True, **{scope: str(root) for scope, root in roots}}}
