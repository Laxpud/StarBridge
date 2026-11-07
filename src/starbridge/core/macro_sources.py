"""准备完整 Java 宏及显式辅助文件，不解析、改写或执行用户源码。

源码文本按原 UTF-8 字节冻结；原路径保留符号链接及 ``..`` 的定位语义，供执行端
维持宏的数据根。JAR 只记录流式摘要，发布请求前再复制到私有目录并核对内容。
摘要与元数据检查仅说明选中的输入，不证明代码安全、类存在或任务运行成功。
"""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


MAX_SOURCE_BYTES = 2_000_000
MAX_SOURCE_FILES = 200
MAX_DEPENDENCIES = 32
_CHUNK_BYTES = 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024
_MACRO_REQUIRED = {'entry_source', 'entry_class'}
_MACRO_OPTIONAL = {'sources', 'classpath'}
_JAVA_IDENTIFIER = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*', re.ASCII)
_JAVA_RESERVED = frozenset('''
abstract assert boolean break byte case catch char class const continue default do double else
 enum extends final finally float for goto if implements import instanceof int interface long
 native new package private protected public return short static strictfp super switch synchronized
 this throw throws transient try void volatile while true false null _
'''.split())
_TYPE_RESTRICTED = frozenset({'var', 'yield', 'record', 'sealed', 'permits'})


def _fields(value, required, optional, label):
    """固定字段对象先校验再读取，拼错字段不能被悄悄忽略。"""
    if (not isinstance(value, dict) or not required <= value.keys()
            or not value.keys() <= required | optional):
        raise ValueError(f'{label} requires fields {sorted(required)} and only optional fields {sorted(optional)}')


def _absolute_path(value, label, suffix=None):
    """只做不改变定位的词法处理；不 resolve 链接，也不把 link/.. 折叠成其表面父目录。"""
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ValueError(f'{label} must be a non-empty absolute path string without NUL')
    try:
        value.encode('utf-8')
    except UnicodeError as error:
        raise ValueError(f'{label} must be representable as UTF-8') from error
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f'{label} must be an absolute path')
    if suffix is not None:
        # Path 会丢掉末尾分隔符；文件定位在转换前拒绝此形式，不能把 file.java/ 当成文件。
        separators = tuple(item for item in (os.sep, os.altsep) if item)
        if value.endswith(separators) or path.suffix != suffix:
            raise ValueError(f'{label} must name an explicit {suffix} file without a trailing separator')
    return str(path)


def _class_name(value):
    """限制可安全嵌入 Java 调用的 ASCII 类名；包、类型和构造器实际存在性由 javac 确认。"""
    if not isinstance(value, str) or not value:
        raise ValueError('entry_class must be a non-empty ASCII qualified Java class name')
    parts = value.split('.')
    if (any(_JAVA_IDENTIFIER.fullmatch(part) is None or part in _JAVA_RESERVED for part in parts)
            or parts[-1] in _TYPE_RESTRICTED):
        raise ValueError('entry_class must contain safe ASCII Java identifiers, not keywords or source syntax')
    return value


def _path_list(value, label, suffix):
    """列表保留首次出现顺序；只合并相同词法路径，不合并可能有不同数据根的链接别名。"""
    if not isinstance(value, list):
        raise ValueError(f'{label} must be an array of absolute file paths')
    result, seen = [], set()
    for item in value:
        path = _absolute_path(item, label, suffix)
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _entries(macros):
    """规范化每个宏并收集显式输入；没有完整宏时由调用方保留原 code 路径，不建空包。"""
    if not isinstance(macros, list) or not macros:
        raise ValueError('macros must be a non-empty array of macro objects')
    entries, sources, dependencies = [], {}, {}
    for macro in macros:
        _fields(macro, _MACRO_REQUIRED, _MACRO_OPTIONAL, 'macro')
        entry = {'entry_source': _absolute_path(macro['entry_source'], 'entry_source', '.java'),
                 'entry_class': _class_name(macro['entry_class']),
                 'sources': _path_list(macro.get('sources', []), 'sources', '.java'),
                 'classpath': _path_list(macro.get('classpath', []), 'classpath', '.jar')}
        entries.append(entry)
        for path in [entry['entry_source'], *entry['sources']]:
            sources.setdefault(path, None)
        for path in entry['classpath']:
            dependencies.setdefault(path, None)
        if len(sources) > MAX_SOURCE_FILES:
            raise ValueError('Macro bundle exceeds 200 distinct Java source paths')
        if len(dependencies) > MAX_DEPENDENCIES:
            raise ValueError('Macro bundle exceeds 32 distinct JAR dependency paths')
    return entries, list(sources), list(dependencies)


