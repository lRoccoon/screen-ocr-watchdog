"""回放测试：把预定义 OCR 输出序列依次喂给 Pipeline，断言每帧的新增消息。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.core.pipeline import Pipeline
from app.notifier.lark_webhook import LarkWebhookNotifier, NotifyResult
from app.ocr.engine import StubOcrEngine
from app.ocr.postprocess import OcrBlock
from app.storage.config import AppConfig, DiffCfg, OcrCfg
from app.storage.history import HistoryStore


FIXTURES = Path(__file__).parent / "fixtures"


def _card_to_blocks(card: dict[str, Any], line_height: int = 16, line_gap: int = 4) -> list[OcrBlock]:
    """把一个 card（user/time/text 三行）展开成 3 个 OcrBlock。"""
    blocks: list[OcrBlock] = []
    y = card["y_top"]
    for txt in (card["user"], card["time"], card["text"]):
        bbox = [[0, y], [200, y], [200, y + line_height], [0, y + line_height]]
        blocks.append((bbox, txt, 0.99))
        y += line_height + line_gap
    return blocks


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _RecordingNotifier(LarkWebhookNotifier):
    def __init__(self):
        super().__init__(webhook_url="https://example.invalid/dummy")
        self.sent_payloads: list[str] = []

    def _post(self, payload: dict) -> NotifyResult:
        self.sent_payloads.append(payload["content"]["text"])
        return NotifyResult(ok=True, message="recorded")


def _build_pipeline(stub: StubOcrEngine, history_path: Path, card_gap: int) -> tuple[Pipeline, _RecordingNotifier]:
    cfg = AppConfig(
        ocr=OcrCfg(card_gap=card_gap),
        diff=DiffCfg(fuzzy_threshold=2, lru_frames=20, batch_threshold=5),
    )
    notifier = _RecordingNotifier()
    history = HistoryStore(history_path)
    pipeline = Pipeline(ocr=stub, notifier=notifier, history=history, config=cfg)
    return pipeline, notifier


def test_replay_basic_scrolling(tmp_path: Path):
    fixture = _load_fixture("replay_basic.json")
    card_gap = fixture["card_gap"]
    frames = fixture["frames"]

    # 把每帧的所有 cards 展开成 OcrBlock 列表
    ocr_frames: list[list[OcrBlock]] = []
    for frame in frames:
        blocks: list[OcrBlock] = []
        for card in frame["cards"]:
            blocks.extend(_card_to_blocks(card))
        ocr_frames.append(blocks)

    stub = StubOcrEngine(ocr_frames)
    dummy_image = Image.new("RGB", (10, 10))
    pipeline, notifier = _build_pipeline(stub, tmp_path / "history.ndjson", card_gap)

    for i, frame in enumerate(frames):
        result = pipeline.process_image(dummy_image)
        expected = frame["expected_new_substrings"]
        actual_texts = [m.text for m in result.new_messages]

        assert len(actual_texts) == len(expected), (
            f"frame {i}: expected {len(expected)} new, got {len(actual_texts)}: {actual_texts}"
        )
        for sub in expected:
            assert any(sub in t for t in actual_texts), (
                f"frame {i}: substring {sub!r} not in actual {actual_texts}"
            )


def test_replay_batch_threshold(tmp_path: Path):
    """单帧 ≥5 条新消息时，飞书 payload 应带 '【批量' 前缀。"""
    bodies = [
        "今天的市场表现非常不错收益喜人",
        "请教老师怎么看待新能源板块走势",
        "我觉得医药股调整充分可以布局了",
        "美联储议息会议结果影响几何呢",
        "港股科技股最近反弹力度很大啊",
        "白酒板块还能继续持有等待估值修复",
    ]
    cards = [
        {"y_top": 100 + i * 100, "user": f"同学甲乙丙丁戊己{i}", "time": "14:30", "text": bodies[i]}
        for i in range(6)
    ]
    blocks: list[OcrBlock] = []
    for c in cards:
        blocks.extend(_card_to_blocks(c))

    stub = StubOcrEngine([blocks])
    dummy_image = Image.new("RGB", (10, 10))
    pipeline, notifier = _build_pipeline(stub, tmp_path / "h.ndjson", card_gap=12)

    result = pipeline.process_image(dummy_image)
    assert len(result.new_messages) == 6
    assert len(notifier.sent_payloads) == 1
    assert notifier.sent_payloads[0].startswith("【批量 6 条】")


def test_replay_no_change_no_notify(tmp_path: Path):
    """两帧内容完全一致，第二帧不应发送。"""
    cards = [{"y_top": 100, "user": "U", "time": "14:30", "text": "完全相同的一条消息内容"}]
    blocks = []
    for c in cards:
        blocks.extend(_card_to_blocks(c))

    stub = StubOcrEngine([blocks, blocks])
    dummy_image = Image.new("RGB", (10, 10))
    pipeline, notifier = _build_pipeline(stub, tmp_path / "h.ndjson", card_gap=12)

    r1 = pipeline.process_image(dummy_image)
    r2 = pipeline.process_image(dummy_image)
    assert len(r1.new_messages) == 1
    assert len(r2.new_messages) == 0
    assert len(notifier.sent_payloads) == 1


def test_history_persists_new_messages(tmp_path: Path):
    fixture = _load_fixture("replay_basic.json")
    card_gap = fixture["card_gap"]
    ocr_frames = []
    for frame in fixture["frames"]:
        blocks = []
        for c in frame["cards"]:
            blocks.extend(_card_to_blocks(c))
        ocr_frames.append(blocks)

    history_path = tmp_path / "h.ndjson"
    stub = StubOcrEngine(ocr_frames)
    dummy_image = Image.new("RGB", (10, 10))
    pipeline, _ = _build_pipeline(stub, history_path, card_gap)

    for _ in fixture["frames"]:
        pipeline.process_image(dummy_image)

    total_expected = sum(len(f["expected_new_substrings"]) for f in fixture["frames"])
    records = HistoryStore(history_path).tail(1000)
    assert len(records) == total_expected
