"""配置加载与保存：YAML + Pydantic schema。"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

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


class ImageDiffCfg(BaseModel):
    pixel_diff_threshold: int = 30
    change_ratio_threshold: float = 0.005
    min_interval_seconds: float = 5.0
    bbox_padding: int = 8


class LarkTargetCfg(BaseModel):
    receive_id: str = ""
    receive_id_type: Literal["chat_id", "open_id", "user_id", "union_id", "email"] = "chat_id"


class NotifierCfg(BaseModel):
    # 新（list 为主）
    lark_webhook_urls: list[str] = Field(default_factory=list)
    lark_targets: list[LarkTargetCfg] = Field(default_factory=list)

    # 旧（list 为空时 fallback，向后兼容 v0.1.0）
    lark_webhook_url: str = ""
    lark_receive_id: str = ""
    lark_receive_id_type: Literal["chat_id", "open_id", "user_id", "union_id", "email"] = "chat_id"

    # 不变
    lark_app_id: str = ""
    lark_app_secret: str = ""
    attach_screenshot: bool = False

    def effective_webhook_urls(self) -> list[str]:
        if self.lark_webhook_urls:
            return [u for u in self.lark_webhook_urls if u]
        if self.lark_webhook_url:
            return [self.lark_webhook_url]
        return []

    def effective_targets(self) -> list[LarkTargetCfg]:
        if self.lark_targets:
            return [t for t in self.lark_targets if t.receive_id]
        if self.lark_receive_id:
            return [
                LarkTargetCfg(
                    receive_id=self.lark_receive_id,
                    receive_id_type=self.lark_receive_id_type,
                )
            ]
        return []


class AppConfig(BaseModel):
    mode: Literal["ocr", "image_diff"] = "ocr"
    region: Region = Field(default_factory=Region)
    interval_seconds: int = 5
    ocr: OcrCfg = Field(default_factory=OcrCfg)
    diff: DiffCfg = Field(default_factory=DiffCfg)
    image_diff: ImageDiffCfg = Field(default_factory=ImageDiffCfg)
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
