from unittest.mock import MagicMock, patch

from app.notifier.lark_webhook import LarkWebhookNotifier


WEBHOOK = "https://example.invalid/webhook"


def _mock_resp(json_data: dict, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    return resp


def test_send_text_success():
    n = LarkWebhookNotifier(WEBHOOK)
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"StatusCode": 0, "msg": "success"})
        r = n.send_text("hello")
    assert r.ok is True
    sent_payload = post.call_args.kwargs["json"]
    assert sent_payload == {"msg_type": "text", "content": {"text": "hello"}}


def test_send_text_server_error():
    n = LarkWebhookNotifier(WEBHOOK)
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 9499, "msg": "bad webhook"})
        r = n.send_text("hello")
    assert r.ok is False
    assert "bad webhook" in r.message


def test_send_text_network_error():
    n = LarkWebhookNotifier(WEBHOOK)
    with patch("app.notifier.lark_webhook.requests.post", side_effect=Exception("boom")):
        r = n.send_text("hello")
    assert r.ok is False
    assert "boom" in r.message


def test_send_empty_webhook_url():
    n = LarkWebhookNotifier("")
    r = n.send_text("hello")
    assert r.ok is False
    assert "empty" in r.message.lower()


def test_send_messages_single():
    n = LarkWebhookNotifier(WEBHOOK)
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"StatusCode": 0, "msg": "ok"})
        n.send_messages(["just one"])
    assert post.call_args.kwargs["json"]["content"]["text"] == "just one"


def test_send_messages_few_concat():
    n = LarkWebhookNotifier(WEBHOOK)
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"StatusCode": 0, "msg": "ok"})
        n.send_messages(["a", "b", "c"], batch_threshold=5)
    text = post.call_args.kwargs["json"]["content"]["text"]
    assert text == "a\n---\nb\n---\nc"


def test_send_messages_batch_prefix():
    n = LarkWebhookNotifier(WEBHOOK)
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"StatusCode": 0, "msg": "ok"})
        n.send_messages([f"m{i}" for i in range(5)], batch_threshold=5)
    text = post.call_args.kwargs["json"]["content"]["text"]
    assert text.startswith("【批量 5 条】")


def test_send_messages_empty():
    n = LarkWebhookNotifier(WEBHOOK)
    with patch("app.notifier.lark_webhook.requests.post") as post:
        r = n.send_messages([])
    assert r.ok is True
    post.assert_not_called()
