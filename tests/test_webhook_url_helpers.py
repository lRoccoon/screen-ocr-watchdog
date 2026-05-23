"""webhook_url_helpers 纯函数单测：URL 多行文本解析 / 渲染。"""
from app.ui.webhook_url_helpers import (
    format_webhook_urls_for_textarea,
    parse_webhook_urls_from_textarea,
)


def test_parse_empty_returns_empty_list():
    assert parse_webhook_urls_from_textarea("") == []
    assert parse_webhook_urls_from_textarea("   \n  \n") == []


def test_parse_strips_whitespace_and_drops_blank_lines():
    text = "  https://a  \n\nhttps://b\n   \nhttps://c\n"
    assert parse_webhook_urls_from_textarea(text) == [
        "https://a",
        "https://b",
        "https://c",
    ]


def test_parse_dedupes_preserving_order():
    text = "https://a\nhttps://b\nhttps://a\n"
    assert parse_webhook_urls_from_textarea(text) == ["https://a", "https://b"]


def test_format_empty_list_returns_empty_string():
    assert format_webhook_urls_for_textarea([], "") == ""


def test_format_merges_list_and_legacy_single_field():
    out = format_webhook_urls_for_textarea(
        webhook_urls=["https://a", "https://b"],
        webhook_url_legacy="https://legacy",
    )
    assert out == "https://a\nhttps://b\nhttps://legacy"


def test_format_skips_legacy_when_already_in_list():
    out = format_webhook_urls_for_textarea(
        webhook_urls=["https://a"],
        webhook_url_legacy="https://a",
    )
    assert out == "https://a"


def test_format_legacy_only():
    out = format_webhook_urls_for_textarea(
        webhook_urls=[],
        webhook_url_legacy="https://legacy",
    )
    assert out == "https://legacy"
