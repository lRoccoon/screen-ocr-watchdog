"""设置窗口飞书 tab 的 webhook URL 文本框解析 / 渲染纯函数。

抽到独立模块是为了让 tests 不需要 import PySide6（headless 环境也能跑）。
"""
from __future__ import annotations


def parse_webhook_urls_from_textarea(text: str) -> list[str]:
    """按行 split → strip → 丢空 → 保序去重。"""
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        u = line.strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def format_webhook_urls_for_textarea(
    webhook_urls: list[str],
    webhook_url_legacy: str,
) -> str:
    """渲染到多行文本框时，把旧单字段 URL（若不在 list 里）合并进去。"""
    merged = list(webhook_urls)
    if webhook_url_legacy and webhook_url_legacy not in merged:
        merged.append(webhook_url_legacy)
    return "\n".join(merged)
