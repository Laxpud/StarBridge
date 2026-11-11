"""分别保存可复用知识与精简案例证据，普通检索和读取只处理知识。

共享目录约定保持不变：用户层是 runtime_root()/memory，显式项目层是
project_dir/.starbridge/memory，同 ID 的项目记录覆盖用户和内置记录。
知识保存在根目录，证据另存于 evidence/<memory_id>/，迁移前的原记录保存在 legacy/。
证据先写入，知识及证据 ID 再原子提交；失败可能留下未引用证据，但不会让普通读取
看见半份知识。读取不创建目录，也不为复用知识要求审阅案例或调用 STAR。
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


SCHEMA_VERSION = 2
MAX_RECORD_BYTES = 2_000_000
MAX_EVIDENCE_BYTES = 4096
# 预算仅限制成功 result，不含协议封套，也不限制知识目录的累计扫描成本。
MAX_SEARCH_RESPONSE_BYTES = 32_768
_SUMMARY_CHARACTERS = {'title': 100, 'problem': 160, 'applicability': 180, 'approach': 220}
_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')
_PARAMETER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_CERTAINTIES = {'user_rule', 'single_observation', 'validated', 'uncertain'}
_REQUIRED = {'problem', 'applicability', 'approach', 'certainty'}
_OPTIONAL = {'title', 'tags', 'recipe', 'exceptions'}
_METADATA = {'schema_version', 'memory_id', 'revision', 'created_at', 'updated_at', 'evidence_ids'}
_LEGACY_REQUIRED = _REQUIRED | {'observed_effect', 'source', 'evidence', 'evidence_scope'}
_LEGACY_OPTIONAL = _OPTIONAL | {'references'}
_LEGACY_METADATA = _METADATA - {'evidence_ids'}
_EVIDENCE_OPTIONAL = {'kind', 'references', 'limitations'}
_NOTICE = ('Matching knowledge records are candidates, not automatically applicable rules. '
           'Review applicability, parameters and exceptions before use. Case evidence is not '
           'searched or returned, and is not a prerequisite for reuse. No STAR operation is performed.')
_RECIPE_NOTICE = ('Recipes are inert source data. Resolve current objects and supply '
                  'parameters explicitly; never reuse or automatically replace prior object IDs.')


class MemoryStoreError(RuntimeError):
    """存储错误必须显式报告，不能解释成没有相关知识。"""


class MemoryCorruptionError(MemoryStoreError):
    """已有记录无法读取或校验；不覆盖、不跳过原文件。"""


class MemoryNotFoundError(MemoryStoreError):
    """所选范围内没有指定知识或其明确引用的证据。"""


class MemoryMigrationRequiredError(MemoryStoreError):
    """旧混合记录尚未提炼；诊断只提供 ID 和修订，不返回案例正文。"""

    def __init__(self, records):
        self.records = [{'memory_id': item['memory_id'], 'revision': item['revision']}
                        for item in records]
        super().__init__('Legacy mixed memories require explicit knowledge migration with '
                         'update_memory; supply problem, applicability, approach and certainty. '
                         + ', '.join(f"{item['memory_id']}@{item['revision']}" for item in self.records[:20]))


class MemoryConflictError(MemoryStoreError):
    """创建 ID 已存在，或预期修订与当前修订不同。"""

    def __init__(self, memory_id, expected_revision, actual_revision):
        self.memory_id = memory_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(f'Memory {memory_id!r} revision conflict: '
                         f'expected {expected_revision!r}, found {actual_revision!r}')


class MemoryBusyError(MemoryStoreError):
    """另一写入者持有锁，本次未写入知识。"""


class MemoryPersistenceError(MemoryStoreError):
    """持久化结果未知时先读取知识修订，不盲目重放，更不能重做算例。"""

    def __init__(self, message, *, may_have_committed=False):
        self.may_have_committed = may_have_committed
        super().__init__(message)


def _seed():
    """默认种子只有可复用规则；来源说明在显式证据读取时提供。"""
    return {
        'schema_version': SCHEMA_VERSION, 'memory_id': 'starccm-unit-expression', 'revision': 1,
        'created_at': '2026-11-05T00:00:00+08:00', 'updated_at': '2026-11-05T00:00:00+08:00',
        'title': 'STAR-CCM+ 表达式中带单位数值的写法',
        'problem': '编写参数或场函数表达式时，需要直接输入带单位的数值。',
        'applicability': 'STAR-CCM+ 参数和场函数的表达式输入；不推断其他 API 或文件格式。',
        'approach': '带单位的数值写成 <1 deg>，不要写成 1 <deg>。',
        'certainty': 'user_rule',
        'tags': ['STAR-CCM+', '单位', '表达式', '参数', '场函数', 'units', 'expression', 'deg'],
        'evidence_ids': ['builtin-unit-expression'],
    }


def _seed_evidence():
    """内置证据不随搜索返回，也不因读取而落盘。"""
    return {
        'schema_version': 1, 'memory_id': 'starccm-unit-expression',
        'evidence_id': 'builtin-unit-expression', 'created_at': '2026-11-05T00:00:00+08:00',
        'summary': '用户在需求讨论中明确纠正了带单位数值的表达式写法。',
        'kind': 'user_rule', 'references': ['StarBridge.md#已讨论的经验示例'],
        'limitations': '未另行运行软件验证。',
    }


def _identifier(value, field='memory_id'):
    """ID 只允许单个安全文件名，不接受目录路径。"""
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f'{field} must contain 1-128 ASCII letters, digits, underscores or hyphens')
    return value


def _json_copy(value):
    """复制严格 JSON，拒绝非有限数、非字符串键和隐式类型转换。"""
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
    """知识正文使用文字，避免把案例路径等结构化元数据夹入普通返回。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be non-empty text')


