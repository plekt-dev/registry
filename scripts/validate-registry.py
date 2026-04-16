#!/usr/bin/env python3
"""Schema + sanity check for registry.json."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: validate-registry.py <path>")
    path = Path(sys.argv[1])
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{path}: invalid JSON: {exc}")

    for field in ("version", "updated_at", "plugins"):
        if field not in doc:
            fail(f"{path}: missing top-level field '{field}'")
    if not isinstance(doc["plugins"], list):
        fail(f"{path}: plugins must be a list")

    seen_names: set[str] = set()
    for i, p in enumerate(doc["plugins"]):
        if not isinstance(p, dict):
            fail(f"plugins[{i}]: must be an object")
        for field in ("name", "author", "license", "description",
                      "category", "tags", "public_key", "versions"):
            if field not in p:
                fail(f"plugins[{i}] ({p.get('name', '?')}): missing '{field}'")
        name = p["name"]
        if name in seen_names:
            fail(f"plugins[{i}]: duplicate name '{name}'")
        seen_names.add(name)

        pk = p["public_key"]
        if pk and not HEX64.match(pk):
            fail(f"plugins[{i}] ({name}): public_key must be 64 lowercase "
                 f"hex chars, got {pk!r}")

        if "official" in p and not isinstance(p["official"], bool):
            fail(f"plugins[{i}] ({name}): official must be a bool")

        versions = p["versions"]
        if not isinstance(versions, list):
            fail(f"plugins[{i}] ({name}): versions must be a list")
        for j, v in enumerate(versions):
            if not isinstance(v, dict):
                fail(f"plugins[{i}].versions[{j}]: must be an object")
            for vf in ("version", "download_url", "checksum_sha256",
                       "size_bytes", "min_core_version", "updated_at"):
                if vf not in v:
                    fail(f"plugins[{i}] ({name}).versions[{j}]: "
                         f"missing '{vf}'")
            cs = v["checksum_sha256"]
            if cs and not HEX64.match(cs):
                fail(f"plugins[{i}] ({name}).versions[{j}]: "
                     f"checksum_sha256 must be 64 hex chars")

    print(f"OK: {path} ({len(doc['plugins'])} plugins)")


if __name__ == "__main__":
    main()
