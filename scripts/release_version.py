#!/usr/bin/env python3
"""检查或准备一致的发布版本；不提交、打 tag、推送或创建发布。"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
JSON_FILES = ("package.json", ".codex-plugin/plugin.json", ".claude-plugin/plugin.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", metavar="VERSION", help="prepare a strictly newer X.Y.Z version")
    args = parser.parse_args()
    try:
        files = {name: (ROOT / name).read_text(encoding="utf-8") for name in (*JSON_FILES, "server.json", "src/starbridge/__init__.py")}
        package = json.loads(files["package.json"])
        current = package["version"]
        if not isinstance(current, str) or not SEMVER.fullmatch(current):
            raise ValueError("current package version must be X.Y.Z")
        for name in JSON_FILES:
            if json.loads(files[name]).get("version") != current:
                raise ValueError(f"{name}: version does not match package.json")
        server = json.loads(files["server.json"])
        if (server.get("version") != current or len(server.get("packages", [])) != 1
                or server["packages"][0].get("version") != current
                or server["packages"][0].get("runtimeArguments", [])[0].get("value") != f"starbridge-cfd[mcp]=={current}"):
            raise ValueError("server.json: versions or runtime pin do not match package.json")
        tree = ast.parse(files["src/starbridge/__init__.py"])
        values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)]
        if values != [current]:
            raise ValueError("Python package version does not match package.json")
        if args.set is None:
            print(f"Versions match: {current}")
            return 0
        new = args.set
        if not SEMVER.fullmatch(new) or tuple(map(int, new.split("."))) <= tuple(map(int, current.split("."))):
            raise ValueError("new version must be a strictly newer X.Y.Z version")

        # 1. 先检查全部版本位置，再仅替换结构化发行声明；不改写历史证据中的版本。
        for name in JSON_FILES:
            old = f'"version": "{current}"'
            if files[name].count(old) != 1:
                raise ValueError(f"{name}: unexpected version formatting")
            files[name] = files[name].replace(old, f'"version": "{new}"')
        old = f'"version": "{current}"'
        if files["server.json"].count(old) != 2 or files["server.json"].count(f"starbridge-cfd[mcp]=={current}") != 1:
            raise ValueError("server.json: unexpected version formatting")
        files["server.json"] = files["server.json"].replace(old, f'"version": "{new}"').replace(
            f"starbridge-cfd[mcp]=={current}", f"starbridge-cfd[mcp]=={new}")
        init = files["src/starbridge/__init__.py"]
        pattern = rf"(?m)^__version__ = (['\"]){re.escape(current)}\1$"
        updated, count = re.subn(pattern, f"__version__ = '{new}'", init)
        if count != 1:
            raise ValueError("Python package: unexpected version formatting")
        files["src/starbridge/__init__.py"] = updated

        # 2. 写入声明后由维护者检查文档、工作区和实际发布内容；这里不执行 Git 外部操作。
        for name, text in files.items():
            (ROOT / name).write_text(text, encoding="utf-8")
        print(f"Prepared {current} -> {new}; review all changes and update version-specific documentation before release.")
        return 0
    except (OSError, ValueError, KeyError, IndexError, TypeError, SyntaxError) as error:
        print(f"Version preparation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
