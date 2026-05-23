"""飞书自建应用图片消息发送：tenant_access_token 缓存 + 上传图 + 发 image 消息。

只用于 mode=image_diff。与 LarkWebhookNotifier 平级、不共享代码。
"""
from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import dataclass
from threading import Lock

import requests
from PIL import Image

log = logging.getLogger(__name__)

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
UPLOAD_URL = "https://open.feishu.cn/open-apis/im/v1/images"
MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
TOKEN_REFRESH_BUFFER_SECONDS = 300  # 剩余 < 5min 视为过期


@dataclass
class NotifyResult:
    ok: bool
    message: str = ""


class LarkImageNotifier:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        receive_id: str,
        receive_id_type: str = "chat_id",
        timeout: float = 10.0,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type
        self.timeout = timeout
        self._token: str = ""
        self._token_expires_at: float = float("-inf")
        self._token_lock = Lock()

    def _credentials_ok(self) -> bool:
        return bool(self.app_id and self.app_secret and self.receive_id)

    def _get_token(self) -> str:
        with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
                return self._token
            resp = requests.post(
                TOKEN_URL,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=self.timeout,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(
                    f"token fetch failed code={data.get('code')} msg={data.get('msg')}"
                )
            self._token = data["tenant_access_token"]
            self._token_expires_at = time.monotonic() + int(data.get("expire", 7200))
            return self._token

    def _upload_image(self, token: str, image: Image.Image) -> str:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        resp = requests.post(
            UPLOAD_URL,
            headers={"Authorization": f"Bearer {token}"},
            data={"image_type": "message"},
            files={"image": ("diff.png", buf, "image/png")},
            timeout=self.timeout,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"upload image failed code={data.get('code')} msg={data.get('msg')}"
            )
        return data["data"]["image_key"]

    def _send_message(self, token: str, image_key: str) -> None:
        resp = requests.post(
            f"{MESSAGE_URL}?receive_id_type={self.receive_id_type}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "receive_id": self.receive_id,
                "msg_type": "image",
                "content": json.dumps({"image_key": image_key}),
            },
            timeout=self.timeout,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"send message failed code={data.get('code')} msg={data.get('msg')}"
            )

    def send_image(self, image: Image.Image) -> NotifyResult:
        if not self._credentials_ok():
            log.error("lark image send skipped: missing app_id/app_secret/receive_id")
            return NotifyResult(ok=False, message="missing credentials (app_id/app_secret/receive_id)")
        try:
            token = self._get_token()
            image_key = self._upload_image(token, image)
            self._send_message(token, image_key)
            return NotifyResult(ok=True, message="ok")
        except Exception as e:
            log.error(
                "lark image notify failed: %s | receive_id=%s receive_id_type=%s",
                e, self.receive_id, self.receive_id_type,
            )
            return NotifyResult(ok=False, message=str(e))