def _description(value, name):
    """仅旧格式读取接受带 description 的说明对象，不把其元数据投影为知识。"""
    _text(value.get('description') if isinstance(value, dict) else value, name)


def _recipe(value):
    """校验可复用方法与当前参数契约，不执行代码或补造对象引用。

    object_reference 必须由新任务定位，不能保存历史 object_id 默认值；普通参数
    可以保留确有复用价值的单位和约束。该校验不认证 Java 语义或行为安全。
    """
    if not isinstance(value, dict):
        raise ValueError('recipe must be a JSON object')
    _text(value.get('code'), 'recipe.code')
    if not isinstance(value.get('imports'), list):
        raise ValueError('recipe.imports must be a list')
    for item in value['imports']:
        _text(item, 'recipe.imports item')
    parameters = value.get('parameters')
    if not isinstance(parameters, dict):
        raise ValueError('recipe.parameters must map names to explicit parameter contracts')
    kinds = {'string', 'number', 'integer', 'boolean', 'object', 'array', 'object_reference'}
    for name, contract in parameters.items():
        if not isinstance(name, str) or _PARAMETER.fullmatch(name) is None or not isinstance(contract, dict):
            raise ValueError('Recipe parameter names must be identifiers with object contracts')
        if not isinstance(contract.get('type'), str) or contract['type'] not in kinds:
            raise ValueError(f'Unsupported parameter type for {name!r}')
        _text(contract.get('description'), f'recipe.parameters.{name}.description')
        if not isinstance(contract.get('required'), bool):
            raise ValueError('Recipe parameter required must be boolean')
        if contract['type'] == 'object_reference' and 'default' in contract:
            raise ValueError('Object references must be resolved for the current case, not defaulted')
    if 'language' in value:
        _text(value['language'], 'recipe.language')


def _timestamp(value, field):
    """元数据时间必须带时区，不以主机本地时区猜测来源。"""
    _text(value, field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f'{field} must be an ISO 8601 timestamp') from error
    if parsed.tzinfo is None:
        raise ValueError(f'{field} must include a time zone')


