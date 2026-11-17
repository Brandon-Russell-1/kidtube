"""Minimal YouTube Data API v3 client that tracks quota spent."""

from __future__ import annotations

import requests

API = "https://www.googleapis.com/youtube/v3"


class YouTubeError(RuntimeError):
    def __init__(self, status: int, reason: str, message: str):
        super().__init__(f"YouTube API error {status} ({reason}): {message}")
        self.status = status
        self.reason = reason

    @property
    def is_quota(self) -> bool:
        return self.reason in {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}

    @property
    def is_bad_key(self) -> bool:
        return self.status in (400, 401, 403) and self.reason in {
            "keyInvalid", "badRequest", "forbidden", "accessNotConfigured",
            "API_KEY_INVALID", "ipRefererBlocked",
        }


class YouTube:
    def __init__(self, api_key: str):
        self._session = requests.Session()
        # Sent as a header so the key can never end up in a logged URL.
        self._session.headers["X-Goog-Api-Key"] = api_key
        self.quota_used = 0

    def _get(self, resource: str, cost: int, **params) -> dict:
        self.quota_used += cost
        try:
            response = self._session.get(f"{API}/{resource}", params=params, timeout=30)
        except requests.RequestException as exc:
            raise YouTubeError(0, "network", type(exc).__name__)
        if response.status_code == 200:
            return response.json()
        reason, message = "unknown", response.reason or ""
        try:
            error = response.json()["error"]
            message = error.get("message", message)
            reason = (error.get("errors") or [{}])[0].get("reason", reason)
        except (ValueError, KeyError, TypeError):
            pass
        raise YouTubeError(response.status_code, reason, message)

    def resolve_channel(self, kind: str, value: str) -> dict | None:
        """Look up a channel by ("id", "UC...") or ("handle", "@name"). 1 unit."""
        lookup = {"id": value} if kind == "id" else {"forHandle": value}
        data = self._get("channels", 1, part="snippet,contentDetails", **lookup)
        items = data.get("items") or []
        if not items:
            return None
        item = items[0]
        return {
            "id": item["id"],
            "title": item["snippet"]["title"],
            "uploads_playlist": item["contentDetails"]["relatedPlaylists"]["uploads"],
        }

    def playlist_page(self, playlist_id: str, page_token: str | None = None):
        """One page (up to 50) of video IDs from a playlist, newest first. 1 unit."""
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        data = self._get("playlistItems", 1, **params)
        ids = [item["contentDetails"]["videoId"] for item in data.get("items") or []]
        return ids, data.get("nextPageToken")

    def search(self, query: str, max_results: int) -> list[str]:
        """Video IDs for a search query. 100 units - use sparingly."""
        data = self._get(
            "search", 100, part="id", q=query, type="video", maxResults=max_results,
            safeSearch="strict", videoEmbeddable="true", relevanceLanguage="en",
        )
        return [
            item["id"]["videoId"]
            for item in data.get("items") or []
            if item.get("id", {}).get("videoId")
        ]

    @staticmethod
    def is_short_url(video_id: str) -> bool | None:
        """Ask youtube.com whether this video is a Short. No API quota.

        youtube.com/shorts/<id> answers 200 for a Short and redirects to the
        normal watch page otherwise. Returns None if the answer is unclear.
        """
        try:
            response = requests.head(
                f"https://www.youtube.com/shorts/{video_id}", allow_redirects=False, timeout=10
            )
        except requests.RequestException:
            return None
        if response.status_code == 200:
            return True
        if response.status_code in (301, 302, 303, 307, 308):
            return "/shorts/" in response.headers.get("Location", "")
        return None

    def videos(self, ids: list[str]) -> list[dict]:
        """Full details for the given IDs. 1 unit per 50 videos.

        IDs that are deleted or private are simply absent from the result.
        """
        items: list[dict] = []
        for start in range(0, len(ids), 50):
            data = self._get(
                "videos", 1,
                part="snippet,contentDetails,status,liveStreamingDetails",
                id=",".join(ids[start:start + 50]), maxResults=50,
            )
            items.extend(data.get("items") or [])
        return items
