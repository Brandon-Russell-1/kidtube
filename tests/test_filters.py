import pytest

from screener.filters import (
    hard_filter, is_short, normalize_video, order_candidates, parse_duration,
)
from screener.rules import parse_rules

RULES = parse_rules({"min_video_minutes": 3, "max_video_minutes": 20})


def make_video(**overrides):
    video = {
        "id": "abc123",
        "title": "How Do Volcanoes Work?",
        "description": "A look inside a volcano.",
        "tags": ["science", "kids"],
        "channel_id": "UC_good",
        "channel_title": "Science Kids",
        "duration_seconds": 8 * 60,
        "embeddable": True,
        "made_for_kids": True,
        "privacy_status": "public",
        "age_restricted": False,
        "live_broadcast_content": "none",
        "was_livestream": False,
    }
    video.update(overrides)
    return video


@pytest.mark.parametrize("iso, seconds", [
    ("PT8M", 480),
    ("PT1H2M3S", 3723),
    ("PT45S", 45),
    ("P1DT1S", 86401),
    ("P0D", 0),
    ("", 0),
    (None, 0),
    ("garbage", 0),
])
def test_parse_duration(iso, seconds):
    assert parse_duration(iso) == seconds


def test_good_video_passes():
    assert hard_filter(make_video(), RULES) == (True, "", "")


@pytest.mark.parametrize("overrides, code", [
    ({"embeddable": False}, "not_embeddable"),
    ({"privacy_status": "unlisted"}, "not_public"),
    ({"age_restricted": True}, "age_restricted"),
    ({"live_broadcast_content": "live"}, "livestream"),
    ({"live_broadcast_content": "upcoming"}, "livestream"),
    ({"was_livestream": True}, "livestream"),
    ({"duration_seconds": 45}, "short"),
    ({"title": "Quick trick #shorts"}, "short"),
    ({"tags": ["Shorts"]}, "short"),
    ({"duration_seconds": 2 * 60}, "too_short"),
    ({"duration_seconds": 21 * 60}, "too_long"),
    ({"duration_seconds": 0}, "too_short"),
])
def test_rejections(overrides, code):
    passed, got_code, reason = hard_filter(make_video(**overrides), RULES)
    assert not passed
    assert got_code == code
    assert reason


def test_duration_limits_are_inclusive():
    assert hard_filter(make_video(duration_seconds=3 * 60), RULES)[0]
    assert hard_filter(make_video(duration_seconds=20 * 60), RULES)[0]


def test_blocked_channel_rejected_before_anything_else():
    video = make_video(channel_id="UC_bad", embeddable=False)
    assert hard_filter(video, RULES, {"UC_bad"})[1] == "channel_blocked"
    assert hard_filter(make_video(), RULES, {"UC_bad"})[0]


def test_word_shorts_in_ordinary_title_is_not_a_short():
    assert not is_short(make_video(title="Why do giraffes wear shorts? A silly story"))


def test_not_made_for_kids_still_passes():
    assert hard_filter(make_video(made_for_kids=False), RULES)[0]


def test_normalize_video_reads_api_shape():
    item = {
        "id": "xyz",
        "snippet": {
            "title": "T", "description": "D", "channelId": "UC1", "channelTitle": "C",
            "publishedAt": "2026-01-01T00:00:00Z", "tags": ["a"],
            "liveBroadcastContent": "none",
            "thumbnails": {"high": {"url": "h.jpg"}, "maxres": {"url": "m.jpg"}},
        },
        "contentDetails": {"duration": "PT5M", "contentRating": {}},
        "status": {"embeddable": True, "madeForKids": True, "privacyStatus": "public"},
    }
    video = normalize_video(item)
    assert video["duration_seconds"] == 300
    assert video["thumbnail"] == "m.jpg"
    assert video["made_for_kids"] and video["embeddable"]
    assert not video["was_livestream"] and not video["age_restricted"]
    assert hard_filter(video, RULES)[0]


def test_normalize_video_flags_past_livestream_and_age_restriction():
    item = {
        "id": "xyz",
        "snippet": {},
        "contentDetails": {"duration": "PT5M", "contentRating": {"ytRating": "ytAgeRestricted"}},
        "status": {},
        "liveStreamingDetails": {"actualStartTime": "2026-01-01T00:00:00Z"},
    }
    video = normalize_video(item)
    assert video["was_livestream"] and video["age_restricted"]
    assert not video["embeddable"]  # missing status must never count as embeddable


def test_order_candidates_prefers_made_for_kids_and_mixes_channels():
    videos = [
        make_video(id="a1", channel_id="A", made_for_kids=False),
        make_video(id="a2", channel_id="A", made_for_kids=True),
        make_video(id="a3", channel_id="A", made_for_kids=True),
        make_video(id="b1", channel_id="B", made_for_kids=True),
        make_video(id="c1", channel_id="C", made_for_kids=False),
    ]
    ordered = [v["id"] for v in order_candidates(videos, 3)]
    assert ordered == ["a2", "b1", "c1"]
    assert len(order_candidates(videos, 40)) == 5


def test_order_candidates_reserves_a_share_for_search_results():
    trusted = [make_video(id=f"t{i}", channel_id=f"T{i % 3}") for i in range(20)]
    searched = [make_video(id=f"s{i}", channel_id=f"S{i}", source="search") for i in range(5)]
    ordered = order_candidates(trusted + searched, 10, search_share=0.2)
    ids = [v["id"] for v in ordered]
    assert len(ids) == 10
    assert sum(i.startswith("s") for i in ids) == 2       # a fifth of 10
    assert all(i.startswith("t") for i in ids[:8])        # trusted channels go first


def test_search_results_fill_slots_trusted_channels_leave_empty():
    trusted = [make_video(id="t1", channel_id="T")]
    searched = [make_video(id=f"s{i}", channel_id=f"S{i}", source="search") for i in range(5)]
    ids = [v["id"] for v in order_candidates(trusted + searched, 4, search_share=0.2)]
    assert ids[0] == "t1" and len(ids) == 4


def test_no_search_results_means_trusted_channels_get_every_slot():
    trusted = [make_video(id=f"t{i}", channel_id="T") for i in range(10)]
    assert len(order_candidates(trusted, 10, search_share=0.2)) == 10


def test_screening_cap_default_and_ceiling():
    assert parse_rules({})["max_videos_screened_per_run"] == 40
    assert parse_rules({"max_videos_screened_per_run": 150})["max_videos_screened_per_run"] == 150
    assert parse_rules({"max_videos_screened_per_run": 99999})["max_videos_screened_per_run"] == 500
    with pytest.raises(ValueError):
        parse_rules({"max_videos_screened_per_run": 0})


def test_long_form_playlist_id():
    from screener.youtube import YouTube
    assert YouTube.long_form_playlist("UCRFIPG2u1DxKLNuE3y2SjHA") == "UULFRFIPG2u1DxKLNuE3y2SjHA"
