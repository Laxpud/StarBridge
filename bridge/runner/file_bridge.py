#!/usr/bin/env python3
"""调用本机 STAR 批处理宏，读取算例对象或按请求修改，另存后重新加载核对。"""

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid

# 直接运行脚本时 Python 只加入 runner 目录；显式加入仓库根以复用共享 Core。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modifier import (ModificationRejected, content_snapshot, java_literal, load_request,
                      same_value, snapshot_diff, verify_modification)
from core.execution import prepare_legacy
from core.snapshot import prepare_snapshot


def digest(path):
    """对文件流式计算摘要，核对源算例在操作前后未发生变化。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_catalog_read(catalog, execution, request, action):
    """在创建文件工作目录或会话活动标记之前，校验目录并裁剪本次只读计划。"""
    from core.execution import prepare_read
    return prepare_read(catalog, execution, request, action)


def prepare_catalog_modification(catalog, execution, request):
    """在创建工作目录或活动标记前，校验目录修改请求并形成小型执行计划。"""
    from core.execution import prepare_modification
    return prepare_modification(catalog, execution, request)


def catalog_readback(plan, request):
    """将修改计划转成重载核对所需的只读计划；新加载不能沿用旧会话引用。"""
    readonly = deepcopy(plan)
    for properties in readonly['properties'].values():
        for property_plan in properties.values():
            property_plan.pop('write', None)
    # 操作计划已按其声明裁剪读取字段；重载只核对这些状态，不携带结构修改入口。
    readonly.pop('operations', None)

    def locator(target):
        """只移除目标契约明确规定的会话引用，不处理属性值中的同名字段。"""
        result = {key: value for key, value in target.items() if key != 'reference'}
        if 'parent' in result:
            result['parent'] = locator(result['parent'])
        return result

    return readonly, {'schema_version': 1, 'action': 'read', 'target': locator(request['target'])}


def catalog_content(catalog, plan, *, retain_references=False):
    """提取目标和属性内容；重载时规范化引用，同会话 Diff 则保留对象身份。"""
    if not catalog.get('inspection_complete'):
        raise RuntimeError('Catalog modification verification requires complete property reads')

    def reference(value):
        """只去掉对象引用协议中的世代和 key；其他字典内容必须完整保留。"""
        if (isinstance(value, dict) and set(value) == {'name', 'java_class', 'reference'}
                and isinstance(value['reference'], dict)
                and set(value['reference']) == {'session_token', 'key'}):
            return {key: value[key] for key in ('name', 'java_class')}
        return value

    def predicate(value):
        """仅规范化标签及身份集合的对象引用；组合顺序和其他规则字段保持不变。"""
        if not isinstance(value, dict):
            return value
        if value.get('type') == 'tag' and 'value' in value:
            return dict(value, value=reference(value['value']))
        if value.get('type') == 'identity' and isinstance(value.get('value'), list):
            return dict(value, value=[reference(item) for item in value['value']])
        if value.get('type') == 'compound' and isinstance(value.get('predicates'), list):
            return dict(value, predicates=[predicate(item) for item in value['predicates']])
        return value

    target = catalog['target']
    properties = {}
    for name, result in catalog['properties'].items():
        if result.get('status') != 'ok':
            raise RuntimeError(f'Catalog property was not read successfully: {name}')
        value = result['value']
        adapter = plan['properties'][target['type']][name]['adapter']
        if retain_references:
            pass
        elif adapter == 'reference':
            value = reference(value)
        elif adapter in ('collection', 'tensor_components', 'tensor_axes') and isinstance(value, list):
            value = [reference(item) for item in value]
        elif (adapter == 'query' and isinstance(value, dict)
              and value.get('mode') == 'static' and isinstance(value.get('objects'), list)):
            value = dict(value, objects=[reference(item) for item in value['objects']])
        elif (adapter == 'query' and isinstance(value, dict)
              and value.get('mode') == 'query' and 'predicate' in value):
            value = dict(value, predicate=predicate(value['predicate']))
        elif adapter in ('tensor_profile', 'tensor_basis', 'tensor_method_state', 'tensor_method_basis',
                         'tensor_axis_basis') and isinstance(value, dict):
            # 只规范明确的方向坐标系引用；轴维数、原始向量和其他元数据仍完整核对。
            value = {**value, **{key: reference(value[key]) for key in
                                ('coordinate_system', 'local_orientation') if key in value}}
            if isinstance(value.get('direction_axes'), list):
                value = {**value, 'direction_axes': [
                    {**axis, 'coordinate_system': reference(axis['coordinate_system'])}
                    if isinstance(axis, dict) and 'coordinate_system' in axis else axis
                    for axis in value['direction_axes']]}
        properties[name] = dict(result, value=value)
    stable_target = {key: target[key] for key in ('type', 'name', 'java_class', 'locator')}
    if retain_references:
        stable_target['reference'] = target['reference']
    return {'target': stable_target, 'properties': properties}


def catalog_diff(before, after, plan):
    """同会话记录 key 变化；跨加载只比较可重定位内容，不将新世代误报为修改。"""
    same_session = before['runtime']['session_token'] == after['runtime']['session_token']
    return snapshot_diff(catalog_content(before, plan, retain_references=same_session),
                         catalog_content(after, plan, retain_references=same_session))


def reload_legacy(star, output, directory, data, plan, snapshot_plan):
    """独立加载旧入口的输出，同时核对共享目录属性与原有完整快照。

    旧请求不必提供目录定位；宏已返回唯一解析的 locator，用它建立重载只读
    请求。原有结果字段由调用方保留，新增目录核对不能弱化旧 expected 契约。
    """
    readonly, request = catalog_readback(plan, {'target': data['catalog']['target']['locator']})
    reopened = execute(star, output, directory, action='catalog-verify',
                       catalog_plan=readonly, catalog_request=request, snapshot_plan=snapshot_plan)
    if reopened['status'] != 'ok':
        raise RuntimeError(f'Legacy reload verification was rejected: {reopened.get("error")}')
    if not same_value(content_snapshot(data['after']), content_snapshot(reopened['after'])):
        raise RuntimeError('Reopened object snapshot differs from saved session')
    if not same_value(catalog_content(data['catalog'], plan),
                      catalog_content(reopened['catalog'], readonly)):
        raise RuntimeError('Reopened catalog values differ from saved session')
    return reopened


def execute(star, source, directory, output=None, name="", value=0.0, unit="", *,
            action=None, host=None, port=None, expected_session="", timeout=None,
            client_userdir=None, modification=None, catalog_plan=None,
            catalog_request=None, session_token=None, legacy_plan=None, snapshot_plan=None):
    """生成宏并调用短生命周期客户端；会话模式只连接指定服务，不传入文件。"""
    catalog_actions = {'catalog-read': 'read', 'catalog-describe': 'describe',
                       'catalog-verify': 'read', 'catalog-modify': 'modify',
                       'file-catalog-modify': 'modify'}
    catalog_call = catalog_plan is not None or catalog_request is not None or action in catalog_actions
    actual_action = action or ('file-set' if output else 'inspect')
    snapshot_call = actual_action in {'inspect', 'save', 'modify', 'file-modify', 'set-scalar',
                                     'file-set', 'catalog-verify', 'catalog-modify', 'file-catalog-modify'}
    if snapshot_call != (snapshot_plan is not None):
        raise ValueError('Snapshot actions require their bundled snapshot plan')
    legacy_call = actual_action in {'modify', 'file-modify', 'set-scalar', 'file-set'}
    if legacy_call != (legacy_plan is not None):
        raise ValueError('Legacy modification requires its bundled catalog plan')
    if legacy_call and catalog_call:
        raise ValueError('Legacy and catalog requests cannot be combined')
    if catalog_call:
        if (catalog_plan is None or not isinstance(catalog_request, dict)
                or action not in catalog_actions
                or catalog_request.get('action') != catalog_actions[action]
                or modification is not None):
            raise ValueError('Catalog operation requires a matching plan, request and action')
        if (action == 'file-catalog-modify') != (output is not None):
            raise ValueError('Only file-catalog-modify requires an output file')
    directory.mkdir(parents=True, exist_ok=False)
    result = directory / "result.json"
    template = Path(__file__).resolve().parents[1] / "java" / "BridgeFileMacro.java"
    macro = directory / "BridgeFileMacro.java"
    replacements = {
        "__RESULT__": str(result),
        "__ACTION__": actual_action,
        "__EXPECTED_SESSION__": str(expected_session),
        "__OUTPUT__": str(output) if output else "",
        "__NAME__": name,
        "__UNIT__": unit,
        "__VALUE__": value,
        # 文件模式每次加载都有独立世代；后台会话传入持久 token，不跨重载复用引用。
        "__SESSION_TOKEN__": session_token or uuid.uuid4().hex,
    }
    # 修改请求单独留存；Java 容器源码由已校验 JSON 生成，不接收任意 Java 片段。
    if modification is not None:
        (directory / "request.json").write_text(
            json.dumps(modification, ensure_ascii=False, indent=2) + "\n")
    if catalog_call:
        (directory / "catalog-plan.json").write_text(
            json.dumps(catalog_plan, ensure_ascii=False, indent=2) + "\n")
        (directory / "catalog-request.json").write_text(
            json.dumps(catalog_request, ensure_ascii=False, indent=2) + "\n")
    if legacy_plan is not None:
        (directory / 'legacy-plan.json').write_text(
            json.dumps(legacy_plan, ensure_ascii=False, indent=2) + '\n')
    if snapshot_plan is not None:
        (directory / 'snapshot-plan.json').write_text(
            json.dumps(snapshot_plan, ensure_ascii=False, indent=2) + '\n')
    containers = {"__MODIFICATION__": modification, "__CATALOG_PLAN__": catalog_plan,
                  "__CATALOG_REQUEST__": catalog_request, "__LEGACY_PLAN__": legacy_plan,
                  "__SNAPSHOT_PLAN__": snapshot_plan}
    text = template.read_text()
    # 一次替换原模板中的占位符，避免用户文本被后续占位符替换再次解释。
    text = re.sub(r"__(?:RESULT|ACTION|EXPECTED_SESSION|OUTPUT|NAME|UNIT|VALUE|MODIFICATION|CATALOG_PLAN|CATALOG_REQUEST|SESSION_TOKEN|LEGACY_PLAN|SNAPSHOT_PLAN)__",
                  lambda match: java_literal(containers[match.group()]) if match.group() in containers
                  else json.dumps(replacements[match.group()], ensure_ascii=True),
                  text)
    # STAR 当前只接收一个宏源文件；辅助类与宏一起编译，不依赖同目录自动找类。
    runtime = template.with_name("CatalogRuntime.java").read_text()
    macro.write_text(text + "\n" + runtime)
    command = [star, "-noretry", "-nbuserdir",
               str(client_userdir or directory / "star-user")]
    if host is not None:
        command += ["-host", host, "-port", str(port), "-batch", str(macro), "-noexit"]
    else:
        command += ["-np", "1", "-batch", str(macro), str(source)]
    (directory / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    with (directory / "star.log").open("w") as log:
        # 本机 C.UTF-8 下 STAR 数值格式提供器出现递归；仅对子进程使用英文区域。
        environment = os.environ.copy()
        environment.update(LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")
        process = subprocess.Popen(command, cwd=directory, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            # 只终止本次创建的客户端进程组，不触碰独立运行的后台服务。
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise RuntimeError(f"Client interrupted; operation outcome may be unknown; see {directory}")
    if process.returncode != 0 or not result.is_file():
        raise RuntimeError(f"STAR did not complete the macro; see {directory / 'star.log'}")
    data = json.loads(result.read_text())
    if data.get("status") != "ok" and not (
            (modification is not None or catalog_call or legacy_call or snapshot_call)
            and data.get("status") == "rejected"):
        raise RuntimeError(f"Invalid macro result: {result}")
    return data


def main():
    """处理文件操作请求；输出目录必须全新，已有文件不被覆盖。"""
    parser = argparse.ArgumentParser(
        description="Inspect simulation objects or modify and verify a saved copy.")
    parser.add_argument("action", choices=["inspect", "describe", "read", "set-scalar", "modify"])
    parser.add_argument("input", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--star", default="starccm+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--value", type=float)
    parser.add_argument("--unit")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--execution", type=Path)
    args = parser.parse_args()
    source = args.input.resolve(strict=True)
    directory = args.work_dir.resolve()
    output = args.output.resolve() if args.output else None
    modification = None
    catalog_plan = catalog_request = None
    legacy_plan = None
    if args.action in ("describe", "read"):
        if any(item is None for item in (args.catalog, args.execution, args.request)):
            parser.error("describe/read require --catalog, --execution and --request")
        catalog_plan, catalog_request = prepare_catalog_read(
            args.catalog, args.execution, args.request, args.action)
    elif args.action == "modify":
        if args.request is None or output is None:
            parser.error("modify requires --request and --output")
        if any(item is not None for item in [args.name, args.value, args.unit]):
            parser.error("modify does not accept --name, --value or --unit")
        if args.catalog is not None or args.execution is not None:
            if args.catalog is None or args.execution is None:
                parser.error('Catalog modify requires both --catalog and --execution')
            catalog_plan, catalog_request = prepare_catalog_modification(
                args.catalog, args.execution, args.request)
        else:
            modification = load_request(args.request)
            legacy_plan = prepare_legacy(modification)
    elif args.catalog is not None or args.execution is not None:
        parser.error("--catalog and --execution are only supported by describe/read/modify")
    elif args.request is not None:
        parser.error("--request is only supported by modify, describe or read")
    if args.action == "set-scalar":
        if output is None or args.name is None or args.value is None or args.unit is None:
            parser.error("set-scalar requires --output, --name, --value and --unit")
        if not math.isfinite(args.value):
            parser.error("--value must be finite")
        legacy_plan = prepare_legacy()
    if args.action in ("set-scalar", "modify"):
        if output.exists() or output == source or output.suffix != ".sim":
            parser.error("--output must be a new .sim file distinct from the input")
        if not output.parent.is_dir():
            parser.error("--output parent directory must exist")
    elif any(item is not None for item in [output, args.name, args.value, args.unit]):
        parser.error("Read-only actions do not accept modification arguments")
    # 兼容快照也来自共享目录；在建立工作目录前校验全部只读映射。
    snapshot_plan = prepare_snapshot() if args.action in ('inspect', 'modify', 'set-scalar') else None
    directory.mkdir(parents=True, exist_ok=False)

    # 1. 为本次调用记录原文件摘要；不复制或重命名用户原始文件。
    original = digest(source)
    try:
        data = execute(args.star, source, directory / "apply", output,
                       args.name or "", args.value or 0.0, args.unit or "",
                       action=("file-catalog-modify" if catalog_plan is not None and args.action == 'modify'
                               else "catalog-" + args.action if catalog_plan is not None
                               else "file-modify" if modification else None),
                       modification=modification, catalog_plan=catalog_plan,
                       catalog_request=catalog_request, legacy_plan=legacy_plan, snapshot_plan=snapshot_plan)
        if data["status"] == "rejected":
            raise ModificationRejected(f'{data["error"]}; see {directory / "apply" / "result.json"}')
        summary = {"input": str(source), "input_sha256": original, "action": args.action}
        if catalog_plan is not None and args.action == 'modify':
            # 2. 新目录写入先在宏中回读，再独立重载同一输出，同时核对旧快照与目录属性。
            read_plan, read_request = catalog_readback(catalog_plan, catalog_request)
            reopened = execute(args.star, output, directory / 'reopen', action='catalog-verify',
                               catalog_plan=read_plan, catalog_request=read_request, snapshot_plan=snapshot_plan)
            if reopened['status'] != 'ok':
                raise RuntimeError(f'Catalog reload verification was rejected: {reopened.get("error")}')
            if not same_value(content_snapshot(data['after']), content_snapshot(reopened['after'])):
                raise RuntimeError('Reopened object snapshot differs from saved session')
            if not same_value(catalog_content(data['catalog'], catalog_plan),
                              catalog_content(reopened['catalog'], read_plan)):
                raise RuntimeError('Reopened catalog values differ from saved session')
            summary.update(output=str(output), modification=catalog_request,
                           catalog_before=data['catalog_before'], catalog=reopened['catalog'],
                           snapshot=reopened['after'], reopened_snapshot_match=True,
                           reopened_catalog_match=True,
                           snapshot_diff=snapshot_diff(data['before'], reopened['after']),
                           catalog_diff=catalog_diff(data['catalog_before'], reopened['catalog'], catalog_plan))
        elif catalog_plan is not None:
            summary["catalog"] = data["catalog"]
        elif modification:
            # 2. 旧 schema 1 保留目标验证，并通过共享目录核对全部已覆盖对象。
            verify_modification(modification, data["before"], data["after"])
            loaded = reload_legacy(args.star, output, directory / 'reopen', data, legacy_plan, snapshot_plan)
            reopened = loaded['after']
            verify_modification(modification, data["before"], reopened)
            summary.update(output=str(output), modification=modification,
                           reopened_snapshot_match=True, snapshot=reopened,
                           snapshot_diff=snapshot_diff(data["before"], reopened),
                           catalog_before=data['catalog_before'], catalog=loaded['catalog'],
                           reopened_catalog_match=True,
                           catalog_diff=catalog_diff(data['catalog_before'], loaded['catalog'], legacy_plan))
        elif output:
            # 2. 重新启动 STAR 加载输出文件；验证落盘结果，而非只看内存回读。
            loaded = reload_legacy(args.star, output, directory / 'reopen', data, legacy_plan, snapshot_plan)
            reopened = loaded['after']
            before = {p["name"]: p for p in data["before"]["parameters"]}
            after = {p["name"]: p for p in reopened["parameters"]}
            saved = {p["name"]: p for p in data["after"]["parameters"]}
            if saved != after:
                raise RuntimeError("Reopened parameter snapshot differs from saved session")
            target = after[args.name]
            actual = target.get("raw_value")
            if (target.get("unit") != args.unit or not isinstance(actual, (int, float))
                    or not math.isclose(actual, args.value, rel_tol=1e-12, abs_tol=1e-12)):
                raise RuntimeError("Reopened target does not match the requested value/unit")
            summary.update(output=str(output), reopened_parameters_match=True,
                           reopened_snapshot_match=True, reopened_catalog_match=True,
                           catalog_before=data['catalog_before'], catalog=loaded['catalog'],
                           catalog_diff=catalog_diff(data['catalog_before'], loaded['catalog'], legacy_plan),
                           parameter_diff=[
                               {"name": name, "before": before.get(name), "after": after.get(name)}
                               for name in sorted(before.keys() | after.keys())
                               if before.get(name) != after.get(name)
                           ])
        else:
            summary["snapshot"] = data["after"]
    finally:
        # 3. 即使执行失败也核对输入；不把宏失败误报成已完成。
        if digest(source) != original:
            raise RuntimeError("Input file changed during execution")
    summary["input_unchanged"] = True
    (directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    # 部分读取仍保留成功字段与原文件核对结果，同时提示调用方检查错误位置。
    if not data["after"].get("inspection_complete", True):
        print("StarBridge warning: Inspection is incomplete; check snapshot read_errors.",
              file=sys.stderr)
    if not data.get("catalog", {}).get("inspection_complete", True):
        print("StarBridge warning: Catalog inspection is incomplete; check property errors.",
              file=sys.stderr)
    print(directory / "summary.json")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(f"StarBridge error: {error}", file=sys.stderr)
        sys.exit(1)
