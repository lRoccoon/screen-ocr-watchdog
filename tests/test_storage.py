from pathlib import Path

from app.storage.config import (
    AppConfig,
    LarkTargetCfg,
    NotifierCfg,
    Region,
    load_config,
    save_config,
)
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


def test_config_default_mode_is_ocr():
    """旧 config 文件不带 mode 字段时，默认走 ocr 模式（向后兼容）。"""
    cfg = AppConfig()
    assert cfg.mode == "ocr"


def test_config_missing_file_has_image_diff_and_notifier_defaults(tmp_path: Path):
    """缺失配置文件时，image_diff 与 notifier 的默认值通过 load_config 路径验证。"""
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg.image_diff.pixel_diff_threshold == 30
    assert cfg.image_diff.change_ratio_threshold == 0.005
    assert cfg.image_diff.min_interval_seconds == 5
    assert cfg.image_diff.bbox_padding == 8
    assert cfg.notifier.lark_app_id == ""
    assert cfg.notifier.lark_receive_id_type == "chat_id"


def test_config_load_image_diff_yaml(tmp_path):
    """加载手写的 image_diff 配置 YAML。"""
    p = tmp_path / "c.yaml"
    p.write_text(
        "mode: image_diff\n"
        "image_diff:\n"
        "  pixel_diff_threshold: 50\n"
        "  change_ratio_threshold: 0.01\n"
        "notifier:\n"
        "  lark_app_id: cli_xxx\n"
        "  lark_app_secret: sec_xxx\n"
        "  lark_receive_id: oc_abc\n"
        "  lark_receive_id_type: chat_id\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.mode == "image_diff"
    assert cfg.image_diff.pixel_diff_threshold == 50
    assert cfg.image_diff.change_ratio_threshold == 0.01
    # 没写的字段保留默认
    assert cfg.image_diff.min_interval_seconds == 5
    assert cfg.notifier.lark_app_id == "cli_xxx"
    assert cfg.notifier.lark_app_secret == "sec_xxx"
    assert cfg.notifier.lark_receive_id_type == "chat_id"


# ---------- effective_webhook_urls ----------

def test_effective_webhook_urls_list_takes_priority():
    """list 非空时优先用 list，忽略单字段。"""
    nc = NotifierCfg(
        lark_webhook_urls=["https://a", "https://b"],
        lark_webhook_url="https://legacy",
    )
    assert nc.effective_webhook_urls() == ["https://a", "https://b"]


def test_effective_webhook_urls_fallback_to_single_field():
    """list 为空时回退到单字段，包装成单元素 list。"""
    nc = NotifierCfg(lark_webhook_url="https://legacy")
    assert nc.effective_webhook_urls() == ["https://legacy"]


def test_effective_webhook_urls_both_empty_returns_empty_list():
    nc = NotifierCfg()
    assert nc.effective_webhook_urls() == []


def test_effective_webhook_urls_drops_blank_entries_in_list():
    """list 里的空字符串视为无效，过滤掉。"""
    nc = NotifierCfg(lark_webhook_urls=["https://a", "", "https://b"])
    assert nc.effective_webhook_urls() == ["https://a", "https://b"]


# ---------- effective_targets ----------

def test_effective_targets_list_takes_priority():
    nc = NotifierCfg(
        lark_targets=[
            LarkTargetCfg(receive_id="oc_a", receive_id_type="chat_id"),
            LarkTargetCfg(receive_id="ou_b", receive_id_type="open_id"),
        ],
        lark_receive_id="legacy",
    )
    ts = nc.effective_targets()
    assert [t.receive_id for t in ts] == ["oc_a", "ou_b"]
    assert [t.receive_id_type for t in ts] == ["chat_id", "open_id"]


def test_effective_targets_fallback_to_single_field():
    nc = NotifierCfg(lark_receive_id="oc_legacy", lark_receive_id_type="chat_id")
    ts = nc.effective_targets()
    assert len(ts) == 1
    assert ts[0].receive_id == "oc_legacy"
    assert ts[0].receive_id_type == "chat_id"


def test_effective_targets_both_empty_returns_empty_list():
    nc = NotifierCfg()
    assert nc.effective_targets() == []


def test_effective_targets_drops_blank_receive_ids_in_list():
    nc = NotifierCfg(
        lark_targets=[
            LarkTargetCfg(receive_id="oc_a"),
            LarkTargetCfg(receive_id=""),
        ],
    )
    ts = nc.effective_targets()
    assert [t.receive_id for t in ts] == ["oc_a"]


# ---------- yaml 兼容 ----------

def test_load_v010_yaml_with_single_webhook_works(tmp_path):
    """v0.1.0 旧 yaml（只有 lark_webhook_url）加载后能拿到生效 list。"""
    p = tmp_path / "c.yaml"
    p.write_text(
        "notifier:\n  lark_webhook_url: https://legacy\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.notifier.lark_webhook_urls == []
    assert cfg.notifier.lark_webhook_url == "https://legacy"
    assert cfg.notifier.effective_webhook_urls() == ["https://legacy"]


def test_load_v010_yaml_with_single_receive_id_works(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "mode: image_diff\n"
        "notifier:\n"
        "  lark_app_id: cli_x\n"
        "  lark_app_secret: sec_x\n"
        "  lark_receive_id: oc_legacy\n"
        "  lark_receive_id_type: chat_id\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.notifier.lark_targets == []
    ts = cfg.notifier.effective_targets()
    assert len(ts) == 1
    assert ts[0].receive_id == "oc_legacy"


def test_load_new_yaml_with_list_fields(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "notifier:\n"
        "  lark_webhook_urls:\n"
        "    - https://a\n"
        "    - https://b\n"
        "  lark_targets:\n"
        "    - {receive_id: oc_a, receive_id_type: chat_id}\n"
        "    - {receive_id: ou_b, receive_id_type: open_id}\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.notifier.effective_webhook_urls() == ["https://a", "https://b"]
    ts = cfg.notifier.effective_targets()
    assert [(t.receive_id, t.receive_id_type) for t in ts] == [
        ("oc_a", "chat_id"),
        ("ou_b", "open_id"),
    ]
