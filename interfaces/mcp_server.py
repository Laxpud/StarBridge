#!/usr/bin/env python3
"""通过官方 Python SDK 提供本机 stdio MCP，所有业务调用交给共享 Core。

stdout 仅用于 MCP 消息；STAR 的输出由原执行器写入请求日志。工具是同步函数，
SDK 在线程中执行，避免长时间 STAR 调用阻塞协议循环；同一会话仍由文件锁互斥。
"""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp import types
from mcp.server import MCPServer
from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr
from jsonschema import Draft202012Validator

from core.service import Service, contract


def tool_result(result):
    """所有 Core 与输入校验结果使用相同封套，兼容只支持文本结果的客户端。"""
    return types.CallToolResult(
        content=[types.TextContent(text=json.dumps(result, ensure_ascii=False, allow_nan=False))],
        structured_content=result, is_error=result['status'] != 'ok')


async def validate_arguments(context, call_next):
    """先按公开 JSON Schema 检查原始参数，防止 SDK 丢弃未知字段或将字符串隐式转成对象。"""
    if context.method == 'tools/call' and isinstance(context.params, dict):
        params = context.params
        for tool in await server.list_tools():
            if tool.name == params.get('name'):
                schema = {**tool.input_schema, 'additionalProperties': False}
                error = next(Draft202012Validator(schema).iter_errors(params.get('arguments', {})), None)
                if error is not None:
                    return tool_result({'status': 'rejected', 'error': {
                        'type': 'ArgumentValidationError', 'message': error.message}})
                break
    result = await call_next(context)
    if context.method == 'tools/list' and isinstance(result, types.ListToolsResult):
        # 发布的 schema 与执行前检查一致；只收紧工具顶层，业务对象仍由 Core 验证。
        for tool in result.tools:
            tool.input_schema['additionalProperties'] = False
    elif context.method == 'tools/list' and isinstance(result, dict):
        # SDK 的协商版本也可能在中间件返回前已转成协议字典。
        for tool in result.get('tools', []):
            tool['inputSchema']['additionalProperties'] = False
    return result


server = MCPServer(
    'StarBridge', version='0.1.0',
    middleware=[validate_arguments],
    instructions=(
        'Use exact release capabilities, then browse_tree/describe_node/read_node_properties '
        'or search_settings to discover settings before modifying. '
        'A write implementation flag does not prove current writability. '
        'Every modification requires the observed expected state. '
        'Save and close are explicit. Client exit does not close STAR. '
        'Never automatically retry uncertain writes; inspect session status and request logs. '
        'Use absolute paths. This server exposes local managed sessions, not GUI sessions.'),
)
service = Service()
READ = types.ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
WRITE = types.ToolAnnotations(read_only_hint=False, destructive_hint=True,
                              idempotent_hint=False, open_world_hint=False)


def call(method, arguments):
    """将 Core 状态同时放入结构化和文本结果，失败时设置 MCP 的 isError。"""
    result = service.call(method, arguments)
    return tool_result(result)


@server.tool(name='starbridge.get_capabilities', annotations=READ)
def get_capabilities(release: StrictStr) -> types.CallToolResult:
    """查询明确版本的目录类型、属性和操作能力；当前模型条件与实例状态需另行读取。"""
    return call('get_capabilities', locals())


@server.tool(name='starbridge.find_objects', annotations=READ)
def find_objects(session_dir: StrictStr, type_id: StrictStr, name: StrictStr | None = None,
                 parent: dict | None = None, offset: StrictInt = 0, limit: StrictInt = 100,
                 timeout: StrictFloat = 180) -> types.CallToolResult:
    """枚举目录类型，可用精确名称过滤；子对象要求完整 parent，分页通过 next_offset 继续。"""
    return call('find_objects', locals())


@server.tool(name='starbridge.describe_object', annotations=READ)
def describe_object(session_dir: StrictStr, target: dict, properties: list[StrictStr] | None = None,
                    timeout: StrictFloat = 180) -> types.CallToolResult:
    """描述 target 的已映射属性、结构操作和当前已声明条件；writable 仅表示写入实现。"""
    return call('describe_object', locals())


@server.tool(name='starbridge.read_properties', annotations=READ)
def read_properties(session_dir: StrictStr, target: dict, properties: list[StrictStr] | None = None,
                    timeout: StrictFloat = 180) -> types.CallToolResult:
    """读取指定属性或该类型全部已映射属性；核对 inspection_complete 和逐属性错误。"""
    return call('read_properties', locals())


@server.tool(name='starbridge.modify', annotations=WRITE)
def modify(session_dir: StrictStr, request: dict, timeout: StrictFloat = 180) -> types.CallToolResult:
    """提交带 expected 的 schema 2 属性修改或 schema 3 结构操作；不自动保存或重试。"""
    return call('modify', locals())


@server.tool(name='starbridge.inspect_session', annotations=READ)
def inspect_session(session_dir: StrictStr, timeout: StrictFloat = 180) -> types.CallToolResult:
    """读取既有 Inspector 快照范围，包含参数、场函数、区域、边界、网格和工作流等清单。"""
    return call('inspect_session', locals())


