#!/usr/bin/env python3
"""连接本机已有 STAR 或启动自有服务，按明确指令修改内存、保存和断开。"""

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


from starbridge.bridge.runner.file_bridge import (catalog_content, catalog_diff, execute,
                         prepare_catalog_modification, prepare_catalog_read, prepare_legacy,
                         prepare_snapshot)
from starbridge.bridge.runner.modifier import ModificationRejected, load_request, snapshot_diff, verify_modification
from starbridge.core.catalog_bundle import check_plan_targets, session_target
from starbridge.core.session_store import session_directory, runtime_root, public_session


class OperationUncertain(RuntimeError):
    """标记本次客户端启动后的不确定结果，区别于并发请求的活动标记。"""


class OperationBusy(ModificationRejected):
    """请求仍在执行；不能把忙碌解释为本次操作失败或未知写入。"""


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
            raise OperationBusy('Session is busy with another Bridge request')
        yield


def client_running(state):
    """检查请求客户端及其进程组；控制进程异常退出后仍保留在运行的客户端为忙碌。"""
    identity = state.get('client_process')
    if identity is None:
        if 'client_process' in state:
            return False
        owner = state.get('request_owner')
        return owner is not None and process_identity(owner['pid']) == owner
    if process_identity(identity['pid']) == identity:
        return True
    # 启动器退出不保证 Java 子进程已结束；组内同次启动后产生的进程仍计为执行中。
    for path in Path('/proc').glob('[0-9]*'):
        try:
            current = process_identity(int(path.name))
            if (current and current['pgid'] == identity['pgid']
                    and current['boot_id'] == identity['boot_id']
                    and int(current['start_ticks']) >= int(identity['start_ticks'])
                    and path.stat().st_uid == os.getuid()):
                return True
        except OSError:
            continue
    return False


def finish_request(directory, state, status, *, uncertain=False):
    """结束已停止的请求，单独保留未确认写入，后续成功读取不会抹掉它。"""
    identifier = state.get('active_request') or state.get('last_request')
    state.update(last_request=identifier, last_request_status=status, active_request=None)
    if uncertain:
        state['uncertain_request'] = identifier
    for key in ('client_process', 'request_owner', 'active_action', 'active_mutating'):
        state.pop(key, None)
    state['state'] = 'uncertain' if state.get('uncertain_request') else 'ready'
    write_json(directory / 'session.json', state)


def refresh_request(directory, state):
    """持锁后恢复中断的调用记录；已结束的只读失败可继续，写入不自动重试。"""
    if state.get('active_request'):
        disconnected = state.get('state') == 'disconnected'
        if client_running(state):
            if not disconnected:
                state['state'] = 'running'
            return
        identifier = state['active_request']
        result = directory / 'requests' / identifier / 'result.json'
        try:
            data = json.loads(result.read_text())
        except (OSError, ValueError):
            data = {}
        mutating = state.get('active_mutating', True)
        # 控制端中断时可能尚未完成 Python 回读检查；只有宏明确 rejected 才证明未赋值。
        uncertain = mutating and data.get('status') != 'rejected'
        finish_request(directory, state, 'uncertain' if uncertain else data.get('status', 'error'),
                       uncertain=uncertain)
        if disconnected:
            state.update(state='disconnected', recovery_required=bool(state.get('uncertain_request')))
            write_json(directory / 'session.json', state)
    elif state.get('state') == 'uncertain' and not state.get('uncertain_request'):
        # 旧记录没有请求类型，不能凭缺少字段推断旧写入未执行。
        state['uncertain_request'] = state.get('last_request', 'legacy-request')
        write_json(directory / 'session.json', state)


def terminate_owned(state):
    """先停止实际算例服务，再清理已记录的 MPI 子进程；逐个核对 PID 身份。"""
    if state.get('ownership') == 'external':
        raise ValueError('External STAR processes must never be terminated by StarBridge')
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


