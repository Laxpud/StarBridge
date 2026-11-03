"""复用安装相关 Java 辅助类；每次请求只生成携带本次参数的小型入口宏。"""

from functools import lru_cache
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from starbridge.core.session_store import runtime_root


@lru_cache(maxsize=8)
def _source(path, modified, size):
    """源码仅在文件元数据变化时重读；参数中的时间和大小用于缓存失效。"""
    return Path(path).read_text()


def source_text(path):
    """取得当前发行源码，源码开发时修改文件也会自动换用新内容。"""
    info = path.stat()
    return _source(str(path), info.st_mtime_ns, info.st_size)


@lru_cache(maxsize=8)
def _installation(executable):
    """只使用所选安装内的库和附带 JDK，不自动切换到其他 STAR 安装。"""
    for parent in Path(executable).parents:
        libraries = parent / 'star' / 'lib' / 'java'
        if libraries.is_dir():
            compilers = sorted(parent.parent.glob('jdk/**/bin/javac'))
            if len(compilers) == 1:
                return parent, compilers[0], tuple(sorted(libraries.rglob('*.jar')))
            return None
    return None


def compile_runtime(star, timeout=90, cache_root=None):
    """按安装路径和辅助类源码编译一次；返回宏 classpath 和内联回退所需源码。

    安装外包装脚本无法定位编译环境时，保持原有 STAR 自行编译的方式。
    编译失败明确报错，不把失败缓存成可用结果；不同请求共用完整的原子发布目录。
    """
    sources = Path(__file__).resolve().parents[1] / 'java'
    texts = {name: source_text(sources / name) for name in ('CatalogRuntime.java', 'DiscoveryRuntime.java')}
    executable = shutil.which(star)
    installation = _installation(str(Path(executable).resolve())) if executable else None
    if installation is None:
        inline = '\n'.join(text.replace('public class ', 'class ', 1) for text in texts.values())
        return None, inline
    root, compiler, jars = installation
    key = hashlib.sha256(json.dumps([str(root), texts], sort_keys=True).encode()).hexdigest()
    cache = cache_root if cache_root is not None else runtime_root() / 'cache' / 'java'
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / key
    with (cache / (key + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = destination / 'ready.json'
        if marker.is_file():
            marker.touch()
            return destination, ''
        with tempfile.TemporaryDirectory(prefix=key + '-', dir=cache) as temporary:
            build = Path(temporary)
            for name, text in texts.items():
                (build / name).write_text(text)
            compiled = subprocess.run([str(compiler), '-proc:none', '-cp', ':'.join(map(str, jars)),
                '-d', str(build), *(str(build / name) for name in texts)],
                capture_output=True, text=True, timeout=timeout)
            if compiled.returncode:
                raise RuntimeError('STAR runtime compilation failed: ' + compiled.stderr[-4000:])
            (build / 'ready.json').write_text(json.dumps({'installation': str(root), 'compiler': str(compiler)}))
            if destination.exists():
                shutil.rmtree(destination)
            build.rename(destination)
        return destination, ''


def prune_runtime_cache(cutoff):
    """在没有活动会话时清理过期编译目录；与首次编译使用同一把锁。"""
    cache = runtime_root() / 'cache' / 'java'
    for marker in cache.glob('*/ready.json'):
        try:
            directory = marker.parent
            with (cache / (directory.name + '.lock')).open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if marker.stat().st_mtime < cutoff:
                    shutil.rmtree(directory)
        except OSError:
            continue
