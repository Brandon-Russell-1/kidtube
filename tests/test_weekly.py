from datetime import datetime, timezone

from screener.weekly import build

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def video(title, channel="SciShow Kids", when="2026-11-15T09:00:00Z", **extra):
    return {"id": title, "title": title, "channel_title": channel, "screened_at": when, **extra}


def test_counts_only_this_week():
    approved = [
        video("Volcanoes"),
        video("Bluey plays", channel="Bluey", kind="fun"),
        video("Old one", when="2026-10-01T09:00:00Z"),
    ]
    rejected = [
        video("Loud toys", stage="ai", reason="Toy unboxing."),
        video("Tiny clip", stage="hard_filter", reason="Too short."),
        video("Old no", when="2026-10-01T09:00:00Z", stage="ai", reason="Old."),
    ]
    text = build(approved, rejected, NOW)
    assert "**2** new videos approved (1 learning, 1 fun)" in text
    assert "**1** rejected by the AI, and **1** by the automatic filters" in text
    assert "pool now holds **3** videos" in text
    assert "Volcanoes" in text and "Old one" not in text
    assert "Toy unboxing." in text and "Too short." not in text


def test_long_channels_are_shortened():
    approved = [video(f"Episode {n}") for n in range(5)]
    text = build(approved, [], NOW)
    assert "**SciShow Kids** (5): Episode 0; Episode 1; Episode 2; and 2 more" in text


def test_titles_cannot_mention_github_users():
    text = build([video("Thanks @someone for watching")], [], NOW)
    assert "@someone" not in text
    assert "@​someone" in text


def test_quiet_week():
    text = build([], [], NOW)
    assert "**0** new videos approved" in text
    assert "New this week" not in text
