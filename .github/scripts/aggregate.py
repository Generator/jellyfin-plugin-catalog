#!/usr/bin/env python3
"""Merge multiple Jellyfin plugin manifests into one catalog manifest.json.

Pure consumer/merger — fetches each plugin's already-rendered manifest.json
and concatenates the arrays, deduplicating by guid (case-insensitive).

Sources are provided via the SOURCE_MANIFESTS env var (newline-separated URLs),
matching the aggregate.yml workflow. Local file paths are also accepted for
offline testing.

Usage:
    SOURCE_MANIFESTS="https://.../manifest.json\\nhttps://.../manifest.json" python3 .github/scripts/aggregate.py
    python3 .github/scripts/aggregate.py --sources "url1,url2" --output manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = ROOT / "manifest.json"
TIMEOUT = 30

DEFAULT_SOURCES = [
    "https://generator.github.io/jellyfin-plugin-trailer2strm/manifest.json",
    "https://generator.github.io/jellyfin-plugin-multify/manifest.json",
    "https://generator.github.io/jellyfin-plugin-extractsubs/manifest.json",
    "https://generator.github.io/jellyfin-plugin-wyzie/manifest.json",
]


def _parse_sources(raw: str | None) -> list[str]:
    """Parse newline-or-comma-separated sources from env / args."""
    if not raw:
        return []
    # Support both newline and comma separators
    parts: list[str] = []
    for chunk in raw.replace(",", "\n").splitlines():
        url = chunk.strip()
        if url:
            parts.append(url)
    return parts


def _fetch_manifest(source: str) -> list[dict]:
    """Fetch a single manifest — handles both URLs and local file paths."""
    try:
        if source.startswith(("http://", "https://")):
            with urllib.request.urlopen(source, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        else:
            # Local file path (for testing)
            data = json.loads(pathlib.Path(source).read_text(encoding="utf-8"))

        if isinstance(data, dict):
            # Some manifests wrap in a single object; normalize to list
            return [data]
        if isinstance(data, list):
            return data
        print(f"warn: unexpected manifest shape from {source}: {type(data).__name__}", file=sys.stderr)
        return []
    except urllib.error.URLError as exc:
        print(f"warn: failed to fetch {source}: {exc}", file=sys.stderr)
        return []
    except (json.JSONDecodeError, OSError) as exc:
        print(f"warn: failed to parse {source}: {exc}", file=sys.stderr)
        return []


def merge_manifests(sources: list[str]) -> list[dict]:
    """Merge manifests, deduplicating by guid (case-insensitive). Pure function."""
    catalog: list[dict] = []
    seen: set[str] = set()

    for url in sources:
        plugins = _fetch_manifest(url)
        print(f"  fetched {len(plugins)} plugin(s) from {url}")
        for plugin in plugins:
            guid = plugin.get("guid")
            if not guid:
                print(f"warn: plugin without guid skipped: {plugin.get('name', '?')}", file=sys.stderr)
                continue
            key = str(guid).lower()
            if key in seen:
                print(f"  dedup: skipping duplicate guid {guid} ({plugin.get('name', '?')})")
                continue
            seen.add(key)
            catalog.append(plugin)

    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge Jellyfin plugin manifests")
    parser.add_argument("--sources", help="Comma-separated source URLs (overrides env)")
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUT), help="Output path")
    args = parser.parse_args()

    if args.sources:
        sources = _parse_sources(args.sources)
    else:
        env_sources = os.environ.get("SOURCE_MANIFESTS")
        if env_sources:
            sources = _parse_sources(env_sources)
        else:
            print("info: SOURCE_MANIFESTS not set — using default 4 plugin URLs")
            sources = DEFAULT_SOURCES

    if not sources:
        print("error: no sources provided", file=sys.stderr)
        return 1

    print(f"Merging {len(sources)} source manifest(s)...")
    catalog = merge_manifests(sources)

    out_path = pathlib.Path(args.output)
    out_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(catalog)} plugin(s) to {out_path}")
    for p in catalog:
        print(f"  - {p.get('name', '?')} ({p.get('guid', '?')}) — {len(p.get('versions', []))} version(s)")

    if not catalog:
        print("warn: catalog is empty — all sources may have failed", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
