"""Builds the daily lineup from the approved pool."""

from __future__ import annotations

import math
import random
from datetime import date

# Weight for an approved video that matches none of topics_wanted.
UNMATCHED_TOPIC_WEIGHT = 0.5
# Each extra pick from a channel already in the lineup is this much less likely.
SAME_CHANNEL_PENALTY = 0.5


def _norm_topic(topic: str) -> str:
    topic = str(topic).strip().lower()
    return topic[:-1] if topic.endswith("s") and len(topic) > 3 else topic


def topic_weight(video: dict, topics_wanted: dict[str, float]) -> float:
    """Highest topics_wanted weight among the video's topics."""
    wanted = {_norm_topic(name): weight for name, weight in topics_wanted.items()}
    matches = [wanted[t] for t in map(_norm_topic, video.get("topics", [])) if t in wanted]
    return max(matches) if matches else UNMATCHED_TOPIC_WEIGHT


def _days_since_shown(video: dict, today: date) -> int | None:
    last = video.get("last_shown")
    if not last:
        return None
    try:
        return (today - date.fromisoformat(last)).days
    except ValueError:
        return None


def is_eligible(video: dict, today: date, repeat_after_days: int) -> bool:
    """True if showing this video today honors repeat_after_days.

    A video already shown today stays eligible, so re-running the job on the
    same day rebuilds the same lineup instead of burning through the pool.
    """
    days = _days_since_shown(video, today)
    return days is None or days <= 0 or days >= repeat_after_days


def _weighted_mixed_pick(
    pool: list[dict], count: int, topics_wanted: dict[str, float], rng: random.Random,
    per_channel: dict[str, int],
) -> list[dict]:
    """Weighted sampling without replacement that spreads picks across channels."""
    pool = list(pool)
    picked: list[dict] = []
    channels = {v.get("channel_id", "") for v in pool} | set(per_channel)
    cap = max(1, math.ceil((count + sum(per_channel.values())) / max(1, len(channels))))

    while pool and len(picked) < count:
        candidates = [v for v in pool if per_channel.get(v.get("channel_id", ""), 0) < cap]
        if not candidates:
            cap += 1
            continue
        weights = [
            topic_weight(v, topics_wanted)
            * (v.get("educational_score", 5) / 10)
            * SAME_CHANNEL_PENALTY ** per_channel.get(v.get("channel_id", ""), 0)
            for v in candidates
        ]
        choice = rng.choices(candidates, weights=weights, k=1)[0]
        picked.append(choice)
        pool.remove(choice)
        channel = choice.get("channel_id", "")
        per_channel[channel] = per_channel.get(channel, 0) + 1
    return picked


def pick_lineup(
    approved: list[dict], rules: dict, today: date, rng: random.Random | None = None
) -> list[dict]:
    """Choose today's videos from the approved pool.

    Picks are weighted by topics_wanted and educational score, spread across
    channels, and skip anything shown within repeat_after_days. If that leaves
    too few, the least-recently-shown videos fill the remaining slots.
    """
    if rng is None:
        rng = random.Random(today.isoformat())
    count = rules["daily_lineup_count"]
    topics_wanted = rules["topics_wanted"]

    # Sort first so the result depends only on the pool and the seed.
    pool = sorted(approved, key=lambda v: v["id"])
    fresh = [v for v in pool if is_eligible(v, today, rules["repeat_after_days"])]
    per_channel: dict[str, int] = {}
    lineup = _weighted_mixed_pick(fresh, count, topics_wanted, rng, per_channel)

    if len(lineup) < count:
        chosen = {v["id"] for v in lineup}
        repeats = sorted(
            (v for v in pool if v["id"] not in chosen),
            key=lambda v: (-(_days_since_shown(v, today) or 0), v["id"]),
        )
        lineup.extend(repeats[: count - len(lineup)])
    return lineup


def mark_shown(lineup: list[dict], today: date) -> None:
    """Record on each approved entry that it was in today's lineup."""
    stamp = today.isoformat()
    for video in lineup:
        if video.get("last_shown") != stamp:
            video["last_shown"] = stamp
            video["shown_count"] = video.get("shown_count", 0) + 1
