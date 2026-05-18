"""pipeline_factory 单测：mode 分发 + 确认 image_diff 不 import paddleocr。"""
from __future__ import annotations

import sys
from pathlib import Path

from app.core.image_pipeline import ImagePipeline
from app.core.pipeline import Pipeline
from app.core.pipeline_factory import build_pipeline
from app.storage.config import AppConfig, ImageDiffCfg, NotifierCfg
from app.storage.history import HistoryStore


def _purge_paddle_modules() -> None:
    for k in [m for m in list(sys.modules) if m.startswith("paddle")]:
        del sys.modules[k]


def test_image_diff_mode_builds_image_pipeline(tmp_path: Path):
    _purge_paddle_modules()
    cfg = AppConfig(
        mode="image_diff",
        image_diff=ImageDiffCfg(),
        notifier=NotifierCfg(
            lark_app_id="cli_x",
            lark_app_secret="sec_x",
            lark_receive_id="oc_x",
        ),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert isinstance(pipe, ImagePipeline)


def test_image_diff_mode_does_not_import_paddleocr(tmp_path: Path):
    _purge_paddle_modules()
    cfg = AppConfig(
        mode="image_diff",
        notifier=NotifierCfg(lark_app_id="x", lark_app_secret="y", lark_receive_id="z"),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    paddle_mods = [m for m in sys.modules if m.startswith("paddle")]
    assert paddle_mods == [], f"image_diff mode should not import paddle*, got {paddle_mods}"


def test_ocr_mode_builds_pipeline(tmp_path: Path):
    cfg = AppConfig(
        mode="ocr",
        notifier=NotifierCfg(lark_webhook_url="https://example.invalid/x"),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert isinstance(pipe, Pipeline)


def test_image_diff_mode_raises_on_missing_credentials(tmp_path: Path):
    cfg = AppConfig(mode="image_diff", notifier=NotifierCfg())  # 三个字段全空
    history = HistoryStore(tmp_path / "h.ndjson")
    try:
        build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    except ValueError as e:
        assert "lark_app_id" in str(e) or "credential" in str(e).lower()
        return
    raise AssertionError("expected ValueError for missing credentials")
