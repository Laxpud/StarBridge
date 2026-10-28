"""校验单项修改请求、定位快照对象，并核对回读值及已覆盖字段的差异。"""

import json
import math
from pathlib import Path


class ModificationRejected(RuntimeError):
    """宏确认尚未写入便拒绝请求；后台会话可以继续处理下一条请求。"""


COLLECTIONS = {
    'parameter': 'parameters',
    'field_function': 'field_functions',
    'region': 'regions',
    'boundary': 'boundaries',
}


def _unique_object(pairs):
    """拒绝重复 JSON 键，避免同一请求在不同解析器中表示不同操作。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate request key: {key}')
        result[key] = value
    return result


def _invalid_constant(value):
    """请求只能使用标准 JSON 数值，不能把 NaN 或 Infinity 当作预期状态。"""
    raise ValueError(f'Non-finite JSON number: {value}')


def load_request(path):
    """读取并校验完整请求；验证结束前不创建工作目录，也不启动 STAR。"""
    request = json.loads(Path(path).read_text(), object_pairs_hook=_unique_object,
                         parse_constant=_invalid_constant)
    if not isinstance(request, dict) or set(request) != {
            'schema_version', 'operation', 'target', 'expected', 'value'}:
        raise ValueError('Request requires schema_version, operation, target, expected and value')
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ValueError('Request schema_version must be 1')
    operation = request['operation']
    if operation not in ('set-definition', 'set-tags'):
        raise ValueError('Unsupported modification operation')
    target, expected = request['target'], request['expected']
    if (not isinstance(target, dict) or not isinstance(target.get('kind'), str)
            or target['kind'] not in COLLECTIONS):
        raise ValueError('Unsupported target kind')
    keys = {'kind', 'name', 'region'} if target['kind'] == 'boundary' else {'kind', 'name'}
    if set(target) != keys or any(not isinstance(target[k], str) or not target[k]
                                  for k in keys):
        raise ValueError('Target requires a non-empty name and, for boundaries, a region')
    if not isinstance(expected, dict) or not isinstance(expected.get('object_type'), str):
        raise ValueError('Expected state requires object_type from an Inspector snapshot')

    # 1. 明确每类修改必须核对的旧属性；其余 expected 字段也会逐项严格比较。
    if operation == 'set-definition':
        if target['kind'] == 'parameter':
            required = {'object_type', 'definition', 'unit'}
            object_type = 'ScalarGlobalParameter'
            value = request['value']
            if (not isinstance(value, dict) or set(value) != {'definition', 'unit'}
                    or not isinstance(value['definition'], str) or not value['definition'].strip()
                    or not isinstance(value['unit'], str)):
                raise ValueError('Scalar value requires a non-empty definition and a result unit')
        elif target['kind'] == 'field_function':
            required = {'object_type', 'definition', 'function_name', 'value_type', 'dimensions'}
            object_type = 'UserFieldFunction'
            if not isinstance(request['value'], str) or not request['value'].strip():
                raise ValueError('Field function definition must be a non-empty string')
        else:
            raise ValueError('set-definition supports scalar parameters and user field functions only')
        if not required <= expected.keys() or any(not isinstance(expected[k], str) for k in required):
            raise ValueError(f'Expected state requires string fields: {", ".join(sorted(required))}')
        if expected['object_type'] != object_type:
            raise ValueError(f'set-definition requires object_type {object_type}')
    else:
        for name, value in [('expected.tags', expected.get('tags')), ('value', request['value'])]:
            if (not isinstance(value, list)
                    or any(not isinstance(tag, str) or not tag for tag in value)
                    or len(value) != len(set(value))):
                raise ValueError(f'{name} must contain unique, non-empty tag names')
        # 标签集合无顺序语义；统一排序后再生成宏、核对旧状态及记录请求。
        expected['tags'] = sorted(expected['tags'])
        request['value'] = sorted(request['value'])

    # 2. 同时检查嵌套 expected 数值；1e999 也不能通过标准 JSON 解析绕过有限性检查。
    java_literal(request)
    return request


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
        return 'java.util.Arrays.asList(' + ','.join(java_literal(v) for v in value) + ')'
    if isinstance(value, dict):
        pairs = [java_literal(item) for pair in value.items() for item in pair]
        return 'fields(' + ','.join(pairs) + ')'
    raise ValueError(f'Unsupported request value type: {type(value).__name__}')


def target_snapshot(snapshot, target):
    """按类别和显示名称定位唯一对象；边界必须先定位其所属区域。"""
    kind = target['kind']
    if kind == 'boundary':
        region = target_snapshot(snapshot, {'kind': 'region', 'name': target['region']})
        objects = region['boundaries']
    else:
        objects = snapshot[COLLECTIONS[kind]]
    matches = [item for item in objects if item['name'] == target['name']]
    if len(matches) != 1:
        raise RuntimeError(f'Target is missing or ambiguous: {target}')
    return matches[0]


def same_value(left, right):
    """按 JSON 类型比较状态；数值允许 1 与 1.0 相等，布尔值不能冒充数值。"""
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same_value(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same_value(a, b) for a, b in zip(left, right))
    return left == right


def verify_modification(request, before, after):
    """核对修改前预期、修改后目标及不应改变的目标身份属性；不判断表达式物理意义。"""
    if not before.get('inspection_complete') or not after.get('inspection_complete'):
        raise RuntimeError('Modification requires complete covered snapshots')
    original = target_snapshot(before, request['target'])
    actual = target_snapshot(after, request['target'])
    for key, value in request['expected'].items():
        if key not in original or not same_value(original[key], value):
            raise RuntimeError(f'Modification precondition was not confirmed: {key}')
    property_name = 'definition' if request['operation'] == 'set-definition' else 'tags'
    scalar = property_name == 'definition' and actual['object_type'] == 'ScalarGlobalParameter'
    value = request['value']['definition'] if scalar else request['value']
    matches = same_value(actual.get(property_name), value)
    if (not matches and property_name == 'definition'
            and actual['object_type'] == 'ScalarGlobalParameter'):
        # STAR 会把纯数值文本 6 规范化为 6.0；真正的表达式仍要求文本一致。
        try:
            wanted, stored = float(value), float(actual[property_name])
            matches = math.isfinite(wanted) and math.isfinite(stored) and wanted == stored
        except (ValueError, TypeError):
            matches = False
    if not matches:
        raise RuntimeError(f'Modification readback mismatch: {property_name}')
    if scalar and actual.get('unit') != request['value']['unit']:
        raise RuntimeError('Modification readback mismatch: unit')
    for key in ('name', 'object_type', 'unit', 'function_name', 'value_type', 'dimensions'):
        if scalar and key == 'unit':
            continue
        if key in original and not same_value(original[key], actual.get(key)):
            raise RuntimeError(f'Target identity or type changed: {key}')


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
