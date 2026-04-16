# Contributing to plekt-registry-source

This repo holds the catalog — not plugin code. Plugin source lives in each author's own repo. Contributions here are:

1. **Adding a new plugin** → PR that adds the static entry + tracking hook.
2. **Rotating a signing key** → PR that updates `public_key` + revokes the old one.
3. **Updating plugin metadata** (description, tags, category) → PR by the plugin author.
4. **Maintainer tasks** — promoting versions, merging auto-sync PRs, acting on compromise reports.

For full instructions and the trust model, see [README.md](./README.md).

## Pull request checklist

- [ ] Plugin repo has its own `PLUGIN_SIGNING_KEY` Environment Secret and release workflow.
- [ ] The `public_key` in `registry.json` exactly matches the key inside the plugin's `.mcpkg` / `mcp.yaml.signature.public_key`.
- [ ] A test release with a `.mcpkg` asset is already published on the plugin's GitHub Releases (or will be, immediately after this PR merges).
- [ ] If editing a version's download URL, checksum, or size manually — explain why. The auto-sync worker handles those fields; manual edits are unusual.
- [ ] If revoking a key, the `reason` field explains **what happened** (leak, rotation, lost access) in one sentence.

Validation runs automatically on every PR:

- `scripts/validate-registry.py` — JSON shape and field rules.
- `scripts/validate-revoked.py` — revocation list shape.
- `scripts/validate-tracked.py` — tracked-plugins.yaml shape.

If those pass and a code owner approves, a maintainer can merge.

## What this repo does NOT accept

- **Binary artifacts** (`.mcpkg`, signed blobs, key files). Releases live on the plugin's own repo via GitHub Releases.
- **Private keys.** Ever. The registry only stores public keys. If you open a PR containing a private key, assume it is compromised the moment CI logs it.
- **Direct edits to another plugin's entry.** The maintainer reviews every PR against `registry.json`; if they see key churn for a plugin they don't maintain themselves, the PR stalls pending proof of authorization. (When the project grows and a `CODEOWNERS` file returns, this becomes a hard gate rather than a convention.)
