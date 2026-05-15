"""主处理管线：image → OCR → 卡片聚合 → diff → 飞书 → 历史。"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image

from app.diff.detector import DiffDetector, Message
from app.notifier.lark_webhook import LarkWebhookNotifier, NotifyResult
from app.ocr.engine import OcrEngine
from app.ocr.postprocess import aggregate_cards
from app.storage.config import AppConfig
from app.storage.history import HistoryStore

log = logging.getLogger(__name__)


@dataclass
class FrameResult:
    new_messages: list[Message]
    notify_result: NotifyResult | None


class Pipeline:
    def __init__(
        self,
        ocr: OcrEngine,
        notifier: LarkWebhookNotifier,
        history: HistoryStore,
        config: AppConfig,
    ) -> None:
        self.ocr = ocr
        self.notifier = notifier
        self.history = history
        self.config = config
        self.detector = DiffDetector(
            lru_frames=config.diff.lru_frames,
            fuzzy_threshold=config.diff.fuzzy_threshold,
        )

    def process_image(self, image: Image.Image) -> FrameResult:
        blocks = self.ocr.recognize(image)
        cards = aggregate_cards(blocks, card_gap=self.config.ocr.card_gap)
        messages = [Message(text=c.text, y_top=c.y_top, y_bottom=c.y_bottom) for c in cards]
        new_msgs = self.detector.detect(messages)
        if not new_msgs:
            return FrameResult(new_messages=[], notify_result=None)

        texts = [m.text for m in new_msgs]
        result = self.notifier.send_messages(
            texts, batch_threshold=self.config.diff.batch_threshold
        )
        if not result.ok:
            log.error(
                "lark notify failed: msg=%s new_count=%d",
                result.message,
                len(new_msgs),
            )
        # 即使发送失败也写历史，便于排查
        for m in new_msgs:
            self.history.append(fingerprint=m.fp, text=m.text)

        return FrameResult(new_messages=new_msgs, notify_result=result)
