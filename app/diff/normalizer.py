"""文本归一化与指纹计算：用于变化检测前的等价比较。"""
from __future__ import annotations

import hashlib
import re
import unicodedata

# 去除空白、ASCII 与常见中文标点
_PUNCT_RE = re.compile(
    r"[\s　 `~!@#$%^&*()\-_=+\[\]{};:'\",.<>/?\\|"
    r"，。！？；：、（）【】《》「」“”‘’·…—～]+"
)


def normalize(text: str) -> str:
    """归一化文本：全角→半角 + 去空白 + 去标点。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return _PUNCT_RE.sub("", text)


def fingerprint(text: str, prefix_chars: int = 60) -> str:
    """归一化后取前 N 字的 SHA1，用作 LRU 去重 key。"""
    norm = normalize(text)
    return hashlib.sha1(norm[:prefix_chars].encode("utf-8")).hexdigest()
