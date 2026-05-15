"""跨平台数据/配置/日志目录解析。"""
from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_dir, user_data_dir, user_log_dir

APP_NAME = "screen-ocr-watchdog"
APP_AUTHOR = "screen-ocr-watchdog"


def config_path() -> Path:
    return Path(user_config_dir(APP_NAME, APP_AUTHOR)) / "config.yaml"


def history_path() -> Path:
    return Path(user_data_dir(APP_NAME, APP_AUTHOR)) / "history.ndjson"


def log_dir() -> Path:
    return Path(user_log_dir(APP_NAME, APP_AUTHOR))