def _identity(info):
    """核对同一普通文件及内容相关元数据，不因读取更新的 atime 误判文件变化。"""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _stream(path, *, limit=None, output=None, collect=False):
    """读取一个显式文件，同时摘要、可选收集或复制，并拒绝读取窗口内可观察的变化。

    非阻塞打开避免文件在 stat 与 open 之间被换成 FIFO 时无限等待；打开后再次要求
    普通文件。元数据在读取前、打开后、读取后及路径上核对，不声称得到文件系统事务。
    """
    descriptor = None
    try:
        before = os.stat(path)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f'Explicit input is not a regular file: {path}')
        if limit is not None and before.st_size > limit:
            raise ValueError('Macro source bytes exceed the 2 MB bundle limit')
        flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(path, flags)
        digest, count, chunks = hashlib.sha256(), 0, []
        with os.fdopen(descriptor, 'rb') as handle:
            descriptor = None
            if _identity(os.fstat(handle.fileno())) != _identity(before):
                raise ValueError(f'Explicit input changed while opening: {path}')
            while chunk := handle.read(_CHUNK_BYTES):
                count += len(chunk)
                if limit is not None and count > limit:
                    raise ValueError('Macro source bytes exceed the 2 MB bundle limit')
                digest.update(chunk)
                if collect:
                    chunks.append(chunk)
                if output is not None and output.write(chunk) != len(chunk):
                    raise OSError('Incomplete dependency write')
            after = os.fstat(handle.fileno())
            if (_identity(before) != _identity(after) or _identity(before) != _identity(os.stat(path))
                    or count != before.st_size):
                raise ValueError(f'Explicit input changed while reading: {path}')
        return digest.hexdigest(), count, b''.join(chunks) if collect else None, _identity(before)
    except OSError as error:
        raise ValueError(f'Cannot read or stage explicit input {path}: {error}') from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _main_attributes(content):
    """按 JAR manifest 的主节读取属性；先拼接物理续行，避免拆开跨行 UTF-8 字符。

    属性名不区分大小写；空行结束主节，后面的具名条目属性不决定 JAR 的 classpath。
    非法头部和没有前一属性的续行明确拒绝，不将无法识别的头部当成不存在依赖。
    """
    attributes, name, value = [], None, bytearray()
    for line in content.replace(b'\r\n', b'\n').replace(b'\r', b'\n').split(b'\n'):
        if not line:
            break
        if line.startswith(b' '):
            if name is None:
                raise ValueError('JAR manifest continuation has no preceding attribute')
            value.extend(line[1:])
            continue
        if name is not None:
            attributes.append((name, bytes(value)))
        match = re.fullmatch(rb'([A-Za-z0-9_-]{1,70}): (.*)', line)
        if match is None:
            raise ValueError('JAR manifest contains an invalid main attribute')
        name, value = match.group(1).lower(), bytearray(match.group(2))
    if name is not None:
        attributes.append((name, bytes(value)))
    for _, value in attributes:
        try:
            value.decode('utf-8')
        except UnicodeError as error:
            raise ValueError('JAR manifest main attributes must contain valid UTF-8') from error
    return attributes


