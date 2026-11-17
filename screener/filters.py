"""Hard filters: cheap yes/no checks that run before any AI call."""

from __future__ import annotations

import re

from .matching import candidate_text, matches

_DURATION = re.compile(
    r"^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)

# Rejections that depend on rules.yaml rather than on the video itself. These
# are re-checked each run so that loosening a rule lets the video back in.
RULE_DEPENDENT_CODES = frozenset({"too_short", "too_long", "channel_blocked"})


def parse_duration(iso: str | None) -> int:
    """Convert a YouTube ISO 8601 duration such as "PT1H2M3S" to seconds.

    Returns 0 for anything missing or unparseable (live streams report "P0D").
    """
    match = _DURATION.match(iso or "")
    if not match:
        return 0
    weeks, days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return (((weeks * 7 + days) * 24 + hours) * 60 + minutes) * 60 + seconds


def _best_thumbnail(thumbnails: dict) -> str:
    for size in ("maxres", "standard", "high", "medium", "default"):
        url = (thumbnails.get(size) or {}).get("url")
        if url:
            return url
    return ""


def normalize_video(item: dict) -> dict:
    """Flatten a videos.list item into the fields the job uses."""
    snippet = item.get("snippet") or {}
    status = item.get("status") or {}
    details = item.get("contentDetails") or {}
    rating = details.get("contentRating") or {}
    return {
        "id": item.get("id", ""),
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "tags": list(snippet.get("tags") or []),
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt", ""),
        "thumbnail": _best_thumbnail(snippet.get("thumbnails") or {}),
        "duration_seconds": parse_duration(details.get("duration")),
        "embeddable": status.get("embeddable") is True,
        "made_for_kids": status.get("madeForKids") is True,
        "privacy_status": status.get("privacyStatus", ""),
        "age_restricted": rating.get("ytRating") == "ytAgeRestricted",
        "live_broadcast_content": snippet.get("liveBroadcastContent", "none"),
        "was_livestream": "liveStreamingDetails" in item,
    }


def is_short(video: dict) -> bool:
    """Best-effort Shorts detection; the API has no flag for it.

    Anything up to 60 seconds, or tagged #shorts, counts. Longer Shorts (they
    can run to 3 minutes) are kept out by min_video_minutes.
    """
    if 0 < video.get("duration_seconds", 0) <= 60:
        return True
    text = " ".join(
        [video.get("title", ""), video.get("description", ""), *video.get("tags", [])]
    ).lower()
    return bool(re.search(r"#shorts?\b", text)) or "shorts" in {
        tag.lower() for tag in video.get("tags", [])
    }


def hard_filter(
    video: dict, rules: dict, blocked_channel_ids: frozenset[str] | set[str] = frozenset()
) -> tuple[bool, str, str]:
    """Decide whether a normalized video may go on to AI screening.

    Returns (passed, code, reason). code is "" when the video passes.
    """
    if video.get("channel_id") in blocked_channel_ids:
        return False, "channel_blocked", "Channel is on the blocked list."
    if video.get("privacy_status") != "public":
        return False, "not_public", "Video is not public."
    if not video.get("embeddable"):
        return False, "not_embeddable", "The uploader does not allow this video to be embedded."
    if video.get("age_restricted"):
        return False, "age_restricted", "YouTube marks this video as age-restricted."
    if video.get("live_broadcast_content", "none") != "none" or video.get("was_livestream"):
        return False, "livestream", "Video is a live stream or a recording of one."
    if is_short(video):
        return False, "short", "Video is a YouTube Short."

    minutes = video.get("duration_seconds", 0) / 60
    if minutes < rules["min_video_minutes"]:
        return (
            False,
            "too_short",
            f"Video is {minutes:.1f} min; the minimum is {rules['min_video_minutes']:g} min.",
        )
    if minutes > rules["max_video_minutes"]:
        return (
            False,
            "too_long",
            f"Video is {minutes:.1f} min; the maximum is {rules['max_video_minutes']:g} min.",
        )
    return True, "", ""


def _interleave(videos: list[dict], limit: int, priority_words: list[str]) -> list[dict]:
    """Up to `limit` videos, taking one per channel in turn.

    Within each channel, videos matching a search button's words go first,
    then madeForKids ones.
    """
    def key(video: dict) -> tuple[bool, bool]:
        wanted = bool(priority_words) and matches(candidate_text(video), priority_words)
        return (not wanted, not video.get("made_for_kids"))

    by_channel: dict[str, list[dict]] = {}
    for video in sorted(videos, key=key):
        by_channel.setdefault(video.get("channel_id", ""), []).append(video)

    ordered: list[dict] = []
    queues = list(by_channel.values())
    while queues and len(ordered) < limit:
        for queue in list(queues):
            if len(ordered) >= limit:
                break
            ordered.append(queue.pop(0))
            if not queue:
                queues.remove(queue)
    return ordered


def order_candidates(videos: list[dict], limit: int, search_share: float = 0.0,
                     priority_words: list[str] | None = None) -> list[dict]:
    """Pick up to `limit` videos to screen.

    Videos from trusted channels come first. Up to `search_share` of the slots
    are kept for search results (videos with source "search"), and search
    results also fill any slots the trusted channels leave empty. Within each
    channel, videos matching `priority_words` are screened first.
    """
    words = priority_words or []
    trusted = [v for v in videos if v.get("source") != "search"]
    searched = [v for v in videos if v.get("source") == "search"]
    reserved = min(len(searched), int(limit * search_share))
    ordered = _interleave(trusted, limit - reserved, words)
    return ordered + _interleave(searched, limit - len(ordered), words)