def _validate(record):
    """识别旧混合格式与知识格式；普通入口另行拒绝未提炼的旧记录。"""
    if not isinstance(record, dict):
        raise ValueError('Memory must be a JSON object')
    version = record.get('schema_version')
    if type(version) is not int or version not in (1, SCHEMA_VERSION):
        raise ValueError('Unsupported memory schema_version')
    legacy = version == 1
    required = _LEGACY_REQUIRED if legacy else _REQUIRED
    optional = _LEGACY_OPTIONAL if legacy else _OPTIONAL
    metadata = _LEGACY_METADATA if legacy else _METADATA
    missing = (required | metadata) - record.keys()
    unknown = record.keys() - (required | optional | metadata)
    if missing or unknown:
        raise ValueError(f'Invalid memory fields: missing={sorted(missing)}, unknown={sorted(unknown)}')
    _identifier(record['memory_id'])
    if type(record['revision']) is not int or record['revision'] < 1:
        raise ValueError('Memory revision must be a positive integer')
    for field in ('created_at', 'updated_at'):
        _timestamp(record[field], field)
    for field in ('problem', 'applicability', 'approach'):
        (_description if legacy else _text)(record[field], field)
    if not isinstance(record['certainty'], str) or record['certainty'] not in _CERTAINTIES:
        raise ValueError('certainty must be user_rule, single_observation, validated or uncertain')
    if legacy:
        for field in ('observed_effect', 'source', 'evidence_scope'):
            _description(record[field], field)
        if not isinstance(record['evidence'], list) or not record['evidence']:
            raise ValueError('Legacy evidence must be a non-empty list')
        for item in record['evidence']:
            _description(item, 'evidence item')
    else:
        ids = record['evidence_ids']
        if not isinstance(ids, list) or len(ids) != len(set(item for item in ids if isinstance(item, str))):
            raise ValueError('evidence_ids must be a list of unique identifiers')
        for item in ids:
            _identifier(item, 'evidence_id')
    for field in ('references', 'exceptions'):
        if field in record:
            if not isinstance(record[field], list):
                raise ValueError(f'{field} must be a list')
            for item in record[field]:
                (_description if legacy else _text)(item, field + ' item')
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


def _knowledge(record):
    """旧正文不做自动摘要或语义猜测，避免案例数值藏在 approach 中继续泄漏。"""
    if record['schema_version'] != SCHEMA_VERSION:
        raise MemoryMigrationRequiredError([record])
    return record


def _roots(project_dir):
    """保留用户和项目覆盖层；共享记忆目录由调用者已有项目规则选择。"""
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
    """重复 JSON 键是损坏，不允许解析器静默使用后一个值。"""
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key!r}')
        result[key] = value
    return result


def _read_json(path, maximum=MAX_RECORD_BYTES):
    """只读有界普通文件；拒绝符号链接、坏 JSON 和非法编码。"""
    if path.is_symlink():
        raise ValueError('Memory files must not be symbolic links')
    with path.open('rb') as handle:
        raw = handle.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('Memory file exceeds its byte limit')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)


def _read_record(path):
    """同时核对记录结构和文件名，不隐藏低优先级存储中的损坏。"""
    try:
        record = _validate(_json_copy(_read_json(path)))
        if path.stem != record['memory_id']:
            raise ValueError('Memory filename and memory_id differ')
        return record
    except (OSError, ValueError, TypeError, RecursionError) as error:
        raise MemoryCorruptionError(f'Cannot read memory record {path}: {error}') from error


def _check_root(root):
    """缺失目录表示尚无记录，权限失败和非目录不能伪装成空存储。"""
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
    """逐层覆盖知识记录；此路径从不打开证据目录或迁移备份。"""
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
    """使用进程退出即释放的系统锁，不删除共享锁文件或回收仍活动的锁。"""
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
        handle.close()


@contextmanager
def _write_scope(roots):
    """按固定顺序锁住所有参与修订比较的层，再写入显式选择的最高层。"""
    with ExitStack() as stack:
        for root in sorted({root for _, root in roots}, key=str):
            stack.enter_context(_lock(root))
        yield roots[-1][1]


def _encoded(record):
    return json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + '\n'


