"""ImagePipeline 单测：detector + notifier 全部用 stub，验证编排行为。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from app.core.image_pipeline import ImagePipeline, ImageFrameResult
from app.notifier.lark_image import NotifyResult
from app.storage.history import HistoryStore


def _img(size=(20, 20), color=(255, 255, 255)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_no_diff_returns_empty_result_no_calls(tmp_path: Path):
    detector = MagicMock()
    detector.detect.return_value = None
    notifier = MagicMock()
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = ImagePipeline(detector=detector, notifier=notifier, history=history, frames_dir=tmp_path / "frames")

    result = pipe.process_image(_img())

    assert isinstance(result, ImageFrameResult)
    assert result.new_messages == []
    assert result.diff_bbox is None
    notifier.send_image.assert_not_called()
    assert list((tmp_path / "frames").glob("*.png")) == []
    assert not (tmp_path / "h.ndjson").exists() or (tmp_path / "h.ndjson").read_text() == ""


def test_diff_triggers_save_notify_history(tmp_path: Path):
    crop = _img((10, 10), (0, 0, 0))
    detector = MagicMock()
    detector.detect.return_value = ((5, 5, 15, 15), crop)
    notifier = MagicMock()
    notifier.send_image.return_value = NotifyResult(ok=True, message="ok")
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = ImagePipeline(detector=detector, notifier=notifier, history=history, frames_dir=tmp_path / "frames")

    result = pipe.process_image(_img())

    assert result.diff_bbox == (5, 5, 15, 15)
    assert result.image_path is not None
    assert Path(result.image_path).exists()
    assert Path(result.image_path).parent == tmp_path / "frames"
    notifier.send_image.assert_called_once_with(crop)
    assert result.notify_result is not None and result.notify_result.ok
    # history 写了一条带 bbox 的记录
    h = history.tail(10)
    assert len(h) == 1
    assert "(5, 5, 15, 15)" in h[0]["text"] or "5, 5, 15, 15" in h[0]["text"]


def test_diff_notify_failure_still_writes_history_and_image(tmp_path: Path):
    crop = _img((10, 10), (0, 0, 0))
    detector = MagicMock()
    detector.detect.return_value = ((0, 0, 10, 10), crop)
    notifier = MagicMock()
    notifier.send_image.return_value = NotifyResult(ok=False, message="network err")
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = ImagePipeline(detector=detector, notifier=notifier, history=history, frames_dir=tmp_path / "frames")

    result = pipe.process_image(_img())

    assert result.notify_result is not None and result.notify_result.ok is False
    # 即使发送失败也存图、写历史，便于排查
    assert Path(result.image_path).exists()
    assert len(history.tail(10)) == 1
