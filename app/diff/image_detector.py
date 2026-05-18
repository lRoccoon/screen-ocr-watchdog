"""画面像素 diff 检测器：状态机持有"上次推送过的画面"作为基线。

每帧：grayscale → 与基线像素差二值化（阈值）→ histogram 统计变化占比。
超阈则 getbbox + padding + crop，并把基线推进为当前帧；不超阈或被节流则返回 None。
"""
from __future__ import annotations

import time
from typing import Optional, Tuple

from PIL import Image, ImageChops, ImageOps

Bbox = Tuple[int, int, int, int]


class ImageDiffDetector:
    def __init__(
        self,
        pixel_diff_threshold: int = 30,
        change_ratio_threshold: float = 0.005,
        min_interval_seconds: float = 5.0,
        bbox_padding: int = 8,
    ) -> None:
        self.pixel_diff_threshold = pixel_diff_threshold
        self.change_ratio_threshold = change_ratio_threshold
        self.min_interval_seconds = min_interval_seconds
        self.bbox_padding = bbox_padding
        self._baseline: Optional[Image.Image] = None
        self._last_pushed_ts: float = float("-inf")

    def detect(
        self,
        frame: Image.Image,
        now: Optional[float] = None,
    ) -> Optional[Tuple[Bbox, Image.Image]]:
        cur = now if now is not None else time.monotonic()

        if self._baseline is None:
            self._baseline = frame.copy()
            return None

        gray_base = ImageOps.grayscale(self._baseline)
        gray_cur = ImageOps.grayscale(frame)
        diff = ImageChops.difference(gray_base, gray_cur)
        thr = self.pixel_diff_threshold
        mask = diff.point(lambda p: 255 if p >= thr else 0)

        bbox = mask.getbbox()
        if bbox is None:
            return None

        hist = mask.histogram()
        changed = sum(hist[1:])  # bin 0 = 未变；其他全是 255
        total = mask.width * mask.height
        if total == 0 or (changed / total) < self.change_ratio_threshold:
            return None

        # 节流：距上次推送不足 min_interval，不推、不推进基线
        if cur - self._last_pushed_ts < self.min_interval_seconds:
            return None

        x0, y0, x1, y1 = bbox
        pad = self.bbox_padding
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(frame.width, x1 + pad)
        y1 = min(frame.height, y1 + pad)
        crop = frame.crop((x0, y0, x1, y1))

        self._baseline = frame.copy()
        self._last_pushed_ts = cur
        return (x0, y0, x1, y1), crop
