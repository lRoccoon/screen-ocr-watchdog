"""设置窗口：Tab 式（监控区域 / 运行参数 / 飞书 / OCR 调试）。"""
from __future__ import annotations

# PySide6 imports are deferred inside the class so that the module-level pure
# helper functions can be imported in headless (no-display) test environments
# without triggering libEGL / libGL errors.

from app.storage.config import AppConfig


# ---------- 纯函数 helper（被 tests/test_settings_window.py 单测）----------

def parse_webhook_urls_from_textarea(text: str) -> list[str]:
    """按行 split → strip → 丢空 → 保序去重。"""
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        u = line.strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def format_webhook_urls_for_textarea(
    webhook_urls: list[str],
    webhook_url_legacy: str,
) -> str:
    """渲染到多行文本框时，把旧单字段 URL（若不在 list 里）合并进去。"""
    merged = list(webhook_urls)
    if webhook_url_legacy and webhook_url_legacy not in merged:
        merged.append(webhook_url_legacy)
    return "\n".join(merged)


# ---------- SettingsWindow ----------

def _import_qt() -> None:
    """Deferred Qt import — called only when SettingsWindow is instantiated."""
    global Signal, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit
    global QPushButton, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget
    global LarkWebhookNotifier
    from PySide6.QtCore import Signal as _Signal  # noqa: PLC0415
    from PySide6.QtWidgets import (  # noqa: PLC0415
        QFormLayout as _QFormLayout,
        QHBoxLayout as _QHBoxLayout,
        QLabel as _QLabel,
        QPlainTextEdit as _QPlainTextEdit,
        QPushButton as _QPushButton,
        QSpinBox as _QSpinBox,
        QTabWidget as _QTabWidget,
        QTextEdit as _QTextEdit,
        QVBoxLayout as _QVBoxLayout,
        QWidget as _QWidget,
    )
    from app.notifier.lark_webhook import LarkWebhookNotifier as _LN  # noqa: PLC0415
    Signal = _Signal
    QFormLayout = _QFormLayout
    QHBoxLayout = _QHBoxLayout
    QLabel = _QLabel
    QPlainTextEdit = _QPlainTextEdit
    QPushButton = _QPushButton
    QSpinBox = _QSpinBox
    QTabWidget = _QTabWidget
    QTextEdit = _QTextEdit
    QVBoxLayout = _QVBoxLayout
    QWidget = _QWidget
    LarkWebhookNotifier = _LN


# Placeholders so type checkers / IDEs see the names at module scope.
# They are overwritten by _import_qt() before any real use.
Signal = None  # type: ignore[assignment]
QFormLayout = None  # type: ignore[assignment]
QHBoxLayout = None  # type: ignore[assignment]
QLabel = None  # type: ignore[assignment]
QPlainTextEdit = None  # type: ignore[assignment]
QPushButton = None  # type: ignore[assignment]
QSpinBox = None  # type: ignore[assignment]
QTabWidget = None  # type: ignore[assignment]
QTextEdit = None  # type: ignore[assignment]
QVBoxLayout = None  # type: ignore[assignment]
QWidget = None  # type: ignore[assignment]
LarkWebhookNotifier = None  # type: ignore[assignment]


class SettingsWindow:
    """设置窗口。实例化时才触发 PySide6 import。"""

    # Signal 是类属性，必须在运行期赋值（PySide6 元类要求），
    # 所以我们用 __init_subclass__ 技巧绕过：真正的 QWidget 子类
    # 在第一次实例化时动态创建。
    _real_class: type | None = None

    def __new__(cls, config: AppConfig) -> "SettingsWindow":  # type: ignore[misc]
        _import_qt()
        if cls._real_class is None:
            cls._real_class = _build_settings_window_class()
        return cls._real_class(config)  # type: ignore[return-value]


