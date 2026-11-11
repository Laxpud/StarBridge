"""提供可直接使用的参数化操作方法，不执行检索结果，也不替调用者选择算例对象。

内置方法使用当前安装的官方 Java API；prepare_recipe 只生成 execute_macro 参数。
资料及编译依据不是实际算例验证。参数契约与工作记忆的 recipe.parameters 同形，
执行绑定额外拒绝未知约束，避免存储时未解释的条件在执行时被悄悄忽略。
"""

from copy import deepcopy
import json
import math
from pathlib import Path
import re

from .macros import prepare as prepare_macro
from starbridge.bridge.runner.modifier import same_value


SCHEMA_VERSION = 1
EVIDENCE_VERSION = {'release': '2602', 'build': '21.02.007'}
_PARAMETER_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_TYPES = ('string', 'number', 'integer', 'boolean', 'object', 'array', 'object_reference')
_CONSTRAINTS = {'type', 'description', 'required', 'default', 'enum', 'minimum', 'maximum',
                'exclusiveMinimum', 'exclusiveMaximum', 'minLength', 'maxLength', 'pattern',
                'minItems', 'maxItems', 'uniqueItems', 'items', 'properties',
                'additionalProperties', 'format', 'nullable', 'unit', 'units', 'examples'}

# schema 描述可以存入记忆的最小方法，不把 effect 缺省解释成只读；调用者仍须明确选择方法。
RECIPE_SCHEMA = {
    'type': 'object', 'required': ['code', 'imports', 'parameters'],
    'properties': {
        'code': {'type': 'string', 'minLength': 1},
        'imports': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}},
        'parameters': {'type': 'object', 'additionalProperties': {
            'type': 'object', 'required': ['type', 'description', 'required'],
            'properties': {'type': {'enum': list(_TYPES)}, 'description': {'type': 'string', 'minLength': 1},
                           'required': {'type': 'boolean'}}, 'additionalProperties': True}},
        'declarations': {'type': 'string'}, 'language': {'enum': ['java', 'Java']},
        'effect': {'enum': ['read', 'mutate']}, 'scope': {'type': 'string', 'minLength': 1},
    },
    'additionalProperties': True,
}


def _json_copy(value):
    """只接受明确的 JSON 数据，拒绝隐式转换键、非有限数和 Java 无法表示的整数。"""
    def visit(item, depth=0):
        if depth > 32:
            raise ValueError('Recipe data exceeds the maximum nesting depth')
        if item is None or type(item) in (str, bool):
            return
        if type(item) is int:
            if not -(2 ** 63) <= item < 2 ** 63:
                raise ValueError('Recipe integers must fit in signed 64-bit values')
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise ValueError('Recipe numbers must be finite')
            return
        if type(item) is list:
            for child in item:
                visit(child, depth + 1)
            return
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError('Recipe object keys must be strings')
            for child in item.values():
                visit(child, depth + 1)
            return
        raise ValueError('Recipe data must contain only JSON values')
    visit(value)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode('utf-8')) > 2_000_000:
        raise ValueError('Recipe data exceeds 2 MB')
    return json.loads(encoded)


