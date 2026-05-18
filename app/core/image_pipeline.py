"""image_diff 模式 pipeline：capture → detector → 写图 + history + notifier。

与 app.core.pipeline.Pipeline 鸭子类型对齐：都暴露 process_image(image)。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

from app.diff.image_detector import ImageDiffDetector
from app.notifier.lark_image import LarkImageNotifier, NotifyResult
from app.storage.history import HistoryStore

log = logging.getLogger(__name__)


@dataclass
class ImageFrameResult:
    # 字段名与 app.core.pipeline.FrameResult 的 new_messages 对齐，
    # 让 AppController._on_frame_done 的 `if fr.new_messages` 检查自然走 false 分支。
    new_messages: list = field(default_factory=list)
    diff_bbox: Optional[Tuple[int, int, int, int]] = None
    image_path: Optional[str] = None
    notify_result: Optional[NotifyResult] = None


class ImagePipeline:
    def __init__(
        self,
        detector: ImageDiffDetector,
        notifier: LarkImageNotifier,
        history: HistoryStore,
        frames_dir: Path,
    ) -> None:
        self.detector = detector
        self.notifier = notifier
        self.history = history
        self.frames_dir = frames_dir
        self.frames_dir.mkdir(parents=True, exist_ok=True)

    def process_image(self, image: Image.Image) -> ImageFrameResult:
        out = self.detector.detect(image)
        if out is None:
            return ImageFrameResult()
        bbox, crop = out

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        image_path = self.frames_dir / f"{ts}.png"
        crop.save(image_path)

        notify_result = self.notifier.send_image(crop)
        if not notify_result.ok:
            log.error(
                "image diff notify failed: msg=%s bbox=%s image=%s",
                notify_result.message, bbox, image_path,
            )

        # 即使发送失败也写历史，便于排查
        self.history.append(fingerprint=f"img_{ts}", text=f"image_diff bbox={bbox}")

        return ImageFrameResult(
            diff_bbox=bbox,
            image_path=str(image_path),
            notify_result=notify_result,
        )
