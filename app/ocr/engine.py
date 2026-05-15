"""OCR 引擎接口与实现。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image

from .postprocess import OcrBlock


class OcrEngine(ABC):
    """OCR 引擎接口：输入 PIL Image，输出 [(bbox, text, conf), ...]。"""

    @abstractmethod
    def recognize(self, image: Image.Image) -> list[OcrBlock]: ...


class PaddleOcrEngine(OcrEngine):
    """PaddleOCR 中文模型封装；首次调用时延迟加载模型，避免 import 即拉模型。"""

    def __init__(self, lang: str = "ch") -> None:
        self.lang = lang
        self._ocr = None

    def _ensure_loaded(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR  # 延迟 import，避免无 paddle 环境也能导入本文件
            self._ocr = PaddleOCR(use_angle_cls=False, lang=self.lang, show_log=False)
        return self._ocr

    def recognize(self, image: Image.Image) -> list[OcrBlock]:
        import numpy as np
        ocr = self._ensure_loaded()
        arr = np.array(image.convert("RGB"))
        result = ocr.ocr(arr, cls=False)
        if not result or result[0] is None:
            return []
        return [(bbox, text, float(conf)) for bbox, (text, conf) in result[0]]


class StubOcrEngine(OcrEngine):
    """测试用：按调用顺序返回预定的 frames，超出则返回空。"""

    def __init__(self, frames: list[list[OcrBlock]]) -> None:
        self._frames = list(frames)
        self._idx = 0

    def recognize(self, image: Image.Image) -> list[OcrBlock]:
        if self._idx >= len(self._frames):
            return []
        frame = self._frames[self._idx]
        self._idx += 1
        return frame

    @property
    def remaining(self) -> int:
        return max(0, len(self._frames) - self._idx)
