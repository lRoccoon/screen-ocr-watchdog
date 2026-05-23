"""设置窗口：Tab 式（监控区域 / 运行参数 / 飞书 / OCR 调试）。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.notifier.lark_webhook import LarkWebhookNotifier
from app.storage.config import AppConfig
from app.ui.webhook_url_helpers import (
    format_webhook_urls_for_textarea,
    parse_webhook_urls_from_textarea,
)


class SettingsWindow(QWidget):
    config_saved = Signal()
    pick_region_requested = Signal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.setWindowTitle("Screen OCR Watchdog · 设置")
        self.resize(560, 440)
        tabs = QTabWidget()
        tabs.addTab(self._build_region_tab(), "监控区域")
        tabs.addTab(self._build_params_tab(), "运行参数")
        tabs.addTab(self._build_lark_tab(), "飞书")
        tabs.addTab(self._build_debug_tab(), "OCR 调试")

        save_btn = QPushButton("保存并应用")
        save_btn.clicked.connect(self._save)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(save_btn)
        layout.addLayout(bottom)

    # ----- Region tab -----
    def _build_region_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.region_label = QLabel(self._region_text())
        pick_btn = QPushButton("重新框选区域…")
        pick_btn.clicked.connect(self.pick_region_requested.emit)
        form.addRow("当前区域:", self.region_label)
        form.addRow(pick_btn)
        return w

    def _region_text(self) -> str:
        r = self.config.region
        if r.width == 0 or r.height == 0:
            return "未配置"
        return f"x={r.x}, y={r.y}, {r.width}×{r.height}"

    def refresh_region(self) -> None:
        self.region_label.setText(self._region_text())

    # ----- Params tab -----
    def _build_params_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.interval = QSpinBox(); self.interval.setRange(1, 60); self.interval.setValue(self.config.interval_seconds)
        self.fuzzy = QSpinBox(); self.fuzzy.setRange(0, 10); self.fuzzy.setValue(self.config.diff.fuzzy_threshold)
        self.lru = QSpinBox(); self.lru.setRange(1, 200); self.lru.setValue(self.config.diff.lru_frames)
        self.batch = QSpinBox(); self.batch.setRange(2, 50); self.batch.setValue(self.config.diff.batch_threshold)
        self.gap = QSpinBox(); self.gap.setRange(1, 100); self.gap.setValue(self.config.ocr.card_gap)
        form.addRow("截屏间隔 (秒):", self.interval)
        form.addRow("模糊匹配阈值:", self.fuzzy)
        form.addRow("LRU 帧数:", self.lru)
        form.addRow("批量阈值:", self.batch)
        form.addRow("卡片间距 (px):", self.gap)
        return w

    # ----- Lark tab -----
    def _build_lark_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.webhook_edit = QPlainTextEdit(
            format_webhook_urls_for_textarea(
                webhook_urls=list(self.config.notifier.lark_webhook_urls),
                webhook_url_legacy=self.config.notifier.lark_webhook_url,
            )
        )
        self.webhook_edit.setPlaceholderText(
            "每行一个 Webhook URL，如：\nhttps://open.feishu.cn/open-apis/bot/v2/hook/xxx"
        )
        self.webhook_edit.setMinimumHeight(120)
        test_btn = QPushButton("发送测试消息")
        test_btn.clicked.connect(self._test_webhook)
        self.webhook_status = QLabel("")
        form.addRow("Webhook URLs:", self.webhook_edit)
        form.addRow(test_btn, self.webhook_status)
        return w

    def _test_webhook(self) -> None:
        urls = parse_webhook_urls_from_textarea(self.webhook_edit.toPlainText())
        if not urls:
            self.webhook_status.setText("请先填写至少一个 URL")
            self.webhook_status.setStyleSheet("color: #c4291a;")
            return
        r = LarkWebhookNotifier(urls).send_text("[Screen OCR Watchdog] 测试消息")
        n = len(urls)
        if r.ok:
            self.webhook_status.setText(f"✓ {n}/{n} 全部成功")
            self.webhook_status.setStyleSheet("color: #1ea84a;")
        else:
            self.webhook_status.setText(f"✗ {r.message}")
            self.webhook_status.setStyleSheet("color: #c4291a;")

    # ----- Debug tab -----
    def _build_debug_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.debug_text = QTextEdit()
        self.debug_text.setReadOnly(True)
        self.debug_text.setPlaceholderText("最近一帧识别到的新消息会显示在这里...")
        layout.addWidget(self.debug_text)
        return w

    def update_debug(self, text: str) -> None:
        self.debug_text.setPlainText(text)

    # ----- Save -----
    def _save(self) -> None:
        self.config.interval_seconds = self.interval.value()
        self.config.diff.fuzzy_threshold = self.fuzzy.value()
        self.config.diff.lru_frames = self.lru.value()
        self.config.diff.batch_threshold = self.batch.value()
        self.config.ocr.card_gap = self.gap.value()
        # 多行文本 → list；同时清空旧单字段，保存后只走 list
        self.config.notifier.lark_webhook_urls = parse_webhook_urls_from_textarea(
            self.webhook_edit.toPlainText()
        )
        self.config.notifier.lark_webhook_url = ""
        self.config_saved.emit()
