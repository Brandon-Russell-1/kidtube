import pytest

from screener.rules import RulesError, parse_rules


def test_channel_buttons():
    assert parse_rules({})["channel_buttons"] == []
    assert parse_rules({"channel_buttons": ["@wbkids", " "]})["channel_buttons"] == ["@wbkids"]


def test_channel_buttons_must_be_a_list():
    with pytest.raises(RulesError):
        parse_rules({"channel_buttons": "@wbkids"})
