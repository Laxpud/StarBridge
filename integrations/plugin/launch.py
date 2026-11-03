"""从插件自带源码启动 MCP，并在用户目录复用锁定的 Python 依赖环境。"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> None:
    """定位插件根目录，选择独立依赖环境，再将进程交给 uv 和 MCP。"""
    parser = argparse.ArgumentParser(description="Prepare or start the bundled StarBridge MCP server.")
    parser.add_argument("--prepare", action="store_true", help="prepare dependencies without starting MCP")
    args = parser.parse_args()
    # 1. 根目录来自脚本位置，不依赖宿主工作目录，也不从 PyPI 下载另一版程序。
    root = Path(__file__).resolve().parents[2]
    uv = shutil.which('uv')
    if uv is None:
        raise SystemExit('StarBridge requires uv on PATH. Install uv and restart the client.')
    # 2. 同一锁文件共享依赖环境；程序始终从当前插件 src 加载，升级无需复制 Skill。
    digest = hashlib.sha256((root / 'uv.lock').read_bytes()).hexdigest()[:16]
    data = Path(os.environ.get('STARBRIDGE_PLUGIN_DATA', str(Path.home() / '.starbridge')))
    environment = data / 'runtimes' / ('plugin-' + digest)
    env = dict(os.environ)
    env['UV_PROJECT_ENVIRONMENT'] = str(environment.resolve())
    env['PYTHONPATH'] = str(root / 'src')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    # uv 不读取 MCP stdin；准备信息走 stderr，stdout 仅用于协议，不在插件目录创建 .venv。
    command = [uv, 'sync', '--project', str(root), '--frozen', '--no-dev',
               '--extra', 'mcp', '--no-install-project']
    subprocess.run(command, env=env, check=True, stdin=subprocess.DEVNULL, stdout=sys.stderr)
    if args.prepare:
        return
    # 禁止将宿主 cwd 加入导入路径，避免仓库根的 starbridge.py 遮蔽真正的软件包。
    python = str(environment.resolve() / 'bin' / 'python')
    os.execve(python, [python, '-P', '-m', 'starbridge.mcp'], env)


if __name__ == '__main__':
    main()
