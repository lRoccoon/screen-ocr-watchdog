"""配置加载与保存：YAML + Pydantic schema。"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Region(BaseModel):
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


class OcrCfg(BaseModel):
    lang: str = "ch"
    card_gap: int = 12


class DiffCfg(BaseModel):
    fuzzy_threshold: int = 2
    lru_frames: int = 20
    batch_threshold: int = 5


class NotifierCfg(BaseModel):
    lark_webhook_url: str = ""
    attach_screenshot: bool = False


class AppConfig(BaseModel):
    region: Region = Field(default_factory=Region)
    interval_seconds: int = 5
    ocr: OcrCfg = Field(default_factory=OcrCfg)
    diff: DiffCfg = Field(default_factory=DiffCfg)
    notifier: NotifierCfg = Field(default_factory=NotifierCfg)


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        return AppConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)


def save_config(cfg: AppConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(cfg.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
