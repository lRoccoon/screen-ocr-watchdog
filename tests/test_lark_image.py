"""LarkImageNotifier 单测：mock requests.post，验证三段流程参数 + token 缓存。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from PIL import Image

from app.notifier.lark_image import LarkImageNotifier


def _make_notifier() -> LarkImageNotifier:
    return LarkImageNotifier(
        app_id="cli_xxx",
        app_secret="sec_xxx",
        receive_id="oc_abc",
        receive_id_type="chat_id",
    )


def _mock_resp(json_data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    return resp


def _png() -> Image.Image:
    return Image.new("RGB", (10, 10), (255, 0, 0))


def _fake_post_factory():
    """返回一个 side_effect 函数：按 URL 返回不同响应。"""
    def side_effect(url, **kwargs):
        if "tenant_access_token" in url:
            return _mock_resp({"code": 0, "tenant_access_token": "t-abc", "expire": 7200})
        if "im/v1/images" in url:
            return _mock_resp({"code": 0, "data": {"image_key": "img_v3_xxx"}})
        if "im/v1/messages" in url:
            return _mock_resp({"code": 0, "data": {"message_id": "om_msg_1"}})
        raise AssertionError(f"unexpected URL: {url}")
    return side_effect


def test_send_image_happy_path():
    n = _make_notifier()
    with patch("app.notifier.lark_image.requests.post", side_effect=_fake_post_factory()) as post:
        r = n.send_image(_png())
    assert r.ok is True
    calls = [c.args[0] for c in post.call_args_list]
    assert any("tenant_access_token" in u for u in calls)
    assert any("im/v1/images" in u for u in calls)
    assert any("im/v1/messages?receive_id_type=chat_id" in u for u in calls)

    # 验证发消息 body
    msg_call = next(c for c in post.call_args_list if "im/v1/messages" in c.args[0])
    body = msg_call.kwargs["json"]
    assert body["receive_id"] == "oc_abc"
    assert body["msg_type"] == "image"
    content = json.loads(body["content"])
    assert content["image_key"] == "img_v3_xxx"


def test_token_cached_second_call_skips_token_endpoint():
    n = _make_notifier()
    with patch("app.notifier.lark_image.requests.post", side_effect=_fake_post_factory()) as post:
        n.send_image(_png())
        n.send_image(_png())
    token_calls = [c for c in post.call_args_list if "tenant_access_token" in c.args[0]]
    assert len(token_calls) == 1, f"token endpoint should be called once, got {len(token_calls)}"


def test_expired_token_triggers_refresh():
    """手动把 _token_expires_at 设到过去，下次 send_image 应触发 token 重新拉取。

    避免 patch time.monotonic 污染全局；直接操控状态字段更稳。
    """
    n = _make_notifier()
    fake_post = MagicMock(side_effect=_fake_post_factory())
    with patch("app.notifier.lark_image.requests.post", fake_post):
        n.send_image(_png())
        n._token_expires_at = float("-inf")  # 强制过期
        n.send_image(_png())
    token_calls = [c for c in fake_post.call_args_list if "tenant_access_token" in c.args[0]]
    assert len(token_calls) == 2, "expired token should be refreshed"


def test_token_endpoint_business_error():
    n = _make_notifier()
    def s(url, **kwargs):
        return _mock_resp({"code": 99991663, "msg": "invalid app_id"})
    with patch("app.notifier.lark_image.requests.post", side_effect=s):
        r = n.send_image(_png())
    assert r.ok is False
    assert "99991663" in r.message or "invalid app_id" in r.message


def test_upload_business_error():
    n = _make_notifier()
    def s(url, **kwargs):
        if "tenant_access_token" in url:
            return _mock_resp({"code": 0, "tenant_access_token": "t-x", "expire": 7200})
        return _mock_resp({"code": 230002, "msg": "image too large"})
    with patch("app.notifier.lark_image.requests.post", side_effect=s):
        r = n.send_image(_png())
    assert r.ok is False
    assert "230002" in r.message or "image too large" in r.message


def test_network_exception_returns_failure():
    n = _make_notifier()
    with patch("app.notifier.lark_image.requests.post", side_effect=Exception("boom")):
        r = n.send_image(_png())
    assert r.ok is False
    assert "boom" in r.message


def test_missing_credentials_short_circuits():
    n = LarkImageNotifier(app_id="", app_secret="", receive_id="oc_abc", receive_id_type="chat_id")
    with patch("app.notifier.lark_image.requests.post") as post:
        r = n.send_image(_png())
    assert r.ok is False
    assert "credential" in r.message.lower() or "app_id" in r.message.lower()
    post.assert_not_called()
