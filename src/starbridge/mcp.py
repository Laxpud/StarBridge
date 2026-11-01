"""提供无需导入可选 SDK 即可查看帮助与版本的 MCP 启动入口。"""

import argparse
import sys

from . import __version__


def main():
    """先解析启动参数，再加载可选协议依赖；只有显式工具调用才操作算例。"""
    parser = argparse.ArgumentParser(description='Run the StarBridge MCP server over stdio.')
    parser.add_argument('--version', action='version', version=f'StarBridge {__version__}')
    parser.parse_args()
    try:
        from .interfaces.mcp_server import server
    except ModuleNotFoundError as error:
        # 仅将明确缺少的接口依赖转换成安装提示，内部模块错误保留原异常供定位。
        if error.name not in {'mcp', 'jsonschema', 'pydantic'}:
            raise
        print(f'StarBridge MCP dependencies are missing. Install starbridge-cfd[mcp]=={__version__}.',
              file=sys.stderr)
        return 1
    server.run(transport='stdio')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
