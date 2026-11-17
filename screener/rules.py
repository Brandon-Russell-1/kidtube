"""Loads rules.yaml and fills in defaults so the rest of the job can trust it."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import config

DEFAULTS = {
    "child_age": 6,
    "timezone": "UTC",
    "topics_wanted": {},
    "topics_banned": [],
    "trusted_channels": [],
    "fun_channels": [],
    "fun_videos_per_day": 3,
    "blocked_channels": [],
    "search_terms": [],
    "min_video_minutes": 3,
    "max_video_minutes": 20,
    "daily_lineup_count": 8,
    "repeat_after_days": 14,
    "min_educational_score": 7,
    "max_videos_screened_per_run": 40,
    "daily_watch_limit_minutes": 45,
    "parent_pin": "1234",
    "free_text_guidance": "",
}


class RulesError(ValueError):
    """rules.yaml is missing or cannot be understood."""


def _topic_weights(raw) -> dict[str, float]:
    """Accept {science: 3}, [science, math], or [{science: 3}, math]."""
    weights: dict[str, float] = {}
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, list):
        items = []
        for entry in raw:
            if isinstance(entry, dict):
                items.extend(entry.items())
            else:
                items.append((entry, 1))
    elif raw is None:
        items = []
    else:
        raise RulesError("topics_wanted must be a list or a mapping of topic: weight")
    for name, weight in items:
        try:
            weight = float(1 if weight is None else weight)
        except (TypeError, ValueError):
            raise RulesError(f"topics_wanted: weight for {name!r} must be a number")
        if weight > 0:
            weights[str(name).strip().lower()] = weight
    return weights


def _string_list(raw, field: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RulesError(f"{field} must be a list")
    return [str(item).strip() for item in raw if str(item).strip()]


def _number(raw, field: str, minimum: float, integer: bool = False):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise RulesError(f"{field} must be a number")
    if value < minimum:
        raise RulesError(f"{field} must be at least {minimum:g}")
    return int(value) if integer else value


def normalize_channel_ref(ref: str) -> tuple[str, str]:
    """Turn a channel ID, handle, or URL into ("id", "UC...") or ("handle", "@name")."""
    ref = ref.strip()
    match = re.search(r"youtube\.com/channel/(UC[\w-]{22})", ref)
    if match:
        return "id", match.group(1)
    match = re.search(r"youtube\.com/(@[\w.\-]+)", ref)
    if match:
        return "handle", match.group(1)
    if re.fullmatch(r"UC[\w-]{22}", ref):
        return "id", ref
    return "handle", ref if ref.startswith("@") else "@" + ref


def parse_rules(raw: dict | None) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RulesError("rules.yaml must be a set of 'name: value' settings")

    rules = {**DEFAULTS, **{k: v for k, v in raw.items() if v is not None}}
    rules["child_age"] = _number(rules["child_age"], "child_age", 1, integer=True)
    rules["timezone"] = str(rules["timezone"]).strip() or "UTC"
    rules["topics_wanted"] = _topic_weights(rules["topics_wanted"])
    for field in ("topics_banned", "trusted_channels", "fun_channels", "blocked_channels",
                  "search_terms"):
        rules[field] = _string_list(rules[field], field)
    rules["fun_videos_per_day"] = _number(
        rules["fun_videos_per_day"], "fun_videos_per_day", 0, integer=True
    )
    rules["min_video_minutes"] = _number(rules["min_video_minutes"], "min_video_minutes", 0)
    rules["max_video_minutes"] = _number(rules["max_video_minutes"], "max_video_minutes", 0)
    if rules["max_video_minutes"] < rules["min_video_minutes"]:
        raise RulesError("max_video_minutes must not be smaller than min_video_minutes")
    rules["daily_lineup_count"] = _number(
        rules["daily_lineup_count"], "daily_lineup_count", 1, integer=True
    )
    rules["repeat_after_days"] = _number(
        rules["repeat_after_days"], "repeat_after_days", 0, integer=True
    )
    score = _number(rules["min_educational_score"], "min_educational_score", 1, integer=True)
    rules["min_educational_score"] = min(score, 10)
    screened = _number(
        rules["max_videos_screened_per_run"], "max_videos_screened_per_run", 1, integer=True
    )
    rules["max_videos_screened_per_run"] = min(screened, config.MAX_SCREENED_PER_RUN_CEILING)
    rules["daily_watch_limit_minutes"] = _number(
        rules["daily_watch_limit_minutes"], "daily_watch_limit_minutes", 0
    )
    rules["parent_pin"] = str(rules["parent_pin"]).strip()
    if not rules["parent_pin"].isdigit():
        raise RulesError("parent_pin must contain digits only (put it in quotes)")
    rules["free_text_guidance"] = " ".join(str(rules["free_text_guidance"]).split())
    return rules


def load_rules(path: Path) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RulesError(f"{path} not found")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RulesError(f"rules.yaml is not valid YAML: {exc}")
    return parse_rules(raw)
