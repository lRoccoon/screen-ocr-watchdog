"""离线回放工具：把 fixture 喂给 pipeline，可对接真实飞书 webhook。

用法：
    .venv/bin/python -m tools.replay_runner \\
        --fixture tests/fixtures/replay_basic.json \\
        --webhook https://open.feishu.cn/open-apis/bot/v2/hook/xxx
不带 --webhook 时只打印到 stdout，不发飞书。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image

from app.core.pipeline import Pipeline
from app.notifier.lark_webhook import LarkWebhookNotifier
from app.ocr.engine import StubOcrEngine
from app.ocr.postprocess import OcrBlock
from app.storage.config import AppConfig
from app.storage.history import HistoryStore


def _card_to_blocks(card: dict[str, Any], line_height: int = 16, line_gap: int = 4) -> list[OcrBlock]:
    blocks: list[OcrBlock] = []
    y = card["y_top"]
    for txt in (card["user"], card["time"], card["text"]):
        bbox = [[0, y], [200, y], [200, y + line_height], [0, y + line_height]]
        blocks.append((bbox, txt, 0.99))
        y += line_height + line_gap
    return blocks


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", required=True)
    p.add_argument("--webhook", default="")
    p.add_argument("--history", default="./replay_history.ndjson")
    args = p.parse_args()

    data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    ocr_frames: list[list[OcrBlock]] = []
    for frame in data["frames"]:
        blocks: list[OcrBlock] = []
        for card in frame["cards"]:
            blocks.extend(_card_to_blocks(card))
        ocr_frames.append(blocks)

    cfg = AppConfig()
    cfg.ocr.card_gap = data.get("card_gap", 12)
    cfg.notifier.lark_webhook_url = args.webhook

    pipeline = Pipeline(
        ocr=StubOcrEngine(ocr_frames),
        notifier=LarkWebhookNotifier(args.webhook),
        history=HistoryStore(Path(args.history)),
        config=cfg,
    )
    dummy = Image.new("RGB", (10, 10))

    for i in range(len(ocr_frames)):
        result = pipeline.process_image(dummy)
        if result.new_messages:
            ok = result.notify_result.ok if result.notify_result else None
            print(f"[frame {i}] new={len(result.new_messages)} notify_ok={ok}")
            for m in result.new_messages:
                print(f"   · {m.text!r}")
        else:
            print(f"[frame {i}] no change")


if __name__ == "__main__":
    main()
