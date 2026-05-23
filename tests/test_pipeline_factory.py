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
    cfg = AppConfig(mode="image_diff", notifier=NotifierCfg())
    history = HistoryStore(tmp_path / "h.ndjson")
    try:
        build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    except ValueError as e:
        msg = str(e).lower()
        assert "lark_app_id" in msg or "credential" in msg or "target" in msg
        return
    raise AssertionError("expected ValueError for missing credentials")


from app.notifier.lark_webhook import LarkWebhookNotifier
from app.notifier.lark_image import LarkImageNotifier
from app.storage.config import LarkTargetCfg


def test_ocr_mode_injects_all_effective_webhook_urls(tmp_path: Path):
    cfg = AppConfig(
        mode="ocr",
        notifier=NotifierCfg(
            lark_webhook_urls=["https://a", "https://b", "https://c"],
        ),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert isinstance(pipe.notifier, LarkWebhookNotifier)
    assert pipe.notifier.webhook_urls == ["https://a", "https://b", "https://c"]


def test_ocr_mode_falls_back_to_single_webhook_url(tmp_path: Path):
    """list 为空、单字段非空：注入 1 元素 list。"""
    cfg = AppConfig(
        mode="ocr",
        notifier=NotifierCfg(lark_webhook_url="https://legacy"),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert pipe.notifier.webhook_urls == ["https://legacy"]


def test_image_diff_mode_injects_all_effective_targets(tmp_path: Path):
    _purge_paddle_modules()
    cfg = AppConfig(
        mode="image_diff",
        notifier=NotifierCfg(
            lark_app_id="cli_x",
            lark_app_secret="sec_x",
            lark_targets=[
                LarkTargetCfg(receive_id="oc_a", receive_id_type="chat_id"),
                LarkTargetCfg(receive_id="ou_b", receive_id_type="open_id"),
            ],
        ),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert isinstance(pipe.notifier, LarkImageNotifier)
    assert [(t.receive_id, t.receive_id_type) for t in pipe.notifier.targets] == [
        ("oc_a", "chat_id"),
        ("ou_b", "open_id"),
    ]


def test_image_diff_mode_falls_back_to_single_receive_id(tmp_path: Path):
    _purge_paddle_modules()
    cfg = AppConfig(
        mode="image_diff",
        notifier=NotifierCfg(
            lark_app_id="cli_x",
            lark_app_secret="sec_x",
            lark_receive_id="oc_legacy",
            lark_receive_id_type="chat_id",
        ),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert len(pipe.notifier.targets) == 1
    assert pipe.notifier.targets[0].receive_id == "oc_legacy"


def test_image_diff_mode_raises_when_no_effective_targets(tmp_path: Path):
    """有 app_id/app_secret 但 list 和单字段都空 → 报错。"""
    _purge_paddle_modules()
    cfg = AppConfig(
        mode="image_diff",
        notifier=NotifierCfg(lark_app_id="cli_x", lark_app_secret="sec_x"),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    try:
        build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    except ValueError as e:
        assert "target" in str(e).lower() or "receive_id" in str(e).lower()
        return
    raise AssertionError("expected ValueError for no effective targets")
