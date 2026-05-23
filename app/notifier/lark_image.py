"""飞书自建应用图片消息发送：tenant_access_token 缓存 + 上传图 + 多目标扇出。

只用于 mode=image_diff。与 LarkWebhookNotifier 平级、不共享代码。
"""
from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import dataclass
from threading import Lock
from typing import Sequence

import requests
from PIL import Image

from app.storage.config import LarkTargetCfg

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
        targets: Sequence[LarkTargetCfg],
        timeout: float = 10.0,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        # 过滤 receive_id 为空的非法 target
        self.targets: list[LarkTargetCfg] = [t for t in targets if t.receive_id]
        self.timeout = timeout
        self._token: str = ""
        self._token_expires_at: float = float("-inf")
        self._token_lock = Lock()

    def _credentials_ok(self) -> bool:
        return bool(self.app_id and self.app_secret and self.targets)

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

    def _send_message(self, token: str, image_key: str, target: LarkTargetCfg) -> None:
        resp = requests.post(
            f"{MESSAGE_URL}?receive_id_type={target.receive_id_type}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "receive_id": target.receive_id,
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
            log.error(
                "lark image send skipped: app_id_set=%s secret_set=%s targets=%d",
                bool(self.app_id), bool(self.app_secret), len(self.targets),
            )
            return NotifyResult(
                ok=False,
                message="missing credentials or no targets configured",
            )

        # 1) token + 2) upload，任一失败则整体失败
        try:
            token = self._get_token()
            image_key = self._upload_image(token, image)
        except Exception as e:
            log.error("lark image prep failed: %s", e)
            return NotifyResult(ok=False, message=str(e))

        # 3) 扇出 send_message，每个 target 独立 try/except
        failures: list[str] = []
        for t in self.targets:
            try:
                self._send_message(token, image_key, t)
            except Exception as e:
                log.error(
                    "lark image send_message failed: receive_id=%s type=%s err=%s",
                    t.receive_id, t.receive_id_type, e,
                )
                failures.append(f"{t.receive_id}={e}")

        n = len(self.targets)
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
