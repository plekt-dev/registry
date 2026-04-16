# plekt-registry

Public, authoritative source of the Plekt plugin catalog and key-revocation list.

This repo is the single source of truth for:

- `registry.json` — all plugins published in the Plekt ecosystem, their per-plugin Ed25519 `public_key`, and their known versions.
- `revoked-keys.json` — Ed25519 public keys that must **not** be trusted (compromised, rotated).
- `tracked-plugins.yaml` — which plugin repositories the scheduled sync worker polls.

---

## Trust model

Each plugin has its own Ed25519 signing keypair:

- **Private key** lives in a GitHub Environment Secret (`PLUGIN_SIGNING_KEY`) inside that plugin's own repo. Only the plugin's release workflow can read it. A required-reviewer approval is recommended.
- **Public key** is committed here in the plugin's `registry.json` entry.
- A Plekt core installs a plugin only when:
  1. the plugin's registry `public_key` is non-empty,
  2. it is **not** in `revoked-keys.json`,
  3. the plugin's `mcp.yaml` was signed with that exact key.

The root of trust is this repo.

---

## Adding your plugin

1. **Generate a keypair** (one-time per plugin):

   ```bash
   go install github.com/plekt-dev/release-tools/cmd/generate-keypair@latest
   generate-keypair > /tmp/myplugin.keys   # print pub + priv
   ```

   Store the private key in your plugin repo's Environment Secret `PLUGIN_SIGNING_KEY`. Keep an offline backup; if the repo is lost, the key is lost.

2. **Set up `.github/workflows/release.yml`** in your plugin repo (see `plekt-dev/tasks-plugin` for a canonical example). The workflow must:
   - Trigger on a semver tag push (`[0-9]+.[0-9]+.[0-9]+`).
   - Use the `release-signing` environment so the secret is gated.
   - Run `sign-with-key` against `mcp.yaml`, build a `.mcpkg` archive, and attach it to the GitHub Release.

3. **Open a PR here** that:
   - Appends a static entry to `registry.json.plugins[]` with your plugin's `name`, `author`, `license`, `description`, `category`, `tags`, and **the public key** from step 1.
   - Appends an entry to `tracked-plugins.yaml` pointing at your release repo.

4. A maintainer reviews and merges. Within 15 minutes the scheduled `sync-versions.yml` workflow picks up your latest release, downloads the `.mcpkg`, verifies the embedded signature matches the key in your registry entry, and records the version details into `registry.json`.

---

## Reporting a compromised key

If your signing private key is leaked, rotated, or you lost access:

1. Open a PR that adds an entry to `revoked-keys.json.revoked[]`:
   ```json
   {
     "public_key": "<64-hex chars>",
     "plugin": "<your plugin name>",
     "revoked_at": "<ISO-8601 timestamp>",
     "reason": "private key leaked in incident ..."
   }
   ```
2. Generate a **new** keypair and update your plugin's `registry.json` entry (same PR).
3. Cut a new release signed with the new key. The sync worker verifies against the new key starting from the next tick.

Compromised keys propagate to every Plekt core on its next registry poll.