def _persist(root, record, *, filename=None, maximum=MAX_RECORD_BYTES):
    """在同一目录 fsync 后原子替换单个记录，不宣称跨文件事务。"""
    name = filename or record['memory_id']
    if not name or Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('Persistence filename must be a single component')
    payload = _encoded(record)
    if len(payload.encode('utf-8')) > maximum:
        raise ValueError('Formatted memory record exceeds its byte limit')
    temporary = None
    committed = False
    try:
        descriptor, name_tmp = tempfile.mkstemp(prefix=f'.{name}.', suffix='.tmp', dir=root)
        temporary = Path(name_tmp)
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / f'{name}.json')
        committed = True
        if os.name != 'nt':
            directory = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except OSError as error:
        state = ('Commit may already be visible; read knowledge before retrying.' if committed else
                 'This record was not committed; unreferenced evidence may remain.')
        raise MemoryPersistenceError(f'Cannot persist memory {name!r}: {error}. {state}',
                                     may_have_committed=committed) from error
    finally:
        if temporary is not None and not committed:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # 临时残留不是正式记录，不参与检索，也不覆盖原始失败。
                pass


def _subdirectory(root, *parts, create=False):
    """证据及备份子目录不得通过符号链接逃逸；普通读取不创建目录。"""
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise MemoryCorruptionError(f'Memory subdirectory must not be a symbolic link: {current}')
        if create:
            try:
                created = not current.exists()
                current.mkdir(mode=0o700, exist_ok=True)
                if created and os.name != 'nt':
                    # 子目录名也需落盘，避免先写入的证据在知识提交后因掉电失去父目录项。
                    parent = os.open(current.parent, os.O_RDONLY)
                    try:
                        os.fsync(parent)
                    finally:
                        os.close(parent)
            except OSError as error:
                raise MemoryPersistenceError(f'Cannot prepare memory subdirectory {current}: {error}') from error
        elif not _check_root(current):
            return None
    return current


def _validate_evidence(record):
    """案例只需简短 summary；其余内容按需给出，整条格式化记录最多 4 KiB。"""
    metadata = {'schema_version', 'memory_id', 'evidence_id', 'created_at'}
    if not isinstance(record, dict) or set(record) - (metadata | {'summary'} | _EVIDENCE_OPTIONAL):
        raise ValueError('Invalid evidence fields')
    if (metadata | {'summary'}) - record.keys():
        raise ValueError('Evidence requires summary and system metadata')
    if type(record['schema_version']) is not int or record['schema_version'] != 1:
        raise ValueError('Unsupported evidence schema_version')
    _identifier(record['memory_id'])
    _identifier(record['evidence_id'], 'evidence_id')
    _timestamp(record['created_at'], 'created_at')
    _text(record['summary'], 'evidence.summary')
    if 'kind' in record and (not isinstance(record['kind'], str) or
            record['kind'] not in {'user_rule', 'documentation', 'compilation', 'execution', 'uncertain'}):
        raise ValueError('Unsupported evidence kind')
    if 'limitations' in record:
        _text(record['limitations'], 'evidence.limitations')
    if 'references' in record:
        if not isinstance(record['references'], list) or len(record['references']) > 8:
            raise ValueError('Evidence references must be a list of at most eight locations')
        for reference in record['references']:
            _text(reference, 'evidence reference')
    if len(_encoded(record).encode('utf-8')) > MAX_EVIDENCE_BYTES:
        raise ValueError('Evidence exceeds 4 KiB; keep a short conclusion and reference existing artifacts')
    return record


def _new_evidence(value, memory_id, now):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - ({'summary'} | _EVIDENCE_OPTIONAL):
        raise ValueError('evidence must be a compact summary object, not a legacy evidence list')
    return _validate_evidence(dict(value, schema_version=1, memory_id=memory_id,
                                   evidence_id=uuid.uuid4().hex, created_at=now))


