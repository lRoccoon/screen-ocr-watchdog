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


def user_data_dir_path() -> Path:
    """user data dir 根（history.ndjson 所在目录），用于派生其他数据子目录如 diff_frames。"""
    return Path(user_data_dir(APP_NAME, APP_AUTHOR))