def _check_manifest(path, expected_identity):
    """拒绝 manifest 引入未冻结的外部 classpath，不递归找依赖或改写原 JAR。

    ZipFile 只打开调用者明确列出的 JAR；manifest 解压读取最多 1 MiB。检查包含
    manifest 文件名和属性名的大小写形式，并拒绝旧式 JAR 索引间接查找；不解压其他
    资源，也不认证整个归档可执行。
    """
    descriptor = None
    try:
        if _identity(os.stat(path)) != expected_identity:
            raise ValueError(f'JAR dependency changed before manifest inspection: {path}')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as source:
            descriptor = None
            if _identity(os.fstat(source.fileno())) != expected_identity:
                raise ValueError(f'JAR dependency changed while opening its manifest: {path}')
            with zipfile.ZipFile(source, 'r') as archive:
                entries = archive.infolist()
                # 旧式 JAR 索引也可能让类加载器追随其他归档；不依赖某个 JDK 恰好禁用它。
                if any(item.filename.upper() == 'META-INF/INDEX.LIST' for item in entries):
                    raise ValueError(f'JAR index indirection is not supported for frozen dependencies: {path}')
                manifests = [item for item in entries if item.filename.upper() == 'META-INF/MANIFEST.MF']
                if len(manifests) > 1:
                    raise ValueError(f'JAR dependency has ambiguous manifest entries: {path}')
                if manifests:
                    manifest = manifests[0]
                    if manifest.file_size > _MAX_MANIFEST_BYTES:
                        raise ValueError(f'JAR manifest exceeds the 1 MiB inspection limit: {path}')
                    with archive.open(manifest) as handle:
                        content = handle.read(_MAX_MANIFEST_BYTES + 1)
                    if len(content) > _MAX_MANIFEST_BYTES or len(content) != manifest.file_size:
                        raise ValueError(f'JAR manifest size does not match its bounded content: {path}')
                    if any(name == b'class-path' and value.strip() for name, value in _main_attributes(content)):
                        raise ValueError(f'JAR manifest Class-Path references cannot be frozen; provide a JAR without that attribute: {path}')
                if (_identity(os.fstat(source.fileno())) != expected_identity
                        or _identity(os.stat(path)) != expected_identity):
                    raise ValueError(f'JAR dependency changed during manifest inspection: {path}')
    except Exception as error:
        # zipfile 及不同压缩器可能报告不同异常；无法检查时统一明确拒绝，不能略过限制。
        raise ValueError(f'Cannot inspect explicit JAR dependency {path}: {error}') from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def prepare_bundle(macros: list[dict], working_directory=None) -> dict:
    """冻结完整宏源码及显式 JAR 清单，返回协议 1 的可序列化编译输入。

    源码总原字节上限为 2,000,000，最多 200 个源路径及 32 个 JAR 路径。JAR 不设
    大小上限，全部流式摘要，不截断；时间与明确选定的总依赖大小成正比。相同 basename
    位于不同目录时分别保存，由 javac 检查重复类。UTF-8 严格解码，保留 BOM 和原换行。
    working_directory 显式绝对目录优先；省略时只接受所有入口具有相同词法父目录。
    本函数不复制项目、算例或依赖，不发现隐式辅助文件；返回后外部文件仍可能变化。
    非空 manifest Class-Path 会引入未冻结依赖，因此明确拒绝；manifest 读取上限为
    1 MiB，归档或 manifest 可见损坏也拒绝，不改写原 JAR 或解压扫描其他资源。
    """
    entries, source_paths, dependency_paths = _entries(macros)
    if working_directory is None:
        parents = {str(Path(entry['entry_source']).parent) for entry in entries}
        if len(parents) != 1:
            raise ValueError('Macro entry sources have different parent directories; specify working_directory')
        working_directory = next(iter(parents))
    working_directory = _absolute_path(working_directory, 'working_directory')
    try:
        if not stat.S_ISDIR(os.stat(working_directory).st_mode):
            raise ValueError('working_directory must be an existing directory')
    except OSError as error:
        raise ValueError(f'Cannot access working_directory: {error}') from error

    # 先取得每份明确源码的稳定字节，再记录依赖；任何一项失败都不返回部分包。
    files, dependencies, observations, total = [], [], {}, 0
    for index, path in enumerate(source_paths):
        relative = f'sources/{index:04d}/{Path(path).name}'
        _relative_path(relative, 'sources', '.java')
        digest, count, content, identity = _stream(path, limit=MAX_SOURCE_BYTES - total, collect=True)
        total += count
        try:
            text = content.decode('utf-8')
        except UnicodeError as error:
            raise ValueError(f'Java source must be valid UTF-8: {path}') from error
        files.append({'path': path, 'relative_path': relative,
                      'text': text, 'sha256': digest})
        observations[path] = identity
    for index, path in enumerate(dependency_paths):
        relative = f'dependencies/{index:04d}/{Path(path).name}'
        _relative_path(relative, 'dependencies', '.jar')
        digest, count, _, identity = _stream(path)
        _check_manifest(path, identity)
        dependencies.append({'path': path, 'relative_path': relative,
                             'sha256': digest, 'bytes': count})
        observations[path] = identity
    # 读取后面的文件期间，前面的输入也可能变化；返回前复查全部显式路径。
    for path, identity in observations.items():
        try:
            if _identity(os.stat(path)) != identity:
                raise ValueError(f'Explicit input changed before bundle preparation completed: {path}')
        except OSError as error:
            raise ValueError(f'Cannot recheck explicit input {path}: {error}') from error
    return {'protocol': 1, 'entries': entries, 'files': files, 'dependencies': dependencies,
            'working_directory': working_directory}


