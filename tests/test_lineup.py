import random
from collections import Counter
from datetime import date, timedelta

from screener.lineup import is_eligible, mark_shown, pick_lineup, topic_weight
from screener.rules import parse_rules

TODAY = date(2026, 11, 16)


def rules(**overrides):
    base = {
        "daily_lineup_count": 8,
        "repeat_after_days": 14,
        "topics_wanted": {"science": 3, "reading": 3, "math": 2, "animals": 2, "art": 1},
    }
    base.update(overrides)
    return parse_rules(base)


def make_pool(channels=6, per_channel=10, topics=("science",)):
    return [
        {
            "id": f"c{c}v{n}",
            "channel_id": f"UC{c}",
            "topics": list(topics),
            "educational_score": 8,
            "last_shown": None,
            "shown_count": 0,
        }
        for c in range(channels)
        for n in range(per_channel)
    ]


def days_ago(n):
    return (TODAY - timedelta(days=n)).isoformat()


def test_picks_requested_count_with_no_duplicates():
    lineup = pick_lineup(make_pool(), rules(), TODAY)
    ids = [v["id"] for v in lineup]
    assert len(ids) == 8
    assert len(set(ids)) == 8


def test_same_day_is_deterministic_and_next_day_differs():
    pool = make_pool()
    first = [v["id"] for v in pick_lineup(pool, rules(), TODAY)]
    again = [v["id"] for v in pick_lineup(list(reversed(pool)), rules(), TODAY)]
    tomorrow = [v["id"] for v in pick_lineup(pool, rules(), TODAY + timedelta(days=1))]
    assert first == again
    assert first != tomorrow


def test_empty_and_small_pools():
    assert pick_lineup([], rules(), TODAY) == []
    assert len(pick_lineup(make_pool(channels=1, per_channel=3), rules(), TODAY)) == 3


def test_recently_shown_videos_are_skipped():
    pool = make_pool()
    recent = {v["id"] for v in pool[:30]}
    for video in pool[:30]:
        video["last_shown"] = days_ago(3)
    lineup = pick_lineup(pool, rules(), TODAY)
    assert len(lineup) == 8
    assert not recent & {v["id"] for v in lineup}


def test_eligibility_boundaries():
    assert is_eligible({"last_shown": None}, TODAY, 14)
    assert is_eligible({"last_shown": days_ago(14)}, TODAY, 14)
    assert not is_eligible({"last_shown": days_ago(13)}, TODAY, 14)
    assert not is_eligible({"last_shown": days_ago(1)}, TODAY, 14)
    # Shown earlier today: a same-day re-run may pick it again.
    assert is_eligible({"last_shown": days_ago(0)}, TODAY, 14)
    assert is_eligible({"last_shown": "not a date"}, TODAY, 14)


def test_short_pool_backfills_with_least_recently_shown():
    pool = make_pool(channels=2, per_channel=5)
    for index, video in enumerate(pool):
        video["last_shown"] = days_ago(index + 1)  # all within 14 days
    pool[0]["last_shown"] = None                   # one fresh video
    lineup = [v["id"] for v in pick_lineup(pool, rules(), TODAY)]
    assert len(lineup) == 8
    assert lineup[0] == pool[0]["id"]
    # The two most recently shown videos are the ones left out.
    assert pool[1]["id"] not in lineup and pool[2]["id"] not in lineup


def test_channels_are_mixed():
    pool = make_pool(channels=8, per_channel=10)
    lineup = pick_lineup(pool, rules(), TODAY)
    assert len({v["channel_id"] for v in lineup}) == 8

    pool = make_pool(channels=4, per_channel=10)
    counts = Counter(v["channel_id"] for v in pick_lineup(pool, rules(), TODAY))
    assert max(counts.values()) == 2 and len(counts) == 4


def test_one_big_channel_does_not_crowd_out_small_ones():
    pool = make_pool(channels=1, per_channel=200)
    pool += [
        {"id": f"small{n}", "channel_id": f"UCsmall{n}", "topics": ["science"],
         "educational_score": 8, "last_shown": None}
        for n in range(3)
    ]
    lineup = pick_lineup(pool, rules(), TODAY)
    assert {f"small{n}" for n in range(3)} <= {v["id"] for v in lineup}


def test_topic_weight_matching():
    wanted = rules()["topics_wanted"]
    assert topic_weight({"topics": ["science"]}, wanted) == 3
    assert topic_weight({"topics": ["Animal", "art"]}, wanted) == 2   # plural/case-insensitive
    assert topic_weight({"topics": ["music"]}, wanted) == 0.5
    assert topic_weight({"topics": []}, wanted) == 0.5


def test_low_priority_topic_beats_a_wanted_one():
    wanted = rules()["topics_wanted"]
    low = ["toy unboxing"]
    assert topic_weight({"topics": ["science", "Toy Unboxing"]}, wanted, low) == 0.1
    assert topic_weight({"topics": ["science"]}, wanted, low) == 3


def test_higher_weighted_topics_appear_more_often():
    pool = []
    for topic in ("science", "art"):
        pool += [
            {"id": f"{topic}{c}_{n}", "channel_id": f"UC{topic}{c}", "topics": [topic],
             "educational_score": 8, "last_shown": None}
            for c in range(10) for n in range(5)
        ]
    seen = Counter()
    for seed in range(200):
        for video in pick_lineup(pool, rules(), TODAY, random.Random(seed)):
            seen[video["topics"][0]] += 1
    assert seen["science"] > 2 * seen["art"]


def test_mark_shown_counts_once_per_day():
    video = {"id": "a", "last_shown": None, "shown_count": 0}
    mark_shown([video], TODAY)
    mark_shown([video], TODAY)
    assert video == {"id": "a", "last_shown": TODAY.isoformat(), "shown_count": 1}
    mark_shown([video], TODAY + timedelta(days=20))
    assert video["shown_count"] == 2


def make_fun(n, channel="UCfun"):
    return [
        {"id": f"fun{i}", "channel_id": channel, "topics": ["cartoons"], "educational_score": 3,
         "kind": "fun", "last_shown": None, "shown_count": 0}
        for i in range(n)
    ]


def test_fun_videos_get_their_slots_spread_through_the_lineup():
    lineup = pick_lineup(make_pool() + make_fun(10), rules(daily_lineup_count=12, fun_videos_per_day=3), TODAY)
    kinds = [v.get("kind") for v in lineup]
    assert len(lineup) == 12
    assert kinds.count("fun") == 3
    positions = [i for i, k in enumerate(kinds) if k == "fun"]
    assert positions == [3, 6, 9]


def test_fun_videos_never_fill_extra_slots():
    small_learning_pool = make_pool(channels=1, per_channel=2)
    lineup = pick_lineup(small_learning_pool + make_fun(10), rules(fun_videos_per_day=3), TODAY)
    assert [v.get("kind") for v in lineup].count("fun") == 3
    assert len(lineup) == 5


def test_no_fun_videos_when_the_allowance_is_zero():
    lineup = pick_lineup(make_pool() + make_fun(10), rules(fun_videos_per_day=0), TODAY)
    assert all(v.get("kind") != "fun" for v in lineup)
    assert len(lineup) == 8


def test_a_small_fun_pool_repeats_rather_than_stealing_learning_slots():
    fun = make_fun(2)
    for video in fun:
        video["last_shown"] = days_ago(1)
    lineup = pick_lineup(make_pool() + fun, rules(fun_videos_per_day=3), TODAY)
    assert [v.get("kind") for v in lineup].count("fun") == 2
    assert len(lineup) == 8
