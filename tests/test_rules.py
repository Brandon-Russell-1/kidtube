import pytest

from screener.rules import RulesError, parse_rules


def test_new_settings_default_to_off():
    rules = parse_rules({})
    assert rules["channel_buttons"] == []
    assert rules["learning_minutes_before_fun"] == 0


def test_channel_buttons_and_learning_first():
    rules = parse_rules({"channel_buttons": ["@wbkids", " "], "learning_minutes_before_fun": 15})
    assert rules["channel_buttons"] == ["@wbkids"]
    assert rules["learning_minutes_before_fun"] == 15


@pytest.mark.parametrize("raw", [
    {"channel_buttons": "@wbkids"},
    {"learning_minutes_before_fun": -1},
    {"learning_minutes_before_fun": "lots"},
])
def test_bad_values_are_refused(raw):
    with pytest.raises(RulesError):
        parse_rules(raw)
