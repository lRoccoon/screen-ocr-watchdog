"""LarkImageNotifier 单测：mock requests.post，验证多 target 扇出 + token 缓存。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from PIL import Image

from app.notifier.lark_image import LarkImageNotifier
from app.storage.config import LarkTargetCfg


T_A = LarkTargetCfg(receive_id="oc_a", receive_id_type="chat_id")
T_B = LarkTargetCfg(receive_id="ou_b", receive_id_type="open_id")
T_C = LarkTargetCfg(receive_id="user@example.com", receive_id_type="email")


def _make_notifier(targets=None) -> LarkImageNotifier:
    return LarkImageNotifier(
        app_id="cli_xxx",
        app_secret="sec_xxx",
        targets=targets if targets is not None else [T_A],
    )


def _mock_resp(json_data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    return resp


def _png() -> Image.Image:
    return Image.new("RGB", (10, 10), (255, 0, 0))


def _fake_post_factory(send_message_side_effect=None):
    """返回一个 side_effect 函数：按 URL 返回不同响应。

    send_message_side_effect 是一个把 (call_idx, target_receive_id, body) → 响应字典 的函数；
    None 时一律返回 success。
    """
    state = {"send_idx": 0}

    def side_effect(url, **kwargs):
        if "tenant_access_token" in url:
            return _mock_resp({"code": 0, "tenant_access_token": "t-abc", "expire": 7200})
        if "im/v1/images" in url:
            return _mock_resp({"code": 0, "data": {"image_key": "img_v3_xxx"}})
        if "im/v1/messages" in url:
            idx = state["send_idx"]
            state["send_idx"] += 1
            body = kwargs.get("json", {})
            if send_message_side_effect is not None:
                return send_message_side_effect(idx, body.get("receive_id"), body)
            return _mock_resp({"code": 0, "data": {"message_id": f"om_msg_{idx}"}})
        raise AssertionError(f"unexpected URL: {url}")

    return side_effect


# ---------- 单 target（兼容原 v0.1.0 行为）----------

def test_send_image_single_target_happy_path():
    n = _make_notifier(targets=[T_A])
    with patch("app.notifier.lark_image.requests.post", side_effect=_fake_post_factory()) as post:
        r = n.send_image(_png())
    assert r.ok is True

    calls = [c.args[0] for c in post.call_args_list]
    assert sum(1 for u in calls if "tenant_access_token" in u) == 1
    assert sum(1 for u in calls if "im/v1/images" in u) == 1
    msg_calls = [c for c in post.call_args_list if "im/v1/messages" in c.args[0]]
    assert len(msg_calls) == 1
    assert "receive_id_type=chat_id" in msg_calls[0].args[0]
    body = msg_calls[0].kwargs["json"]
    assert body["receive_id"] == "oc_a"
    content = json.loads(body["content"])
    assert content["image_key"] == "img_v3_xxx"


def test_token_cached_across_consecutive_send_image():
    n = _make_notifier(targets=[T_A])
    with patch("app.notifier.lark_image.requests.post", side_effect=_fake_post_factory()) as post:
        n.send_image(_png())
        n.send_image(_png())
    token_calls = [c for c in post.call_args_list if "tenant_access_token" in c.args[0]]
    assert len(token_calls) == 1


def test_expired_token_triggers_refresh():
    n = _make_notifier(targets=[T_A])
    fake_post = MagicMock(side_effect=_fake_post_factory())
    with patch("app.notifier.lark_image.requests.post", fake_post):
        n.send_image(_png())
        n._token_expires_at = float("-inf")
        n.send_image(_png())
    token_calls = [c for c in fake_post.call_args_list if "tenant_access_token" in c.args[0]]
    assert len(token_calls) == 2


def test_token_endpoint_business_error():
    n = _make_notifier(targets=[T_A])

    def s(url, **kwargs):
        return _mock_resp({"code": 99991663, "msg": "invalid app_id"})

    with patch("app.notifier.lark_image.requests.post", side_effect=s):
        r = n.send_image(_png())
    assert r.ok is False
    assert "99991663" in r.message or "invalid app_id" in r.message


def test_upload_business_error_aborts_send():
    """upload 失败，整体失败且不调用任何 send_message。"""
    n = _make_notifier(targets=[T_A, T_B])

    def s(url, **kwargs):
        if "tenant_access_token" in url:
            return _mock_resp({"code": 0, "tenant_access_token": "t-x", "expire": 7200})
        if "im/v1/images" in url:
            return _mock_resp({"code": 230002, "msg": "image too large"})
        raise AssertionError(f"send_message should not be called, url={url}")

    with patch("app.notifier.lark_image.requests.post", side_effect=s) as post:
        r = n.send_image(_png())
    assert r.ok is False
    # send_message URL 完全没被调过
    assert not any("im/v1/messages" in c.args[0] for c in post.call_args_list)


def test_network_exception_returns_failure():
    n = _make_notifier(targets=[T_A])
    with patch("app.notifier.lark_image.requests.post", side_effect=Exception("boom")):
        r = n.send_image(_png())
    assert r.ok is False
    assert "boom" in r.message


# ---------- 多 target ----------

def test_send_image_multi_targets_all_success_upload_once():
    """3 个 target 全成功：token 1 次、upload 1 次、send_message 3 次。"""
    n = _make_notifier(targets=[T_A, T_B, T_C])
    with patch("app.notifier.lark_image.requests.post", side_effect=_fake_post_factory()) as post:
        r = n.send_image(_png())
    assert r.ok is True

    token_n = sum(1 for c in post.call_args_list if "tenant_access_token" in c.args[0])
    upload_n = sum(1 for c in post.call_args_list if "im/v1/images" in c.args[0])
    msg_calls = [c for c in post.call_args_list if "im/v1/messages" in c.args[0]]
    assert (token_n, upload_n, len(msg_calls)) == (1, 1, 3)

    # 每个 target 都用了自己的 receive_id 和 receive_id_type
    used = [
        (
            c.kwargs["json"]["receive_id"],
            c.args[0].split("receive_id_type=")[-1],
        )
        for c in msg_calls
    ]
    assert used == [
        ("oc_a", "chat_id"),
        ("ou_b", "open_id"),
        ("user@example.com", "email"),
    ]


def test_send_image_multi_targets_one_send_fail_does_not_block_others():
    """3 个 target，第 2 个 send_message 业务错误：upload 仍 1 次，send_message 3 次，ok=False。"""
    def send_side_effect(idx, receive_id, body):
        if receive_id == "ou_b":
            return _mock_resp({"code": 230020, "msg": "bot not in chat"})
        return _mock_resp({"code": 0, "data": {"message_id": "om"}})

    n = _make_notifier(targets=[T_A, T_B, T_C])
    fake = _fake_post_factory(send_message_side_effect=send_side_effect)
    with patch("app.notifier.lark_image.requests.post", side_effect=fake) as post:
        r = n.send_image(_png())

    upload_n = sum(1 for c in post.call_args_list if "im/v1/images" in c.args[0])
    msg_n = sum(1 for c in post.call_args_list if "im/v1/messages" in c.args[0])
    assert upload_n == 1
    assert msg_n == 3
    assert r.ok is False
    assert "1/3" in r.message
    assert "ou_b" in r.message


def test_send_image_multi_targets_network_exception_on_one_continues():
    """第 1 个 send_message 抛网络异常，其他 2 个仍然发出。"""
    def send_side_effect(idx, receive_id, body):
        if idx == 0:
            raise Exception("network timeout")
        return _mock_resp({"code": 0, "data": {"message_id": "om"}})

    n = _make_notifier(targets=[T_A, T_B, T_C])
    fake = _fake_post_factory(send_message_side_effect=send_side_effect)
    with patch("app.notifier.lark_image.requests.post", side_effect=fake) as post:
        r = n.send_image(_png())

    msg_n = sum(1 for c in post.call_args_list if "im/v1/messages" in c.args[0])
    assert msg_n == 3
    assert r.ok is False
    assert "timeout" in r.message.lower()


def test_send_image_empty_targets_short_circuits():
    n = _make_notifier(targets=[])
    with patch("app.notifier.lark_image.requests.post") as post:
        r = n.send_image(_png())
    assert r.ok is False
    assert "target" in r.message.lower() or "credential" in r.message.lower()
    post.assert_not_called()


def test_send_image_missing_credentials_short_circuits():
    n = LarkImageNotifier(app_id="", app_secret="", targets=[T_A])
    with patch("app.notifier.lark_image.requests.post") as post:
        r = n.send_image(_png())
    assert r.ok is False
    post.assert_not_called()