def _archive_legacy(root, record):
    """迁移前保存原记录；同名备份不同则拒绝，不覆盖已有追溯依据。"""
    directory = _subdirectory(root, 'legacy', create=True)
    name = f"{record['memory_id']}-r{record['revision']}"
    path = directory / f'{name}.json'
    if path.exists() or path.is_symlink():
        try:
            if _read_json(path) != record:
                raise ValueError('Existing legacy archive differs')
        except (OSError, ValueError) as error:
            raise MemoryCorruptionError(f'Cannot preserve legacy archive {path}: {error}') from error
    else:
        _persist(directory, record, filename=name)


def _commit(root, record, evidence):
    """先持久化证据，再提交引用；中途失败不改写原知识或伪称操作撤销。"""
    if evidence is not None:
        record['evidence_ids'].append(evidence['evidence_id'])
    _validate(record)
    if evidence is not None:
        directory = _subdirectory(root, 'evidence', record['memory_id'], create=True)
        target = directory / f"{evidence['evidence_id']}.json"
        if target.exists() or target.is_symlink():
            raise ValueError('Evidence ID already exists; immutable evidence cannot be replaced')
        _persist(directory, evidence, filename=evidence['evidence_id'], maximum=MAX_EVIDENCE_BYTES)
    _persist(root, record)


def _ack(record, scope, evidence):
    """写入只返回修订和状态，不重复回传方法正文或案例。"""
    return {'memory_id': record['memory_id'], 'revision': record['revision'],
            'schema_version': SCHEMA_VERSION, 'storage_scope': scope,
            'evidence_added': evidence is not None}


def get_memory(memory_id, project_dir=None):
    """只读知识、参数契约和必要限制；证据仅有 ID，不打开其文件。"""
    return _knowledge(_get(_identifier(memory_id), _roots(project_dir)))


def record_memory(entry, project_dir=None):
    """创建知识；可选 evidence 另存精简案例，不要求为记录额外收集或验证。"""
    data = _json_copy(entry)
    if not isinstance(data, dict):
        raise ValueError('entry must be a JSON object')
    if data.get('evidence', {}) is None:
        raise ValueError('Omit evidence when no new case is being recorded')
    if (set(data) & _METADATA) - {'memory_id'}:
        raise ValueError('System metadata cannot be supplied when recording a memory')
    memory_id = _identifier(data.pop('memory_id', uuid.uuid4().hex))
    now = datetime.now(timezone.utc).isoformat()
    evidence = _new_evidence(data.pop('evidence', None), memory_id, now)
    record = _validate(dict(data, schema_version=SCHEMA_VERSION, memory_id=memory_id,
                            revision=1, created_at=now, updated_at=now, evidence_ids=[]))
    roots = _roots(project_dir)
    with _write_scope(roots) as root:
        try:
            current = _get(memory_id, roots)
        except MemoryNotFoundError:
            pass
        else:
            raise MemoryConflictError(memory_id, None, current['revision'])
        _commit(root, record, evidence)
    return _ack(record, roots[-1][0], evidence)


def update_memory(memory_id, expected_revision, changes, project_dir=None):
    """修改知识或追加必要证据；修订比较、旧记录备份和提交处于同一写锁内。

    新格式的可选字段用 null 删除，evidence 是可选的新案例而非整库替换。
    迁移旧格式必须显式提供四个知识必填字段，不能自动把项目报告当成通用做法。
    """
    memory_id = _identifier(memory_id)
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError('expected_revision must be a positive integer')
    delta = _json_copy(changes)
    if not isinstance(delta, dict) or not delta or set(delta) - (_REQUIRED | _OPTIONAL | {'evidence'}):
        raise ValueError('changes may contain only knowledge fields and an optional compact evidence')
    if delta.get('evidence', {}) is None:
        raise ValueError('Omit evidence when no new case is being recorded')
    now = datetime.now(timezone.utc).isoformat()
    evidence = _new_evidence(delta.pop('evidence', None), memory_id, now)
    if not delta and evidence is None:
        raise ValueError('changes must change knowledge or add evidence')
    roots = _roots(project_dir)
    with _write_scope(roots) as root:
        current = _get(memory_id, roots)
        if current['revision'] != expected_revision:
            raise MemoryConflictError(memory_id, expected_revision, current['revision'])
        legacy = current['schema_version'] == 1
        if legacy:
            if not _REQUIRED <= delta.keys():
                raise MemoryMigrationRequiredError([current])
            updated = {key: current[key] for key in ('memory_id', 'revision', 'created_at', 'updated_at')}
            updated.update(schema_version=SCHEMA_VERSION, evidence_ids=[])
        else:
            updated = _json_copy(current)
        for key, value in delta.items():
            if key in _OPTIONAL and value is None:
                updated.pop(key, None)
            else:
                updated[key] = value
        updated['revision'] += 1
        updated['updated_at'] = now
        _validate(updated)
        if legacy:
            _archive_legacy(root, current)
        _commit(root, updated, evidence)
    return _ack(updated, roots[-1][0], evidence)


