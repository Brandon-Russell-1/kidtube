import pytest

from screener.filters import order_candidates
from screener.matching import approved_text, matches
from screener.rules import RulesError, parse_rules


@pytest.mark.parametrize("text, words, expected", [
    ("Dinosaur Facts for Kids", ["dinosaurs"], True),          # plural word, singular title
    ("Spidey and His Amazing Friends", ["spiderman", "spidey"], True),
    ("Marvel's Spider-Man: Halloween", ["spiderman"], True),   # hyphen ignored
    ("Cassini: The Spacecraft That Flew Into Saturn", ["space"], True),  # start of a word
    ("Learn about education", ["cat"], False),                 # not inside a word
    ("Top 30 Moments from Arthur", ["art for kids hub"], False),
    ("How It's Made: Crayons", ["how its made"], True),        # apostrophe ignored
    ("PAW Patrol Rescue", ["paw patrol"], True),
    ("Patrol PAW", ["paw patrol"], False),                     # phrases keep their order
])
def test_matching(text, words, expected):
    assert matches(text, words) is expected


def test_approved_text_includes_topics_and_fun_tag():
    video = {"title": "Episode", "channel_title": "Bluey", "topics": ["family"], "kind": "fun"}
    assert matches(approved_text(video), ["fun"])
    assert matches(approved_text(video), ["family"])
    assert not matches(approved_text({**video, "kind": "learning"}), ["fun"])


def test_search_buttons_parse():
    rules = parse_rules({"search_buttons": [
        "space",
        {"word": "Paw  Patrol", "emoji": "🚒"},
        {"word": "spiderman", "also_match": "spidey"},
    ]})
    assert rules["search_buttons"] == [
        {"word": "space", "emoji": "", "match": ["space"]},
        {"word": "Paw Patrol", "emoji": "🚒", "match": ["Paw Patrol"]},
        {"word": "spiderman", "emoji": "", "match": ["spiderman", "spidey"]},
    ]
    with pytest.raises(RulesError):
        parse_rules({"search_buttons": [{"emoji": "🚒"}]})
    with pytest.raises(RulesError):
        parse_rules({"search_buttons": ["a word that is far too long for a button"]})


def test_button_matches_are_screened_first_within_a_channel():
    videos = [
        {"id": "plain", "channel_id": "A", "title": "Counting to ten", "made_for_kids": True},
        {"id": "dino", "channel_id": "A", "title": "T-Rex facts", "made_for_kids": False},
    ]
    assert [v["id"] for v in order_candidates(videos, 1, priority_words=["trex"])] == ["dino"]
    assert [v["id"] for v in order_candidates(videos, 1)] == ["plain"]
