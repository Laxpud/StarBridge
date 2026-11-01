#!/usr/bin/env python3
"""保留原离线目录命令路径，复用已安装发行包中的同一实现。"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from starbridge.tools.catalog.catalog import main

if __name__ == '__main__':
    raise SystemExit(main())