def _get_evidence(memory_id, evidence_id, roots):
    """仅在显式追溯入口读取；继承知识仍可引用用户层或内置证据。"""
    for _, root in reversed(roots):
        directory = _subdirectory(root, 'evidence', memory_id)
        if directory is None:
            continue
        path = directory / f'{evidence_id}.json'
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise MemoryCorruptionError(f'Cannot inspect evidence {path}: {error}') from error
        try:
            record = _validate_evidence(_read_json(path, MAX_EVIDENCE_BYTES))
            if record['memory_id'] != memory_id or record['evidence_id'] != evidence_id:
                raise ValueError('Evidence filename or owning memory differs')
            return record
        except (OSError, ValueError, TypeError, RecursionError) as error:
            raise MemoryCorruptionError(f'Cannot read evidence {path}: {error}') from error
    seed = _seed_evidence()
    if (memory_id, evidence_id) == (seed['memory_id'], seed['evidence_id']):
        return seed
    raise MemoryNotFoundError(f'Evidence {evidence_id!r} for memory {memory_id!r} was not found')


def get_memory_evidence(memory_id, project_dir=None, evidence_id=None, offset=0, limit=20):
    """显式读取所选知识关联的精简证据，普通搜索/读取不会调用此函数。"""
    memory_id = _identifier(memory_id)
    if type(offset) is not int or not 0 <= offset <= 2_147_483_647 or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('Invalid evidence offset or limit')
    roots = _roots(project_dir)
    knowledge = _knowledge(_get(memory_id, roots))
    ids = knowledge['evidence_ids']
    if evidence_id is not None:
        _identifier(evidence_id, 'evidence_id')
        if evidence_id not in ids:
            raise MemoryNotFoundError('Evidence is not referenced by the selected knowledge revision')
        ids = [evidence_id]
    result = {'kind': 'memory_evidence', 'memory_id': memory_id, 'revision': knowledge['revision'],
              'records': [], 'total': len(ids), 'offset': offset, 'limit': limit, 'next_offset': None,
              'read_status': 'complete', 'budget': {'max_bytes': MAX_SEARCH_RESPONSE_BYTES}}
    for identifier in ids[offset:offset + limit]:
        result['records'].append(_get_evidence(memory_id, identifier, roots))
        result['next_offset'] = offset + len(result['records'])
        _search_response_size(result)
        if result['budget']['serialized_bytes'] > MAX_SEARCH_RESPONSE_BYTES:
            result['records'].pop()
            break
    end = offset + len(result['records'])
    result['next_offset'] = end if end < len(ids) else None
    result['read_status'] = 'partial' if offset > 0 or result['next_offset'] is not None else 'complete'
    if _search_response_size(result) > MAX_SEARCH_RESPONSE_BYTES:
        raise MemoryStoreError('Evidence response metadata exceeds its byte budget')
    return result


def _tokens(text):
    """背景只用于词法加权，不声称具备语义检索能力。"""
    terms = set()
    for word in re.findall(r'[a-z0-9_]+|[\u3400-\u9fff]+', text.casefold()):
        terms.add(word)
        if len(word) > 1 and '\u3400' <= word[0] <= '\u9fff':
            terms.update(word[index:index + 2] for index in range(len(word) - 1))
    return terms