def _build_settings_window_class() -> type:
    """在 Qt 可用后动态构建真正的 QWidget 子类。"""

    class _SettingsWindow(QWidget):  # type: ignore[misc,valid-type]
        config_saved = Signal()  # type: ignore[misc]
        pick_region_requested = Signal()  # type: ignore[misc]

        def __init__(self, config: AppConfig) -> None:
            super().__init__()
            self.config = config
            self.setWindowTitle("Screen OCR Watchdog · 设置")
            self.resize(560, 440)
            tabs = QTabWidget()  # type: ignore[misc]
            tabs.addTab(self._build_region_tab(), "监控区域")
            tabs.addTab(self._build_params_tab(), "运行参数")
            tabs.addTab(self._build_lark_tab(), "飞书")
            tabs.addTab(self._build_debug_tab(), "OCR 调试")

            save_btn = QPushButton("保存并应用")  # type: ignore[misc]
            save_btn.clicked.connect(self._save)

            layout = QVBoxLayout(self)  # type: ignore[misc]
            layout.addWidget(tabs)
            bottom = QHBoxLayout()  # type: ignore[misc]
            bottom.addStretch(1)
            bottom.addWidget(save_btn)
            layout.addLayout(bottom)

        # ----- Region tab -----
        def _build_region_tab(self) -> QWidget:  # type: ignore[valid-type]
            w = QWidget()  # type: ignore[misc]
            form = QFormLayout(w)  # type: ignore[misc]
            self.region_label = QLabel(self._region_text())  # type: ignore[misc]
            pick_btn = QPushButton("重新框选区域…")  # type: ignore[misc]
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
        def _build_params_tab(self) -> QWidget:  # type: ignore[valid-type]
            w = QWidget()  # type: ignore[misc]
            form = QFormLayout(w)  # type: ignore[misc]
            self.interval = QSpinBox(); self.interval.setRange(1, 60); self.interval.setValue(self.config.interval_seconds)  # type: ignore[misc]
            self.fuzzy = QSpinBox(); self.fuzzy.setRange(0, 10); self.fuzzy.setValue(self.config.diff.fuzzy_threshold)  # type: ignore[misc]
            self.lru = QSpinBox(); self.lru.setRange(1, 200); self.lru.setValue(self.config.diff.lru_frames)  # type: ignore[misc]
            self.batch = QSpinBox(); self.batch.setRange(2, 50); self.batch.setValue(self.config.diff.batch_threshold)  # type: ignore[misc]
            self.gap = QSpinBox(); self.gap.setRange(1, 100); self.gap.setValue(self.config.ocr.card_gap)  # type: ignore[misc]
            form.addRow("截屏间隔 (秒):", self.interval)
            form.addRow("模糊匹配阈值:", self.fuzzy)
            form.addRow("LRU 帧数:", self.lru)
            form.addRow("批量阈值:", self.batch)
            form.addRow("卡片间距 (px):", self.gap)
            return w

        # ----- Lark tab -----
        def _build_lark_tab(self) -> QWidget:  # type: ignore[valid-type]
            w = QWidget()  # type: ignore[misc]
            form = QFormLayout(w)  # type: ignore[misc]
            self.webhook_edit = QPlainTextEdit(  # type: ignore[misc]
                format_webhook_urls_for_textarea(
                    webhook_urls=list(self.config.notifier.lark_webhook_urls),
                    webhook_url_legacy=self.config.notifier.lark_webhook_url,
                )
            )
            self.webhook_edit.setPlaceholderText(
                "每行一个 Webhook URL，如：\nhttps://open.feishu.cn/open-apis/bot/v2/hook/xxx"
            )
            self.webhook_edit.setMinimumHeight(120)
            test_btn = QPushButton("发送测试消息")  # type: ignore[misc]
            test_btn.clicked.connect(self._test_webhook)
            self.webhook_status = QLabel("")  # type: ignore[misc]
            form.addRow("Webhook URLs:", self.webhook_edit)
            form.addRow(test_btn, self.webhook_status)
            return w

        def _test_webhook(self) -> None:
            urls = parse_webhook_urls_from_textarea(self.webhook_edit.toPlainText())
            if not urls:
                self.webhook_status.setText("请先填写至少一个 URL")
                self.webhook_status.setStyleSheet("color: #c4291a;")
                return
            r = LarkWebhookNotifier(urls).send_text("[Screen OCR Watchdog] 测试消息")  # type: ignore[misc]
            n = len(urls)
            if r.ok:
                self.webhook_status.setText(f"✓ {n}/{n} 全部成功")
                self.webhook_status.setStyleSheet("color: #1ea84a;")
            else:
                self.webhook_status.setText(f"✗ {r.message}")
                self.webhook_status.setStyleSheet("color: #c4291a;")

        # ----- Debug tab -----
        def _build_debug_tab(self) -> QWidget:  # type: ignore[valid-type]
            w = QWidget()  # type: ignore[misc]
            layout = QVBoxLayout(w)  # type: ignore[misc]
            self.debug_text = QTextEdit()  # type: ignore[misc]
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

    return _SettingsWindow
