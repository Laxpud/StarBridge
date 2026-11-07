"""独立编译并执行最小会话生命周期宏，不加载结构化目录或发现辅助类。

open前先用所选安装JDK编译完整模板；成功只证明当前模板可编译，随后仍需真实
服务器版本与加载对象检查。用户宏和业务API的可用性不能由该预检查推断。
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile

from .java_runtime import _JAVAC_ISOLATION_POLICY, _installation, source_text
from .macro_execution import compile_program
from .modifier import java_literal
from starbridge.core.session_store import runtime_root, session_version


def render(state, action, result, output=None):
    """仅将数据填入独立模板；身份与保存逻辑不经过CatalogRuntime。"""
    if action not in ('session-info', 'save'):
        raise ValueError('Unsupported lifecycle action')
    version = session_version(state)
    values = {'RESULT': str(result), 'ACTION': action, 'RELEASE': version['release'],
              'BUILD': version['build'], 'EXPECTED_KEY': state.get('simulation_key', ''),
              'EXPECTED_SESSION': state.get('current_file') or '',
              'OUTPUT': str(output) if output is not None else ''}
    source = Path(__file__).resolve().parents[1] / 'java' / 'StarBridgeLifecycle.java'
    return re.sub(r'__([A-Z_]+)__', lambda match: java_literal(values[match.group(1)]), source_text(source))


def _selected_installation(star):
    """要求选定安装内唯一工具链，不用系统javac或邻近版本代替未知环境。"""
    executable = shutil.which(star)
    selected = _installation(str(Path(executable).resolve())) if executable else None
    if selected is None:
        raise ValueError('Selected STAR installation JDK and libraries could not be located unambiguously; '
                         'use the actual installation launcher, not an external wrapper')
    return selected


def prepare(star, version, timeout=90):
    """在启动或接入服务器前编译最小生命周期模板，缓存按真实版本和所选库隔离。

    同一安装路径原地升级不能复用旧编译凭据；库的文件元数据参与缓存键。
    只生成编译产物，不调用STAR、读取算例或证明任意宏API已受支持。
    """
    state = {'star_version': version}
    version = session_version(state)
    root, compiler, jars = _selected_installation(star)
    source = render(state, 'session-info', '/unused/starbridge-preflight-result.json')
    # 隔离策略变更也使预检查失效；旧编译证明不能代表新策略下已成功编译。
    fingerprint = [source, version, str(root), str(compiler), _JAVAC_ISOLATION_POLICY,
                   [(str(jar), jar.stat().st_mtime_ns, jar.stat().st_size) for jar in jars]]
    key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    cache = runtime_root() / 'cache' / 'lifecycle'
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / key
    with (cache / (key + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = destination / 'ready.json'
        if marker.is_file():
            marker.touch()
            return json.loads(marker.read_text())
        with tempfile.TemporaryDirectory(prefix='.preparing-', dir=cache) as temporary:
            directory = Path(temporary)
            macro = directory / 'StarBridgeLifecycle.java'
            macro.write_text(source)
            compiled = compile_program(star, macro, directory, min(timeout, 90))
            if compiled['status'] != 'compiled':
                raise ValueError('Lifecycle preflight requires compilation using the selected installation JDK')
            proof = {**compiled, 'star_version': version, 'compiler': str(compiler),
                     'scope': 'minimal_lifecycle_template', 'runtime_identity': 'not_checked'}
            (directory / 'ready.json').write_text(json.dumps(proof) + '\n')
            if destination.exists():
                # 旧清理器可能只删marker；持同一把锁清理本缓存的残留目录后发布，不冒用无凭据旧产物。
                if destination.is_symlink() or destination.resolve().parent != cache.resolve():
                    raise ValueError('Lifecycle cache destination is outside its managed cache directory')
                shutil.rmtree(destination)
            directory.rename(destination)
    return proof


def prune_cache(cutoff):
    """使用与编译相同的锁整目录清理过期产物，不只删除ready凭据留下失效目录。"""
    cache = runtime_root() / 'cache' / 'lifecycle'
    for marker in cache.glob('*/ready.json'):
        try:
            directory = marker.parent
            if directory.is_symlink() or directory.resolve().parent != cache.resolve():
                continue
            with (cache / (directory.name + '.lock')).open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if marker.stat().st_mtime < cutoff:
                    shutil.rmtree(directory)
        except OSError:
            # 编译或其他清理正在进行时保留缓存；不会因此阻止会话连接。
            continue


def _receipt(result):
    """只接受完整生命周期终态；没有凭据时不把客户端退出当成保存成功。"""
    try:
        data = json.loads(result.read_text())
    except (OSError, ValueError):
        return None
    if data.get('status') in ('ok', 'rejected', 'uncertain') and isinstance(data.get('after'), dict):
        return data
    return None


def execute(state, directory, action, timeout, *, output=None, on_client_start=None, on_client_launch=None):
    """编译当前请求后只启动一个短生命周期客户端，保留保存异常与传输中断的区别。"""
    _selected_installation(state['star'])
    directory.mkdir(parents=True, exist_ok=False)
    result = directory / 'result.json'
    macro = directory / 'StarBridgeLifecycle.java'
    macro.write_text(render(state, action, result, output))
    compiled = compile_program(state['star'], macro, directory, min(timeout, 90))
    if compiled['status'] != 'compiled':
        raise ValueError('Lifecycle request was not precompiled with the selected installation JDK')
    (directory / 'compilation.json').write_text(json.dumps(compiled) + '\n')
    command = [state['star'], '-noretry', '-nbuserdir', str(directory.parent.parent / 'client-settings'),
               '-host', state.get('host', 'localhost'), '-port', str(state['port']), '-batch', str(macro), '-noexit']
    (directory / 'command.json').write_text(json.dumps(command) + '\n')
    interrupted = False
    with (directory / 'star.log').open('w') as log:
        process = None
        try:
            if on_client_launch is not None:
                on_client_launch('attempted')
            try:
                process = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                           env=dict(os.environ, LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8'))
            except (OSError, ValueError):
                if on_client_launch is not None:
                    on_client_launch('not_started')
                raise
            if on_client_start is not None:
                on_client_start(process.pid)
            process.wait(timeout=timeout)
        except BaseException:
            interrupted = True
            # 只停止本次客户端进程组；缺少PID不代表没有启动，也不将超时当成保存撤销。
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    data = _receipt(result)
    if data is None:
        raise RuntimeError(f'Lifecycle client has no final receipt; inspect {directory}')
    return dict(data, compilation=compiled, client_returncode=process.returncode if process is not None else None,
                transport_interrupted=interrupted)
