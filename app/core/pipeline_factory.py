"""按 config.mode 构造对应 pipeline。

抽离这层是为了：
1. 单测可以在没有 Qt 的情况下验证 mode 分发与 import 隔离。
2. image_diff 模式下不通过任何路径 import 到 paddleocr。
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from app.core.image_pipeline import ImagePipeline
from app.core.pipeline import Pipeline
from app.diff.image_detector import ImageDiffDetector
from app.notifier.lark_image import LarkImageNotifier
from app.notifier.lark_webhook import LarkWebhookNotifier
from app.ocr.engine import PaddleOcrEngine
from app.storage.config import AppConfig
from app.storage.history import HistoryStore

PipelineLike = Union[Pipeline, ImagePipeline]


def build_pipeline(
    config: AppConfig,
    history: HistoryStore,
    frames_dir: Path,
) -> PipelineLike:
    if config.mode == "image_diff":
        nc = config.notifier
        if not (nc.lark_app_id and nc.lark_app_secret and nc.lark_receive_id):
            raise ValueError(
                "image_diff mode requires notifier.lark_app_id / lark_app_secret / lark_receive_id"
            )
        ic = config.image_diff
        detector = ImageDiffDetector(
            pixel_diff_threshold=ic.pixel_diff_threshold,
            change_ratio_threshold=ic.change_ratio_threshold,
            min_interval_seconds=ic.min_interval_seconds,
            bbox_padding=ic.bbox_padding,
        )
        notifier = LarkImageNotifier(
            app_id=nc.lark_app_id,
            app_secret=nc.lark_app_secret,
            receive_id=nc.lark_receive_id,
            receive_id_type=nc.lark_receive_id_type,
        )
        return ImagePipeline(
            detector=detector,
            notifier=notifier,
            history=history,
            frames_dir=frames_dir,
        )

    # ocr mode
    ocr = PaddleOcrEngine(lang=config.ocr.lang)
    notifier = LarkWebhookNotifier(config.notifier.lark_webhook_url)
    return Pipeline(ocr=ocr, notifier=notifier, history=history, config=config)
