#!/usr/bin/env python3
"""管理本机后台 STAR 会话，通过临时批处理客户端连续读取、修改和另存。"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid

from file_bridge import digest, execute


def write_json(path, data):
    """原子更新会话记录，避免中断后读到只写了一半的 JSON。"""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def process_identity(pid):
    """读取 Linux 进程启动时刻与进程组；PID 复用不能视为原服务仍然存活。"""
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return {'pid': pid, 'start_ticks': fields[19], 'pgid': int(fields[2]),
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(state):
    """只承认本次启动记录对应的进程，不通过端口猜测会话身份。"""
    owner = state.get('process')
    server = state.get('server_process')
    return (owner is not None and process_identity(owner['pid']) == owner
            and (server is None or process_identity(server['pid']) == server))


def descendants(pid):
    """枚举已知启动器的子进程；MPI 会创建自己的进程组，不能只记启动器 PGID。"""
    identities = []
    pending = [pid]
    seen = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        identity = process_identity(current)
        if identity is None:
            continue
        identities.append(identity)
        for path in Path(f'/proc/{current}/task').glob('*/children'):
            try:
                pending.extend(int(child) for child in path.read_text().split())
            except FileNotFoundError:
                pass
    return identities


@contextmanager
def locked(directory):
    """同一会话一次只允许一个 Bridge 请求，锁在进程退出时自动释放。"""
    with (directory / 'session.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Session is busy with another Bridge request')
        yield


def terminate_owned(state):
    """先停止实际算例服务，再清理已记录的 MPI 子进程；逐个核对 PID 身份。"""
    owner = state.get('process')
    owned = state.get('owned_processes', [])
    if owner is not None and process_identity(owner['pid']) == owner:
        owned = descendants(owner['pid']) + owned
    owned = list({item['pid']: item for item in owned}.values())
    server = state.get('server_process', owner)

    def send(identity, sig):
        if identity is not None and process_identity(identity['pid']) == identity:
            try:
                os.kill(identity['pid'], sig)
            except ProcessLookupError:
                pass

    send(server, signal.SIGTERM)
    for sig, seconds in [(None, 10), (signal.SIGTERM, 5), (signal.SIGKILL, 5)]:
        if sig is not None:
            for item in reversed(owned):
                send(item, sig)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not any(process_identity(item['pid']) == item for item in owned):
                return
            time.sleep(0.2)
    raise RuntimeError('Managed server processes did not terminate')


def request(directory, state, action, timeout, *, output=None, name='', value=0.0, unit=''):
    """连接已登记的服务并校验目标文件身份；修改失败不自动重试。"""
    if not alive(state):
        raise RuntimeError('Managed server is not running; refusing to connect to its old port')
    identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    run = directory / 'requests' / identifier
    write_json(directory / 'session.json', dict(state, active_request=identifier))
    data = execute(state['star'], None, run, output, name, value, unit,
                   action=action, host=state['host'], port=state['port'],
                   expected_session=state['current_file'], timeout=timeout,
                   client_userdir=directory / 'client-settings')
    if not alive(state):
        raise RuntimeError('Server exited or changed identity during request')
    if digest(Path(state['input'])) != state['input_sha256']:
        raise RuntimeError('Original input file changed')
    state['current_file'] = data['after']['session_path']
    state['modified'] = data['after']['modified']
    state['last_request'] = identifier
    state['active_request'] = None
    state['state'] = 'ready'
    write_json(directory / 'session.json', state)
    return data, run


def start(args, directory):
    """复制输入并启动独立服务，随后用一次只读请求确认该算例可用。"""
    source = args.input.resolve(strict=True)
    if not source.is_file():
        raise ValueError('Input must be a file')
    star = shutil.which(args.star)
    if star is None:
        raise ValueError(f'STAR executable not found: {args.star}')
    directory.mkdir(parents=True, exist_ok=False)
    with locked(directory):
        # 1. 隔离磁盘文件；本机原件永远不作为后台服务的保存目标。
        original = digest(source)
        working = directory / 'working.sim'
        shutil.copy2(source, working)
        if digest(working) != original or digest(source) != original:
            raise RuntimeError('Input changed while creating working copy')
        # 2. 端口冲突提前失败，服务还会使用 portrange=1 禁止自动换到其他端口。
        with socket.socket() as probe:
            probe.bind(('0.0.0.0', args.port))
        command = [star, '-server', '-np', '1', '-noretry', '-loc', '-port', str(args.port),
                   '-portrange', '1', '-load', str(working)]
        write_json(directory / 'server-command.json', command)
        environment = os.environ.copy()
        environment.update(LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8')
        state = {'schema_version': 1, 'state': 'starting', 'host': 'localhost',
                 'port': args.port, 'star': star, 'input': str(source),
                 'input_sha256': original, 'working_copy': str(working),
                 'current_file': str(working), 'modified': None, 'active_request': None}
        with (directory / 'server.log').open('w') as log:
            process = subprocess.Popen(command, cwd=directory, env=environment,
                                       stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        state['process'] = process_identity(process.pid)
        write_json(directory / 'session.json', state)
        try:
            # 3. 等待本次服务自身报告端口，不能把其他进程的端口当作启动成功。
            deadline = time.monotonic() + args.timeout
            while True:
                if process.poll() is not None or not alive(state):
                    raise RuntimeError(f'Server startup failed; see {directory / "server.log"}')
                log = (directory / 'server.log').read_text(errors='replace')
                if re.search(r'Server::start -host \S+:' + str(args.port) + r'\b', log):
                    rank = re.search(r'Process rank 0 \S+ (\d+)', log)
                    if rank is None:
                        raise RuntimeError('Server rank PID was not reported')
                    state['owned_processes'] = descendants(process.pid)
                    state['server_process'] = process_identity(int(rank[1]))
                    if state['server_process'] not in state['owned_processes']:
                        raise RuntimeError('Server rank does not belong to the managed launcher')
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Server startup timed out')
                time.sleep(0.2)
            _, run = request(directory, state, 'inspect', max(1, deadline - time.monotonic()))
            state['initial_request'] = run.name
            write_json(directory / 'session.json', state)
        except BaseException:
            terminate_owned(state)
            process.wait(timeout=10)
            state['state'] = 'failed'
            write_json(directory / 'session.json', state)
            raise
    return state


def operate(args, directory):
    """对管理目录中的现有会话执行一个命令；不接管用户手动启动的 STAR。"""
    with locked(directory):
        state = json.loads((directory / 'session.json').read_text())
        if args.action == 'status':
            return dict(state, server_alive=alive(state))
        # 启动器异常退出时，显式放弃仍可清理身份匹配的遗留 MPI 进程。
        if not alive(state) and not (args.action == 'stop' and args.discard):
            raise RuntimeError('Managed server is not running')
        uncertain = state['state'] != 'ready' or state.get('active_request') is not None
        if uncertain and not (args.action == 'stop' and args.discard):
            raise RuntimeError('Previous operation outcome is unknown; inspect logs or stop --discard')
        if args.action == 'stop':
            # 先读取 STAR 的修改标志；本机另存后仍可能为真，不擅自清除此标志。
            # 失败或仍有修改时，只有显式 discard 才允许放弃剩余内存状态。
            if not args.discard:
                data, _ = request(directory, state, 'inspect', args.timeout)
                if data['after']['modified']:
                    raise RuntimeError('Unsaved changes exist; save first or use stop --discard')
            terminate_owned(state)
            state['state'] = 'stopped'
            state['active_request'] = None
            state['server_alive'] = False
            write_json(directory / 'session.json', state)
            return state
        output = None
        if args.action == 'save':
            output = args.output.resolve()
            if (output.exists() or output.suffix != '.sim' or not output.parent.is_dir()
                    or output == Path(state['input'])):
                raise ValueError('Output must be a new .sim file with an existing parent directory')
        try:
            data, run = request(directory, state, args.action, args.timeout, output=output,
                                name=getattr(args, 'name', ''), value=getattr(args, 'value', 0.0),
                                unit=getattr(args, 'unit', ''))
            if args.action == 'set-scalar':
                target = next(p for p in data['after']['parameters'] if p['name'] == args.name)
                actual = target.get('raw_value')
                if (target.get('unit') != args.unit or not isinstance(actual, (int, float))
                        or not math.isclose(actual, args.value, rel_tol=1e-12, abs_tol=1e-12)):
                    raise RuntimeError('Readback does not match requested scalar value/unit')
            if output:
                if not output.is_file() or Path(data['after']['session_path']).resolve() != output:
                    raise RuntimeError('Saved file/path was not confirmed')
            return {'session': str(directory), 'process': state['process'],
                    'request_result': str(run / 'result.json'), 'snapshot': data['after']}
        except BaseException:
            # 超时或客户端失败可能发生在写入之后；保留不确定状态并禁止静默重试。
            state['state'] = 'uncertain'
            write_json(directory / 'session.json', state)
            raise


def main():
    """提供显式生命周期命令；每次调用结束不会自动关闭后台会话。"""
    if not sys.platform.startswith('linux'):
        raise RuntimeError('Session prototype currently supports Linux only')
    parser = argparse.ArgumentParser(description='Manage a persistent local STAR simulation server.')
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ['start', 'status', 'inspect', 'set-scalar', 'save', 'stop']:
        command = commands.add_parser(action)
        command.add_argument('--session-dir', type=Path, required=True)
        if action != 'status':
            command.add_argument('--timeout', type=float, default=180)
        if action == 'start':
            command.add_argument('input', type=Path)
            command.add_argument('--star', default='starccm+')
            command.add_argument('--port', type=int, default=49001)
        elif action == 'set-scalar':
            command.add_argument('--name', required=True)
            command.add_argument('--value', type=float, required=True)
            command.add_argument('--unit', required=True)
        elif action == 'save':
            command.add_argument('--output', type=Path, required=True)
        elif action == 'stop':
            command.add_argument('--discard', action='store_true')
    args = parser.parse_args()
    if args.action != 'status' and (not math.isfinite(args.timeout) or args.timeout <= 0):
        parser.error('--timeout must be positive and finite')
    if args.action == 'start' and not 1024 <= args.port <= 65535:
        parser.error('--port must be between 1024 and 65535')
    if args.action == 'set-scalar' and not math.isfinite(args.value):
        parser.error('--value must be finite')
    directory = args.session_dir.resolve()
    result = start(args, directory) if args.action == 'start' else operate(args, directory)
    # 部分对象读取失败不意味着会话身份不确定；保留可用快照，并显式提示缺失内容。
    if not result.get('snapshot', {}).get('inspection_complete', True):
        print('StarBridge warning: Inspection is incomplete; check snapshot read_errors.',
              file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, StopIteration) as error:
        print(f'StarBridge error: {error}', file=sys.stderr)
        sys.exit(1)