def _excerpt(text, limit, source):
    selected = text[:limit]
    return {'text': selected, 'source': source, 'characters': len(text),
            'returned_characters': len(selected), 'truncated': len(selected) < len(text)}


def _summary_field(value, limit, field):
    item = _excerpt(value, limit, field)
    if not item['truncated']:
        item.pop('characters')
        item.pop('returned_characters')
    item.pop('source')
    return item


def _candidate_summary(candidate, project_dir):
    """摘要只投影知识，代码通过 get_memory 按需取得，不附案例或案例读取指令。"""
    record = candidate['memory']
    summary = {name: _summary_field(record[name], limit, name)
               for name, limit in _SUMMARY_CHARACTERS.items() if name in record}
    exceptions = record.get('exceptions', [])
    if exceptions:
        summary['first_exception'] = _summary_field(exceptions[0], 160, 'exceptions[0]')
    terms = candidate['match']['matched_terms']
    arguments = {'memory_id': record['memory_id']}
    if project_dir is not None:
        arguments['project_dir'] = project_dir
    return {
        'memory_id': record['memory_id'], 'revision': record['revision'],
        'certainty': record['certainty'], 'storage_scope': candidate['storage_scope'],
        'summary': summary,
        'summary_truncated': any(item['truncated'] for item in summary.values()) or len(exceptions) > 1,
        'has_recipe': 'recipe' in record,
        'full_record': {'method': 'get_memory', 'arguments': arguments},
        'match': {'score': candidate['match']['score'], 'matched_fields': candidate['match']['matched_fields'],
                  'matched_terms': [term[:64] for term in terms[:8]], 'matched_term_count': len(terms),
                  'matched_terms_truncated': len(terms) > 8 or any(len(term) > 64 for term in terms[:8])},
        'requires_context_review': True,
    }


def _search_response_size(result):
    """将计数字段自身计入 UTF-8 JSON 预算，不把字节数当作模型 token 数。"""
    size = 0
    while True:
        result['budget']['serialized_bytes'] = size
        measured = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        if measured == size:
            return size
        size = measured