def request(directory, state, action, timeout, *, output=None, name='', value=0.0, unit='',
            modification=None, catalog_plan=None, catalog_request=None, legacy_plan=None,
            snapshot_plan=None, discovery_request=None):
    """核对进程和加载对象身份后执行请求；不检查磁盘原文件摘要或自动保存。"""
    if not alive(state):
        raise RuntimeError('Managed server is not running; refusing to connect to its old port')
    check_plan_targets(catalog_plan, legacy_plan, snapshot_plan, target=session_target(state))
    # 旧管理会话升级时在持锁请求中只补一次世代标识；对象 key 必须与该 token 配对。
    if not state.get('session_token'):
        state['session_token'] = uuid.uuid4().hex
        write_json(directory / 'session.json', state)
    identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    run = directory / 'requests' / identifier
    mutating = action in ('save', 'modify', 'set-scalar', 'catalog-modify')
    state.update(active_request=identifier, active_action=action, active_mutating=mutating,
                 request_owner=process_identity(os.getpid()), state='running')
    write_json(directory / 'session.json', state)

    def record_client(pid):
        """客户端启动后立即保存进程身份，供服务中断后的状态查询使用。"""
        state['client_process'] = process_identity(pid)
        write_json(directory / 'session.json', state)

    try:
        data = execute(state['star'], None, run, output, name, value, unit,
                       action=action, host=state['host'], port=state['port'],
                       expected_session=state['current_file'] or '', timeout=timeout,
                       client_userdir=directory / 'client-settings', modification=modification,
                       catalog_plan=catalog_plan, catalog_request=catalog_request,
                       session_token=state['session_token'], legacy_plan=legacy_plan, snapshot_plan=snapshot_plan,
                       discovery_request=discovery_request,
                       expected_simulation_key=state.get('simulation_key', ''), on_client_start=record_client,
                       debug=state.get('debug', False))
        if not alive(state):
            raise RuntimeError('Server exited or changed identity during request')
        state['current_file'] = data['after']['session_path']
        state['modified'] = data['after']['modified']
    except BaseException as error:
        dispatched = 'client_process' in state
        if dispatched and client_running(state):
            write_json(directory / 'session.json', state)
            if isinstance(error, Exception):
                raise OperationBusy('Request client is still running; query session_status') from error
            raise
        uncertain = mutating and dispatched
        finish_request(directory, state, 'uncertain' if uncertain else 'error', uncertain=uncertain)
        if uncertain and isinstance(error, Exception):
            raise OperationUncertain(str(error)) from error
        raise
    finish_request(directory, state, data['status'], uncertain=data['status'] == 'uncertain')
    return data, run


def local_servers(star):
    """从同一安装、同一用户的本机进程查找监听端口，不扫描网络或其他用户。

    端口仅作为候选；连接后还要由宏核对实际算例路径、版本和 Simulation key。
    Linux /proc 不可见的进程无法自动接入，不能据此宣称发现了所有 GUI。
    """
    # 1. 只考虑安装内 STAR 原生程序；Java 客户端的辅助 HTTP 端口不作为候选。
    installation = Path(star).resolve().parents[1]
    listeners = {}
    for name in ('tcp', 'tcp6'):
        for line in Path('/proc/net', name).read_text().splitlines()[1:]:
            fields = line.split()
            if fields[3] == '0A':
                listeners[fields[9]] = int(fields[1].rsplit(':', 1)[1], 16)
    found = {}
    for process in Path('/proc').glob('[0-9]*'):
        try:
            if process.stat().st_uid != os.getuid():
                continue
            executable = (process / 'exe').resolve(strict=True)
            # 已安装启动器的 _get_starccm_server_binary 使用 star-ccm+；
            # 排除 Python 启动器、插件服务和 MPI 辅助程序的监听端口。
            if not executable.is_relative_to(installation) or executable.name != 'star-ccm+':
                continue
            identity = process_identity(int(process.name))
            if identity is None:
                continue
            for fd in (process / 'fd').iterdir():
                link = os.readlink(fd)
                if link.startswith('socket:[') and link[8:-1] in listeners:
                    port = listeners[link[8:-1]]
                    found[(identity['pid'], port)] = {'process': identity, 'port': port}
        except (OSError, ValueError):
            # 进程可能在枚举期间退出；后续连接前还会再次检查身份。
            continue
    return list(found.values())


