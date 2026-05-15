"""飞书自定义机器人 Webhook 发送。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import requests

log = logging.getLogger(__name__)


@dataclass
class NotifyResult:
    ok: bool
    message: str = ""


class LarkWebhookNotifier:
    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout

    def _post(self, payload: dict) -> NotifyResult:
        if not self.webhook_url:
            log.error("lark webhook send skipped: empty webhook_url")
            return NotifyResult(ok=False, message="webhook_url is empty")
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
            data = resp.json()
        except Exception as e:
            log.error("lark webhook request failed: %s | payload_keys=%s", e, list(payload))
            return NotifyResult(ok=False, message=str(e))
        # 飞书 webhook 成功返回 {"StatusCode":0, "msg":"success"} 或新版 {"code":0, "msg":"success"}
        ok = (data.get("StatusCode") == 0) or (data.get("code") == 0)
        if not ok:
            log.error("lark webhook server error: code=%s msg=%s", data.get("code"), data.get("msg"))
        return NotifyResult(ok=ok, message=str(data.get("msg", "")))

    def send_text(self, text: str) -> NotifyResult:
        return self._post({"msg_type": "text", "content": {"text": text}})

    def send_messages(self, messages: Sequence[str], batch_threshold: int = 5) -> NotifyResult:
        """把一帧的多条新消息合并成单条飞书消息。"""
        if not messages:
            return NotifyResult(ok=True, message="no messages")
        n = len(messages)
        if n == 1:
            return self.send_text(messages[0])
        body = "\n---\n".join(messages)
        if n >= batch_threshold:
            text = f"【批量 {n} 条】如刚刚滚动过页面可忽略\n\n{body}"
        else:
            text = body
        return self.send_text(text)
