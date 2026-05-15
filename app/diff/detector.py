"""新增消息检测：LRU N 帧去重 + 编辑距离模糊匹配。"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable

from rapidfuzz.distance import Levenshtein

from .normalizer import fingerprint, normalize


@dataclass(frozen=True)
class Message:
    text: str
    y_top: int = 0
    y_bottom: int = 0

    @property
    def fp(self) -> str:
        return fingerprint(self.text)


class DiffDetector:
    """每次 detect() 返回当前帧相对最近 N 帧的新增消息。"""

    def __init__(self, lru_frames: int = 20, fuzzy_threshold: int = 2) -> None:
        if lru_frames < 1:
            raise ValueError("lru_frames must be >= 1")
        self.lru_frames = lru_frames
        self.fuzzy_threshold = fuzzy_threshold
        self._frames: OrderedDict[int, list[tuple[str, str]]] = OrderedDict()
        self._index: dict[str, str] = {}  # fp -> normalized_text
        self._next_frame_id = 0

    def _is_known(self, norm: str, fp: str) -> bool:
        if not norm:
            return True  # 空消息算已知，被过滤
        if fp in self._index:
            return True
        if self.fuzzy_threshold <= 0:
            return False
        # 短文本禁用模糊匹配：避免 "好的" vs "收到" 这种短消息被误判为同
        min_len = max(4, self.fuzzy_threshold * 2)
        if len(norm) < min_len:
            return False
        for known in self._index.values():
            if len(known) < min_len:
                continue
            if Levenshtein.distance(norm, known, score_cutoff=self.fuzzy_threshold) <= self.fuzzy_threshold:
                return True
        return False

    def detect(self, messages: Iterable[Message]) -> list[Message]:
        """返回相对 LRU 窗口的新增消息（按 y_top 升序）。"""
        new_msgs: list[Message] = []
        frame_entries: list[tuple[str, str]] = []

        for msg in messages:
            norm = normalize(msg.text)
            fp = msg.fp
            frame_entries.append((fp, norm))
            if not self._is_known(norm, fp):
                new_msgs.append(msg)
                # 同一帧内重复也只算一次
                self._index[fp] = norm

        # 当前帧入 LRU
        frame_id = self._next_frame_id
        self._next_frame_id += 1
        self._frames[frame_id] = frame_entries
        # 把当前帧的所有 fp 也补进 index（包含未被判为新但同样需要后续去重的）
        for fp, norm in frame_entries:
            if norm and fp not in self._index:
                self._index[fp] = norm

        # 淘汰最老帧
        while len(self._frames) > self.lru_frames:
            _, evicted = self._frames.popitem(last=False)
            for fp, _ in evicted:
                if not any(fp == e_fp for entries in self._frames.values() for e_fp, _ in entries):
                    self._index.pop(fp, None)

        new_msgs.sort(key=lambda m: m.y_top)
        return new_msgs
