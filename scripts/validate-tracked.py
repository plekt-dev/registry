#!/usr/bin/env python3
"""Schema + sanity check for tracked-plugins.yaml."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: validate-tracked.py <path>")
    path = Path(sys.argv[1])
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        fail(f"{path}: invalid YAML: {exc}")

    if not isinstance(doc, dict):
        fail(f"{path}: root must be a mapping")
    if "repos" not in doc:
        fail(f"{path}: missing 'repos' key")
    repos = doc["repos"]
    if not isinstance(repos, list):
        fail(f"{path}: repos must be a list")

    seen_repos: set[str] = set()
    seen_plugins: set[str] = set()
    for i, r in enumerate(repos):
        if not isinstance(r, dict):
            fail(f"repos[{i}]: must be a mapping")
        for field in ("github", "plugin"):
            if field not in r:
                fail(f"repos[{i}]: missing '{field}'")
        gh = r["github"]
        if not REPO_RE.match(gh):
            fail(f"repos[{i}]: github must be 'owner/repo', got {gh!r}")
        if gh in seen_repos:
            fail(f"repos[{i}]: duplicate github repo {gh}")
        seen_repos.add(gh)
        pl = r["plugin"]
        if pl in seen_plugins:
            fail(f"repos[{i}]: duplicate plugin {pl}")
        seen_plugins.add(pl)

    print(f"OK: {path} ({len(repos)} tracked repos)")


if __name__ == "__main__":
    main()
