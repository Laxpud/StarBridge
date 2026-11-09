"""编译并执行通用 Java 步骤，复用 STAR 服务而不复制或重载算例。

执行器不额外调用保存；用户 Java 及 STAR 原有自动保存仍可能写文件，甚至晚于宏凭据。
每次请求只启动一个客户端；全部步骤在同一宏中完成。源码和逐步凭据保留在
会话运行目录，用于结果恢复和方法复用，不能用客户端退出码代替任务完成状态。
"""

from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import zipfile

from .java_runtime import _JAVAC_ISOLATION_POLICY, _installation, _run_javac, source_text
from .modifier import java_literal
from starbridge.core.session_store import session_version


def declared_effect(request):
    """聚合调用者对整个程序的影响声明；同样覆盖用户声明和类／实例初始化。

    任一步为 mutate，则初始化按 mutate 处理；全部步骤为 read 才声明整个初始化只读。
    该规则必须与会话的 active_mutating 一致，不分析 Java，也不证明源码没有副作用。
    """
    return 'mutate' if any(step['effect'] == 'mutate' for step in request['steps']) else 'read'


def program_class(request):
    """完整源码使用本请求独有的包装类名，避免与已有宏或依赖中的常见类名碰撞。"""
    return ('StarBridgeProgram_' + request['fingerprint'][:20]
            if request.get('source_bundle') else 'StarBridgeProgram')


def step_body(step, classes):
    """代码步骤保持原方法体；源码步骤直接构造原宏，不抽取方法、不使用吞异常的 play。"""
    if 'code' in step:
        return step['code']
    entry = step['macro']
    source = java_literal(entry['entry_source'])
    name = entry['entry_class']
    # 此处生成的来源类构造位于本步骤 running 凭据之后；用户其他代码仍可能先主动引用它。
    # 原宏构造期间的 active simulation 遵循官方语义（尚未绑定），不伪称能在任意 Java
    # 构造器执行前注入实例上下文。
    return '\n'.join([
        'result.put("entry_class", ' + java_literal(name) + ');',
        'result.put("entry_source", ' + source + ');',
        'result.put("completion_basis", "entrypoint_returned");',
        'result.put("reported_results", "not_provided");',
        'result.put("entrypoint_returned", false);',
        'result.put("phase", "checking_class_origin");',
        'java.security.CodeSource sourceOrigin = ' + name + '.class.getProtectionDomain().getCodeSource();',
        'if (sourceOrigin == null || !"file".equals(sourceOrigin.getLocation().getProtocol()) ||',
        '        !Files.isSameFile(Path.of(sourceOrigin.getLocation().toURI()), Path.of(' + java_literal(str(classes)) + ')))',
        '    throw new IllegalStateException("Entry class did not load from this request source compilation");',
        'result.put("class_origin", sourceOrigin.getLocation().toString());',
        'result.put("phase", "constructing");',
        'star.common.StarMacro sourceMacro = new ' + name + '();',
        'result.put("phase", "binding_context");',
        'sourceMacro.setActiveSimulation(sim);',
        'sourceMacro.savePath(new star.base.neo.NeoScriptFile(new java.io.File(' + source + ')));',
        'result.put("phase", "executing");',
        'sourceMacro.execute();',
        'result.put("phase", "entrypoint_returned");',
        'result.put("entrypoint_returned", true);',
    ])


def step_metadata(step):
    """源码步骤的完成依据是入口返回，不把没有结构化业务输出当成完整读取。"""
    metadata = {key: step[key] for key in ('id', 'scope', 'effect')}
    metadata['status'] = 'not_started'
    if 'macro' in step:
        metadata.update(program_kind='source_macro', completion_basis='entrypoint_returned',
                        entry_class=step['macro']['entry_class'], entry_source=step['macro']['entry_source'])
    return metadata


