"""系统托盘控制器：三态图标 + 右键菜单。"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


_STATE_COLORS = {
    "running": "#1ea84a",
    "paused": "#d4a017",
    "error": "#c4291a",
}


def _make_dot_icon(color: str) -> QIcon:
    pix = QPixmap(32, 32)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QColor(color))
    p.drawEllipse(4, 4, 24, 24)
    p.end()
    return QIcon(pix)


class TrayController(QObject):
    pause_toggled = Signal()
    open_settings = Signal()
    open_history = Signal()
    pick_region = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.tray = QSystemTrayIcon()
        menu = QMenu()
        self.act_pause = QAction("暂停", menu)
        self.act_pause.triggered.connect(self.pause_toggled.emit)
        menu.addAction(self.act_pause)
        menu.addSeparator()
        menu.addAction("打开设置…", self.open_settings.emit)
        menu.addAction("查看历史…", self.open_history.emit)
        menu.addAction("重新框选区域…", self.pick_region.emit)
        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)
        self.tray.setContextMenu(menu)
        self.set_state("running")

    def set_state(self, state: str, reason: str = "") -> None:
        color = _STATE_COLORS.get(state, _STATE_COLORS["running"])
        self.tray.setIcon(_make_dot_icon(color))
        if state == "paused":
            self.tray.setToolTip("Screen OCR Watchdog · 已暂停")
            self.act_pause.setText("继续")
        elif state == "error":
            self.tray.setToolTip(f"Screen OCR Watchdog · 异常: {reason}")
        else:
            self.tray.setToolTip("Screen OCR Watchdog · 运行中")
            self.act_pause.setText("暂停")

    def show(self) -> None:
        self.tray.show()
