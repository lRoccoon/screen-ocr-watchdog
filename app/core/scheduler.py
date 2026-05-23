"""工作线程：定时调用 pipeline.process_image，结果通过 callback 通知 UI。

设计要点：
- 在工作线程跑，避免 OCR 阻塞 UI
- 用 Event.wait(remaining) 代替 sleep，保证 stop 时能立即退出
- 暂停/恢复用单独的 Event 标志，不退出线程
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from app.capture.mss_capturer import Capturer

log = logging.getLogger(__name__)

OnFrame = Callable[[Any], None]
OnError = Callable[[Exception], None]


class WatchdogRunner:
    def __init__(
        self,
        pipeline: Any,
        capturer: Capturer,
        interval_seconds: float,
        on_frame: OnFrame,
        on_error: OnError,
    ) -> None:
        self.pipeline = pipeline
        self.capturer = capturer
        self.interval = max(0.5, interval_seconds)
        self.on_frame = on_frame
        self.on_error = on_error
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._paused = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="watchdog")
        self._thread.start()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            start_t = time.time()
            if not self._paused.is_set():
                try:
                    image = self.capturer.capture()
                    result = self.pipeline.process_image(image)
                    self.on_frame(result)
                except Exception as e:
                    log.error("watchdog frame failed: %s", e, exc_info=True)
                    try:
                        self.on_error(e)
                    except Exception:
                        log.exception("on_error callback raised")
            elapsed = time.time() - start_t
            remaining = max(0.1, self.interval - elapsed)
            if self._stop.wait(remaining):
                break