def render(state, request, result):
    """将数据与源码分别填入入口和延迟初始化的 Payload，不把用户声明放入入口类。

    只替换原模板，参数文本不会再次解释为占位符。身份与全部对象参数绑定通过后，
    Java 入口先写初始化凭据再创建 Payload；源码完整权限不因移动类位置变成沙箱。
    """
    template = Path(__file__).resolve().parents[1] / 'java' / 'StarBridgeProgram.java'
    version = session_version(state)
    values = {
        'RESULT': java_literal(str(result)),
        'EXPECTED_KEY': java_literal(state['simulation_key']),
        'RELEASE': java_literal(version['release']),
        'BUILD': java_literal(version['build']),
        'REQUEST_ID': java_literal(request['request_id']),
        'INITIALIZATION_EFFECT': java_literal(declared_effect(request)),
        'PARAMETERS': java_literal(request['parameters']),
        'IMPORTS': '\n'.join('import ' + item + ';' for item in request['imports']),
        'DECLARATIONS': request['declarations'],
        'OBJECT_BINDING_SETUP': '\n'.join(
            'bindParameter(' + java_literal(entry['path']) + ', DiscoveryRuntime.resolveObject(sim, '
            + java_literal(entry['binding']) + ', ' + java_literal(state['session_token']) + '));'
            for entry in request.get('object_bindings', [])),
        'STEP_METADATA': '\n'.join('steps.add(' + java_literal(step_metadata(step))
                                  + ');' for step in request['steps']),
        'STEP_CASES': '\n'.join(f'case {index}: step{index}(result); break;'
                                for index in range(len(request['steps']))),
        'STEP_METHODS': '\n'.join(
            f'private void step{index}(Map<String, Object> result) throws Exception {{\n{step_body(step, Path(result).parent / "classes")}\n}}'
            for index, step in enumerate(request['steps'])),
    }
    # 只重命名受信模板中的包装类，不触碰原宏源码、普通步骤代码或任何参数文本。
    skeleton = source_text(template).replace('StarBridgeProgram', program_class(request))
    text = re.sub(r'__([A-Z_]+)__', lambda match: values[match.group(1)], skeleton)
    if request.get('object_bindings'):
        # 仅对象参数需要公共身份解析器。无绑定的通用宏仍不依赖结构化发现辅助类。
        # 此处只调用不设精确版本门槛的 resolveObject；安装JDK校验直接引用，固定registry签名在运行时检查。
        helper = source_text(template.with_name('DiscoveryRuntime.java'))
        text += '\n' + helper.replace('public class DiscoveryRuntime {', 'class DiscoveryRuntime {', 1)
    return text


def render_launch(request, directory):
    """生成无用户类型编译引用的入口；冻结依赖只在入口编译完成后进入独立运行加载器。"""
    name = 'StarBridgeLaunch_' + request['fingerprint'][:20]
    runtime_paths = [directory / 'classes', *(directory / item['relative_path']
        for item in request.get('source_bundle', {}).get('dependencies', []))]
    values = {'LAUNCH_CLASS': name, 'PROGRAM_CLASS': java_literal(program_class(request)),
              'PROGRAM_SOURCE': java_literal(str(directory / (program_class(request) + '.java'))),
              'CLASSES': java_literal(str(directory / 'classes')),
              'LOCAL_DISCOVERY': java_literal(bool(request.get('object_bindings'))),
              'RUNTIME_PATHS': 'new String[] {' + ', '.join(java_literal(str(path)) for path in runtime_paths) + '}'}
    template = Path(__file__).resolve().parents[1] / 'java' / 'StarBridgeLaunch.java'
    return name, re.sub(r'__([A-Z_]+)__', lambda match: values[match.group(1)], source_text(template))


