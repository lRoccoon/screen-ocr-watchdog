"""把 PaddleOCR 输出的零散文本块聚合为消息卡片。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# PaddleOCR 单个文本块：bbox 是 4 个角点 [[x,y], ...]
OcrBlock = tuple[list[list[float]], str, float]


_NOISE_PATTERNS = [
    re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$"),       # 时间戳 14:30 / 14:30:00
    re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$"),         # 日期 2025-05-16
    re.compile(r"^[\W_]+$"),                        # 纯标点/分隔符
]


def _is_noise(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    return any(p.match(t) for p in _NOISE_PATTERNS)


@dataclass(frozen=True)
class Card:
    text: str
    y_top: int
    y_bottom: int


def _bbox_y_range(bbox: list[list[float]]) -> tuple[int, int]:
    ys = [int(p[1]) for p in bbox]
    return min(ys), max(ys)


def aggregate_cards(blocks: Iterable[OcrBlock], card_gap: int = 12) -> list[Card]:
    """先按物理 y 间距分组，再在组内过滤噪声。

    用真实 OCR 块的位置判断分卡，避免被过滤的时间戳让"用户名→正文"间的物理距离虚增。
    """
    rows: list[tuple[int, int, str]] = []
    for bbox, text, _conf in blocks:
        y_top, y_bot = _bbox_y_range(bbox)
        rows.append((y_top, y_bot, text))
    if not rows:
        return []
    rows.sort(key=lambda r: r[0])

    # 1. 按物理 gap 分组
    groups: list[list[tuple[int, int, str]]] = [[rows[0]]]
    prev_bot = rows[0][1]
    for row in rows[1:]:
        y_top, y_bot, _ = row
        if y_top - prev_bot > card_gap:
            groups.append([row])
        else:
            groups[-1].append(row)
        prev_bot = max(prev_bot, y_bot)

    # 2. 每组内过滤噪声后生成卡片
    cards: list[Card] = []
    for group in groups:
        kept = [r for r in group if not _is_noise(r[2])]
        if not kept:
            continue
        y_top = min(r[0] for r in kept)
        y_bot = max(r[1] for r in kept)
        text = "\n".join(r[2] for r in kept)
        cards.append(Card(text=text, y_top=y_top, y_bottom=y_bot))
    return cards