def _text(value, name):
    """参数名称和说明必须有实际内容，不能用空文本掩盖缺失条件。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be non-empty text')


def _contract(contract, name, *, top=True, depth=0):
    """校验支持的约束语法；不认识的约束拒绝执行，而不是当成无约束。"""
    if depth > 16 or not isinstance(contract, dict):
        raise ValueError(f'{name} must be a bounded parameter contract')
    unknown = set(contract) - _CONSTRAINTS
    if unknown:
        raise ValueError(f'Unsupported parameter constraints at {name}: {sorted(unknown)}')
    kind = contract.get('type')
    if kind not in _TYPES:
        raise ValueError(f'Unsupported parameter type at {name}')
    if top:
        _text(contract.get('description'), f'{name}.description')
        if type(contract.get('required')) is not bool:
            raise ValueError(f'{name}.required must be a boolean')
    for flag in ('required', 'nullable', 'uniqueItems', 'additionalProperties'):
        if flag in contract and type(contract[flag]) is not bool:
            raise ValueError(f'{name}.{flag} must be a boolean')
    for key in ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'):
        if key in contract and (kind not in ('number', 'integer') or type(contract[key]) not in (int, float)):
            raise ValueError(f'{name}.{key} requires a finite numeric bound on a numeric parameter')
    for key in ('minLength', 'maxLength', 'minItems', 'maxItems'):
        applicable = kind == ('string' if key.endswith('Length') else 'array')
        if key in contract and (not applicable or type(contract[key]) is not int or contract[key] < 0):
            raise ValueError(f'{name}.{key} requires a nonnegative integer on the matching type')
    if 'pattern' in contract:
        if kind != 'string' or not isinstance(contract['pattern'], str):
            raise ValueError(f'{name}.pattern requires a string parameter and regex text')
        try:
            re.compile(contract['pattern'])
        except re.error as error:
            raise ValueError(f'Invalid pattern at {name}: {error}') from error
    if 'format' in contract and (kind != 'string' or contract['format'] not in ('absolute_path', 'new_file')):
        raise ValueError(f'{name}.format must be absolute_path or new_file on a string')
    if 'enum' in contract and (not isinstance(contract['enum'], list) or not contract['enum']):
        raise ValueError(f'{name}.enum must be a non-empty array')
    if 'items' in contract:
        if kind != 'array':
            raise ValueError(f'{name}.items is only supported for arrays')
        _contract(contract['items'], f'{name}.items', top=False, depth=depth + 1)
    if 'properties' in contract:
        if kind not in ('object', 'object_reference') or not isinstance(contract['properties'], dict):
            raise ValueError(f'{name}.properties requires an object parameter')
        for key, child in contract['properties'].items():
            _contract(child, f'{name}.{key}', top=False, depth=depth + 1)
    if 'uniqueItems' in contract and kind != 'array':
        raise ValueError(f'{name}.uniqueItems is only supported for arrays')
    if 'additionalProperties' in contract and (kind not in ('object', 'object_reference') or 'properties' not in contract):
        raise ValueError(f'{name}.additionalProperties requires an explicit object properties contract')
    for lower, upper in (('minimum', 'maximum'), ('minLength', 'maxLength'), ('minItems', 'maxItems')):
        if lower in contract and upper in contract and contract[lower] > contract[upper]:
            raise ValueError(f'{name} has inconsistent bounds')
    if kind == 'object_reference' and 'default' in contract:
        raise ValueError(f'{name} must resolve a current object reference, not use a stored default')
    if 'default' in contract:
        _bound(contract, contract['default'], f'{name}.default')


def _bound(contract, value, name):
    """验证一个实际绑定，不强制转换类型，不从旧记忆补对象或推断单位。"""
    if 'enum' in contract and not any(same_value(value, candidate) for candidate in contract['enum']):
        raise ValueError(f'{name} is not an allowed enum value')
    if value is None and contract.get('nullable', False):
        return
    kind = contract['type']
    valid = {'string': type(value) is str, 'boolean': type(value) is bool,
             'integer': type(value) is int, 'number': type(value) in (int, float),
             'object': type(value) is dict, 'array': type(value) is list,
             'object_reference': type(value) is dict}[kind]
    if not valid:
        raise ValueError(f'{name} must have type {kind}')
    for key, reject in (('minimum', lambda x, y: x < y), ('maximum', lambda x, y: x > y),
                        ('exclusiveMinimum', lambda x, y: x <= y), ('exclusiveMaximum', lambda x, y: x >= y)):
        if key in contract and reject(value, contract[key]):
            raise ValueError(f'{name} violates {key}')
    if kind == 'string':
        if 'minLength' in contract and len(value) < contract['minLength']:
            raise ValueError(f'{name} is too short')
        if 'maxLength' in contract and len(value) > contract['maxLength']:
            raise ValueError(f'{name} is too long')
        if 'pattern' in contract and re.search(contract['pattern'], value) is None:
            raise ValueError(f'{name} does not match its pattern')
        if 'format' in contract:
            path = Path(value)
            if not value or '\x00' in value or not path.is_absolute():
                raise ValueError(f'{name} must be an absolute path')
            # new_file 的存在性只在执行端 preflight 与 CREATE_NEW 核对；此处不能依赖
            # 当前磁盘状态，否则同 request_id 在上次已导出后无法走原执行凭据重放路径。
    if kind == 'array':
        if 'minItems' in contract and len(value) < contract['minItems']:
            raise ValueError(f'{name} contains too few items')
        if 'maxItems' in contract and len(value) > contract['maxItems']:
            raise ValueError(f'{name} contains too many items')
        if contract.get('uniqueItems') and any(same_value(item, previous)
                for index, item in enumerate(value) for previous in value[:index]):
            raise ValueError(f'{name} must contain unique items')
        if 'items' in contract:
            for index, item in enumerate(value):
                _bound(contract['items'], item, f'{name}[{index}]')
    if kind in ('object', 'object_reference'):
        if kind == 'object_reference':
            if set(value) != {'object_id'}:
                raise ValueError(f'{name} requires exactly object_id')
            _text(value.get('object_id'), f'{name}.object_id')
        if 'properties' in contract:
            properties = contract['properties']
            if not contract.get('additionalProperties', False) and set(value) - set(properties):
                raise ValueError(f'{name} contains unknown object properties')
            for key, child in properties.items():
                if key in value:
                    _bound(child, value[key], f'{name}.{key}')
                elif child.get('required', False):
                    raise ValueError(f'{name}.{key} is required')


def object_reference_paths(contracts, parameters):
    """按已审阅的参数契约定位对象引用，普通 JSON 字段不会因名称相似被自动执行。"""
    paths = []

    def visit(contract, value, path):
        if len(path) > 64:
            raise ValueError('Object parameter nesting exceeds 64 levels')
        if contract['type'] == 'object_reference':
            paths.append(path)
        elif contract['type'] == 'object' and isinstance(value, dict):
            for name, child in sorted(contract.get('properties', {}).items()):
                if name in value:
                    visit(child, value[name], [*path, name])
        elif contract['type'] == 'array' and 'items' in contract:
            for index, item in enumerate(value):
                visit(contract['items'], item, [*path, index])

    for name, contract in sorted(contracts.items()):
        if name in parameters:
            visit(contract, parameters[name], [name])
    return paths


def validate_parameters(contracts, parameters):
    """为内置方法及显式选中的 memory.recipe 绑定参数，返回独立 JSON 副本。

    contracts 与 memory.recipe.parameters 同形。只填充声明过的 default，未知参数直接
    拒绝；object_reference 只验证带 object_id 的对象形状，当前会话身份仍由调用方核对。
    unit/units 是资料元数据，不自动换算。未支持的自定义约束可存记忆，但不能静默执行。
    """
    contracts = _json_copy(contracts)
    parameters = _json_copy(parameters)
    if not isinstance(contracts, dict) or not isinstance(parameters, dict):
        raise ValueError('Recipe contracts and parameters must be JSON objects')
    if set(parameters) - set(contracts):
        raise ValueError(f'Unknown recipe parameters: {sorted(set(parameters) - set(contracts))}')
    result = {}
    for name, contract in contracts.items():
        if _PARAMETER_NAME.fullmatch(name) is None:
            raise ValueError(f'Invalid recipe parameter name: {name!r}')
        _contract(contract, name)
        if name in parameters:
            value = parameters[name]
        elif 'default' in contract:
            value = deepcopy(contract['default'])
        elif contract['required']:
            raise ValueError(f'Missing required recipe parameter: {name}')
        else:
            continue
        _bound(contract, value, name)
        result[name] = value
    return result


def validate_recipe(recipe):
    """验证与工作记忆兼容的单方法源码和参数契约，不执行或自动接受检索候选。

    effect 未声明时保留未声明状态，由执行方按 mutate 保守处理或明确选择。
    其他 JSON 元数据原样保留，但源码只使用 code/imports/declarations，不解释额外字段。
    """
    result = _json_copy(recipe)
    if not isinstance(result, dict):
        raise ValueError('recipe must be a JSON object')
    _text(result.get('code'), 'recipe.code')
    if not isinstance(result.get('parameters'), dict):
        raise ValueError('recipe.parameters must map names to contracts')
    # 不用空 bindings 验证必填项，只检查每份契约及其声明的默认值。
    for name, contract in result['parameters'].items():
        if _PARAMETER_NAME.fullmatch(name) is None:
            raise ValueError(f'Invalid recipe parameter name: {name!r}')
        _contract(contract, name)
    if result.get('language', 'java') not in ('java', 'Java'):
        raise ValueError('Only Java recipes can be prepared for execute_macro')
    effect = result.get('effect', 'mutate')
    scope = result.get('scope', 'Caller-selected memory recipe; review applicability before execution')
    prepare_macro('recipe-schema', [{'id': 'recipe', 'code': result['code'], 'effect': effect, 'scope': scope}],
                  imports=result.get('imports'), declarations=result.get('declarations', ''))
    if not isinstance(result.get('imports'), list):
        raise ValueError('recipe.imports must be an explicit list')
    return result


# 下列辅助方法在宏内运行。各字段独立保留可用性；不知道的状态不写成零或 false。
_STATUS_HELPERS = r'''
/** 读取一个有限 JSON 标量，局部 getter 失败不抹掉其他运行信息。 */
private Map<String,Object> recipeObserved(java.util.function.Supplier<Object> reader) {
    try {
        Object value = reader.get();
        if (value instanceof Number && !Double.isFinite(((Number)value).doubleValue()))
            return fields("status", "unavailable", "reason", "non_finite_value");
        return fields("status", "ok", "value", value);
    } catch (RuntimeException error) {
        return fields("status", "error", "error", error.getClass().getName(), "message", String.valueOf(error.getMessage()));
    }
}
/** 收集当前计数及运行标志；它们不证明收敛，也不能推出用户中断或停止准则的原因。 */
private Map<String,Object> recipeSolverStatus() {
    SimulationIterator iterator = sim.getSimulationIterator();
    Map<String,Object> result = fields(
        "current_iteration", recipeObserved(() -> iterator.getCurrentIteration()),
        "current_time_level", recipeObserved(() -> iterator.getCurrentTimeLevel()),
        "is_iterating", recipeObserved(() -> iterator.isIterating()),
        "is_busy", recipeObserved(() -> iterator.isBusy()),
        "has_runnable_solver", recipeObserved(() -> iterator.getRunnableSolver() != null));
    boolean complete = true;
    for (Object value : result.values())
        if (!"ok".equals(((Map<?,?>)value).get("status"))) complete = false;
    result.put("read_status", complete ? "complete" : "partial");
    result.put("convergence", "not_assessed");
    result.put("stop_reason", "not_determined");
    return result;
}
/** 读取现有自动保存配置，不改变文件集或触发器；未知配置使执行前检查失败。
 * 普通体网格任务已观察到 batch=true、mesh=false 仍在宏凭据写出后保存；不能只检查 mesh。
 * 表面网格也保守纳入 batch 风险，但该分支尚无相同真实观察。这里不是最终磁盘状态快照。
 */
private Map<String,Object> recipeAutosave(String operation) {
    AutoSave auto = sim.getSimulationIterator().getAutoSave();
    List<Object> sets = new ArrayList<>();
    boolean scheduled = false;
    for (AutoSaveFileSet set : auto.getAutoSaveFileSetManager().getObjects()) {
        boolean enabled = set.getStarUpdate().getEnabled();
        scheduled |= enabled;
        sets.add(fields("name", set.getPresentationName(), "enabled", enabled));
    }
    boolean batch = auto.getAutoSaveBatch();
    boolean mesh = auto.getAutoSaveMesh();
    boolean checkpoint = auto.getCheckpoint();
    boolean applicable = operation.equals("solver") ? scheduled || batch || checkpoint
                         : batch || (operation.equals("volume") && mesh);
    return fields("file_sets", sets, "scheduled_enabled", scheduled, "batch_enabled", batch,
                  "after_volume_mesh_enabled", mesh, "after_next_step_enabled", checkpoint,
                  "may_save_during_operation", applicable, "operation", operation,
                  "save_boundary", "operation_and_batch_client_completion",
                  "batch_save_may_follow_macro_receipt", batch,
                  "explicit_save_called", false, "configuration_changed", false);
}
/** 在只读预检查步骤中拒绝超出执行范围的自动保存，不擅自替用户关闭已有配置。 */
private void recipeCheckAutosave(Map<String,Object> autosave) {
    if (Boolean.TRUE.equals(autosave.get("may_save_during_operation"))
            && !Boolean.TRUE.equals(parameters.get("allow_existing_autosave")))
        throw new IllegalArgumentException("Existing automatic saving may run; explicitly set allow_existing_autosave=true to preserve and allow those settings");
}
'''

_EXPORT_HELPERS = r'''
/** 只在指定管理器的现有直接对象中按精确显示名称匹配，歧义和缺失均在导出前拒绝。 */
private <T extends star.base.neo.NamedObject> T recipeNamed(Collection<? extends star.base.neo.NamedObject> objects, String name, Class<T> expected) {
    star.base.neo.NamedObject match = null;
    for (star.base.neo.NamedObject candidate : objects) {
        if (!name.equals(candidate.getPresentationName())) continue;
        if (match != null) throw new IllegalArgumentException("Ambiguous object name: " + name);
        match = candidate;
    }
    if (match == null) throw new IllegalArgumentException("Object not found: " + name);
    if (!expected.isInstance(match)) throw new IllegalArgumentException("Unsupported export target type: " + match.getClass().getName());
    return expected.cast(match);
}
/** 执行端重新核对输出；预检查不能代替最终 CREATE_NEW，也不自动创建父目录。 */
private Path recipeOutput() {
    Path path = Path.of((String)parameters.get("output"));
    if (!path.isAbsolute() || !Files.isDirectory(path.getParent()))
        throw new IllegalArgumentException("Output must be absolute and have an existing parent directory");
    if (Files.exists(path, LinkOption.NOFOLLOW_LINKS))
        throw new IllegalArgumentException("Output already exists: " + path);
    return path;
}
/** 仅复制新导出的数据，不复制算例；CREATE_NEW 防止预检查后的并发文件创建被覆盖。
 * 文件内容写入不是事务：磁盘故障可能留下部分新文件，保留它供恢复，绝不删用户目标。
 */
private long recipePublish(Path staged, Path output) throws java.io.IOException {
    if (!Files.isRegularFile(staged, LinkOption.NOFOLLOW_LINKS))
        throw new java.io.IOException("STAR export returned without a regular output file");
    try (java.io.OutputStream stream = Files.newOutputStream(output, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
        return Files.copy(staged, stream);
    }
}
/** 清理仅限本次独占临时目录中的固定文件；清理失败不会推翻已经完成的导出。 */
private void recipeCleanup(Path staged, Path directory, Map<String,Object> result) {
    try {
        Files.deleteIfExists(staged);
        Files.delete(directory);
        result.put("temporary_cleanup", "completed");
    } catch (java.io.IOException error) {
        result.put("temporary_cleanup", "incomplete");
        result.put("temporary_directory", directory.toString());
        result.put("temporary_cleanup_error", error.toString());
    }
}
'''


def _parameter(kind, description, *, required=False, **constraints):
    """用与工作记忆相同的字段声明内置方法参数，默认值也是显式契约的一部分。"""
    return dict(type=kind, description=description, required=required, **constraints)


def _evidence(*members):
    """资料位置使用安装相对路径，避免把开发机绝对安装路径变成运行依赖。"""
    return {'level': 'official_javadoc_and_static_compilation', 'version': dict(EVIDENCE_VERSION),
            'real_operation_validated': False, 'sources': [
                {'kind': 'installed_official_javadoc', 'installation_relative': 'doc/client/html/' + member}
                for member in members],
            'scope': 'API signatures and documented semantics; no mesh, solve or export was executed for this evidence'}


def _step(identifier, effect, scope, code):
    """每步描述实际范围；预检查与变更分开，拒绝时后续变更明确保持未开始。"""
    return dict(id=identifier, effect=effect, scope=scope, code=code.strip())


def _gui_presentation_recipe():
    """把独立编译的 GUI 表示辅助类嵌入显式方法，不给普通宏增加 GUI 初始化或模块依赖。"""
    from starbridge.bridge.runner.java_runtime import source_text
    source = source_text(Path(__file__).resolve().parents[1] / 'bridge' / 'java' / 'GuiPresentation.java')
    imports = [line.removeprefix('import ').removesuffix(';')
               for line in source.splitlines() if line.startswith('import ')]
    declarations = '\n'.join(line for line in source.splitlines() if not line.startswith('import '))
    declarations = declarations.replace('public final class GuiPresentation {',
                                        'private static final class GuiPresentation {', 1)
    selector = {'type': 'object', 'properties': {
        'java_class': {'type': 'string', 'minLength': 1, 'required': True},
        'name': {'type': 'string', 'minLength': 1}}, 'additionalProperties': False}
    target = {'type': 'object', 'properties': {
        'object': {'type': 'object_reference', 'required': True},
        'child_path': {'type': 'array', 'maxItems': 8, 'items': selector},
        'property_name': {'type': 'string'}}, 'additionalProperties': False}
    return {
        'title': '查询对象对应的 GUI 位置',
        'description': '在一次连接中查询当前对象的官方树路径、可选属性栏标签及首层菜单动作；不打开窗口或执行动作。逐目标及逐区段报告缺失、错误和预算耗尽。',
        'parameters': {
            'targets': _parameter('array', '当前目标列表，每项 object={object_id: 当前引用}；可用 child_path 按 java_class 和可选当前 name 逐层选择虚拟分组。property_name 使用描述返回的属性名称，不是 property_id。',
                                  required=True, minItems=1, maxItems=32, items=target),
            'include_properties': _parameter('boolean', '读取目标节点属性栏元数据，不读取值；指定 property_name 时无论此项如何均查询该属性。', default=False),
            'include_actions': _parameter('boolean', '构建但不显示节点弹出菜单，读取首层组件的实际标签；不展开子菜单、不执行动作，不读取另一 GUI 窗口的启用状态。', default=False),
            'max_items': _parameter('integer', '每个目标各区段最多检查的项数；不是 STAR 内部节点构建的耗时或内存上限。', default=64, minimum=1, maximum=256),
        },
        'imports': imports, 'declarations': declarations,
        'steps': [_step('presentation', 'read', '当前绑定对象的官方节点位置及显示元数据；不请求打开视图或选择节点、不返回业务属性值、不执行动作，原生构造可能内部读取所需状态', r'''
result.put("presentation", GuiPresentation.inspect(sim, (List<?>)parameters.get("targets"),
    Boolean.TRUE.equals(parameters.get("include_properties")),
    Boolean.TRUE.equals(parameters.get("include_actions")), ((Number)parameters.get("max_items")).intValue()));
''')],
        'applicability': [
            '对象须先绑定到当前 Simulation；仅查询，不创建 CFD 对象或加载副本。',
            '标准树节点模型与另一客户端当前可见布局、自定义树、选中项不同；读取 source、tree_scope 和 remote_gui_observed。',
            '只把实际祖先到达根节点的路径标为 resolved；不以拥有者链替代失败路径。虚拟分组选择不创建可修改的业务引用。',
            '业务值仍须 read_properties 或明确宏读取。read_status=partial 时检查逐目标和逐区段状态，不能把宏 completed 当成全部位置已取得。',
            '界面观察不是原子快照；已有 GUI 并发变更可能改变名称、可见属性及动作。',
        ],
        'evidence': _evidence('star/common/ui/SimulationProcessNode.html',
            'star/coremodule/RootProcessObject.html#setRootObject(star.common.RootObject)',
            'star/coremodule/StarBeanNode.html#getNode(star.common.ui.RootProcessNode,star.base.neo.ClientServerObject)'),
    }


def _builtins():
    """每次返回独立方法定义，调用者不能通过修改列表结果改变后续执行源码。"""
    allow = _parameter('boolean', '明确允许沿用当前算例已有自动保存，包括可能发生在宏凭据写出后的 batch 保存；不修改配置，也不是每步确认。', default=False)
    name = _parameter('string', '当前算例中目标对象的精确显示名称，不能照搬历史对象名。', required=True, minLength=1)
    output = _parameter('string', '服务所在机器上新输出文件的绝对路径，父目录须存在。', required=True, format='new_file')
    delimiter = _parameter('string', '导出字段分隔符；默认逗号。', default=',', enum=[',', '\t', ';'])
    solver_preflight = _step('preflight', 'read', '当前求解器、运行状态及现有自动保存配置，不启动计算', r'''
SimulationIterator iterator = sim.getSimulationIterator();
if (iterator.isBusy()) throw new IllegalStateException("Simulation is already busy");
if (iterator.getRunnableSolver() == null) throw new IllegalStateException("No runnable solver is available");
Map<String,Object> autosave = recipeAutosave("solver");
recipeCheckAutosave(autosave);
shared.put("iterator", iterator);
shared.put("autosave", autosave);
result.put("solver", recipeSolverStatus());
result.put("autosave", autosave);
''')
    recipes = {
        'solver.status': {
            'title': '读取求解运行状态', 'description': '集中读取迭代编号、时间步编号、busy 和 iterating；局部不可用明确标出。',
            'parameters': {}, 'imports': [], 'declarations': _STATUS_HELPERS,
            'steps': [_step('status', 'read', '当前 SimulationIterator 的运行标志与计数，不读取完整求解历史', r'''
result.put("solver", recipeSolverStatus());
result.put("autosave", recipeObserved(() -> recipeAutosave("solver")));
result.put("operation_returned", true);
''')],
            'applicability': ['已加载的 Simulation；读取时仍可能变化，不是跨 getter 的原子快照。'],
            'evidence': _evidence('star/common/SimulationIterator.html#getCurrentIteration()',
                                  'star/common/SimulationIterator.html#isBusy()'),
        },
        'solver.step': {
            'title': '执行指定数量的求解步', 'description': '使用 step(n,true) 等待返回；n 在稳态为迭代、瞬态为时间步，可能被用户中断。',
            'parameters': {'iterations': _parameter('integer', '请求执行的步骤数：稳态迭代或瞬态时间步，不等于实际完成的迭代增量。',
                                                   required=True, minimum=1, maximum=2147483647),
                           'allow_existing_autosave': allow},
            'imports': [], 'declarations': _STATUS_HELPERS, 'steps': [solver_preflight, _step(
                'step', 'mutate', '按当前已配置模型求解指定步数；不显式保存，不改变停止准则或自动保存', r'''
SimulationIterator iterator = (SimulationIterator)shared.get("iterator");
int requested = ((Long)parameters.get("iterations")).intValue();
iterator.step(requested, true);
result.put("operation_returned", true);
result.put("requested_steps", requested);
result.put("step_unit", "iteration_or_time_step_as_configured");
result.put("solver", recipeSolverStatus());
result.put("autosave", shared.get("autosave"));
result.put("requested_steps_completed", "not_inferred_from_return");
''')],
            'applicability': ['当前算例已有可运行求解器、网格与所需设置。',
                              'step 不等同 run 的停止准则语义；等待返回仍可能是用户中断，检查实际前后计数。'],
            'evidence': _evidence('star/common/SimulationIterator.html#step(int,boolean)',
                                  'star/common/AutoSave.html#getAutoSaveBatch()',
                                  'star/common/AutoSave.html#getCheckpoint()',
                                  'star/common/AutoSaveBase.html#getStarUpdate()'),
        },
        'solver.run': {
            'title': '按当前停止准则求解', 'description': '使用 run(true) 等待停止准则或用户中断；不调整停止准则，也不推断收敛。',
            'parameters': {'allow_existing_autosave': allow}, 'imports': [], 'declarations': _STATUS_HELPERS,
            'steps': [solver_preflight, _step('run', 'mutate', '沿用当前启用的停止准则运行，不改变算例设置或显式保存', r'''
((SimulationIterator)shared.get("iterator")).run(true);
result.put("operation_returned", true);
result.put("solver", recipeSolverStatus());
result.put("autosave", shared.get("autosave"));
result.put("stopping_criteria_satisfied", "not_inferred_from_return");
''')],
            'applicability': ['当前算例已有可运行求解器及明确停止条件；运行时长由算例决定。'],
            'evidence': _evidence('star/common/SimulationIterator.html#run(boolean)',
                                  'star/common/AutoSave.html#getAutoSaveBatch()',
                                  'star/common/AutoSave.html#getCheckpoint()',
                                  'star/common/AutoSaveBase.html#getStarUpdate()'),
        },
        'mesh.generate': {
            'title': '运行现有网格流水线', 'description': '生成当前已配置的表面或体网格；读取 API 状态，不宣称网格质量通过。',
            'parameters': {'kind': _parameter('string', 'surface 为表面网格，volume 为体网格。', default='volume', enum=['surface', 'volume']),
                           'allow_existing_autosave': allow},
            'imports': ['star.meshing.MeshPipelineController'], 'declarations': _STATUS_HELPERS,
            'steps': [_step('preflight', 'read', '当前网格控制器状态与现有自动保存，不生成或清除网格', r'''
MeshPipelineController controller = sim.get(MeshPipelineController.class);
if (controller.isGeneratingMesh() || sim.getSimulationIterator().isBusy())
    throw new IllegalStateException("Simulation is already generating mesh or solving");
Map<String,Object> autosave = recipeAutosave((String)parameters.get("kind"));
recipeCheckAutosave(autosave);
shared.put("controller", controller);
shared.put("autosave", autosave);
result.put("autosave", autosave);
result.put("is_generating_mesh", false);
'''), _step('generate', 'mutate', '运行现有网格流水线；不额外调用清理或保存，重建网格可能使已有解失效', r'''
MeshPipelineController controller = (MeshPipelineController)shared.get("controller");
String kind = (String)parameters.get("kind");
if (kind.equals("surface")) controller.generateSurfaceMesh();
else controller.generateVolumeMesh();
result.put("operation_returned", true);
result.put("kind", kind);
result.put("is_generating_mesh", recipeObserved(() -> controller.isGeneratingMesh()));
result.put("did_generate", recipeObserved(() -> kind.equals("surface") ? controller.didGenerateSurfaceMesh() : controller.didGenerateVolumeMesh()));
result.put("autosave", shared.get("autosave"));
result.put("mesh_quality", "not_assessed");
''')],
            'applicability': ['已有可执行网格流水线及所需几何；该方法不负责建立网格配置。',
                              'didGenerate 与 isGeneratingMesh 是 API 原始状态，不是质量验证或通用异步终态保证。',
                              'batch 自动保存也会影响体网格任务；表面网格保守按同样风险检查，不宣称该分支已实测。',
                              '宏凭据的 session_path 是当时观察，不保证包含后续 batch 客户端自动保存引起的路径变化。'],
            'evidence': {
                **_evidence('star/meshing/MeshPipelineController.html#generateVolumeMesh()',
                            'star/meshing/MeshPipelineController.html#generateSurfaceMesh()',
                            'star/meshing/MeshPipelineController.html#isGeneratingMesh()',
                            'star/common/AutoSave.html#getAutoSaveMesh()',
                            'star/common/AutoSave.html#getAutoSaveBatch()'),
                'level': 'official_javadoc_static_compilation_and_scoped_task_observation',
                'scope': 'API signatures and scoped 2602 volume-mesh observations, including revised batch-autosave refusal; not validation of every mesh kind, version or save mode',
                'observations': [{
                    'kind': 'normal_task_observation', 'version': dict(EVIDENCE_VERSION),
                    'observed_effect': 'A self-created 909-cell case was automatically saved after the macro receipt although after_volume_mesh_enabled=false and batch_enabled=true',
                    'scope': 'One pre-fix volume-mesh execution; not a surface-mesh observation or a general validation of automatic-save behavior',
                    'correction': 'Both mesh kinds now treat batch_enabled as a possible save trigger; surface coverage is conservative, not empirically established',
                    'artifacts': [
                        'outputs/requirements-first/runtime/sessions/8f12cc01fa5d4b8f826a4e22855701cf/requests/macro-channel-volume-mesh-1/result.json',
                        'outputs/requirements-first/runtime/sessions/8f12cc01fa5d4b8f826a4e22855701cf/requests/macro-channel-volume-mesh-1/star.log#L343-L350'],
                }, {
                    'kind': 'scoped_task_observation', 'version': dict(EVIDENCE_VERSION),
                    'observed_effect': 'With autosave disabled the configured volume-mesh method returned; with batch=true and mesh=false the revised default preflight refused before generation',
                    'scope': 'The disposable configured 2602 channel only; surface meshing and other autosave combinations remain unverified',
                    'artifacts': ['outputs/requirements-first/reference-workflow/02-execute_recipe.json',
                                  'outputs/requirements-first/reference-workflow/35-execute_recipe.json'],
                }],
            },
        },
    }
    # 三类导出共用精确现有对象定位及最终 CREATE_NEW；STAR 内建导出仅写独占临时目录。
    for kind, java_type, manager in [('plot', 'StarPlot', 'getPlotManager'),
                                      ('table', 'Table', 'getTableManager'),
                                      ('report', 'star.base.report.Report', 'getReportManager')]:
        params = {'name': name, 'output': output}
        if kind != 'report':
            params['delimiter'] = delimiter
        if kind == 'table':
            params['extract'] = _parameter('boolean', 'true 先调用 extract 更新提取数据；false 导出现有提取数据，不宣称最新。', default=False)
        # 下面只组合固定内部 API 名称，不把任何用户参数拼进 Java 源码。
        preflight = f'''{java_type} object = recipeNamed(sim.{manager}().getObjects(), (String)parameters.get("name"), {java_type}.class);
Path output = recipeOutput();
shared.put("object", object);
shared.put("output", output);
result.put("name", object.getPresentationName());
result.put("java_class", object.getClass().getName());
result.put("output", output.toString());'''
        if kind == 'report':
            export_code = r'''
star.base.report.Report report = (star.base.report.Report)shared.get("object");
Path output = (Path)shared.get("output");
try (java.io.PrintWriter writer = new java.io.PrintWriter(Files.newBufferedWriter(output,
        java.nio.charset.StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE))) {
    report.printReport(writer);
    writer.flush();
    if (writer.checkError()) throw new java.io.IOException("Report output write failed");
}
result.put("operation_returned", true);
result.put("output", output.toString());
result.put("bytes", Files.size(output));
result.put("format", "STAR_report_text");
result.put("report_values_validity", "not_assessed; inspect report text for diagnostics");
'''
            sources = ['star/base/report/Report.html#printReport(java.io.PrintWriter)']
        else:
            extract = 'if (Boolean.TRUE.equals(parameters.get("extract"))) object.extract();' if kind == 'table' else ''
            export_code = f'''{java_type} object = ({java_type})shared.get("object");
Path output = (Path)shared.get("output");
Path temporary = Files.createTempDirectory(output.getParent(), ".starbridge-export-");
Path staged = temporary.resolve("data.csv");
try {{
    {extract}
    object.export(staged.toString(), (String)parameters.get("delimiter"));
    long bytes = recipePublish(staged, output);
    result.put("operation_returned", true);
    result.put("output", output.toString());
    result.put("bytes", bytes);
    result.put("delimiter", parameters.get("delimiter"));
    result.put("extract_requested", Boolean.TRUE.equals(parameters.get("extract")));
    result.put("data_validity", "not_assessed");
}} finally {{ recipeCleanup(staged, temporary, result); }}'''
            sources = [f'star/common/{java_type}.html#export(java.lang.String,java.lang.String)']
            if kind == 'table':
                sources.append('star/common/Table.html#extract()')
        recipes[kind + '.export'] = {
            'title': {'plot': '导出图表数据', 'table': '导出表数据', 'report': '导出报告文本'}[kind],
            'description': '导出当前明确选择的已有对象到新文件，不运行求解、不保存算例，不覆盖已有文件。',
            'parameters': params, 'imports': [], 'declarations': _EXPORT_HELPERS,
            'steps': [_step('preflight', 'read', '按精确显示名称定位已有对象并核对输出路径，不写文件', preflight),
                      _step('export', 'mutate', '仅导出所选对象到新文件；表提取是否更新由 extract 参数决定', export_code)],
            'applicability': ['对象须位于对应管理器，名称唯一；不通过缺失名称自动创建对象。',
                              'CREATE_NEW 防覆盖，但数据写入不是事务；异常可能留下部分新文件，应检查后再决定后续。',
                              '已有 GUI 并发改动不被 Bridge 会话锁隔离。'],
            'evidence': _evidence(*sources),
        }
    recipes['objects.gui_locations'] = _gui_presentation_recipe()
    for recipe_id, recipe in recipes.items():
        recipe.update(recipe_id=recipe_id, schema_version=SCHEMA_VERSION,
                      completion={'basis': 'explicit_API_return_and_recorded_status',
                                  'convergence': 'not_assessed', 'physics_validity': 'not_assessed',
                                  'implicit_simulation_save': 'no_explicit_save_call; existing_autosave_requires_explicit_allowance_for_mesh_or_solver'},
                      parameter_binding='data_only; no source substitution; resolve current objects explicitly')
    return recipes


def list_recipes(recipe_id=None, include_source=False):
    """默认仅返回方法索引，选中后再取完整条件；源码可用于审阅、修改和组合宏。

    include_source 必须明确选择一个方法，避免默认把整个方法库塞入上下文。返回的
    parameters 仍是参数契约，不是实际绑定；execute_recipe 继续通过原准备器校验。
    """
    if type(include_source) is not bool:
        raise ValueError('include_source must be a boolean')
    methods = _builtins()
    if recipe_id is not None and (not isinstance(recipe_id, str) or recipe_id not in methods):
        raise ValueError(f'Unknown built-in recipe: {recipe_id!r}')
    if include_source and recipe_id is None:
        raise ValueError('include_source requires an explicit recipe_id')
    # 列表视图由全量详情改为索引，单独提升响应版本；方法定义/参数/执行指纹仍沿用版本1。
    result = {'schema_version': 2,
              'view': 'detail' if recipe_id is not None else 'index',
              'evidence_notice': 'Review applicability and evidence; a listed method is not proof of current task coverage or physical validity'}
    if recipe_id is None:
        result['recipes'] = [{
            'recipe_id': recipe['recipe_id'], 'title': recipe['title'], 'description': recipe['description'],
            'effects': sorted({step['effect'] for step in recipe['steps']}),
            'detail': {'method': 'list_recipes', 'arguments': {'recipe_id': recipe['recipe_id']}},
        } for recipe in methods.values()]
        result['reuse'] = 'Select one method for parameters and evidence; add include_source=true for unchanged steps/imports/declarations. Methods are optional starting points, not a capability whitelist.'
    else:
        recipe = methods[recipe_id]
        result['memory_recipe_schema'] = deepcopy(RECIPE_SCHEMA)
        result['recipes'] = [{key: deepcopy(value) for key, value in recipe.items()
                              if key not in ('steps', 'imports', 'declarations')}]
        if include_source:
            result['source'] = {key: deepcopy(recipe[key]) for key in ('steps', 'imports', 'declarations')}
            result['source_usage'] = ('Pass reviewed source fields to execute_macro with current parameters and a new request_id. '
                'parameters in recipes[] are contracts, not bindings. When combining methods, resolve helper/step-name conflicts and shared state; do not concatenate blindly. '
                'Use execute_recipe for unchanged parameter validation and object-reference binding.')
    return result


def prepare_recipe(recipe_id, parameters):
    """将明确选中的内置方法绑定为 execute_macro 参数，并保留依据及完成判据元数据。

    调用方只把 steps/imports/declarations/parameters 交给 execute_macro，再自行提供当前
    session_id、稳定 request_id、intent 和 timeout；不能把元数据误当宏参数。此函数既不
    执行 Java，也不自动保存、复制或关闭算例。参数校验不证明当前对象或物理设置有效。
    """
    if not isinstance(recipe_id, str) or recipe_id not in _builtins():
        raise ValueError(f'Unknown built-in recipe: {recipe_id!r}')
    recipe = _builtins()[recipe_id]
    contracts = recipe['parameters']
    recipe['parameters'] = validate_parameters(contracts, parameters)
    # 内置方法和记忆方法使用相同的类型契约；先保留引用路径，再把 parameters 换为本次数据。
    recipe['object_parameter_paths'] = object_reference_paths(contracts, recipe['parameters'])
    # 共用宏准备器核对步骤、导入和数据边界，不使用它生成的请求标识或执行凭据。
    checked = prepare_macro('recipe-preparation', recipe['steps'], recipe['parameters'],
                            recipe['imports'], recipe['declarations'])
    for key in ('steps', 'imports', 'declarations', 'parameters'):
        recipe[key] = checked[key]
    return recipe
