"""入口：加载配置 → 启动 Qt App → 装托盘 → 启动 watchdog worker。"""
from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from app.capture.mss_capturer import MssCapturer
from app.core.pipeline import FrameResult, Pipeline
from app.core.scheduler import WatchdogRunner
from app.notifier.lark_webhook import LarkWebhookNotifier
from app.ocr.engine import OcrEngine, PaddleOcrEngine
from app.ocr.postprocess import OcrBlock
from app.paths import config_path, history_path, log_dir
from app.storage.config import load_config, save_config
from app.storage.history import HistoryStore
from app.ui.history_view import HistoryView
from app.ui.region_picker import RegionPicker
from app.ui.settings_window import SettingsWindow
from app.ui.tray import TrayController

log = logging.getLogger("screen-ocr-watchdog")


def _build_ocr() -> OcrEngine:
    """允许通过环境变量切换为 noop OCR，便于无 paddle 环境的 UI 烟雾测试。"""
    if os.environ.get("SOW_FAKE_OCR") == "1":
        from PIL import Image

        class _NoopOcr(OcrEngine):
            def recognize(self, image: "Image.Image") -> list[OcrBlock]:  # type: ignore[override]
                return []

        log.info("using noop OCR engine (SOW_FAKE_OCR=1)")
        return _NoopOcr()
    return PaddleOcrEngine(lang="ch")


class WatchdogSignals(QObject):
    frame_done = Signal(object)
    error = Signal(str)


class AppController:
    def __init__(self) -> None:
        self.cfg_path = config_path()
        self.config = load_config(self.cfg_path)
        self.history = HistoryStore(history_path())
        self.ocr = _build_ocr()
        self.signals = WatchdogSignals()
        self.runner: WatchdogRunner | None = None
        self._paused = False

        self.tray = TrayController()
        self.tray.pause_toggled.connect(self.toggle_pause)
        self.tray.open_settings.connect(self.open_settings)
        self.tray.open_history.connect(self.open_history)
        self.tray.pick_region.connect(self.start_region_pick)
        self.tray.quit_requested.connect(self.quit)
        self.signals.frame_done.connect(self._on_frame_done)
        self.signals.error.connect(self._on_error)

        self._settings: SettingsWindow | None = None
        self._history_view: HistoryView | None = None
        self._region_picker: RegionPicker | None = None

    def start(self) -> None:
        self.tray.show()
        if self.config.region.width == 0 or self.config.region.height == 0:
            QMessageBox.information(
                None,
                "首次启动",
                "请右键托盘图标 →“重新框选区域”选择聊天区，\n再到“设置 · 飞书”填入 Webhook URL。",
            )
            return
        self.restart_runner()

    def restart_runner(self) -> None:
        if self.runner:
            self.runner.stop()
            self.runner = None
        if self.config.region.width == 0 or self.config.region.height == 0:
            log.warning("region not configured, runner not started | region=%s", self.config.region)
            return
        r = self.config.region
        capturer = MssCapturer(r.x, r.y, r.width, r.height)
        notifier = LarkWebhookNotifier(self.config.notifier.lark_webhook_url)
        pipeline = Pipeline(ocr=self.ocr, notifier=notifier, history=self.history, config=self.config)
        self.runner = WatchdogRunner(
            pipeline=pipeline,
            capturer=capturer,
            interval_seconds=self.config.interval_seconds,
            on_frame=lambda fr: self.signals.frame_done.emit(fr),
            on_error=lambda e: self.signals.error.emit(str(e)),
        )
        self.runner.start()
        if self._paused:
            self.runner.pause()
            self.tray.set_state("paused")
        else:
            self.tray.set_state("running")

    def toggle_pause(self) -> None:
        if not self.runner:
            return
        if self._paused:
            self.runner.resume()
            self._paused = False
            self.tray.set_state("running")
        else:
            self.runner.pause()
            self._paused = True
            self.tray.set_state("paused")

    def open_settings(self) -> None:
        if self._settings is None:
            self._settings = SettingsWindow(self.config)
            self._settings.config_saved.connect(self._on_config_saved)
            self._settings.pick_region_requested.connect(self.start_region_pick)
        self._settings.refresh_region()
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def open_history(self) -> None:
        if self._history_view is None:
            self._history_view = HistoryView(self.history)
        self._history_view.refresh()
        self._history_view.show()
        self._history_view.raise_()
        self._history_view.activateWindow()

    def start_region_pick(self) -> None:
        self._region_picker = RegionPicker()
        self._region_picker.region_picked.connect(self._on_region_picked)
        self._region_picker.cancelled.connect(lambda: log.info("region pick cancelled"))
        self._region_picker.showFullScreen()

    def _on_region_picked(self, x: int, y: int, w: int, h: int) -> None:
        if w < 10 or h < 10:
            log.warning("region too small (%dx%d), ignored", w, h)
            return
        self.config.region.x, self.config.region.y = x, y
        self.config.region.width, self.config.region.height = w, h
        save_config(self.config, self.cfg_path)
        log.info("region set to (%d,%d) %dx%d", x, y, w, h)
        if self._settings:
            self._settings.refresh_region()
        self.restart_runner()

    def _on_config_saved(self) -> None:
        save_config(self.config, self.cfg_path)
        log.info("config saved to %s", self.cfg_path)
        self.restart_runner()

    def _on_frame_done(self, fr: FrameResult) -> None:
        if fr.new_messages and self._settings is not None:
            self._settings.update_debug("\n---\n".join(m.text for m in fr.new_messages))

    def _on_error(self, msg: str) -> None:
        log.error("watchdog runtime error: %s", msg)
        self.tray.set_state("error", msg[:80])

    def quit(self) -> None:
        if self.runner:
            self.runner.stop()
        QApplication.instance().quit()


def _setup_logging() -> None:
    """配置日志：始终写文件到 user log dir；若有 stderr 也挂一份控制台。

    PyInstaller --windowed 模式下 sys.stderr 为 None，StreamHandler 默认会用
    sys.stderr 报错——所以必须先判断。文件日志是运行期问题排查的唯一手段。
    """
    log_file = log_dir() / "app.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [logging.FileHandler(log_file, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    log.info("log file: %s", log_file)


def main() -> None:
    _setup_logging()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = AppController()
    controller.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
