"""全屏半透明遮罩 + 鼠标拖框选区。"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget


class RegionPicker(QWidget):
    region_picked = Signal(int, int, int, int)  # x, y, w, h（屏幕绝对坐标）
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 覆盖所有屏幕（含多屏）
        rect = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(rect)
        self._start = None
        self._end = None
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = e.position().toPoint()
            self._end = self._start
            self.update()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._start is not None:
            self._end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self._start and self._end:
            r = QRect(self._start, self._end).normalized()
            offset = self.geometry().topLeft()
            self.region_picked.emit(
                r.x() + offset.x(),
                r.y() + offset.y(),
                r.width(),
                r.height(),
            )
            self.close()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()

    def paintEvent(self, _e) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self._start and self._end:
            r = QRect(self._start, self._end).normalized()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(r, QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(80, 180, 255), 2))
            painter.drawRect(r)
