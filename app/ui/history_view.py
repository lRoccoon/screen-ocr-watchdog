"""历史只读列表：最近 100 条已推送消息。"""
from __future__ import annotations

from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from app.storage.history import HistoryStore


class HistoryView(QWidget):
    def __init__(self, history: HistoryStore) -> None:
        super().__init__()
        self.history = history
        self.setWindowTitle("Screen OCR Watchdog · 历史")
        self.resize(560, 480)
        self.list = QListWidget()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.addWidget(refresh_btn)
        layout.addWidget(self.list)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for rec in reversed(self.history.tail(100)):
            self.list.addItem(QListWidgetItem(f"[{rec['ts']}]\n{rec['text']}"))