def connect(args, directory):
    """串行处理连接与复用，避免三端同时为同一 STAR 建立互不共享锁的会话。"""
    directory.parent.mkdir(parents=True, exist_ok=True)
    with locked(directory.parent):
        prune_sessions()
        return start(args, directory)


def prune_sessions():
    """连接时清理超过 30 天的已结束运行数据，保留未确认请求与所有算例文件。

    只处理新版服务生成的目录；运行中的会话、旧手工目录和需要恢复的记录不删除。
    不启动常驻清理服务，也不触碰项目目录中的报告和导出。
    """
    cutoff = time.time() - 30 * 86400
    idle = True
    for record in (runtime_root() / 'sessions').glob('*/session.json'):
        try:
            directory = record.parent
            with locked(directory):
                state = json.loads(record.read_text())
                if (state.get('state') not in ('stopped', 'disconnected')
                        or state.get('active_request') or state.get('recovery_required')):
                    idle = False
                    continue
                if (state.get('schema_version') != 2 or state.get('session_id') != directory.name
                        or directory.is_symlink() or record.stat().st_mtime >= cutoff
                        or any(directory.rglob('*.sim*'))):
                    continue
                shutil.rmtree(directory)
        except (OSError, ValueError, ModificationRejected):
            # 清理失败不阻碍连接；并发占用或损坏记录留给使用者处理。
            idle = False
            continue
    # 只有登记会话均已结束时才删缓存，避免计划文件正被其他客户端加载。
    # 保留目录，重建缓存的写入方始终使用原子替换；不删除未知扩展名的文件。
    if idle:
        from starbridge.bridge.runner.java_runtime import prune_runtime_cache
        prune_runtime_cache(cutoff)
        for path in (runtime_root() / 'cache').rglob('*.json'):
            try:
                if 'java' in path.relative_to(runtime_root() / 'cache').parts:
                    continue
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue


def compact_request(state, run, action):
    """成功请求只保留简短操作记录；失败或调试请求留下完整诊断文件。"""
    if state.get('debug') or state.get('state') != 'ready' or state.get('active_request'):
        return
    try:
        write_json(run / 'operation.json', {
            'action': action, 'status': state.get('last_request_status'),
            'current_file': state.get('current_file'), 'modified': state.get('modified')})
        for path in run.iterdir():
            if path.name != 'operation.json':
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
    except OSError:
        # 清理不是算例操作的一部分；清理失败不能把已确认的修改变成 uncertain。
        return


