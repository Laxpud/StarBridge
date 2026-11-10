#!/usr/bin/env python3
"""按 GitHub 正式发布记录生成 Vibekits 同步 PR；仅供 Actions 显式触发。"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


SOURCE = Path(__file__).resolve().parent.parent
MARKET_REPO = "Laxpud/my-awesome-vibekits"
SOURCE_REPO = "Laxpud/StarBridge"


def run(*args: str, cwd: Path, capture: bool = False) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def main() -> int:
    try:
        market = Path(os.environ["VIBEKITS_CHECKOUT"]).resolve()
        version = json.loads((SOURCE / "package.json").read_text(encoding="utf-8"))["version"]
        if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version):
            raise ValueError("expected a stable X.Y.Z version")
        tag = f"v{version}"
        commit = run("git", "rev-parse", "HEAD", cwd=SOURCE, capture=True)
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("source checkout has no full commit SHA")
        run("python3", "scripts/release_version.py", cwd=SOURCE)
        release = json.loads(run("gh", "release", "view", tag, "--repo", SOURCE_REPO,
                                 "--json", "tagName,publishedAt,url,isDraft", cwd=SOURCE, capture=True))
        if release["tagName"] != tag or release["isDraft"] or not release["publishedAt"]:
            raise ValueError("a published release for this version is required")
        if release["url"] != f"https://github.com/{SOURCE_REPO}/releases/tag/{tag}":
            raise ValueError("unexpected release evidence URL")
        tag_commit = run("git", "rev-parse", f"refs/tags/{tag}^{{commit}}", cwd=SOURCE, capture=True)
        if commit != tag_commit:
            raise ValueError("release tag does not identify this source checkout")
        timestamp = int(datetime.fromisoformat(release["publishedAt"].replace("Z", "+00:00")).timestamp())

        def require_current_main() -> None:
            # 市场同步器从 catalog 的 main 拉取；只在 main 与正式发布提交完全一致时允许执行。
            line = run("git", "ls-remote", "origin", "refs/heads/main", cwd=SOURCE, capture=True)
            if not line or line.split()[0] != commit:
                raise ValueError("StarBridge main no longer matches the published commit; refusing to sync another snapshot")

        require_current_main()
        if run("git", "status", "--porcelain", cwd=market, capture=True):
            raise ValueError("market checkout must be clean")
        help_text = run("python3", "scripts/sync_plugin_metadata.py", "--help", cwd=market, capture=True)
        if "--release-info" not in help_text:
            raise ValueError("market main lacks release-info support; publish the existing market synchronizer changes first")
        with tempfile.TemporaryDirectory(prefix="starbridge-release-info-") as temp:
            info = Path(temp) / "release-info.json"
            info.write_text(json.dumps({"releases": [{"plugin": "starbridge", "version": version,
                "commit": commit, "publishTimestamp": timestamp, "publishEvidence": release["url"]}]}), encoding="utf-8")
            command = ("python3", "scripts/sync_plugin_metadata.py", "--fetch-external", "--plugin", "starbridge",
                       "--release-info", str(info))
            # 预览和写入分别拉取 main，因此每一步之后都复核来源；任何变化都不能成为 PR。
            run(*command, cwd=market)
            require_current_main()
            run(*command, "--write", cwd=market)
            require_current_main()
        run("python3", "scripts/sync_plugin_metadata.py", cwd=market)
        run("python3", "scripts/check_codex_install.py", "--all", "--check-external", cwd=market)
        run("python3", "scripts/check_markdown_links.py", cwd=market)
        run("python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v", cwd=market)
        run("git", "diff", "--check", cwd=market)
        if not run("git", "status", "--porcelain", cwd=market, capture=True):
            print("Market already matches this release; no PR is needed.")
            return 0
        branch = f"automation/starbridge-v{version}"
        existing = run("git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}", cwd=market, capture=True)
        if existing:
            raise ValueError(f"market branch {branch} already exists; inspect its PR rather than overwrite it")
        # 只提交同步器生成的四个文件，不包含 checkout 中的其他内容。
        files = ("plugin-catalog.json", ".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json", "dsh/index.json")
        run("git", "checkout", "-b", branch, cwd=market)
        run("git", "config", "user.name", "github-actions[bot]", cwd=market)
        run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", cwd=market)
        run("git", "add", "--", *files, cwd=market)
        run("git", "commit", "-m", f"chore(starbridge): sync {version}", cwd=market)
        require_current_main()
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=market)
        body = f"Sync StarBridge {version} from {release['url']}.\n\nCommit: `{commit}`\n\nReview the generated catalog and three marketplace files before merging."
        run("gh", "pr", "create", "--repo", MARKET_REPO, "--base", "main", "--head", branch,
            "--title", f"chore(starbridge): sync {version}", "--body", body, cwd=market)
        return 0
    except (OSError, subprocess.CalledProcessError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"Vibekits sync failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
