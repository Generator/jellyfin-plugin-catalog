# Jellyfin Plugin Catalog

Unified Jellyfin plugin repository — add **one URL** and get every plugin from the `Generator` org in the Jellyfin catalog.

> **Catalog URL**
> ```
> https://generator.github.io/jellyfin-plugin-catalog/manifest.json
> ```
> Alternative (GitHub raw): `https://raw.githubusercontent.com/Generator/jellyfin-plugin-catalog/main/manifest.json`

## Plugins

| Plugin | Description | Source |
|--------|-------------|--------|
| **Trailer2Strm** | Creates `.strm` files pointing to official IMDb trailers | [`jellyfin-plugin-trailer2strm`](../jellyfin-plugin-trailer2strm) |
| **Multify** | Unified notification plugin (Telegram, Gotify, ntfy, webhooks) | [`jellyfin-plugin-multify`](../jellyfin-plugin-multify) |
| **Better Subtitle Extractor** | Extracts embedded subtitles via ffmpeg | [`jellyfin-plugin-extractsubs`](../jellyfin-plugin-extractsubs) |
| **Wyzie Subtitles** | On-demand subtitle provider backed by `sub.wyzie.io` | [`jellyfin-plugin-wyzie`](../jellyfin-plugin-wyzie) |

## Installation

1. Open Jellyfin Dashboard → **Plugins** → **Repositories** → **+** (or **Manage Repositories**).
2. Add:
   - **Repository Name**: `Generator Catalog`
   - **Repository URL**: `https://generator.github.io/jellyfin-plugin-catalog/manifest.json`
3. Save, confirm the warning.
4. Open the **Catalog** tab — all four plugins appear together. Click **Install** on any.

Individual per-plugin URLs (`https://generator.github.io/jellyfin-plugin-<name>/manifest.json`) continue to work.

## How It Works

This repository is a **pure merger** — it never builds plugins. On every release (and daily), it:

1. Fetches each plugin's already-rendered `manifest.json` from its `gh-pages` branch.
2. Concatenates the arrays, deduplicating by `guid` (case-insensitive).
3. Commits `manifest.json` at the repo root, served via GitHub Pages.

```
jellyfin-plugin-*  --release-->  gh-pages/manifest.json  --fetch-->  jellyfin-plugin-catalog/manifest.json  -->  Jellyfin
```

- **Workflow**: [`.github/workflows/aggregate.yml`](.github/workflows/aggregate.yml) — `repository_dispatch` (`plugin-released`) + `workflow_dispatch` + daily cron `17 4 * * *` + push-on-change.
- **Merger script**: [`.github/scripts/aggregate.py`](.github/scripts/aggregate.py) — `SOURCE_MANIFESTS` env (newline-separated URLs), 30s timeout, skips failed sources, case-insensitive guid dedup.

## Development

```bash
# Preview the merged catalog locally (fetches live manifests)
python3 .github/scripts/aggregate.py
cat manifest.json | jq '.[].name'

# Use local files for offline testing
python3 .github/scripts/aggregate.py --sources ./fixtures/trailer2strm.json,./fixtures/multify.json --output /tmp/manifest.json

# Override via env
SOURCE_MANIFESTS="https://example.com/a.json
https://example.com/b.json" python3 .github/scripts/aggregate.py
```

To trigger a refresh after a plugin release: **Actions → 🔄 Aggregate Plugin Catalog → Run workflow** (manual), or wait for the daily cron / `repository_dispatch` (requires `CATALOG_PAT` in the plugin repo — optional).

### Optional: Wire near-real-time updates

Add to each plugin's `release.yml` after the release step:

```yaml
      - name: Notify catalog repo
        if: success()
        run: |
          curl -X POST \
            -H "Authorization: Bearer ${{ secrets.CATALOG_PAT }}" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/repos/Generator/jellyfin-plugin-catalog/dispatches \
            -d '{"event_type":"plugin-released"}'
```

Requires a PAT with `repo` scope stored as `CATALOG_PAT` — the daily cron is the fallback if not configured.

## Reference

- Design doc (reference only, not tracked): `UNIFIED-MANIFEST.md` (local)
- Jellyfin plugin repository format: JSON array of plugin objects (`guid`, `name`, `versions[]`, etc.)
