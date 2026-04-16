#!/usr/bin/env python3
"""Schema + sanity check for revoked-keys.json."""

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
        fail("usage: validate-revoked.py <path>")
    path = Path(sys.argv[1])
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{path}: invalid JSON: {exc}")

    for field in ("version", "updated_at", "revoked"):
        if field not in doc:
            fail(f"{path}: missing top-level field '{field}'")
    if not isinstance(doc["revoked"], list):
        fail(f"{path}: revoked must be a list")

    seen: set[str] = set()
    for i, e in enumerate(doc["revoked"]):
        if not isinstance(e, dict):
            fail(f"revoked[{i}]: must be an object")
        for field in ("public_key", "plugin", "revoked_at", "reason"):
            if field not in e:
                fail(f"revoked[{i}]: missing '{field}'")
        pk = e["public_key"]
        if not HEX64.match(pk):
            fail(f"revoked[{i}]: public_key must be 64 lowercase hex chars, "
                 f"got {pk!r}")
        if pk in seen:
            fail(f"revoked[{i}]: duplicate public_key {pk}")
        seen.add(pk)
        if not e["reason"].strip():
            fail(f"revoked[{i}] ({pk[:16]}...): reason must be non-empty")

    print(f"OK: {path} ({len(doc['revoked'])} revoked keys)")


if __name__ == "__main__":
    main()
