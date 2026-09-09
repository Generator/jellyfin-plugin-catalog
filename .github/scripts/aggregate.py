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
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

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


def _parse_timestamp(value: str) -> datetime:
    """Parse ISO8601 timestamp; fallback to epoch on failure (pure)."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _normalize_version(version: str) -> tuple[int, ...]:
    """Convert version string to comparable tuple; non-numeric parts become 0."""
    parts: list[int] = []
    for p in re.split(r"[.\-+]", version or ""):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    # Pad to 4 components for stable semver compare (e.g. 1.0.0 -> 1.0.0.0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def _extract_url_tag(source_url: str) -> str | None:
    """Extract version tag from GitHub release URL like .../download/v1.1.0/..."""
    if not source_url:
        return None
    m = re.search(r"/download/v([^/]+)/", source_url)
    return m.group(1) if m else None


def _sanitize_versions(versions: list[dict]) -> list[dict]:
    """Deduplicate, correct mismatches, drop legacy single-digit, sort descending (pure, immutable)."""
    if not versions:
        return []

    # 1) Drop legacy single-digit versions when richer versions exist (e.g. "7" vs "1.1.1.0")
    has_dotted = any("." in str(v.get("version", "")) for v in versions)
    filtered = [
        dict(v)
        for v in versions
        if not (has_dotted and re.fullmatch(r"\d+", str(v.get("version", ""))))
    ]
    dropped_legacy = len(versions) - len(filtered)
    if dropped_legacy:
        print(f"  sanitize: dropped {dropped_legacy} legacy single-digit version(s)", file=sys.stderr)

    # 2) Correct version/url tag mismatch (e.g. version 0.0.6.0 but URL /v0.0.7/)
    corrected: list[dict] = []
    for v in filtered:
        entry = dict(v)
        tag = _extract_url_tag(str(entry.get("sourceUrl", "")))
        ver = str(entry.get("version", ""))
        if tag and tag != ver:
            # Normalize comparison: tag "0.0.7" vs version "0.0.7.0" considered equal
            if _normalize_version(tag) != _normalize_version(ver):
                # Preserve 4-part convention when original was 4-part (e.g. 0.0.6.0 -> 0.0.7.0)
                patched = tag
                if ver.count(".") == 3 and tag.count(".") == 2:
                    patched = f"{tag}.0"
                print(
                    f"  sanitize: version/url mismatch {ver} vs tag v{tag} -> patching to {patched}",
                    file=sys.stderr,
                )
                entry["version"] = patched
        corrected.append(entry)

    # 3) Deduplicate by version string keep newest timestamp
    by_version: dict[str, dict] = {}
    for v in corrected:
        key = str(v.get("version", ""))
        existing = by_version.get(key)
        if existing is None:
            by_version[key] = v
        else:
            if _parse_timestamp(str(v.get("timestamp", ""))) > _parse_timestamp(
                str(existing.get("timestamp", ""))
            ):
                print(f"  sanitize: dedup version {key} -> keeping newest timestamp", file=sys.stderr)
                by_version[key] = v
            else:
                print(f"  sanitize: dedup version {key} -> keeping existing", file=sys.stderr)

    deduped = list(by_version.values())

    # 4) Sort descending by timestamp then semver
    def sort_key(v: dict) -> tuple[datetime, tuple[int, ...]]:
        return (_parse_timestamp(str(v.get("timestamp", ""))), _normalize_version(str(v.get("version", ""))))

    deduped.sort(key=sort_key, reverse=True)
    return deduped


def _sanitize_plugin(plugin: dict) -> dict:
    """Return new plugin dict with sanitized versions (pure, immutable)."""
    sanitized = dict(plugin)
    versions = plugin.get("versions", [])
    if isinstance(versions, list):
        sanitized["versions"] = _sanitize_versions(versions)
    return sanitized


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
    """Merge manifests, deduplicating by guid and sanitizing versions (pure)."""
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
            catalog.append(_sanitize_plugin(plugin))

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
