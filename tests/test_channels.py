from datetime import date

import pytest

from screener.channels import icon_from_snippet, merge, needs_lookup, prune, safe_icon

TODAY = date(2026, 11, 17)
ICON = "https://yt3.ggpht.com/abc-123=s88-c-k-c0x00ffffff-no-rj"


@pytest.mark.parametrize("url, ok", [
    (ICON, True),
    ("https://yt3.googleusercontent.com/xyz=s88-c-k", True),
    ("http://yt3.ggpht.com/abc", False),                 # not https
    ("https://evil.example/yt3.ggpht.com/abc", False),   # wrong host
    ("https://yt3.ggpht.com.evil.example/abc", False),   # lookalike host
    ("https://yt3.ggpht.com/abc\"><script>", False),     # stray characters
    (None, False),
])
def test_safe_icon(url, ok):
    assert safe_icon(url) == (url if ok else None)


def test_icon_from_snippet_prefers_smallest_safe_size():
    snippet = {"thumbnails": {
        "default": {"url": "https://elsewhere.example/a.jpg"},
        "medium": {"url": ICON},
    }}
    assert icon_from_snippet(snippet) == ICON
    assert icon_from_snippet({}) is None


def test_needs_lookup_finds_missing_and_stale():
    cache = {
        "UCfresh": {"icon": ICON, "checked": "2026-11-10"},
        "UCstale": {"icon": ICON, "checked": "2026-09-01"},
        "UCbroken": {"icon": ICON, "checked": "not a date"},
    }
    ids = {"UCfresh", "UCstale", "UCbroken", "UCnew"}
    assert needs_lookup(cache, ids, TODAY, 30) == ["UCbroken", "UCnew", "UCstale"]


def test_merge_records_lookups_and_drops_unsafe_icons():
    cache = {"UCgone": {"title": "Old name", "icon": ICON, "checked": "2026-09-01"}}
    found = {"UCa": {"title": "A", "icon": ICON}, "UCb": {"title": "B", "icon": "javascript:x"}}
    merged = merge(cache, ["UCa", "UCb", "UCgone"], found, TODAY)
    assert merged["UCa"] == {"title": "A", "icon": ICON, "checked": "2026-11-17"}
    assert merged["UCb"]["icon"] is None
    # A channel YouTube didn't return keeps its title but loses its icon until the next check.
    assert merged["UCgone"] == {"title": "Old name", "icon": None, "checked": "2026-11-17"}


def test_prune_keeps_pool_channels_only():
    cache = {"UCa": {}, "UCb": {}}
    assert prune(cache, {"UCa"}) == {"UCa": {}}
