#!/usr/bin/env python3
"""
sync-versions.py — poll GitHub Releases of tracked plugins, update registry.json.

Runs inside plekt-registry-source on a 15-minute schedule (see
.github/workflows/sync-versions.yml). For each enabled repo in
tracked-plugins.yaml:

  1. Fetch the GitHub Releases list.
  2. For each non-draft, non-prerelease release with a .mcpkg asset:
     a. Download the .mcpkg to a temp file.
     b. Compute SHA-256 and size locally.
     c. Extract mcp.yaml from the .mcpkg (it's a tar.gz) and parse the
        `signature.public_key` field.
     d. COMPROMISE GATE — the signing key must match
        `plugins[name].public_key` in registry.json. Mismatch →
        log ERROR, DO NOT update versions[]. (A leaked/switched Environment
        Secret in the plugin repo cannot reach the registry this way.)
     e. REVOCATION GATE — the plugin's registry public_key must not be in
        revoked-keys.json. If it is, skip the whole plugin.
     f. Otherwise upsert the version entry into `plugins[name].versions[]`.
  3. Write registry.json if anything changed.

The workflow commits the diff using the built-in GITHUB_TOKEN.

Idempotent: reruns without new releases are no-ops.
Backfill: first run pulls in every existing release with a .mcpkg asset.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

GITHUB_API = "https://api.github.com"
HTTP_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def github_headers() -> dict[str, str]:
    """GITHUB_TOKEN lifts the unauthenticated 60 req/hr rate limit to 5000."""
    h = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_releases(repo: str) -> list[dict]:
    url = f"{GITHUB_API}/repos/{repo}/releases?per_page=100"
    r = requests.get(url, headers=github_headers(), timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return [
        rel
        for rel in r.json()
        if not rel.get("draft") and not rel.get("prerelease")
    ]


def find_mcpkg_asset(release: dict) -> dict | None:
    for asset in release.get("assets", []):
        if asset.get("name", "").endswith(".mcpkg"):
            return asset
    return None


def download_mcpkg(url: str) -> tuple[bytes, str, int]:
    """Download .mcpkg to a tempfile, return (content, sha256, size).

    We hold the whole .mcpkg in memory: plugins are small (<100 MB), and
    we need the bytes to both hash and extract mcp.yaml. Streaming would
    add complexity without benefit at this size.
    """
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
        r.raise_for_status()
        buf = io.BytesIO()
        for chunk in r.iter_content(65536):
            if chunk:
                buf.write(chunk)
        data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest(), len(data)


def extract_mcp_yaml(mcpkg_bytes: bytes) -> bytes | None:
    """Return the raw mcp.yaml content from a .mcpkg (tar.gz), or None."""
    try:
        with tarfile.open(fileobj=io.BytesIO(mcpkg_bytes), mode="r:gz") as tar:
            for member in tar.getmembers():
                if os.path.basename(member.name) == "mcp.yaml" and member.isfile():
                    f = tar.extractfile(member)
                    if f is not None:
                        return f.read()
    except (tarfile.TarError, OSError) as exc:
        print(f"  ERROR extracting mcp.yaml: {exc}", file=sys.stderr)
    return None


def parse_signature_pubkey(mcp_yaml_bytes: bytes) -> str | None:
    """Return the mcp.yaml signature.public_key, or None."""
    try:
        doc = yaml.safe_load(mcp_yaml_bytes)
    except yaml.YAMLError as exc:
        print(f"  ERROR parsing mcp.yaml: {exc}", file=sys.stderr)
        return None
    if not isinstance(doc, dict):
        return None
    sig = doc.get("signature")
    if not isinstance(sig, dict):
        return None
    pk = sig.get("public_key")
    return pk if isinstance(pk, str) and pk else None


def find_plugin(registry: dict, name: str) -> dict | None:
    for p in registry.get("plugins", []):
        if p.get("name") == name:
            return p
    return None


def upsert_version(plugin: dict, entry: dict) -> str:
    """'added' | 'replaced' | 'unchanged'. Newest-first ordering."""
    versions = plugin.setdefault("versions", [])
    for i, existing in enumerate(versions):
        if existing.get("version") == entry["version"]:
            if existing == entry:
                return "unchanged"
            versions[i] = entry
            return "replaced"
    versions.insert(0, entry)
    return "added"


def build_entry(
    asset: dict,
    tag: str,
    sha: str,
    size: int,
    existing: dict | None,
) -> dict:
    entry: dict = {
        "version": tag,
        "download_url": asset["browser_download_url"],
        "checksum_sha256": sha,
        "size_bytes": size,
        "min_core_version": (existing or {}).get("min_core_version") or "0.1.0",
        "updated_at": iso_now(),
    }
    for key in ("dependencies", "optional_dependencies"):
        if existing and key in existing:
            entry[key] = existing[key]
    return entry


def process_repo(
    plugin: dict,
    github_repo: str,
    revoked: set[str],
) -> bool:
    """Sync one GitHub repo into the given plugin entry. Returns True on mutation."""
    expected_pub = plugin.get("public_key", "")
    if not expected_pub:
        print(f"  WARN {plugin['name']}: registry entry has no public_key, skipping")
        return False

    if expected_pub in revoked:
        print(f"  SKIP {plugin['name']}: public_key is revoked")
        return False

    try:
        releases = fetch_releases(github_repo)
    except requests.RequestException as exc:
        print(f"  ERROR fetching releases: {exc}", file=sys.stderr)
        return False

    # Iterate oldest → newest so the last insert(0) lands the newest release
    # at versions[0] on a cold start. On steady state only new tags mutate
    # anything.
    changed = False
    for release in reversed(releases):
        tag = release.get("tag_name", "")
        if not tag:
            continue

        asset = find_mcpkg_asset(release)
        if asset is None:
            print(f"  skip {tag}: no .mcpkg asset attached")
            continue

        existing = next(
            (v for v in plugin.get("versions", []) if v.get("version") == tag),
            None,
        )
        # Fast path: identical size → assume nothing changed, skip download.
        if existing and existing.get("size_bytes") == asset.get("size"):
            continue

        try:
            mcpkg_bytes, sha, size = download_mcpkg(asset["browser_download_url"])
        except requests.RequestException as exc:
            print(f"  ERROR downloading {tag}: {exc}", file=sys.stderr)
            continue

        # COMPROMISE GATE — the .mcpkg's embedded signing key must match the
        # key the registry has on record. A leaked/rotated Environment Secret
        # in the plugin repo would produce a different pubkey and be caught
        # here, so registry.json never auto-adopts the attacker's key.
        mcp_yaml = extract_mcp_yaml(mcpkg_bytes)
        if mcp_yaml is None:
            print(f"  ERROR {tag}: cannot read mcp.yaml from .mcpkg, skipping",
                  file=sys.stderr)
            continue
        mcp_pub = parse_signature_pubkey(mcp_yaml)
        if not mcp_pub:
            print(f"  ERROR {tag}: mcp.yaml has no signature.public_key, skipping",
                  file=sys.stderr)
            continue
        if mcp_pub != expected_pub:
            # Loud failure — this is the signal that the plugin's keypair
            # changed without a corresponding registry update. Real key
            # rotations happen via PR to registry.json FIRST; auto-sync
            # trusts only what the registry already trusts.
            print(
                f"  COMPROMISE ALERT {plugin['name']} {tag}: "
                f"mcp.yaml signed by {mcp_pub[:16]}... but registry says "
                f"{expected_pub[:16]}... — not updating versions[]",
                file=sys.stderr,
            )
            continue

        entry = build_entry(asset, tag, sha, size, existing)
        action = upsert_version(plugin, entry)
        if action != "unchanged":
            print(f"  {action} {plugin['name']} {tag}")
            changed = True

    return changed


def sync(registry_path: Path, revoked_path: Path, config_path: Path) -> bool:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    revoked_doc = json.loads(revoked_path.read_text(encoding="utf-8"))
    revoked: set[str] = set()
    for entry in revoked_doc.get("revoked", []):
        pk = entry.get("public_key")
        if pk:
            revoked.add(pk)

    changed = False
    for repo_cfg in config.get("repos", []):
        if not repo_cfg.get("enabled", True):
            continue

        github_repo = repo_cfg["github"]
        plugin_name = repo_cfg["plugin"]

        plugin = find_plugin(registry, plugin_name)
        if plugin is None:
            print(
                f"WARN: plugin '{plugin_name}' missing in registry.json — "
                f"add the static entry (name, author, public_key, ...) before "
                f"enabling sync."
            )
            continue

        print(f"checking {github_repo} ({plugin_name})...")
        if process_repo(plugin, github_repo, revoked):
            changed = True

    if changed:
        registry["updated_at"] = iso_now()
        registry_path.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"{registry_path.name} updated")
    else:
        print("no changes")

    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", required=True,
                    help="Path to registry.json")
    ap.add_argument("--revoked", required=True,
                    help="Path to revoked-keys.json")
    ap.add_argument("--config", required=True,
                    help="Path to tracked-plugins.yaml")
    args = ap.parse_args()

    registry_path = Path(args.registry)
    revoked_path = Path(args.revoked)
    config_path = Path(args.config)

    for p, label in ((registry_path, "registry"),
                     (revoked_path, "revoked-keys"),
                     (config_path, "config")):
        if not p.is_file():
            print(f"error: {label} file not found: {p}", file=sys.stderr)
            return 2

    sync(registry_path, revoked_path, config_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
