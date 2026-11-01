#!/usr/bin/env python3
"""保留仓库内 JSON CLI 命令；源码与安装版使用同一 starbridge 包。"""

from pathlib import Path
import sys

# 只为源码脚本加入 src，包内模块不修改 sys.path，也不依赖调用者工作目录。
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from starbridge.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
