from unittest.mock import MagicMock, patch

from app.notifier.lark_webhook import LarkWebhookNotifier


URL_A = "https://example.invalid/webhook/aaa"
URL_B = "https://example.invalid/webhook/bbb"
URL_C = "https://example.invalid/webhook/ccc"


def _mock_resp(json_data: dict, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    return resp


# ---------- 单 URL（兼容原 v0.1.0 行为）----------

def test_send_text_single_url_success():
    n = LarkWebhookNotifier([URL_A])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"StatusCode": 0, "msg": "success"})
        r = n.send_text("hello")
    assert r.ok is True
    assert post.call_count == 1
    sent_payload = post.call_args.kwargs["json"]
    assert sent_payload == {"msg_type": "text", "content": {"text": "hello"}}


def test_send_text_single_url_server_error():
    n = LarkWebhookNotifier([URL_A])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 9499, "msg": "bad webhook"})
        r = n.send_text("hello")
    assert r.ok is False


def test_send_text_single_url_network_error():
    n = LarkWebhookNotifier([URL_A])
    with patch("app.notifier.lark_webhook.requests.post", side_effect=Exception("boom")):
        r = n.send_text("hello")
    assert r.ok is False
    assert "boom" in r.message


# ---------- 空 list ----------

def test_send_with_empty_url_list():
    n = LarkWebhookNotifier([])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        r = n.send_text("hello")
    assert r.ok is False
    assert "no webhook urls" in r.message.lower()
    post.assert_not_called()


# ---------- 多 URL ----------

def test_send_text_multi_urls_all_success():
    n = LarkWebhookNotifier([URL_A, URL_B, URL_C])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 0, "msg": "success"})
        r = n.send_text("hello")
    assert r.ok is True
    assert post.call_count == 3
    called_urls = [c.args[0] for c in post.call_args_list]
    assert called_urls == [URL_A, URL_B, URL_C]


def test_send_text_multi_urls_one_network_fail_does_not_block_others():
    """1 个抛 Exception，其他 2 个仍然被调用；总体 ok=False。"""
    n = LarkWebhookNotifier([URL_A, URL_B, URL_C])

    def side_effect(url, **kwargs):
        if url == URL_B:
            raise Exception("network timeout")
        return _mock_resp({"code": 0, "msg": "success"})

    with patch("app.notifier.lark_webhook.requests.post", side_effect=side_effect) as post:
        r = n.send_text("hello")

    assert post.call_count == 3
    assert r.ok is False
    # message 应能定位是哪个 URL 失败（含 url 尾段 + 错误简述）
    assert "1/3" in r.message
    assert "bbb" in r.message
    assert "timeout" in r.message.lower()


def test_send_text_multi_urls_one_server_error():
    """1 个返回 code != 0，其他 2 个 OK。"""
    n = LarkWebhookNotifier([URL_A, URL_B, URL_C])

    def side_effect(url, **kwargs):
        if url == URL_B:
            return _mock_resp({"code": 9499, "msg": "invalid webhook"})
        return _mock_resp({"code": 0, "msg": "success"})

    with patch("app.notifier.lark_webhook.requests.post", side_effect=side_effect):
        r = n.send_text("hello")
    assert r.ok is False
    assert "1/3" in r.message
    assert "bbb" in r.message


def test_send_text_multi_urls_all_fail():
    n = LarkWebhookNotifier([URL_A, URL_B])
    with patch("app.notifier.lark_webhook.requests.post", side_effect=Exception("boom")):
        r = n.send_text("hello")
    assert r.ok is False
    assert "all 2" in r.message.lower() or "2/2" in r.message


# ---------- send_messages 行为不变（payload 只 build 一次） ----------

def test_send_messages_single_payload_dispatched_to_each_url():
    n = LarkWebhookNotifier([URL_A, URL_B])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 0, "msg": "ok"})
        n.send_messages(["m"])
    # 2 个 URL 都收到同一份 payload
    payloads = [c.kwargs["json"] for c in post.call_args_list]
    assert payloads == [
        {"msg_type": "text", "content": {"text": "m"}},
        {"msg_type": "text", "content": {"text": "m"}},
    ]


def test_send_messages_few_concat_to_each_url():
    n = LarkWebhookNotifier([URL_A, URL_B])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 0, "msg": "ok"})
        n.send_messages(["a", "b", "c"], batch_threshold=5)
    payloads = [c.kwargs["json"] for c in post.call_args_list]
    assert all(p["content"]["text"] == "a\n---\nb\n---\nc" for p in payloads)


def test_send_messages_batch_prefix_applied_each_url():
    n = LarkWebhookNotifier([URL_A, URL_B])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 0, "msg": "ok"})
        n.send_messages([f"m{i}" for i in range(5)], batch_threshold=5)
    payloads = [c.kwargs["json"] for c in post.call_args_list]
    assert all(p["content"]["text"].startswith("【批量 5 条】") for p in payloads)


def test_send_messages_empty_short_circuits():
    n = LarkWebhookNotifier([URL_A])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        r = n.send_messages([])
    assert r.ok is True
    post.assert_not_called()
