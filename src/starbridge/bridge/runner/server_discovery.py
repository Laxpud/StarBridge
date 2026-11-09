"""只读发现当前可见的本机 STAR 原生进程及其 TCP 监听候选。

仅覆盖本用户可读的 /proc 和当前网络命名空间；权限、隐藏进程、缺失的
TCP 表及枚举竞态都可能造成遗漏，空列表也不证明没有服务器。
候选依据不证明 STAR 协议、版本或当前算例；这些仍须由调用者 probe 核对。
"""

from collections.abc import Callable
import os
from pathlib import Path


def _identity(pid: int, identity_reader: Callable) -> dict | None:
    """沿用调用方的进程身份定义，容忍退出或受限的 /proc 读取。"""
    try:
        return identity_reader(pid)
    except (OSError, ValueError, IndexError):
        return None


def _executable(process: Path) -> Path | None:
    """只承认同 UID 进程的实际原生程序，不相信 argv[0] 或进程名称。"""
    try:
        if process.stat().st_uid != os.getuid():
            return None
        executable = (process / 'exe').resolve(strict=True)
        return executable if executable.name == 'star-ccm+' else None
    except (OSError, RuntimeError):
        return None


def _socket_inodes(process: Path) -> set[str]:
    """逐个读取当前 fd；一个 fd 消失或不可读不丢弃其余 socket。"""
    inodes = set()
    try:
        with os.scandir(process / 'fd') as entries:
            for entry in entries:
                try:
                    link = os.readlink(entry.path)
                except OSError:
                    continue
                if link.startswith('socket:[') and link.endswith(']'):
                    inodes.add(link[8:-1])
    except OSError:
        # 目录本身不可见或枚举中途失败时，也只能保留已观察到的部分。
        pass
    return inodes


def _listening_ports(process: Path) -> set[int]:
    """取 TCP 表读取前后均由该进程 fd 持有、且表中为 LISTEN 的端口。"""
    owned = _socket_inodes(process)
    if not owned:
        return set()
    listeners = set()
    for name in ('tcp', 'tcp6'):
        try:
            with Path('/proc/net', name).open(encoding='ascii') as table:
                for line in table:
                    fields = line.split()
                    if len(fields) < 10 or fields[3] != '0A' or fields[9] not in owned:
                        continue
                    try:
                        port = int(fields[1].rsplit(':', 1)[1], 16)
                    except (ValueError, IndexError):
                        continue
                    if 1 <= port <= 65535:
                        listeners.add((fields[9], port))
        except OSError:
            # 某一地址族不可读时仍可使用另一族，不能据此声称覆盖全部监听。
            continue
    still_owned = _socket_inodes(process)
    return {port for inode, port in listeners if inode in still_owned}


def _declaration(process: Path) -> dict:
    """只解析端口声明；不解析 encoded-session，更不按其中的路径筛掉进程。"""
    evidence = {'port': None, 'portrange': None, 'status': 'unreadable'}
    try:
        command = (process / 'cmdline').read_bytes()
    except OSError:
        return evidence
    if not command or not command.endswith(b'\0'):
        return evidence
    arguments = command.split(b'\0')[1:-1]
    counts = {}
    for flag, key in ((b'-port', 'port'), (b'-portrange', 'portrange')):
        # 重复声明（包括无效值或等号形式）不能按“最后一个生效”猜测。
        positions = [index for index, arg in enumerate(arguments)
                     if arg == flag or arg.startswith(flag + b'=')]
        counts[key] = len(positions)
        if len(positions) != 1:
            continue
        index = positions[0]
        if arguments[index] != flag or index + 1 >= len(arguments):
            continue
        value = arguments[index + 1]
        if not value.isdigit():
            continue
        try:
            number = int(value)
        except ValueError:
            continue
        if 1 <= number <= 65535:
            evidence[key] = number
    evidence['occurrences'] = counts
    if any(count > 1 for count in counts.values()):
        evidence['status'] = 'ambiguous'
    elif any(count == 0 for count in counts.values()):
        evidence['status'] = 'missing'
    elif evidence['port'] is None or evidence['portrange'] is None:
        evidence['status'] = 'invalid'
    elif evidence['portrange'] != 1:
        evidence['status'] = 'non_single_range'
    else:
        evidence['status'] = 'single_port'
    return evidence


def discover(star, requested_port: int | None, identity_reader: Callable) -> list[dict]:
    """查找所选启动器安装内、同 UID 的原生进程及其真实监听。

    star 与原 local_servers 一样是已选启动器路径；identity_reader 使用现有
    process_identity(pid)。每项保留 process、port，另含 executable（供后续
    复核）、port_declaration（数值、出现次数及状态）和以下 port_basis：
    declared_port 表示唯一有效的 -port P、-portrange 1 与实际监听吻合；
    requested_port 表示调用者显式选中了真实监听，优先于声明筛选；
    undetermined 表示声明不足以筛选，保留所有已观察到的监听候选。

    读取前后核对身份、UID 和实际程序；结果仍非原子快照，probe 前后应调用
    endpoint_alive。不可见范围可能遗漏，不能把返回列表当作完整服务清单。
    """
    if requested_port is not None and (type(requested_port) is not int
                                       or not 1 <= requested_port <= 65535):
        raise ValueError('requested_port must be an integer from 1 to 65535, or None')
    installation = Path(star).resolve().parents[1]
    found = []
    try:
        with os.scandir('/proc') as entries:
            for entry in entries:
                if not entry.name.isdecimal():
                    continue
                pid = int(entry.name)
                process = Path(entry.path)
                identity = _identity(pid, identity_reader)
                if identity is None:
                    continue
                executable = _executable(process)
                if executable is None or not executable.is_relative_to(installation):
                    continue
                declaration = _declaration(process)
                ports = _listening_ports(process)
                if (_executable(process) != executable
                        or _identity(pid, identity_reader) != identity):
                    continue
                if declaration['status'] == 'single_port':
                    declaration['status'] = ('listening' if declaration['port'] in ports
                                             else 'not_listening')
                if requested_port is not None:
                    ports &= {requested_port}
                    basis = 'requested_port'
                elif declaration['status'] == 'listening':
                    ports = {declaration['port']}
                    basis = 'declared_port'
                else:
                    basis = 'undetermined'
                for port in sorted(ports):
                    found.append({'process': identity, 'port': port, 'port_basis': basis,
                                  'port_declaration': declaration,
                                  'executable': str(executable)})
    except OSError:
        # /proc 本身不可枚举时同样只能返回目前已经确认的候选。
        pass
    return sorted(found, key=lambda item: (item['process']['pid'], item['port']))


def endpoint_alive(candidate: dict, identity_reader: Callable) -> bool:
    """复核 discover 返回项的身份、UID、实际程序和当前 fd 所属 TCP 监听。

    不重新套用默认声明筛选，显式选中的辅助监听也可以存活。不可读或已变化
    时返回 False；True 仅是本次观察，不证明协议，也不保证下次操作时仍存活。
    """
    identity = candidate.get('process')
    port = candidate.get('port')
    executable = candidate.get('executable')
    if (not isinstance(identity, dict) or type(identity.get('pid')) is not int
            or identity['pid'] <= 0 or type(port) is not int or not 1 <= port <= 65535
            or not isinstance(executable, str)):
        return False
    pid = identity['pid']
    process = Path('/proc') / str(pid)
    if _identity(pid, identity_reader) != identity:
        return False
    expected = Path(executable)
    if _executable(process) != expected:
        return False
    ports = _listening_ports(process)
    return (port in ports and _executable(process) == expected
            and _identity(pid, identity_reader) == identity)
