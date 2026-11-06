"""编译并执行通用 Java 步骤，复用 STAR 服务而不复制或重载算例。

执行器不额外调用保存；用户 Java 及 STAR 原有自动保存仍可能写文件，甚至晚于宏凭据。
每次请求只启动一个客户端；全部步骤在同一宏中完成。源码和逐步凭据保留在
会话运行目录，用于结果恢复和方法复用，不能用客户端退出码代替任务完成状态。
"""

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile

from .java_runtime import _installation, source_text
from .modifier import java_literal
from starbridge.core.session_store import session_version


def render(state, request, result):
    """将数据与源码分别填入固定入口；仅替换原模板，参数文本不会再次被解释为占位符。"""
    template = Path(__file__).resolve().parents[1] / 'java' / 'StarBridgeProgram.java'
    version = session_version(state)
    values = {
        'RESULT': java_literal(str(result)),
        'EXPECTED_KEY': java_literal(state['simulation_key']),
        'RELEASE': java_literal(version['release']),
        'BUILD': java_literal(version['build']),
        'REQUEST_ID': java_literal(request['request_id']),
        'PARAMETERS': java_literal(request['parameters']),
        'IMPORTS': '\n'.join('import ' + item + ';' for item in request['imports']),
        'DECLARATIONS': request['declarations'],
        'OBJECT_BINDING_SETUP': '\n'.join(
            'bindParameter(' + java_literal(entry['path']) + ', DiscoveryRuntime.resolveObject(sim, '
            + java_literal(entry['binding']) + ', ' + java_literal(state['session_token']) + '));'
            for entry in request.get('object_bindings', [])),
        'STEP_METADATA': '\n'.join('steps.add(' + java_literal({
            'id': step['id'], 'scope': step['scope'], 'effect': step['effect'], 'status': 'not_started'})
            + ');' for step in request['steps']),
        'STEP_CASES': '\n'.join(f'case {index}: step{index}(result); break;'
                                for index in range(len(request['steps']))),
        'STEP_METHODS': '\n'.join(
            f'private void step{index}(Map<String, Object> result) throws Exception {{\n{step["code"]}\n}}'
            for index, step in enumerate(request['steps'])),
    }
    text = re.sub(r'__([A-Z_]+)__', lambda match: values[match.group(1)], source_text(template))
    if request.get('object_bindings'):
        # 仅对象参数需要公共身份解析器。无绑定的通用宏仍不依赖结构化发现辅助类。
        # 此处只调用不设精确版本门槛的 resolveObject；安装JDK校验直接引用，固定registry签名在运行时检查。
        helper = source_text(template.with_name('DiscoveryRuntime.java'))
        text += '\n' + helper.replace('public class DiscoveryRuntime {', 'class DiscoveryRuntime {', 1)
    return text


def compile_program(star, macro, directory, timeout):
    """能定位当前安装 JDK 时先编译，语法错误在连接客户端前拒绝，不冒用其他版本库。"""
    executable = shutil.which(star)
    installation = _installation(str(Path(executable).resolve())) if executable else None
    if installation is None:
        # 包装脚本不解析内容；由 STAR 自己编译，但此时编译失败不能预先证明没有运行。
        return {'status': 'deferred_to_star', 'reason': 'Installation JDK was not located'}
    root, compiler, jars = installation
    classes = directory / 'classes'
    classes.mkdir()
    process = subprocess.run([str(compiler), '-proc:none', '-encoding', 'UTF-8',
        '-cp', os.pathsep.join(map(str, jars)), '-d', str(classes), str(macro)],
        capture_output=True, text=True, timeout=timeout,
        env=dict(os.environ, LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8'))
    (directory / 'compile.log').write_text(process.stdout + process.stderr)
    if process.returncode:
        raise ValueError('Macro compilation rejected before execution: ' + process.stderr[-6000:])
    return {'status': 'compiled', 'installation': str(root)}


def final_receipt(path):
    """只接受原子落盘的明确终态；中间 running 凭据保留步骤信息，但不能解除未知写入。"""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if (data.get('status') not in ('ok', 'rejected', 'partial', 'uncertain', 'error')
            or data.get('execution', {}).get('status') not in
            ('completed', 'partial', 'failed', 'uncertain', 'rejected')
            or not isinstance(data.get('after'), dict)):
        return None
    return data


def execute(state, directory, request, timeout, on_client_start, *, on_client_launch=None):
    """保留请求与阶段凭据，执行一次客户端；超时只终止本次客户端，不终止算例服务。"""
    result = directory / 'result.json'
    # 渲染校验在占用 ID 之前完成，确定的本地数据错误不会留下无终态的请求目录。
    text = render(state, request, result)
    directory.parent.mkdir(parents=True, exist_ok=True)
    # 请求和源码先在临时目录完整准备，再原子发布 ID；中断不能占用一个缺少请求内容的 ID。
    with tempfile.TemporaryDirectory(prefix='.preparing-', dir=directory.parent) as temporary:
        pending = Path(temporary)
        (pending / 'macro-request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2) + '\n')
        (pending / 'StarBridgeProgram.java').write_text(text)
        pending.rename(directory)
    macro = directory / 'StarBridgeProgram.java'

    def reject(error):
        """记录已知未派发的准备或启动失败，不把本地错误升级为未知算例修改。"""
        # 完整保留确定未派发的拒绝，重发同一 ID 只返回此凭据而不会再次尝试。
        data = {'status': 'rejected', 'after': {'session_path': state['current_file'],
                'modified': state['modified']}, 'execution': {'request_id': request['request_id'],
                'status': 'rejected', 'uncertain': False,
                'steps': [dict(id=step['id'], scope=step['scope'], effect=step['effect'], status='not_started')
                          for step in request['steps']], 'reason': str(error)}}
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(result)
        return data

    try:
        compilation = compile_program(state['star'], macro, directory, min(timeout, 90))
        (directory / 'compilation.json').write_text(json.dumps(compilation) + '\n')
        command = [state['star'], '-noretry', '-nbuserdir', str(directory.parent.parent / 'client-settings'),
                   '-host', state['host'], '-port', str(state['port']), '-batch', str(macro), '-noexit']
        (directory / 'command.json').write_text(json.dumps(command) + '\n')
        environment = dict(os.environ, LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8')
        log = (directory / 'star.log').open('w')
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return reject(error)
    with log:
        process = None
        try:
            # 派发记录先于Popen；创建和PID登记都受中断处理保护。
            if on_client_launch is not None:
                on_client_launch('attempted')
            try:
                process = subprocess.Popen(command, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            except (OSError, ValueError) as error:
                if on_client_launch is not None:
                    on_client_launch('not_started')
                return reject(error)
            on_client_start(process.pid)
            process.wait(timeout=timeout)
        except BaseException:
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
            data = final_receipt(result)
            if data is not None:
                # 宏可能已结束，只是客户端退出迟滞。确切终态优先于传输超时，不能永久锁死会话。
                return dict(data, client_returncode=process.returncode if process is not None else None,
                            compilation=compilation, transport_interrupted=True)
            raise RuntimeError(f'Macro client interrupted; inspect the receipt and session before continuing: {directory}')
    data = final_receipt(result)
    if data is None:
        raise RuntimeError(f'Macro has no final receipt; inspect partial steps and {directory / "star.log"}')
    # 已落盘的终态是执行依据；客户端随后退出异常仍单独报告，不重复执行已经完成的步骤。
    data['client_returncode'] = process.returncode
    data['compilation'] = compilation
    return data
