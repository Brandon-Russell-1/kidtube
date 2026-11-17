"""Writes the weekly summary for the parent: python -m screener.weekly > summary.md

The weekly workflow posts it as a GitHub issue, and GitHub emails the issue to
the repo owner. It covers what the screening job decided. What he watched
stays on the iPad and is shown on the parent page instead.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from . import config

TITLES_PER_CHANNEL = 3
CHANNELS_LISTED = 40
REJECTIONS_LISTED = 15


def _when(entry: dict) -> datetime | None:
    try:
        return datetime.strptime(entry.get("screened_at") or "", "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def _plain(text) -> str:
    """One line of text that cannot ping a GitHub user or break the list."""
    return " ".join(str(text or "").split()).replace("@", "@​").replace("|", "/")


def build(approved: list[dict], rejected: list[dict], now: datetime, days: int = 7) -> str:
    since = now - timedelta(days=days)

    def recent(entries):
        return [e for e in entries if (_when(e) or since) > since]

    new = recent(approved)
    turned_down = recent(rejected)
    fun = sum(v.get("kind") == "fun" for v in new)
    by_ai = [r for r in turned_down if r.get("stage") == "ai"]
    lines = [
        f"## KidTube: the week ending {now.strftime('%B %d, %Y').replace(' 0', ' ')}",
        "",
        f"- **{len(new)}** new videos approved ({len(new) - fun} learning, {fun} fun)",
        f"- **{len(by_ai)}** rejected by the AI, and **{len(turned_down) - len(by_ai)}** "
        "by the automatic filters (too short, too long, Shorts, and so on)",
        f"- The approved pool now holds **{len(approved)}** videos",
    ]

    if new:
        by_channel: dict[str, list[str]] = {}
        for video in new:
            by_channel.setdefault(video.get("channel_title") or "Unknown channel", []).append(
                video.get("title") or video.get("id", ""))
        ranked = sorted(by_channel.items(), key=lambda item: (-len(item[1]), item[0].lower()))
        lines += ["", "### New this week, by channel"]
        for channel, titles in ranked[:CHANNELS_LISTED]:
            shown = "; ".join(_plain(t) for t in titles[:TITLES_PER_CHANNEL])
            more = len(titles) - TITLES_PER_CHANNEL
            lines.append(f"- **{_plain(channel)}** ({len(titles)}): {shown}"
                         + (f"; and {more} more" if more > 0 else ""))
        if len(ranked) > CHANNELS_LISTED:
            lines.append(f"- and {len(ranked) - CHANNELS_LISTED} more channels")

    if by_ai:
        newest = sorted(by_ai, key=lambda r: r.get("screened_at") or "", reverse=True)
        lines += ["", "### Some of what the AI turned down"]
        for entry in newest[:REJECTIONS_LISTED]:
            lines.append(f"- **{_plain(entry.get('title'))}** ({_plain(entry.get('channel_title'))}): "
                         f"{_plain(entry.get('reason'))}")

    lines += [
        "",
        "The full lists, and what he watched this week, are on the parent page of "
        "the kid site (long-press the top-right corner). What he watches never "
        "leaves the iPad, so it is not in this email.",
    ]
    return "\n".join(lines) + "\n"


def _videos(path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("videos", [])
    except (FileNotFoundError, ValueError):
        return []


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(build(_videos(config.APPROVED_PATH), _videos(config.REJECTED_PATH),
                datetime.now(timezone.utc)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