def start(args, directory):
    """优先核对已有服务器，只有无匹配会话时才直接加载原算例启动服务。"""
    source = args.input.resolve(strict=True) if args.input is not None else None
    if source is not None and not source.is_file():
        raise ValueError('Input must be a file')
    star = shutil.which(args.star)
    if star is None:
        raise ValueError(f'STAR executable not found: {args.star}')
    directory.mkdir(parents=True, exist_ok=False)
    with locked(directory):
        # 1. 项目位置在连接时固定；另存为不会悄悄迁移项目产物目录。
        state = {'schema_version': 2, 'session_id': directory.name,
                 'state': 'starting', 'host': 'localhost', 'star': star,
                 'input': str(source) if source is not None else None,
                 'current_file': str(source) if source is not None else None,
                 'modified': None, 'active_request': None,
                 'project_dir': str(getattr(args, 'project_dir', None) or source.parent),
                 'debug': getattr(args, 'debug', False),
                 'session_token': uuid.uuid4().hex, 'catalog_target': args.snapshot_plan['target']}
        matches = []
        for candidate in local_servers(star):
            if args.port is not None and candidate['port'] != args.port:
                continue
            probe_state = dict(state, ownership='external', **candidate)
            # 先用最小只读请求识别当前加载文件，不生成全范围 Inspector 快照。
            probe = directory / 'probes' / uuid.uuid4().hex
            try:
                data = execute(star, None, probe, action='session-info', host='localhost',
                               port=candidate['port'], timeout=min(args.timeout, 15),
                               client_userdir=directory / 'client-settings',
                               snapshot_plan=args.snapshot_plan, session_token=state['session_token'], debug=state['debug'])
            except RuntimeError:
                continue
            info = data['after']
            if (data['status'] == 'ok' and alive(probe_state) and (source is None or
                    (info.get('session_path') and Path(info['session_path']).resolve() == source))):
                matches.append(dict(probe_state, simulation_key=info['simulation_key'],
                                    current_file=info.get('session_path') or None,
                                    modified=info['modified'], state='ready'))
        if len(matches) > 1:
            state['state'] = 'failed'
            write_json(directory / 'session.json', state)
            raise ValueError('Multiple STAR sessions match input; specify port to select one')
        if matches:
            state = matches[0]
            # 已登记的连接继续沿用其锁、引用世代和进程所有权；不能将自有服务误记为外部。
            for record in directory.parent.glob('*/session.json'):
                try:
                    existing = json.loads(record.read_text())
                except (OSError, ValueError):
                    continue
                if (existing.get('port') == state['port'] and alive(existing)
                        and existing.get('simulation_key') == state['simulation_key']
                        and existing.get('server_process', existing.get('process')) == state['process']):
                    if existing.get('recovery_required'):
                        # 重连沿用未确认记录，允许只读核对，不能用新 ID 绕过写入限制。
                        with locked(record.parent):
                            existing = json.loads(record.read_text())
                            refresh_request(record.parent, existing)
                            existing['state'] = ('running' if existing.get('active_request') else
                                                 'uncertain' if existing.get('uncertain_request') else 'ready')
                            write_json(record, existing)
                        shutil.rmtree(directory)
                        return existing
                    if existing.get('state') not in ('stopped', 'disconnected', 'failed'):
                        shutil.rmtree(directory)
                        return existing
            write_json(directory / 'session.json', state)
            if not state.get('debug'):
                shutil.rmtree(directory / 'probes', ignore_errors=True)
            return state
        if source is None:
            state['state'] = 'failed'
            write_json(directory / 'session.json', state)
            raise ValueError('No accessible STAR session at the specified port')
        # 2. 端口冲突提前失败，服务还会使用 portrange=1 禁止自动换到其他端口。
        with socket.socket() as probe:
            probe.bind(('0.0.0.0', args.port or 0))
            port = probe.getsockname()[1]
        command = [star, '-server', '-np', '1', '-noretry', '-loc', '-port', str(port),
                   '-portrange', '1', '-load', str(source)]
        write_json(directory / 'server-command.json', command)
        environment = os.environ.copy()
        environment.update(LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8')
        state.update(ownership='owned', port=port)
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
                if re.search(r'Server::start -host \S+:' + str(port) + r'\b', log):
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
            data, run = request(directory, state, 'session-info', max(1, deadline - time.monotonic()),
                                snapshot_plan=args.snapshot_plan)
            if data['status'] != 'ok':
                raise ModificationRejected(f'Initial inspection rejected: {data.get("error")}; see {run}')
            state['initial_request'] = run.name
            state['simulation_key'] = data['after']['simulation_key']
            write_json(directory / 'session.json', state)
            compact_request(state, run, 'session-info')
        except BaseException:
            terminate_owned(state)
            process.wait(timeout=10)
            state['state'] = 'failed'
            write_json(directory / 'session.json', state)
            raise
    return state


def operate(args, directory):
    """对已有连接执行命令；外部会话断开只更新本地记录，不结束 STAR 进程。"""
    if args.action == 'status':
        try:
            with locked(directory):
                state = json.loads((directory / 'session.json').read_text())
                refresh_request(directory, state)
                return dict(state, server_alive=alive(state))
        except OperationBusy:
            state = json.loads((directory / 'session.json').read_text())
            return dict(state, state='running', server_alive=alive(state))
    with locked(directory):
        state = json.loads((directory / 'session.json').read_text())
        refresh_request(directory, state)
        if state['state'] in ('stopped', 'disconnected', 'failed'):
            raise ValueError('Session is closed; open a new connection')
        if args.action == 'stop' and state.get('ownership') == 'external':
            state['recovery_required'] = state['state'] != 'ready' or bool(state.get('active_request'))
            state['state'] = 'disconnected'
            write_json(directory / 'session.json', state)
            return state
        # 启动器异常退出时，显式放弃仍可清理身份匹配的遗留 MPI 进程。
        if not alive(state) and not (args.action == 'stop' and args.discard):
            raise RuntimeError('Managed server is not running')
        if state.get('active_request'):
            raise OperationBusy('Request is still running; query session_status')
        if (state.get('uncertain_request') and args.action in ('save', 'modify', 'set-scalar', 'stop')
                and not (args.action == 'stop' and args.discard)):
            raise OperationUncertain('Write outcome is unconfirmed; status and read-only requests remain available')
        # 持锁后从会话绑定选择版本。所有本地计划校验都在请求活动标记与 uncertain
        # 捕获块之前完成，版本错配只拒绝本次输入，不污染可继续使用的会话。
        if not (args.action == 'stop' and args.discard):
            target = session_target(state)
            catalog_plan = getattr(args, 'catalog_plan', None)
            check_plan_targets(catalog_plan, target=target)
            if args.action == 'set-scalar' or (args.action == 'modify' and catalog_plan is None):
                args.legacy_plan = prepare_legacy(getattr(args, 'modification', None), target=target)
            if (args.action in ('inspect', 'save', 'set-scalar', 'stop')
                    or (args.action == 'modify' and (catalog_plan is None or getattr(args, 'audit', False)))):
                args.snapshot_plan = prepare_snapshot(target)
            check_plan_targets(catalog_plan, getattr(args, 'legacy_plan', None),
                               getattr(args, 'snapshot_plan', None), target=target)
        if args.action == 'stop':
            # 先读取 STAR 的修改标志；本机另存后仍可能为真，不擅自清除此标志。
            # 失败或仍有修改时，只有显式 discard 才允许放弃剩余内存状态。
            if not args.discard:
                data, run = request(directory, state, 'inspect', args.timeout,
                                    snapshot_plan=args.snapshot_plan)
                if data['status'] != 'ok':
                    raise ModificationRejected(f'Close inspection rejected: {data.get("error")}; see {run}')
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
            # GUI 可能在连接后另存为；先读取同一对象的当前路径，再决定显式保存的目标。
            data, info_run = request(directory, state, 'session-info', args.timeout,
                                     snapshot_plan=args.snapshot_plan)
            if data['status'] != 'ok':
                raise ModificationRejected(f'Save identity check rejected: {data.get("error")}')
            compact_request(state, info_run, 'session-info')
            destination = getattr(args, 'output', None) or state.get('current_file')
            if not destination:
                raise ValueError('This simulation has no save path; specify output')
            output = Path(destination).resolve()
            current = Path(state['current_file']).resolve() if state.get('current_file') else None
            if (not output.parent.is_dir() or (output != current and
                    (output.exists() or output.suffix != '.sim'))):
                raise ValueError('Save-as requires a new .sim file with an existing parent directory')
        try:
            catalog_call = getattr(args, 'catalog_plan', None) is not None
            action = 'catalog-' + args.action if catalog_call else args.action
            data, run = request(directory, state, action, args.timeout, output=output,
                                name=getattr(args, 'name', ''), value=getattr(args, 'value', 0.0),
                                unit=getattr(args, 'unit', ''), modification=getattr(args, 'modification', None),
                                catalog_plan=getattr(args, 'catalog_plan', None),
                                catalog_request=getattr(args, 'catalog_request', None),
                                legacy_plan=getattr(args, 'legacy_plan', None),
                                snapshot_plan=getattr(args, 'snapshot_plan', None),
                                discovery_request=getattr(args, 'discovery_request', None))
            if data['status'] == 'rejected':
                raise ModificationRejected(f'{data["error"]}; see {run / "result.json"}')
            if data['status'] == 'uncertain':
                raise OperationUncertain(f'{data.get("error", "Write verification failed")}; see {run / "result.json"}')
            if args.action == 'modify' and not catalog_call:
                verify_modification(args.modification, data['before'], data['after'])
            if args.action == 'modify' and catalog_call:
                # 目录回读已由 Java 验证；此处仍要求完整结果，避免成功封套掩盖缺失字段。
                catalog_content(data['catalog_before'], args.catalog_plan)
                catalog_content(data['catalog'], args.catalog_plan)
            legacy_plan = getattr(args, 'legacy_plan', None)
            if legacy_plan is not None:
                catalog_content(data['catalog_before'], legacy_plan)
                catalog_content(data['catalog'], legacy_plan)
            if args.action == 'set-scalar':
                target = next(p for p in data['after']['parameters'] if p['name'] == args.name)
                actual = target.get('raw_value')
                if (target.get('unit') != args.unit or not isinstance(actual, (int, float))
                        or not math.isclose(actual, args.value, rel_tol=1e-12, abs_tol=1e-12)):
                    raise RuntimeError('Readback does not match requested scalar value/unit')
            if output:
                if not output.is_file() or Path(data['after']['session_path']).resolve() != output:
                    raise RuntimeError('Saved file/path was not confirmed')
            result = {'session_id': state.get('session_id', str(directory))}
            if state.get('uncertain_request'):
                result['uncertain_request'] = state['uncertain_request']
            if state.get('debug'):
                result['request_result'] = str(run / 'result.json')
            if output:
                result['output'] = str(output)
            if args.action == 'discovery':
                result['discovery'] = data['discovery']
            elif catalog_call:
                # 目录结果独立封装；最小会话元数据不能冒充旧 Inspector 的完整快照。
                result['catalog'] = data['catalog']
            else:
                result['snapshot'] = data['after']
            if legacy_plan is not None:
                # 旧结果字段继续保留；目录结果补充说明统一修改器实际核对的内容。
                result.update(catalog_before=data['catalog_before'], catalog=data['catalog'],
                              catalog_diff=catalog_diff(data['catalog_before'], data['catalog'], legacy_plan))
            if args.action == 'modify':
                result['modification'] = args.catalog_request if catalog_call else args.modification
                if not catalog_call or data.get('snapshot_audit'):
                    result.update(snapshot=data['after'], snapshot_diff=snapshot_diff(data['before'], data['after']))
                if 'setter_attempts' in data:
                    result['setter_attempts'] = data['setter_attempts']
                if catalog_call:
                    result['catalog_before'] = data['catalog_before']
                    if data.get('snapshot_audit'):
                        result['catalog_diff'] = catalog_diff(data['catalog_before'], data['catalog'], args.catalog_plan)
            compact_request(state, run, action)
            return result
        except ModificationRejected:
            # 宏已确认写入前拒绝，request 已清除活动标记；不把拒绝变成未知写入结果。
            raise
        except (OperationUncertain, OperationBusy):
            raise
        except BaseException as error:
            # 请求执行器已经区分传输失败；这里只处理成功返回后发现的写入回读或保存核对失败。
            if args.action in ('save', 'modify', 'set-scalar') and state.get('last_request_status') == 'ok':
                finish_request(directory, state, 'uncertain', uncertain=True)
                if isinstance(error, Exception):
                    raise OperationUncertain(str(error)) from error
            raise


def main():
    """提供显式生命周期命令；每次调用结束不会自动关闭后台会话。"""
    if not sys.platform.startswith('linux'):
        raise RuntimeError('Session prototype currently supports Linux only')
    parser = argparse.ArgumentParser(description='Manage a persistent local STAR simulation server.')
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ['start', 'status', 'inspect', 'describe', 'read', 'set-scalar', 'modify', 'save', 'stop']:
        command = commands.add_parser(action)
        if action != 'start':
            command.add_argument('--session-id', required=True)
        if action != 'status':
            command.add_argument('--timeout', type=float, default=180)
        if action == 'start':
            command.add_argument('input', type=Path)
            command.add_argument('--star', default='starccm+')
            command.add_argument('--catalog-release', help='Expected release; detected from the selected executable when omitted')
            command.add_argument('--port', type=int)
            command.add_argument('--project-dir', type=Path)
            command.add_argument('--debug', action='store_true')
        elif action == 'set-scalar':
            command.add_argument('--name', required=True)
            command.add_argument('--value', type=float, required=True)
            command.add_argument('--unit', required=True)
        elif action == 'save':
            command.add_argument('--output', type=Path)
        elif action == 'modify':
            command.add_argument('--request', type=Path, required=True)
            command.add_argument('--audit', action='store_true')
            command.add_argument('--catalog', type=Path)
            command.add_argument('--execution', type=Path)
        elif action in ('describe', 'read'):
            command.add_argument('--catalog', type=Path, required=True)
            command.add_argument('--execution', type=Path, required=True)
            command.add_argument('--request', type=Path, required=True)
        elif action == 'stop':
            command.add_argument('--discard', action='store_true')
    args = parser.parse_args()
    if args.action != 'status' and (not math.isfinite(args.timeout) or args.timeout <= 0):
        parser.error('--timeout must be positive and finite')
    if args.action == 'start' and args.port is not None and not 1024 <= args.port <= 65535:
        parser.error('--port must be between 1024 and 65535')
    if args.action == 'set-scalar' and not math.isfinite(args.value):
        parser.error('--value must be finite')
    if args.action == 'modify':
        # 请求格式在写入活动标记前完成校验，格式错误不影响已有会话。
        if args.catalog is not None or args.execution is not None:
            if args.catalog is None or args.execution is None:
                parser.error('Catalog modify requires both --catalog and --execution')
            args.catalog_plan, args.catalog_request = prepare_catalog_modification(
                args.catalog, args.execution, args.request)
        else:
            args.modification = load_request(args.request)
    elif args.action in ('describe', 'read'):
        # 目录、成员指纹与请求校验在获取会话活动标记之前完成；无效输入不会污染会话。
        args.catalog_plan, args.catalog_request = prepare_catalog_read(
            args.catalog, args.execution, args.request, args.action)
    # 新会话显式绑定；既有会话在持锁后使用保存的目标，不依赖新的 CLI 默认值。
    # status 与显式 discard 不加载目录，以便目录损坏时仍能查询或清理本次服务。
    if args.action == 'start':
        # 细分 CLI 与共享入口采用同一安装探测和目录分配，不再各自选择默认版本。
        from starbridge.core.service import Service
        result = Service().open_session(str(args.input.resolve()), star=args.star,
            release=args.catalog_release, port=args.port, timeout=args.timeout,
            project_dir=str(args.project_dir.resolve()) if args.project_dir else None,
            debug=args.debug)
    else:
        result = operate(args, session_directory(args.session_id))
        if args.action in ('status', 'stop'):
            result = public_session(result)
    # 部分对象读取失败不意味着会话身份不确定；保留可用快照，并显式提示缺失内容。
    if not result.get('snapshot', {}).get('inspection_complete', True):
        print('StarBridge warning: Inspection is incomplete; check snapshot read_errors.',
              file=sys.stderr)
    if not result.get('catalog', {}).get('inspection_complete', True):
        print('StarBridge warning: Catalog inspection is incomplete; check property errors.',
              file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cli():
    """为脚本与安装命令提供相同退出码和 stderr 错误提示。"""
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, StopIteration) as error:
        print(f'StarBridge error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(cli())
