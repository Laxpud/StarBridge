"""从用户指定的程序或有界本机搜索中读取 STAR 版本，不按目录名或支持清单猜版本。

版本探测只调用程序的 -version，不加载算例或创建管理会话。发现安装、具备结构化适配、
通用生命周期预编译与成功接入是不同状态；未登记版本也可检测，但不冒充已受支持。
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from .catalog_bundle import BUNDLES
from .discovery_policy import TARGET


VERSION = re.compile(r'\bSTAR-CCM\+\s+(\S+)\s+Build\s+([^\s(]+)')
DEFAULT_ROOTS = ('/opt/Siemens', '/opt/siemens')


def inspect_installation(star, timeout):
    """读取一个指定启动器的实际版本和本机文档位置，不更换程序或回退产品版本。

    1. 解析用户提供的绝对路径或 PATH 命令，并保留解析后的程序身份。
    2. 运行 -version；保留无法识别或失败结果，不从版本邻近性推断兼容。
    3. 将实际 release/Build 与注册表比较，并独立报告 Javadoc 可定位情况。
    """
    if not isinstance(star, str) or not star or ('/' in star and not Path(star).is_absolute()):
        raise ValueError('star must be an executable name on PATH or an absolute path')
    executable = shutil.which(star)
    result = {'requested_star': star, 'executable': None, 'status': 'not_found',
              'version': None, 'catalog_supported': False, 'runtime_discovery_supported': False,
              'javadoc_root': None, 'runtime_state': 'not_checked',
              'generic_lifecycle': {'preflight': 'not_checked', 'registered_catalog_required': False,
                                    'requires': ['selected_installation_JDK_compilation', 'server_identity_check']}}
    if executable is None:
        result['reason'] = 'Executable was not found or is not executable'
        return result
    # 保留调用路径：某些启动器按 argv[0] 区分版本，不能把解析符号链接变成更换启动命令。
    executable = Path(executable).absolute()
    resolved_executable = executable.resolve()
    result['executable'] = str(executable)
    result['resolved_executable'] = str(resolved_executable)
    result['command'] = [str(executable), '-version']
    # 文档定位与现有发现规则一致：解析符号链接，但不解析外部包装脚本内容。
    result['javadoc_root'] = next((str(parent) for parent in resolved_executable.parents
        if (parent / 'doc/client/html/type-search-index.js').is_file()), None)
    try:
        completed = subprocess.run(result['command'], capture_output=True, text=True,
                                   errors='replace', timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {**result, 'status': 'timeout', 'reason': 'STAR version query timed out'}
    except OSError as error:
        return {**result, 'status': 'command_failed', 'reason': str(error)}
    output = completed.stdout + '\n' + completed.stderr
    result.update(returncode=completed.returncode, version_output=output.strip()[:4096],
                  output_truncated=len(output.strip()) > 4096)
    if completed.returncode != 0:
        return {**result, 'status': 'command_failed', 'reason': 'STAR version query returned a nonzero exit code'}
    versions = set(VERSION.findall(output))
    if len(versions) != 1:
        return {**result, 'status': 'unrecognized_version',
                'reason': 'Expected one unambiguous STAR release/Build in -version output; no version was inferred'}
    release, build = versions.pop()
    version = {'release': release, 'build': build}
    return {**result, 'status': 'ok', 'version': version,
            'catalog_supported': BUNDLES.get(release) == build,
            'runtime_discovery_supported': version == TARGET,
            'discovery_environment_ready': version == TARGET and result['javadoc_root'] is not None}


def discover_installations(star=None, search_roots=None, timeout=30):
    """枚举有限范围内的安装候选并探测版本，不自动替用户选择安装。

    显式 star 只探测该程序。否则检查 PATH 中的 starccm+ 和指定安装根目录，
    根目录未给出时使用常见厂商目录；只匹配有限层级、最多探测 20 个不同调用路径。
    结果报告搜索范围与截断，未找到不能解释为整台机器未安装 STAR。
    """
    if star is not None and search_roots is not None:
        raise ValueError('Provide star or search_roots, not both')
    roots = list(DEFAULT_ROOTS) if search_roots is None else search_roots
    if not isinstance(roots, list) or len(roots) > 20 or any(
            not isinstance(root, str) or not Path(root).is_absolute() for root in roots):
        raise ValueError('search_roots must contain at most 20 absolute directory paths')
    started = time.monotonic()
    candidates, seen, truncations, errors = [], set(), [], []

    def add(candidate, source):
        """按绝对调用路径去重，保留可能按 argv[0] 选择版本的别名；上限之外不继续探测。"""
        resolved = shutil.which(str(candidate))
        if resolved is None:
            return
        resolved = str(Path(resolved).absolute())
        if resolved in seen:
            return
        if len(candidates) >= 20:
            if 'max_candidates' not in truncations:
                truncations.append('max_candidates')
            return
        seen.add(resolved)
        candidates.append((resolved, source))

    if star is not None:
        result = inspect_installation(star, timeout)
        return {'installations': [result], 'selection': 'user_supplied', 'auto_selected': False,
                'coverage': {'mode': 'explicit_executable', 'whole_machine_complete': False}}
    # PATH 的当前默认命令优先呈现，但发现多个安装不代表获准切换用户指定的版本。
    for directory in os.get_exec_path():
        add(Path(directory) / 'starccm+', 'PATH')
    patterns = ('star/bin/starccm+', 'bin/starccm+', 'STAR-CCM+*/star/bin/starccm+',
                '*/star/bin/starccm+', '*/STAR-CCM+*/star/bin/starccm+')
    for root in roots:
        try:
            for pattern in patterns:
                for candidate in Path(root).glob(pattern):
                    if len(candidates) >= 20 or time.monotonic() - started >= timeout:
                        truncations.append('search_budget')
                        break
                    add(candidate, root)
        except OSError as error:
            errors.append({'root': root, 'message': str(error)})
    installations = []
    for candidate, source in candidates:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            truncations.append('time_budget')
            break
        installations.append({**inspect_installation(candidate, remaining), 'found_via': source})
    return {'installations': installations, 'selection': 'required', 'auto_selected': False,
            'coverage': {'mode': 'PATH_and_installation_roots', 'search_roots': roots,
                         'candidate_count': len(candidates), 'probed_count': len(installations),
                         'truncations': sorted(set(truncations)), 'errors': errors,
                         'whole_machine_complete': False},
            'next_step': '按用户指定版本和任务选择 executable；用实际 version 查询 get_capabilities。多个不同版本无法由任务决定时再询问用户。'}
