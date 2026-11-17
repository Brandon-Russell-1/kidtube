"""Entry point for the nightly screening job: python -m screener.run"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import ai, config
from .filters import RULE_DEPENDENT_CODES, hard_filter, normalize_video, order_candidates
from .lineup import mark_shown, pick_lineup
from .rules import RulesError, load_rules, normalize_channel_ref
from .transcripts import TranscriptFetcher
from .youtube import YouTube, YouTubeError


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_in(tz_name: str) -> date:
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except (ZoneInfoNotFoundError, ValueError):
        print(f"WARNING: unknown timezone {tz_name!r} in rules.yaml; using UTC.")
        return datetime.now(timezone.utc).date()


def load_videos(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("videos", [])
    except FileNotFoundError:
        return []


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def rejection(video: dict, stage: str, code: str, reason: str, **extra) -> dict:
    return {
        "id": video["id"],
        "title": video.get("title", ""),
        "channel_id": video.get("channel_id", ""),
        "channel_title": video.get("channel_title", ""),
        "duration_seconds": video.get("duration_seconds", 0),
        "stage": stage,
        "code": code,
        "reason": reason,
        **extra,
        "screened_at": now_iso(),
    }


class Run:
    def __init__(self, rules: dict):
        self.rules = rules
        self.approved = load_videos(config.APPROVED_PATH)
        self.rejected = load_videos(config.REJECTED_PATH)
        self.problems: list[str] = []   # things the parent should fix; fail the run
        self.warnings: list[str] = []
        self.stats = {"hard_rejected": 0, "ai_approved": 0, "ai_rejected": 0, "removed": 0}
        self.blocked_ids: set[str] = set()

    def known_ids(self) -> set[str]:
        return {v["id"] for v in self.approved} | {v["id"] for v in self.rejected}

    # ── YouTube ──────────────────────────────────────────────────────────────

    def _youtube_failed(self, exc: YouTubeError, doing: str) -> bool:
        """Record a YouTube error. Returns True if the job should stop calling YouTube."""
        if exc.is_quota:
            self.problems.append(f"YouTube API quota is used up for today ({doing}).")
            return True
        if exc.status in (400, 401, 403):
            self.problems.append(
                f"YouTube rejected the request while {doing}: {exc}. Check that "
                "YOUTUBE_API_KEY is correct and YouTube Data API v3 is enabled for it."
            )
            return True
        self.warnings.append(f"YouTube error while {doing}: {exc}")
        return False

    def resolve_blocked(self, yt: YouTube) -> None:
        for ref in self.rules["blocked_channels"]:
            kind, value = normalize_channel_ref(ref)
            if kind == "id":
                self.blocked_ids.add(value)
                continue
            channel = yt.resolve_channel(kind, value)
            if channel:
                self.blocked_ids.add(channel["id"])
            else:
                self.warnings.append(f"Blocked channel {ref} was not found on YouTube.")

    def recheck_rule_dependent_rejections(self) -> None:
        """Forget rejections that a rules.yaml change has since made obsolete."""
        kept = []
        for entry in self.rejected:
            if entry.get("stage") == "hard_filter" and entry.get("code") in RULE_DEPENDENT_CODES:
                minutes = entry.get("duration_seconds", 0) / 60
                still_fails = {
                    "too_short": minutes < self.rules["min_video_minutes"],
                    "too_long": minutes > self.rules["max_video_minutes"],
                    "channel_blocked": entry.get("channel_id") in self.blocked_ids,
                }[entry["code"]]
                if not still_fails:
                    continue
            kept.append(entry)
        self.rejected = kept

    def recheck_approved(self, yt: YouTube) -> None:
        """Remove approved videos that were deleted, restricted, or now break a hard rule."""
        if not self.approved:
            return
        live = {item["id"]: normalize_video(item) for item in
                yt.videos([v["id"] for v in self.approved])}
        kept = []
        for entry in self.approved:
            current = live.get(entry["id"])
            if current is None:
                ok, code, reason = False, "unavailable", "Video was deleted or made private."
            else:
                ok, code, reason = hard_filter(current, self.rules, self.blocked_ids)
            if ok:
                kept.append(entry)
            else:
                self.rejected.append(rejection(
                    entry, "hard_filter", code, f"Removed after approval: {reason}"))
                self.stats["removed"] += 1
        self.approved = kept

    def gather_candidates(self, yt: YouTube) -> list[dict]:
        """Unseen videos from trusted channels (and maybe one search), normalized."""
        known = self.known_ids()
        new_ids: list[str] = []

        for ref in self.rules["trusted_channels"]:
            kind, value = normalize_channel_ref(ref)
            try:
                channel = yt.resolve_channel(kind, value)
                if channel is None:
                    self.warnings.append(f"Trusted channel {ref} was not found on YouTube.")
                    continue
                if channel["id"] in self.blocked_ids:
                    continue
                found, token = [], None
                for _ in range(config.MAX_UPLOAD_PAGES_PER_CHANNEL):
                    ids, token = yt.playlist_page(channel["uploads_playlist"], token)
                    found.extend(i for i in ids if i not in known and i not in found)
                    if len(found) >= config.MAX_NEW_IDS_PER_CHANNEL or not token:
                        break
                found = found[: config.MAX_NEW_IDS_PER_CHANNEL]
                print(f"  {channel['title']}: {len(found)} unseen videos")
                new_ids.extend(i for i in found if i not in new_ids)
            except YouTubeError as exc:
                if self._youtube_failed(exc, f"reading channel {ref}"):
                    break

        terms = self.rules["search_terms"]
        if terms and len(new_ids) < config.MAX_SCREENED_PER_RUN and not self.problems:
            start = date.today().toordinal()
            for offset in range(min(config.MAX_SEARCHES_PER_RUN, len(terms))):
                term = terms[(start + offset) % len(terms)]
                try:
                    ids = yt.search(term, config.SEARCH_RESULTS_PER_QUERY)
                    fresh = [i for i in ids if i not in known and i not in new_ids]
                    print(f"  Search {term!r}: {len(fresh)} unseen videos")
                    new_ids.extend(fresh)
                except YouTubeError as exc:
                    if self._youtube_failed(exc, f"searching for {term!r}"):
                        break

        if not new_ids:
            return []
        try:
            return [normalize_video(item) for item in yt.videos(new_ids)]
        except YouTubeError as exc:
            self._youtube_failed(exc, "fetching video details")
            return []

    # ── Screening ────────────────────────────────────────────────────────────

    def apply_hard_filters(self, candidates: list[dict]) -> list[dict]:
        survivors = []
        for video in candidates:
            ok, code, reason = hard_filter(video, self.rules, self.blocked_ids)
            if ok:
                survivors.append(video)
            else:
                self.rejected.append(rejection(video, "hard_filter", code, reason))
                self.stats["hard_rejected"] += 1
        return survivors

    def drop_confirmed_shorts(self, videos: list[dict]) -> list[dict]:
        """Second Shorts check for brief videos, which the API cannot flag."""
        kept = []
        for video in videos:
            brief = video["duration_seconds"] <= config.SHORTS_MAX_SECONDS
            if brief and YouTube.is_short_url(video["id"]):
                self.rejected.append(rejection(
                    video, "hard_filter", "short", "Video is a YouTube Short."))
                self.stats["hard_rejected"] += 1
            else:
                kept.append(video)
        return kept

    def screen_with_ai(self, videos: list[dict]) -> None:
        import anthropic

        client = anthropic.Anthropic()
        system_prompt = ai.build_system_prompt(self.rules)
        transcripts = TranscriptFetcher()
        failures = 0

        for video in videos:
            transcript = transcripts.fetch(video["id"])
            try:
                decision = ai.screen_video(client, system_prompt, video, transcript)
            except ai.AIFatalError as exc:
                self.problems.append(f"{exc} Check the ANTHROPIC_API_KEY secret.")
                break
            except ai.AITransientError as exc:
                failures += 1
                self.warnings.append(f"AI call failed for {video['id']} ({exc}); will retry next run.")
                if failures >= config.AI_FAILURES_BEFORE_GIVING_UP:
                    self.warnings.append("Stopped screening early after repeated AI failures.")
                    break
                continue
            failures = 0

            approved, reason = ai.final_verdict(decision, self.rules)
            audit = {
                "educational_score": decision["educational_score"],
                "topics": decision["topics"],
                "used_transcript": transcript is not None,
                "model": config.MODEL_ID,
            }
            mark = "APPROVED" if approved else "rejected"
            print(f"  {mark} [{decision['educational_score']}/10] {video['title'][:70]}")
            if approved:
                self.approved.append({
                    "id": video["id"],
                    "title": video["title"],
                    "channel_id": video["channel_id"],
                    "channel_title": video["channel_title"],
                    "duration_seconds": video["duration_seconds"],
                    "published_at": video["published_at"],
                    "thumbnail": video["thumbnail"],
                    "made_for_kids": video["made_for_kids"],
                    "reason": reason,
                    **audit,
                    "screened_at": now_iso(),
                    "last_shown": None,
                    "shown_count": 0,
                })
                self.stats["ai_approved"] += 1
            else:
                self.rejected.append(rejection(video, "ai", "ai_rejected", reason, **audit))
                self.stats["ai_rejected"] += 1
        print(f"  Transcripts fetched for {transcripts.fetched} of the screened videos.")

    # ── Output ───────────────────────────────────────────────────────────────

    def write_outputs(self, today: date) -> list[dict]:
        lineup = pick_lineup(self.approved, self.rules, today)
        mark_shown(lineup, today)
        stamp = now_iso()
        save_json(config.APPROVED_PATH, {"updated": stamp, "videos": self.approved})
        save_json(config.REJECTED_PATH, {"updated": stamp, "videos": self.rejected})
        save_json(config.LINEUP_PATH, {
            "date": today.isoformat(),
            "generated_at": stamp,
            "settings": {
                "daily_watch_limit_minutes": self.rules["daily_watch_limit_minutes"],
                "pin_sha256": hashlib.sha256(self.rules["parent_pin"].encode()).hexdigest(),
                "pin_length": len(self.rules["parent_pin"]),
                "repo": os.environ.get("GITHUB_REPOSITORY", ""),
            },
            "videos": [
                {key: v[key] for key in (
                    "id", "title", "channel_title", "thumbnail", "duration_seconds",
                    "topics", "educational_score", "reason")}
                for v in lineup
            ],
        })
        return lineup


def summarize(run: Run, lineup: list[dict], today: date, quota: int) -> str:
    s = run.stats
    lines = [
        f"## KidTube screening run for {today.isoformat()}",
        "",
        f"- New videos approved by AI: **{s['ai_approved']}**",
        f"- New videos rejected by AI: **{s['ai_rejected']}**",
        f"- Rejected by hard filters: **{s['hard_rejected']}**",
        f"- Previously approved videos removed: **{s['removed']}**",
        f"- Approved pool: **{len(run.approved)}** videos",
        f"- Today's lineup: **{len(lineup)}** videos",
        f"- YouTube API quota used: about **{quota}** of 10,000 units",
    ]
    if run.problems:
        lines += ["", "### Problems to fix", *[f"- {p}" for p in run.problems]]
    if run.warnings:
        lines += ["", "### Warnings", *[f"- {w}" for w in run.warnings]]
    return "\n".join(lines) + "\n"


def main() -> int:
    # Video titles contain emoji; never let a console encoding crash the run.
    sys.stdout.reconfigure(errors="replace")
    try:
        rules = load_rules(config.RULES_PATH)
    except RulesError as exc:
        print(f"ERROR in rules.yaml: {exc}")
        return 1

    today = today_in(rules["timezone"])
    run = Run(rules)
    quota = 0

    youtube_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not youtube_key:
        run.problems.append("The YOUTUBE_API_KEY secret is not set, so no new videos were found.")
    else:
        yt = YouTube(youtube_key)
        try:
            run.resolve_blocked(yt)
            run.recheck_rule_dependent_rejections()
            run.recheck_approved(yt)
            print("Gathering candidates...")
            candidates = run.gather_candidates(yt)
        except YouTubeError as exc:
            run._youtube_failed(exc, "preparing the run")
            candidates = []
        quota = yt.quota_used

        survivors = run.apply_hard_filters(candidates)
        to_screen = run.drop_confirmed_shorts(
            order_candidates(survivors, config.MAX_SCREENED_PER_RUN))
        print(
            f"{len(candidates)} unseen videos, {len(survivors)} passed the hard filters, "
            f"screening {len(to_screen)} with {config.MODEL_ID}."
        )
        if to_screen:
            if os.environ.get("ANTHROPIC_API_KEY", "").strip():
                run.screen_with_ai(to_screen)
            else:
                run.problems.append(
                    "The ANTHROPIC_API_KEY secret is not set, so no videos were screened.")

    # Always write a lineup, even when discovery failed, so the kid site keeps
    # working from the existing approved pool.
    lineup = run.write_outputs(today)
    summary = summarize(run, lineup, today, quota)
    print("\n" + summary)
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write(summary)
    return 1 if run.problems else 0


if __name__ == "__main__":
    sys.exit(main())