def _relative_path(value, prefix, suffix):
    """协议路径固定使用斜线，拒绝绝对定位、父级跳转、重复分隔符和平台相关歧义。"""
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('Bundle relative_path must be a safe slash-separated relative path')
    path = PurePosixPath(value)
    if (path.is_absolute() or str(path) != value or any(part in ('.', '..') for part in path.parts)
            or len(path.parts) != 3 or path.parts[0] != prefix or path.suffix != suffix
            or re.fullmatch('[0-9]{4}', path.parts[1]) is None):
        raise ValueError(f'Bundle relative_path must stay within {prefix}/ and end with {suffix}')
    return path.parts


def _digest(value):
    """内容摘要使用明确的小写 SHA-256 文本，不接受缺失值或宽松类型转换。"""
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('Bundle sha256 must contain exactly 64 lowercase hexadecimal characters')
    return value


@contextmanager
def _new_file(root_descriptor, parts):
    """相对于已打开私有目录逐层创建，拒绝符号链接及已有目标，不沿链接逃出目录。"""
    current, descriptor = os.dup(root_descriptor), None
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=current)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0),
                            dir_fd=current)
            os.close(current)
            current = child
        descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                             | getattr(os, 'O_CLOEXEC', 0), 0o600, dir_fd=current)
        with os.fdopen(descriptor, 'wb') as output:
            descriptor = None
            yield output
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(current)


