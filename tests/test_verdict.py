from screener.ai import build_user_prompt, final_verdict
from screener.rules import parse_rules

RULES = parse_rules({"min_educational_score": 7})


def decision(approve=True, score=8):
    return {"approve": approve, "educational_score": score, "topics": [], "reason": "r"}


def test_learning_videos_need_the_minimum_score():
    assert final_verdict(decision(score=8), RULES)[:1] == (True,)
    assert final_verdict(decision(score=8), RULES)[2] == "learning"
    approved, reason, kind = final_verdict(decision(score=5), RULES)
    assert not approved and "below the minimum" in reason and kind == ""


def test_fun_channel_videos_skip_the_score_but_not_the_ai_verdict():
    assert final_verdict(decision(score=3), RULES, fun=True) == (True, "r", "fun")
    assert final_verdict(decision(score=8), RULES, fun=True) == (True, "r", "learning")
    assert final_verdict(decision(approve=False, score=3), RULES, fun=True)[0] is False


def test_prompt_says_where_the_video_came_from():
    video = {"title": "t", "channel_title": "c", "duration_seconds": 300}
    assert "picked for fun" in build_user_prompt({**video, "source": "fun"}, None)
    assert "not vetted" in build_user_prompt({**video, "source": "search"}, None)
    assert "parent trusts" in build_user_prompt({**video, "source": "trusted"}, None)