def jar_classes(path):
    """只索引二进制类型，不将资源重名当成冲突；多版本 JAR 映射到其实际类名。"""
    try:
        with zipfile.ZipFile(path) as archive:
            result = set()
            for name in archive.namelist():
                if name.startswith('META-INF/versions/'):
                    parts = name.split('/', 3)
                    name = parts[3] if len(parts) == 4 and parts[2].isdigit() else ''
                if name.endswith('.class') and not name.startswith('META-INF/') and name != 'module-info.class':
                    result.add(name)
            return result
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError(f'Cannot inspect Java class names in {path}: {error}') from error


@lru_cache(maxsize=4)
def installed_classes(signature):
    """缓存少量实际安装的类索引，任一库文件身份或内容相关元数据变化即重新读取。"""
    result = {}
    for path, *_ in signature:
        for name in jar_classes(path):
            result.setdefault(name, path)
    return result


def check_class_conflicts(jars, classpath, classes):
    """拒绝来源间重复类，避免 javac、STAR 编译器与运行类加载器选择不同定义。

    不提供覆盖安装类或逐步骤切换库版本的语义。即使重复定义当前字节相同也拒绝，
    以免把类所属 JAR、资源或后续升级顺序隐式当成可交换；错误指出类型及两侧路径。
    """
    signature = []
    for path in jars:
        info = path.stat()
        signature.append((str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
    installed = installed_classes(tuple(signature))
    selected = {}

    def register(name, source):
        previous = installed.get(name) or selected.get(name)
        if previous is not None:
            raise ValueError(f'Conflicting Java class {name}: {previous} and {source}; use one compatible definition')
        selected[name] = str(source)

    for path in classpath:
        for name in sorted(jar_classes(path)):
            register(name, path)
    for path in sorted(classes.rglob('*.class')):
        register(path.relative_to(classes).as_posix(), path)


def compile_program(star, macro, directory, timeout, *, sources=(), classpath=(), generated_sources=()):
    """一次编译用户程序与生成的薄启动，供客户端直接加载本请求的class。

    仅纯code在无法定位安装JDK时保留STAR自行编译的兼容路径；源码/JAR请求仍须拒绝。
    generated_sources是受信执行器生成的入口，不把它误算为用户多文件请求而取消该回退；
    编译失败不能回退重试。带辅助单元的编译使用空sourcepath，不隐式编译旁边的源码。
    私有空processorpath隔绝编译classpath的插件发现；这不是运行代码沙箱。
    """
    executable = shutil.which(star)
    installation = _installation(str(Path(executable).resolve())) if executable else None
    if installation is None:
        if sources or classpath:
            raise ValueError('Full-source macros require the selected installation JDK and libraries before dispatch')
        # 包装脚本不解析内容；由 STAR 自己编译，但此时编译失败不能预先证明没有运行。
        return {'status': 'deferred_to_star', 'reason': 'Installation JDK was not located'}
    root, compiler, jars = installation
    classes = directory / 'classes'
    classes.mkdir()
    dependencies = list(jars) + list(classpath)
    if any(os.pathsep in str(path) for path in dependencies):
        raise ValueError('Classpath file paths must not contain the platform classpath separator')
    source_options = []
    explicit_sources = bool(sources or classpath or generated_sources)
    if explicit_sources:
        empty_sourcepath = directory / 'empty-sourcepath'
        empty_sourcepath.mkdir()
        # 带薄启动的纯code也只编译显式单元；不改变其他调用者的既有单文件生命周期编译。
        source_options = ['-sourcepath', str(empty_sourcepath), '-implicit:none']
    process = _run_javac(compiler, ['-encoding', 'UTF-8', *source_options,
        '-cp', os.pathsep.join(map(str, dependencies)), '-d', str(classes), str(macro),
        *map(str, sources), *map(str, generated_sources)],
        directory, timeout, env=dict(os.environ, LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8'))
    (directory / 'compile.log').write_text(process.stdout + process.stderr)
    if process.returncode:
        raise ValueError('Macro compilation rejected before execution: ' + process.stderr[-6000:])
    # 生成的启动宏不引入用户依赖；不能仅因增加它就给纯code附加全安装类名扫描。
    if sources or classpath:
        check_class_conflicts(jars, classpath, classes)
    return {'status': 'compiled', 'installation': str(root), 'compiler_isolation': _JAVAC_ISOLATION_POLICY,
            **({'source_lookup': 'explicit_units_only'} if explicit_sources else {}),
            **({'class_conflicts': 'none_observed'} if sources or classpath else {})}


def check_source_entries(request, directory):
    """入口必须在本请求源码的编译输出中，不能仅由依赖 JAR 的同名类满足引用。

    javac 支持静态内部入口类；Java 源码中的 Outer.Inner 与 class 文件的 Outer$Inner
    不同，因此枚举包／嵌套边界，并拒绝多个实际候选，不自行猜测歧义入口。
    """
    for step in request['steps']:
        if 'macro' not in step:
            continue
        name = step['macro']['entry_class']
        parts = name.split('.')
        candidates = [directory / 'classes' / Path(*parts[:index], '$'.join(parts[index:]) + '.class')
                      for index in range(len(parts))]
        matches = [path for path in candidates if path.is_file()]
        if len(matches) != 1:
            raise ValueError(f'Entry class must be produced unambiguously by the source bundle: {name}')


def final_receipt(path):
    """只接受属于本请求的有效明确终态；损坏或中间凭据不能解除未知写入。"""
    from starbridge.core.execution_receipt import load_receipt, final_document
    path = Path(path)
    identifier = path.parent.name
    expected = identifier[len('macro-'):] if identifier.startswith('macro-') else None
    return final_document(load_receipt(path, expected))


def star_compiler_classpath(directory, working_directory):
    """给STAR编译入口明确的空用户路径，拒绝实际cwd中可自动发现的javac插件描述符。

    NeoScript未设置独立processorpath，并把用户设置和cwd加入编译classpath。冻结的JAR
    只供编译后运行加载器使用；这里不能仅省略-classpath而回退旧设置。cwd仍保持真实任务
    语义，已存在的描述符（包括软链接）须拒绝，其他查找错误不能当作不存在。
    安装模块、JVM环境和目录仍可信；此检查不防御同权限进程在检查后写入，不构成沙箱。
    """
    provider = Path(working_directory) / 'META-INF' / 'services' / 'com.sun.source.util.Plugin'
    try:
        provider.lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError('Working directory exposes a javac Plugin provider before macro identity checks: ' + str(provider))
    empty = directory / 'star-compiler-classpath'
    if os.pathsep in str(empty):
        raise ValueError('STAR compiler classpath directory must not contain the platform classpath separator')
    empty.mkdir(mode=0o700)
    return empty


def execute(state, directory, request, timeout, on_client_start, *, on_client_launch=None):
    """保留请求与阶段凭据，执行一次客户端；超时只终止本次客户端，不终止算例服务。"""
    result = directory / 'result.json'
    # 渲染校验在占用 ID 之前完成，确定的本地数据错误不会留下无终态的请求目录。
    text = render(state, request, result)
    # 两类请求都准备薄启动候选；实际派发哪一个入口由下面的编译结果决定。
    # 不伪造source_bundle或改变请求指纹，旧请求仍由会话层直接返回原凭据。
    launch_name, launch_text = render_launch(request, directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    # 请求和源码先在临时目录完整准备，再原子发布 ID；中断不能占用一个缺少请求内容的 ID。
    with tempfile.TemporaryDirectory(prefix='.preparing-', dir=directory.parent) as temporary:
        pending = Path(temporary)
        (pending / 'macro-request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2) + '\n')
        (pending / (program_class(request) + '.java')).write_text(text)
        (pending / (launch_name + '.java')).write_text(launch_text)
        source_paths, dependencies = [], []
        if request.get('source_bundle'):
            from starbridge.core.macro_sources import materialize_bundle
            sources, jars = materialize_bundle(request['source_bundle'], pending)
            source_paths = [path.relative_to(pending) for path in sources]
            dependencies = [path.relative_to(pending) for path in jars]
        pending.rename(directory)
    macro = directory / (program_class(request) + '.java')
    sources = [directory / path for path in source_paths]
    launch = directory / (launch_name + '.java')
    classpath = [directory / path for path in dependencies]

    def reject(error):
        """记录已知未派发的准备或启动失败，不把本地错误升级为未知算例修改。"""
        # 完整保留确定未派发的拒绝，重发同一 ID 只返回此凭据而不会再次尝试。
        data = {'status': 'rejected', 'after': {'session_path': state['current_file'],
                'modified': state['modified']}, 'execution': {'request_id': request['request_id'],
                'status': 'rejected', 'uncertain': False,
                'initialization': {'status': 'not_started', 'effect': declared_effect(request),
                                   'scope': 'Caller declarations and payload construction; effect aggregates all declared steps'},
                'steps': [step_metadata(step) for step in request['steps']], 'reason': str(error)}}
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(result)
        return data

    try:
        working_directory = request.get('working_directory', directory)
        compiler_classpath = star_compiler_classpath(directory, working_directory)
        compilation = compile_program(state['star'], macro, directory, min(timeout, 90),
                                      sources=sources, classpath=classpath, generated_sources=[launch])
        check_source_entries(request, directory)
        precompiled = compilation['status'] == 'compiled'
        if precompiled:
            # 明确的本地准备失败仍在派发前拒绝；不能因缺失产物改用旧入口重试。
            for name in (program_class(request), launch_name):
                if not (directory / 'classes' / (name + '.class')).is_file():
                    raise ValueError('Required generated class is absent after compilation: ' + name)
        batch = launch if precompiled else macro
        compilation.update(star_compiler_classpath='private_empty_directory',
                           cwd_plugin_provider='absent_at_preflight',
                           runtime_loading_plan='dedicated_url_loader' if precompiled else 'star_macro_loader',
                           runtime_loader_policy='request_local_generated_families_v1' if precompiled else 'star_managed',
                           star_compiles='generated_launcher_only' if precompiled else 'program_source')
        (directory / 'compilation.json').write_text(json.dumps(compilation) + '\n')
        command = [state['star'], '-noretry', '-nbuserdir', str(directory.parent.parent / 'client-settings'),
                   '-classpath', str(compiler_classpath)]
        command += ['-host', state['host'], '-port', str(state['port']), '-batch', str(batch), '-noexit']
        (directory / 'command.json').write_text(json.dumps(command) + '\n')
        environment = dict(os.environ, LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8')
        log = (directory / 'star.log').open('w')
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return reject(error)
    with log:
        process = None
        try:
            # 派发记录先于Popen；创建和PID登记都受中断处理保护。
            if on_client_launch is not None:
                on_client_launch('attempted')
            try:
                process = subprocess.Popen(command, cwd=working_directory,
                                           env=environment, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            except (OSError, ValueError) as error:
                if on_client_launch is not None:
                    on_client_launch('not_started')
                return reject(error)
            on_client_start(process.pid)
            process.wait(timeout=timeout)
        except BaseException:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            data = final_receipt(result)
            if data is not None:
                # 宏可能已结束，只是客户端退出迟滞。确切终态优先于传输超时，不能永久锁死会话。
                return dict(data, client_returncode=process.returncode if process is not None else None,
                            compilation=compilation, transport_interrupted=True)
            raise RuntimeError(f'Macro client interrupted; inspect the receipt and session before continuing: {directory}')
    data = final_receipt(result)
    if data is None:
        raise RuntimeError(f'Macro has no final receipt; inspect partial steps and {directory / "star.log"}')
    # 已落盘的终态是执行依据；客户端随后退出异常仍单独报告，不重复执行已经完成的步骤。
    data['client_returncode'] = process.returncode
    data['compilation'] = compilation
    return data
