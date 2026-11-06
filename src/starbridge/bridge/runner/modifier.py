"""提供执行拒绝类型、JSON 到 Java 字面量转换及快照差异。"""

import json
import math


class ModificationRejected(RuntimeError):
    """宏确认尚未写入便拒绝请求；后台会话可以继续处理下一条请求。"""


def java_literal(value):
    """将已解析 JSON 转成显式 Java 容器字面量；字符串转义后才进入宏源码。"""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, int):
        if not -(2 ** 63) <= value < 2 ** 63:
            raise ValueError('Request integers must fit in a signed 64-bit value')
        return 'Long.valueOf(' + json.dumps(str(value)) + ')'
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Request numbers must be finite')
        return 'Double.valueOf(' + json.dumps(str(value)) + ')'
    if isinstance(value, list):
        # 显式 Object[] 防止单个 null 被 Java 解释为整个 varargs 数组，确保 [null] 仍是一项列表。
        return 'java.util.Arrays.asList(new Object[]{' + ','.join(java_literal(v) for v in value) + '})'
    if isinstance(value, dict):
        pairs = [java_literal(item) for pair in value.items() for item in pair]
        return 'fields(' + ','.join(pairs) + ')'
    raise ValueError(f'Unsupported request value type: {type(value).__name__}')


def same_value(left, right):
    """按 JSON 类型比较状态；数值允许 1 与 1.0 相等，布尔值不能冒充数值。"""
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same_value(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same_value(a, b) for a, b in zip(left, right))
    return left == right


def content_snapshot(snapshot):
    """比较对象内容时排除加载名称、文件路径和 STAR 的 modified 标志。"""
    return {k: v for k, v in snapshot.items()
            if k not in ('simulation_name', 'session_path', 'modified')}


def snapshot_diff(before, after):
    """记录已覆盖字段的差异；path 为 JSON Pointer，标量数组作为整体记录。"""
    changes = []

    def visit(left, right, path):
        if same_value(left, right):
            return
        if isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys():
            for key in sorted(left):
                token = key.replace('~', '~0').replace('/', '~1')
                visit(left[key], right[key], path + '/' + token)
        elif (isinstance(left, list) and isinstance(right, list) and len(left) == len(right)
              and all(isinstance(v, dict) for v in left + right)):
            for index, (a, b) in enumerate(zip(left, right)):
                visit(a, b, path + '/' + str(index))
        else:
            changes.append({'path': path, 'before': left, 'after': right})

    visit(content_snapshot(before), content_snapshot(after), '')
    return changes
