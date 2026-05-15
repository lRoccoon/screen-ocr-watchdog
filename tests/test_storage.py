from pathlib import Path

from app.storage.config import AppConfig, Region, load_config, save_config
from app.storage.history import HistoryStore


def test_config_missing_returns_defaults(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert isinstance(cfg, AppConfig)
    assert cfg.interval_seconds == 5
    assert cfg.diff.lru_frames == 20


def test_config_save_then_reload_roundtrips(tmp_path: Path):
    cfg = AppConfig(
        region=Region(x=10, y=20, width=300, height=400),
        interval_seconds=8,
    )
    p = tmp_path / "c.yaml"
    save_config(cfg, p)
    reloaded = load_config(p)
    assert reloaded.region.x == 10
    assert reloaded.region.width == 300
    assert reloaded.interval_seconds == 8


def test_history_append_and_tail(tmp_path: Path):
    h = HistoryStore(tmp_path / "h.ndjson")
    h.append("fp1", "hello")
    h.append("fp2", "world")
    recs = h.tail(10)
    assert [r["text"] for r in recs] == ["hello", "world"]
    assert [r["fingerprint"] for r in recs] == ["fp1", "fp2"]


def test_history_tail_limits(tmp_path: Path):
    h = HistoryStore(tmp_path / "h.ndjson")
    for i in range(5):
        h.append(f"fp{i}", f"m{i}")
    recs = h.tail(2)
    assert [r["text"] for r in recs] == ["m3", "m4"]


def test_history_empty_when_no_file(tmp_path: Path):
    h = HistoryStore(tmp_path / "h.ndjson")
    assert h.tail(10) == []
