#!/usr/bin/env python3
"""保留仓库路径形式的 MCP 启动方式，转发到安装版共用的入口。"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starbridge.mcp import main

if __name__ == '__main__':
    raise SystemExit(main())
