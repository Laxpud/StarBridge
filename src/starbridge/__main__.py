"""支持通过 python -m starbridge 调用与安装命令相同的 JSON CLI。"""

from .cli import main

if __name__ == '__main__':
    raise SystemExit(main())
