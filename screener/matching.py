"""Word matching for the kid site's search buttons.

site/app.js has the same rules in JavaScript; keep the two in step.

A word matches when it starts a word in the text, ignoring case, hyphens, and
apostrophes, with a trailing "s" dropped from longer words. So "dinosaurs"
finds "Dinosaur Facts", "spiderman" finds "Spider-Man", and "space" finds
"Spacecraft", but "cat" does not find "education".
"""

from __future__ import annotations

import re


def normalize(text: str) -> str:
    text = re.sub(r"['’\-]", "", str(text or "").lower())
    return " " + re.sub(r"[^a-z0-9]+", " ", text).strip() + " "


def stem(word: str) -> str:
    word = normalize(word).strip()
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def matches(text: str, words: list[str]) -> bool:
    haystack = normalize(text)
    return any(s and f" {s}" in haystack for s in map(stem, words))


def approved_text(video: dict) -> str:
    """What a search button looks at for an approved video."""
    parts = [video.get("title", ""), video.get("channel_title", ""), *video.get("topics", [])]
    if video.get("kind") == "fun":
        parts.append("fun")
    return " ".join(parts)


def candidate_text(video: dict) -> str:
    """What the screening job looks at to put likely button matches first."""
    return " ".join([video.get("title", ""), video.get("channel_title", ""),
                     *video.get("tags", [])])
