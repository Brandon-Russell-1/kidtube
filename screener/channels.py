"""Channel icons for the kid site's feed, cached in data/channels.json.

The site shows each video's channel icon next to its title. Icons come from
YouTube's channel details and are looked up again now and then, because
channels change them. Only https URLs on YouTube's own image hosts are kept, so
the site never loads an image from anywhere else.
"""

from __future__ import annotations

import re
from datetime import date

ICON_URL = re.compile(r"^https://yt3\.(?:ggpht|googleusercontent)\.com/[\w\-./=~%]+$")


def safe_icon(url) -> str | None:
    """The URL if it is an https image on YouTube's icon hosts, else None."""
    return url if isinstance(url, str) and ICON_URL.match(url) else None


def icon_from_snippet(snippet: dict) -> str | None:
    """The smallest channel icon in a channels.list snippet that is safe to show."""
    thumbnails = (snippet or {}).get("thumbnails") or {}
    for size in ("default", "medium", "high"):
        icon = safe_icon((thumbnails.get(size) or {}).get("url"))
        if icon:
            return icon
    return None


def needs_lookup(cache: dict, channel_ids: set[str], today: date, max_age_days: int) -> list[str]:
    """Channels with no cached icon, or one last checked over max_age_days ago."""
    stale = []
    for channel_id in sorted(channel_ids):
        checked = (cache.get(channel_id) or {}).get("checked")
        try:
            age = (today - date.fromisoformat(checked)).days
        except (TypeError, ValueError):
            age = None
        if age is None or age > max_age_days:
            stale.append(channel_id)
    return stale


def merge(cache: dict, looked_up: list[str], found: dict[str, dict], today: date) -> dict:
    """Record a lookup. A channel YouTube didn't return keeps no icon until the next check."""
    merged = dict(cache)
    for channel_id in looked_up:
        info = found.get(channel_id) or {}
        merged[channel_id] = {
            "title": info.get("title") or (cache.get(channel_id) or {}).get("title", ""),
            "icon": safe_icon(info.get("icon")),
            "checked": today.isoformat(),
        }
    return merged


def button_ids(refs: list[tuple[str, str]], known: dict[tuple[str, str], str],
               lookup) -> tuple[list[str], list[tuple[str, str]]]:
    """Channel IDs for the parent's channel_buttons, in the parent's order.

    refs and the keys of known are ("id", "UC...") or ("handle", "@name") pairs.
    known holds channels this run already looked up; lookup(kind, value) asks
    YouTube for the rest and returns an ID or None. Also returns the refs that
    were not found. Handles are matched without regard to case.
    """
    def key(ref):
        kind, value = ref
        return (kind, value.lower() if kind == "handle" else value)

    seen = {key(ref): cid for ref, cid in known.items()}
    ids: list[str] = []
    missing = []
    for ref in refs:
        kind, value = ref
        if kind == "id":
            cid = value
        elif key(ref) in seen:
            cid = seen[key(ref)]
        else:
            cid = seen[key(ref)] = lookup(kind, value)
        if cid is None:
            missing.append(ref)
        elif cid not in ids:
            ids.append(cid)
    return ids, missing


def prune(cache: dict, channel_ids: set[str]) -> dict:
    """Keep only channels that still have approved videos."""
    return {cid: entry for cid, entry in cache.items() if cid in channel_ids}
