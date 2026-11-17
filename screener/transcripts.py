"""Best-effort transcript fetching. Never raises; returns None on any failure.

YouTube often blocks transcript requests from cloud IPs such as GitHub's
runners, so after a few failures in a row this stops trying for the rest of
the run and the job screens on title, description, and tags instead.
"""

from __future__ import annotations

import requests

from . import config

# Failures that say something about the video, not about us being blocked.
_VIDEO_SPECIFIC = {
    "TranscriptsDisabled", "NoTranscriptFound", "NoTranscriptAvailable",
    "VideoUnavailable", "VideoUnplayable", "AgeRestricted", "InvalidVideoId",
}
_LANGUAGES = ["en", "en-US", "en-GB"]


class _TimeoutSession(requests.Session):
    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", 15)
        return super().request(*args, **kwargs)


class TranscriptFetcher:
    def __init__(self):
        self.consecutive_failures = 0
        self.fetched = 0
        self.gave_up = False

    def fetch(self, video_id: str) -> str | None:
        if self.gave_up:
            return None
        try:
            text = self._fetch(video_id)
        except Exception as exc:  # the library raises many types; none may fail the run
            if type(exc).__name__ not in _VIDEO_SPECIFIC:
                self.consecutive_failures += 1
                if self.consecutive_failures >= config.TRANSCRIPT_FAILURES_BEFORE_GIVING_UP:
                    self.gave_up = True
                    print(
                        f"  Transcripts unavailable from this machine "
                        f"({type(exc).__name__}); using titles and descriptions only."
                    )
            return None
        self.consecutive_failures = 0
        if not text:
            return None
        self.fetched += 1
        return text[: config.TRANSCRIPT_MAX_CHARS]

    @staticmethod
    def _fetch(video_id: str) -> str:
        from youtube_transcript_api import YouTubeTranscriptApi

        if hasattr(YouTubeTranscriptApi, "fetch"):  # library version 1.0 and later
            api = YouTubeTranscriptApi(http_client=_TimeoutSession())
            snippets = api.fetch(video_id, languages=_LANGUAGES)
            parts = [snippet.text for snippet in snippets]
        else:
            snippets = YouTubeTranscriptApi.get_transcript(video_id, languages=_LANGUAGES)
            parts = [snippet["text"] for snippet in snippets]
        return " ".join(" ".join(parts).split())
