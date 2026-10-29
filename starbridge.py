#!/usr/bin/env python3
"""通过 JSON 参数调用与 MCP 同源的 Core API；已有细分 CLI 继续保留。"""

import argparse
import json
from pathlib import Path
import sys

from core.catalog import read_json
from core.service import METHODS, Service, contract


def main():
    """从一个请求文件读取参数，输出状态封套；异常也只形成一个 JSON 结果。"""
    parser = argparse.ArgumentParser(description='Call the shared StarBridge service with JSON arguments.')
    parser.add_argument('method', choices=(*METHODS, 'contract'))
    parser.add_argument('--arguments', type=Path, help='JSON object containing method arguments')
    args = parser.parse_args()
    if args.method == 'contract':
        if args.arguments is not None:
            parser.error('contract does not accept arguments')
        result = {'status': 'ok', 'result': contract()}
    else:
        if args.arguments is None:
            parser.error('--arguments is required')
        try:
            result = Service().call(args.method, read_json(args.arguments))
        except (OSError, ValueError) as error:
            result = {'status': 'rejected', 'error': {'type': type(error).__name__, 'message': str(error)}}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
