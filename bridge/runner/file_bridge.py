#!/usr/bin/env python3
"""调用本机 STAR 批处理宏，读取文件或修改标量参数后另存并重新加载核对。"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys


def digest(path):
    """对文件流式计算摘要，核对源算例在操作前后未发生变化。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def execute(star, source, directory, output=None, name="", value=0.0, unit="", *,
            action=None, host=None, port=None, expected_session="", timeout=None,
            client_userdir=None):
    """生成宏并调用短生命周期客户端；会话模式只连接指定服务，不传入文件。"""
    directory.mkdir(parents=True, exist_ok=False)
    result = directory / "result.json"
    template = Path(__file__).resolve().parents[1] / "java" / "BridgeFileMacro.java"
    macro = directory / "BridgeFileMacro.java"
    replacements = {
        "__RESULT__": str(result),
        "__ACTION__": action or ("file-set" if output else "inspect"),
        "__EXPECTED_SESSION__": str(expected_session),
        "__OUTPUT__": str(output) if output else "",
        "__NAME__": name,
        "__UNIT__": unit,
        "__VALUE__": value,
    }
    text = template.read_text()
    # 一次替换原模板中的占位符，避免用户文本被后续占位符替换再次解释。
    text = re.sub(r"__(?:RESULT|ACTION|EXPECTED_SESSION|OUTPUT|NAME|UNIT|VALUE)__",
                  lambda match: json.dumps(replacements[match.group()], ensure_ascii=True),
                  text)
    macro.write_text(text)
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
    if data.get("status") != "ok":
        raise RuntimeError(f"Invalid macro result: {result}")
    return data


def main():
    """处理文件操作请求；输出目录必须全新，已有文件不被覆盖。"""
    parser = argparse.ArgumentParser(
        description="Inspect simulation parameters or set a scalar and verify a saved copy.")
    parser.add_argument("action", choices=["inspect", "set-scalar"])
    parser.add_argument("input", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--star", default="starccm+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--value", type=float)
    parser.add_argument("--unit")
    args = parser.parse_args()
    source = args.input.resolve(strict=True)
    directory = args.work_dir.resolve()
    output = args.output.resolve() if args.output else None
    if args.action == "set-scalar":
        if output is None or args.name is None or args.value is None or args.unit is None:
            parser.error("set-scalar requires --output, --name, --value and --unit")
        if not math.isfinite(args.value):
            parser.error("--value must be finite")
        if output.exists() or output == source or output.suffix != ".sim":
            parser.error("--output must be a new .sim file distinct from the input")
        if not output.parent.is_dir():
            parser.error("--output parent directory must exist")
    elif any(item is not None for item in [output, args.name, args.value, args.unit]):
        parser.error("inspect does not accept modification arguments")
    directory.mkdir(parents=True, exist_ok=False)

    # 1. 为本次调用记录原文件摘要；不复制或重命名用户原始文件。
    original = digest(source)
    try:
        data = execute(args.star, source, directory / "apply", output,
                       args.name or "", args.value or 0.0, args.unit or "")
        summary = {"input": str(source), "input_sha256": original, "action": args.action}
        if output:
            # 2. 重新启动 STAR 加载输出文件；验证落盘结果，而非只看内存回读。
            reopened = execute(args.star, output, directory / "reopen")["after"]
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
    print(directory / "summary.json")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(f"StarBridge error: {error}", file=sys.stderr)
        sys.exit(1)
