"""飞书自定义机器人 Webhook 发送：支持多个 URL，best-effort 部分失败。"""
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


def _url_tail(url: str, n: int = 12) -> str:
    return url[-n:] if len(url) > n else url


class LarkWebhookNotifier:
    def __init__(self, webhook_urls: Sequence[str], timeout: float = 10.0) -> None:
        # 过滤空字符串，构造完即 immutable
        self.webhook_urls: list[str] = [u for u in webhook_urls if u]
        self.timeout = timeout

    def _post(self, payload: dict) -> NotifyResult:
        if not self.webhook_urls:
            log.error("lark webhook send skipped: no webhook urls configured")
            return NotifyResult(ok=False, message="no webhook urls configured")

        failures: list[str] = []
        for url in self.webhook_urls:
            tail = _url_tail(url)
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                data = resp.json()
            except Exception as e:
                log.error(
                    "lark webhook send failed: url_tail=%s err=%s payload_keys=%s",
                    tail, e, list(payload),
                )
                failures.append(f"hook[..{tail}]={e}")
                continue

            ok = (data.get("StatusCode") == 0) or (data.get("code") == 0)
            if not ok:
                log.error(
                    "lark webhook server error: url_tail=%s code=%s msg=%s",
                    tail, data.get("code"), data.get("msg"),
                )
                failures.append(f"hook[..{tail}]=code={data.get('code')}")

        n = len(self.webhook_urls)
        if not failures:
            return NotifyResult(ok=True, message="ok")
        if len(failures) == n:
            return NotifyResult(
                ok=False,
                message=f"all {n} targets failed: {'; '.join(failures)}",
            )
        return NotifyResult(
            ok=False,
            message=f"{len(failures)}/{n} targets failed: {'; '.join(failures)}",
        )

    def send_text(self, text: str) -> NotifyResult:
        return self._post({"msg_type": "text", "content": {"text": text}})

    def send_messages(self, messages: Sequence[str], batch_threshold: int = 5) -> NotifyResult:
        """把一帧的多条新消息合并成单条飞书消息（再扇出到所有 URL）。"""
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
