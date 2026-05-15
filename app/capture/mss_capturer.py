"""跨平台区域截屏。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image


class Capturer(ABC):
    @abstractmethod
    def capture(self) -> Image.Image: ...


class MssCapturer(Capturer):
    """基于 mss 的跨平台截屏。mss 实例不可跨线程共享，因此在第一次 capture() 时按当前线程懒创建。"""

    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self.region = {"left": x, "top": y, "width": width, "height": height}
        self._sct = None

    def capture(self) -> Image.Image:
        import mss
        if self._sct is None:
            self._sct = mss.mss()
        raw = self._sct.grab(self.region)
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
