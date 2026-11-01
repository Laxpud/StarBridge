#!/usr/bin/env python3
"""保留原文件 Bridge 脚本参数与退出语义，执行逻辑统一由包内入口提供。"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from starbridge.bridge.runner.file_bridge import cli

if __name__ == '__main__':
    raise SystemExit(cli())
