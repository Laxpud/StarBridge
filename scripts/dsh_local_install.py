#!/usr/bin/env python3
"""把当前工作区打包为 DSH bundle，并按用户指定的 profile 安装。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "@laxpud/dsh-starbridge"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="DSH profile to modify; required unless --pack-only is used")
    parser.add_argument("--pack-only", action="store_true", help="only create the local package")
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "starbridge/dsh-packages",
        help="persistent directory for package snapshots (default: XDG_DATA_HOME/starbridge/dsh-packages)",
    )
    args = parser.parse_args()
    if not args.pack_only and not args.profile:
        parser.error("--profile is required unless --pack-only is used")
    if args.profile and (args.profile in {".", "..", "node_modules"} or args.profile.startswith("-")
                         or args.profile != args.profile.strip() or "/" in args.profile or "\\" in args.profile):
        parser.error("invalid DSH profile name")

    # 1. 每次保留独立的快照路径：profile 的 file: 来源可能需要在日后重新安装时读取它。
    # 不使用固定文件名覆盖旧内容，避免同版本源码变更时沿用旧包或破坏其他 profile 的来源。
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_dir = args.output_dir.resolve()
        snapshot_dir = Path(tempfile.mkdtemp(prefix="starbridge-", dir=output_dir))
        print(f"Source: {ROOT}", flush=True)
        print(f"Package directory: {snapshot_dir}", flush=True)
        if not args.pack_only:
            print(f"DSH profile: {args.profile} (DSH_HOME={os.environ.get('DSH_HOME') or '~/.dsh'})", flush=True)
        result = subprocess.run(
            ["npm", "pack", "--ignore-scripts", "--json", "--pack-destination", str(snapshot_dir)],
            cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE,
        )
        records = json.loads(result.stdout)
        if len(records) != 1 or records[0].get("name") != PACKAGE_NAME:
            raise ValueError("npm pack returned an unexpected package")
        filename = records[0]["filename"]
        if Path(filename).name != filename or not filename.endswith(".tgz"):
            raise ValueError("npm pack returned an invalid package filename")
        package = snapshot_dir / filename
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        print(f"Package: {package}\nSHA256: {digest}", flush=True)

        # 2. 原生安装器修改所选 profile；失败时保留包供排查，不触碰其他配置。
        if not args.pack_only:
            subprocess.run(
                ["dsh", "plugin", "--profile", args.profile, "add", str(package), "--config.auto-install-peers=false"],
                cwd=ROOT, check=True,
            )
            print("Installation command completed. Reload the profile and verify MCP and Skill discovery.")
            print("Keep the package snapshot: the profile may reference its path for future installs.")
        return 0
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError) as error:
        print(f"Local package/install failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