@server.tool(name='starbridge.browse_tree', annotations=READ)
def browse_tree(session_dir: StrictStr, node_id: StrictStr | None = None,
                cursor: StrictStr | None = None, offset: StrictInt = 0, limit: StrictInt = 100,
                scope: StrictStr = 'simulation', max_nodes: StrictInt = 2000,
                timeout: StrictFloat = 180) -> types.CallToolResult:
    """浏览根或 node_id 的一层对象；保留分页、未知代理和未展开状态，不隐式扫描全树。"""
    return call('browse_tree', locals())


@server.tool(name='starbridge.describe_node', annotations=READ)
def describe_node(session_dir: StrictStr, node_id: StrictStr | None = None,
                  scope: StrictStr = 'simulation', timeout: StrictFloat = 180,
                  property_ids: list[StrictStr] | None = None, cursor: StrictStr | None = None,
                  limit: StrictInt = 100) -> types.CallToolResult:
    """描述实际 Bean 属性、来源和规则支持状态；返回 property_id，不执行未知 getter。"""
    return call('describe_node', locals())


@server.tool(name='starbridge.read_node_properties', annotations=READ)
def read_node_properties(session_dir: StrictStr, node_id: StrictStr, property_ids: list[StrictStr],
                         timeout: StrictFloat = 180) -> types.CallToolResult:
    """读取明确选择的发现属性；核对完整性及单项错误，引用会在执行前重新验证。"""
    return call('read_node_properties', locals())


@server.tool(name='starbridge.search_settings', annotations=READ)
def search_settings(session_dir: StrictStr, query: StrictStr, expand: StrictBool = False,
                    max_nodes: StrictInt = 100, max_depth: StrictInt = 4,
                    scope: StrictStr = 'simulation', timeout: StrictFloat = 180,
                    limit: StrictInt = 100, cursor: StrictStr | None = None) -> types.CallToolResult:
    """按名称、说明与中英文术语搜索；显式 expand 才扩展发现，空命中不表示全算例不存在。"""
    return call('search_settings', locals())


@server.tool(name='starbridge.relocate_node', annotations=READ)
def relocate_node(session_dir: StrictStr, locator: list[dict],
                  timeout: StrictFloat = 180) -> types.CallToolResult:
    """根据返回的结构化 locator 在当前加载中重新定位；同名歧义拒绝，不复用旧会话引用。"""
    return call('relocate_node', locals())


@server.tool(name='starbridge.modify_node_property', annotations=WRITE)
def modify_node_property(session_dir: StrictStr, node_id: StrictStr, property_id: StrictStr,
                         expected: dict | StrictStr | StrictBool | StrictInt | StrictFloat,
                         value: dict | StrictStr | StrictBool | StrictInt | StrictFloat,
                         timeout: StrictFloat = 180) -> types.CallToolResult:
    """提交观察到的 expected 与新值；只执行已接受规则的一次赋值，回读及 Diff 后显式保存。"""
    return call('modify_node_property', locals())


@server.tool(name='starbridge.open_session', annotations=WRITE)
def open_session(input: StrictStr, session_dir: StrictStr, star: StrictStr = 'starccm+',
                 release: StrictStr = '2602', port: StrictInt = 49001,
                 timeout: StrictFloat = 180) -> types.CallToolResult:
    """复制输入并启动独立后台会话；session_dir 必须不存在，star 可执行程序须匹配 release。"""
    return call('open_session', locals())


@server.tool(name='starbridge.session_status', annotations=READ)
def session_status(session_dir: StrictStr) -> types.CallToolResult:
    """读取会话记录并检查进程身份；不启动 Java 客户端，也不重新检查 STAR Build。"""
    return call('session_status', locals())


@server.tool(name='starbridge.save_session', annotations=WRITE)
def save_session(session_dir: StrictStr, output: StrictStr, timeout: StrictFloat = 180) -> types.CallToolResult:
    """将内存状态另存到尚不存在的 .sim 文件；不覆盖原文件，不自动关闭会话。"""
    return call('save_session', locals())


@server.tool(name='starbridge.close_session', annotations=WRITE)
def close_session(session_dir: StrictStr, discard: StrictBool = False,
                  timeout: StrictFloat = 180) -> types.CallToolResult:
    """关闭本工具管理的会话；有修改或结果不确定时，仅显式 discard=true 才允许放弃内存状态。"""
    return call('close_session', locals())


@server.resource('starbridge://contract', mime_type='application/json')
def service_contract() -> str:
    """读取状态、路径、请求版本和恢复约定；不访问算例。"""
    return json.dumps(contract(), ensure_ascii=False, allow_nan=False)


@server.resource('starbridge://catalog/{release}', mime_type='application/json')
def catalog_capabilities(release: str) -> str:
    """读取版本目录能力；与 get_capabilities 同源，目录损坏或未知版本会明确失败。"""
    return json.dumps(service.get_capabilities(release), ensure_ascii=False, allow_nan=False)


if __name__ == '__main__':
    server.run(transport='stdio')