def search_memory(query, context=None, limit=5, project_dir=None, offset=0):
    """只检索知识字段，默认返回五条短摘要；空查询可显式分页浏览。

    query 按空白分为关键词，全部关键词必须在知识字段中命中；context 仅影响排序。
    证据正文、案例来源、旧备份和 evidence_ids 不参与匹配，也不随结果返回。
    仍需全量读取所选层的知识记录，分页不是存储快照或全局扫描成本保证。
    """
    if not isinstance(query, str) or len(query) > 4000:
        raise ValueError('query must be text of at most 4000 characters')
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('limit must be an integer from 1 to 200')
    if type(offset) is not int or not 0 <= offset <= 2_147_483_647:
        raise ValueError('offset must be an integer from 0 to 2147483647')
    if context is not None and not isinstance(context, (str, dict)):
        raise ValueError('context must be text, a JSON object or null')
    query, context = _json_copy(query), _json_copy(context)
    roots = _roots(project_dir)
    selected_project = str(Path(project_dir).expanduser().resolve()) if project_dir is not None else None
    seed = _seed()
    records = {seed['memory_id']: (seed, 'builtin')}
    # 1. 根目录只包含知识；不递归遍历 evidence/legacy，也不为普通读取验证案例是否可用。
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
    legacy = [record for record, _ in records.values() if record['schema_version'] == 1]
    if legacy:
        raise MemoryMigrationRequiredError(legacy)
    # 2. 所有空白关键词都要命中，避免一个“文件”或“表”把整库案例召回。
    query_terms = sorted(set(query.casefold().split()))
    context_text = context if isinstance(context, str) else json.dumps(context, ensure_ascii=False) if context is not None else ''
    context_terms = _tokens(context_text)
    weights = {'title': 5, 'problem': 5, 'tags': 4, 'applicability': 3, 'approach': 3,
               'exceptions': 2, 'recipe': 1}
    candidates = []
    for record, scope in records.values():
        fields = {key: json.dumps(record[key], ensure_ascii=False).casefold() for key in weights if key in record}
        matches = {key: [term for term in query_terms if term in value] for key, value in fields.items()}
        matched = sorted({term for terms in matches.values() for term in terms})
        if len(matched) != len(query_terms):
            continue
        score = sum(weights[key] * len(terms) * 10 for key, terms in matches.items())
        score += sum(weights[key] * sum(term in value for term in context_terms) for key, value in fields.items())
        candidates.append({'memory': record, 'storage_scope': scope,
                           'match': {'score': score, 'matched_terms': matched,
                                     'matched_fields': sorted(key for key, terms in matches.items() if terms)}})
    candidates.sort(key=lambda candidate: (-candidate['match']['score'], candidate['memory']['memory_id']))
    total = len(candidates)
    result = {
        'kind': 'memory_match_candidates', 'representation': 'knowledge_summaries',
        'application': 'review_required', 'notice': _NOTICE, 'recipe_usage': _RECIPE_NOTICE,
        'query': _excerpt(query, 256, 'query'),
        'context': _excerpt(context_text, 256, 'context') if context is not None else None,
        'candidates': [], 'total_matches': total, 'offset': offset, 'limit': limit,
        'page_end_reason': 'response_budget',
        'read_scope': {'builtin': True, **{scope: str(root) for scope, root in roots}},
        'coverage': {'scope': 'knowledge_summaries', 'knowledge_only': True, 'evidence_scanned': False,
                     'full_records_returned': False, 'store_read_status': 'complete', 'snapshot': False,
                     'scan': 'all_scope_knowledge_loaded_and_ranked_before_pagination', 'scan_globally_bounded': False,
                     'continuation': 'Keep query/context/project_dir unchanged; every page recomputes live ranking.',
                     'revision': 'Compare get_memory revision before reusing or updating.'},
        'budget': {'max_bytes': MAX_SEARCH_RESPONSE_BYTES, 'encoding': 'UTF-8 JSON; ensure_ascii=False, allow_nan=False',
                   'scope': 'result_only_excludes_service_envelope_and_protocol',
                   'summary_field_characters': {**_SUMMARY_CHARACTERS, 'first_exception': 160}},
    }

    def page_state():
        returned = len(result['candidates'])
        result['returned'] = returned
        result['next_offset'] = offset + returned if offset + returned < total else None
        result['truncated'] = (offset > 0 and total > 0) or result['next_offset'] is not None
        excerpted = any(item['summary_truncated'] for item in result['candidates'])
        match_excerpted = any(item['match']['matched_terms_truncated'] for item in result['candidates'])
        result['coverage'].update(summaries_excerpted=excerpted, match_explanations_excerpted=match_excerpted,
                                  all_matches_returned=not result['truncated'])
        result['read_status'] = 'partial' if result['truncated'] or excerpted or match_excerpted else 'complete'

    # 3. 在完整候选边界分页；超预算不静默跳过某条知识。
    page_state()
    if _search_response_size(result) > MAX_SEARCH_RESPONSE_BYTES:
        raise MemoryStoreError('Memory search metadata exceeds the result byte budget')
    for candidate in candidates[offset:offset + limit]:
        result['candidates'].append(_candidate_summary(candidate, selected_project))
        page_state()
        if _search_response_size(result) > MAX_SEARCH_RESPONSE_BYTES:
            result['candidates'].pop()
            page_state()
            if not result['candidates']:
                raise MemoryStoreError('Cannot represent knowledge within the search result budget; use get_memory')
            break
    else:
        result['page_end_reason'] = 'offset_beyond_matches' if offset > total else 'limit' if result['next_offset'] is not None else 'results_end'
    if _search_response_size(result) > MAX_SEARCH_RESPONSE_BYTES:
        raise MemoryStoreError('Memory search result exceeds its byte budget')
    return result
