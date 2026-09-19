"""vision.extract_codes() 的 JSON 抽取邏輯回歸測試。

2026-09-19:模型有時會在 ```json``` fence 前面先加一段說明文字,舊的錨定正規式
(^```...```$)比對失敗、整段(含說明文字)丟給 json.loads() 直接炸掉,見 vision.py
模組說明。這裡固定住當時 Carson 實測撞到的真實回應內容,防止regres。
"""
from __future__ import annotations

from unittest import mock

from webhook import vision


def _fake_response(content: str):
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def _run(content: str) -> list[str]:
    with mock.patch("webhook.vision.os.environ.get", return_value="fake-key"):
        with mock.patch("webhook.vision.requests.post", return_value=_fake_response(content)):
            return [it["code"] for it in vision.extract_codes(b"fake-bytes", "image/png", max_codes=5)]


def test_prose_before_fence_still_parses():
    content = (
        "根據畫面內容,我可以看到一檔股票:\n\n"
        "**凱基台灣TOP50** - 這是凱基投信發行的ETF，正確代號是 **00922**\n\n"
        "```json\n{\"codes\": [\"00922\"]}\n```"
    )
    assert _run(content) == ["00922"]


def test_pure_fenced_json_still_parses():
    content = "```json\n{\"codes\": [\"2330\", \"2603\"]}\n```"
    assert _run(content) == ["2330", "2603"]


def test_plain_json_no_fence_still_parses():
    content = '{"codes": ["2330"]}'
    assert _run(content) == ["2330"]


def test_empty_content_raises_vision_error():
    import pytest
    with pytest.raises(vision.VisionError):
        _run("")


def test_draft_fence_then_real_fence_uses_last():
    content = (
        "這是格式範例:\n```json\n這不是合法JSON\n```\n\n"
        "實際結果:\n```json\n{\"codes\": [\"2330\"]}\n```"
    )
    assert _run(content) == ["2330"]


def test_two_valid_json_fences_uses_last_not_first():
    content = (
        "草稿:\n```json\n{\"codes\": [\"9999\"]}\n```\n\n"
        "修正:\n```json\n{\"codes\": [\"2330\"]}\n```"
    )
    assert _run(content) == ["2330"]


def test_prose_mentions_fence_syntax_before_real_fence():
    content = (
        "我通常會用```json```格式回答。\n\n"
        "實際結果:```json\n{\"codes\": [\"2330\"]}\n```"
    )
    assert _run(content) == ["2330"]


def test_last_valid_json_without_codes_key_falls_back_to_earlier():
    content = (
        "```json\n{\"codes\": [\"2330\", \"2603\"]}\n```\n\n"
        "備註:```json\n{\"foo\": \"bar\"}\n```"
    )
    assert _run(content) == ["2330", "2603"]


def test_last_valid_json_with_null_codes_falls_back_to_earlier():
    content = (
        "```json\n{\"codes\": [\"2330\"]}\n```\n\n"
        "```json\n{\"codes\": null}\n```"
    )
    assert _run(content) == ["2330"]


def test_nested_backticks_inside_fence_content_still_parses():
    content = (
        "```json\n{\"codes\": [\"2330\"], \"note\": \"a ```nested``` backtick\"}\n```"
    )
    assert _run(content) == ["2330"]


def test_orphan_unmatched_brace_before_real_object_still_parses():
    content = 'note { \n\n{"codes": ["2330"]}'
    assert _run(content) == ["2330"]