def materialize_bundle(bundle, directory) -> tuple[list[Path], list[Path]]:
    """在调用者已新建的私有目录中写入冻结源码并复制经过摘要核对的 JAR。

    不重读原源码：UTF-8 文本与准备摘要必须匹配。JAR 复制时重新核对全部字节、大小
    和读取窗口内元数据，运行 classpath 只使用返回的新文件。所有目标采用 CREATE_NEW；
    出错保留私有目录内部分文件，由 Runner 清理，不删输入或覆盖已有目标。
    使用 POSIX dir_fd 与 O_NOFOLLOW 防止父目录链接绕过路径校验；缺少这些能力时拒绝，
    不退回有目录链接竞态的写法。此处不编译、加载或执行代码，也不创建模拟输入。
    """
    _fields(bundle, {'protocol', 'entries', 'files', 'dependencies', 'working_directory'}, set(), 'bundle')
    if type(bundle['protocol']) is not int or bundle['protocol'] != 1:
        raise ValueError('Unsupported macro bundle protocol')
    _, source_paths, dependency_paths = _entries(bundle['entries'])
    _absolute_path(bundle['working_directory'], 'working_directory')
    if not isinstance(bundle['files'], list) or not isinstance(bundle['dependencies'], list):
        raise ValueError('Bundle files and dependencies must be arrays')
    if len(bundle['files']) > MAX_SOURCE_FILES or len(bundle['dependencies']) > MAX_DEPENDENCIES:
        raise ValueError('Bundle exceeds its source or dependency count limit')
    prepared_sources, prepared_dependencies, destinations, seen_sources, seen_dependencies = [], [], set(), [], []
    total = 0
    # 完整校验所有记录后才创建目标，避免字段错误留下不必要的部分源码。
    for source in bundle['files']:
        _fields(source, {'path', 'relative_path', 'text', 'sha256'}, set(), 'source record')
        path = _absolute_path(source['path'], 'source path', '.java')
        parts = _relative_path(source['relative_path'], 'sources', '.java')
        if Path(path).name != parts[-1] or parts in destinations or path in seen_sources:
            raise ValueError('Bundle source basename, original path or destination is inconsistent')
        if not isinstance(source['text'], str):
            raise ValueError('Bundle source text must be a UTF-8 string')
        try:
            content = source['text'].encode('utf-8')
        except UnicodeError as error:
            raise ValueError('Bundle source text is not representable as UTF-8') from error
        total += len(content)
        if total > MAX_SOURCE_BYTES:
            raise ValueError('Macro source bytes exceed the 2 MB bundle limit')
        if hashlib.sha256(content).hexdigest() != _digest(source['sha256']):
            raise ValueError('Frozen Java source does not match its preparation digest')
        destinations.add(parts)
        seen_sources.append(path)
        prepared_sources.append((parts, content))
    for dependency in bundle['dependencies']:
        _fields(dependency, {'path', 'relative_path', 'sha256', 'bytes'}, set(), 'dependency record')
        path = _absolute_path(dependency['path'], 'dependency path', '.jar')
        parts = _relative_path(dependency['relative_path'], 'dependencies', '.jar')
        if (Path(path).name != parts[-1] or parts in destinations or path in seen_dependencies
                or type(dependency['bytes']) is not int or dependency['bytes'] < 0):
            raise ValueError('Bundle dependency path, destination or byte size is inconsistent')
        destinations.add(parts)
        seen_dependencies.append(path)
        prepared_dependencies.append((parts, path, _digest(dependency['sha256']), dependency['bytes']))
    if seen_sources != source_paths or seen_dependencies != dependency_paths:
        raise ValueError('Bundle files and dependencies must exactly match the ordered explicit entry inputs')
    if (not hasattr(os, 'O_DIRECTORY') or not hasattr(os, 'O_NOFOLLOW')
            or os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd):
        raise ValueError('Secure bundle staging requires directory-relative no-follow file operations')
    if not isinstance(directory, (str, Path)):
        raise ValueError('Bundle staging directory must be an absolute directory path')
    root = Path(_absolute_path(str(directory), 'bundle staging directory'))
    source_outputs, dependency_outputs = [], []
    try:
        # 根目录须已存在且自身不能是符号链接；目录句柄固定后，子目录均相对句柄打开。
        root_descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
        try:
            for parts, content in prepared_sources:
                with _new_file(root_descriptor, parts) as output:
                    if output.write(content) != len(content):
                        raise OSError('Incomplete source write')
                source_outputs.append(root.joinpath(*parts))
            for parts, path, expected_digest, expected_size in prepared_dependencies:
                with _new_file(root_descriptor, parts) as output:
                    digest, count, _, identity = _stream(path, output=output)
                    if digest != expected_digest or count != expected_size:
                        raise ValueError(f'JAR dependency changed after bundle preparation: {path}')
                    _check_manifest(path, identity)
                dependency_outputs.append(root.joinpath(*parts))
        finally:
            os.close(root_descriptor)
    except OSError as error:
        raise ValueError(f'Cannot materialize macro bundle without overwriting existing paths: {error}') from error
    return source_outputs, dependency_outputs
