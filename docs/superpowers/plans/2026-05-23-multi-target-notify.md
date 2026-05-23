# 多群通知支持 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `LarkWebhookNotifier` / `LarkImageNotifier` 支持把同一帧推送到多个飞书目标，部分失败 best-effort，向后兼容 v0.1.0 单字段配置。

**Architecture:** `NotifierCfg` 加 `lark_webhook_urls` / `lark_targets` 两条 list 字段，并提供 `effective_*()` 方法把 list+单字段合并成生效列表；两个 notifier 构造器都接收 list，遍历发送并聚合 `NotifyResult`；image_diff 模式 1 次 token + 1 次 upload + N 次 send_message 共享 image_key；OCR 设置 UI 把 webhook URL 单行输入换成 `QPlainTextEdit` 多行，每行一个 URL。

**Tech Stack:** Python 3.11 / Pydantic / PySide6 / requests / pytest（mock requests.post）

**Spec:** `docs/superpowers/specs/2026-05-23-multi-target-notify-design.md`

---

## File Structure

**新增 / 修改文件：**

| 文件 | 操作 | 责任 |
|---|---|---|
| `app/storage/config.py` | 修改 | 加 `LarkTargetCfg` model；`NotifierCfg` 加 `lark_webhook_urls` / `lark_targets` list 字段 + `effective_webhook_urls()` / `effective_targets()` |
| `app/notifier/lark_webhook.py` | 修改 | 构造器 `webhook_urls: Sequence[str]`；`_post` 遍历所有 URL；聚合 `NotifyResult` |
| `app/notifier/lark_image.py` | 修改 | 构造器 `targets: Sequence[LarkTargetCfg]`；`send_image` 1 token + 1 upload + N send_message |
| `app/core/pipeline_factory.py` | 修改 | 用 `cfg.notifier.effective_*()` 注入 |
| `app/ui/settings_window.py` | 修改 | webhook 单行 `QLineEdit` → `QPlainTextEdit`；加载/保存逻辑；测试按钮聚合显示 |
| `tools/replay_runner.py` | 修改 | 跟随 `LarkWebhookNotifier` 签名变更 |
| `tests/test_storage.py` | 扩充 | `effective_*` 三种情况 + 加载 v0.1.0 旧 yaml + 加载新 yaml |
| `tests/test_notifier.py` | 重写 | 多 URL 聚合语义 + 单 URL 兼容 |
| `tests/test_lark_image.py` | 重写 | 多 target 聚合语义 + upload 复用 |
| `tests/test_pipeline_factory.py` | 扩充 | 注入 notifier 拿到的列表长度 |
| `tests/test_pipeline_replay.py` | 修改 | 跟随 `LarkWebhookNotifier` 签名变更 |
| `README.md` | 修改 | 多群配置示例段落 |

---

## Task 1: `NotifierCfg` 加 list 字段 + `effective_*` 方法

**Files:**
- Modify: `app/storage/config.py`
- Test: `tests/test_storage.py`

### Step 1.1: 写 effective_* 的失败测试

- [ ] **Step 1.1.1** 把以下用例 append 到 `tests/test_storage.py`：

```python
from app.storage.config import (
    AppConfig,
    LarkTargetCfg,
    NotifierCfg,
    Region,
    load_config,
    save_config,
)


# ---------- effective_webhook_urls ----------

def test_effective_webhook_urls_list_takes_priority():
    """list 非空时优先用 list，忽略单字段。"""
    nc = NotifierCfg(
        lark_webhook_urls=["https://a", "https://b"],
        lark_webhook_url="https://legacy",
    )
    assert nc.effective_webhook_urls() == ["https://a", "https://b"]


def test_effective_webhook_urls_fallback_to_single_field():
    """list 为空时回退到单字段，包装成单元素 list。"""
    nc = NotifierCfg(lark_webhook_url="https://legacy")
    assert nc.effective_webhook_urls() == ["https://legacy"]


def test_effective_webhook_urls_both_empty_returns_empty_list():
    nc = NotifierCfg()
    assert nc.effective_webhook_urls() == []


def test_effective_webhook_urls_drops_blank_entries_in_list():
    """list 里的空字符串视为无效，过滤掉。"""
    nc = NotifierCfg(lark_webhook_urls=["https://a", "", "https://b"])
    assert nc.effective_webhook_urls() == ["https://a", "https://b"]


# ---------- effective_targets ----------

def test_effective_targets_list_takes_priority():
    nc = NotifierCfg(
        lark_targets=[
            LarkTargetCfg(receive_id="oc_a", receive_id_type="chat_id"),
            LarkTargetCfg(receive_id="ou_b", receive_id_type="open_id"),
        ],
        lark_receive_id="legacy",
    )
    ts = nc.effective_targets()
    assert [t.receive_id for t in ts] == ["oc_a", "ou_b"]
    assert [t.receive_id_type for t in ts] == ["chat_id", "open_id"]


def test_effective_targets_fallback_to_single_field():
    nc = NotifierCfg(lark_receive_id="oc_legacy", lark_receive_id_type="chat_id")
    ts = nc.effective_targets()
    assert len(ts) == 1
    assert ts[0].receive_id == "oc_legacy"
    assert ts[0].receive_id_type == "chat_id"


def test_effective_targets_both_empty_returns_empty_list():
    nc = NotifierCfg()
    assert nc.effective_targets() == []


def test_effective_targets_drops_blank_receive_ids_in_list():
    nc = NotifierCfg(
        lark_targets=[
            LarkTargetCfg(receive_id="oc_a"),
            LarkTargetCfg(receive_id=""),
        ],
    )
    ts = nc.effective_targets()
    assert [t.receive_id for t in ts] == ["oc_a"]


# ---------- yaml 兼容 ----------

def test_load_v010_yaml_with_single_webhook_works(tmp_path):
    """v0.1.0 旧 yaml（只有 lark_webhook_url）加载后能拿到生效 list。"""
    p = tmp_path / "c.yaml"
    p.write_text(
        "notifier:\n  lark_webhook_url: https://legacy\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.notifier.lark_webhook_urls == []
    assert cfg.notifier.lark_webhook_url == "https://legacy"
    assert cfg.notifier.effective_webhook_urls() == ["https://legacy"]


def test_load_v010_yaml_with_single_receive_id_works(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "mode: image_diff\n"
        "notifier:\n"
        "  lark_app_id: cli_x\n"
        "  lark_app_secret: sec_x\n"
        "  lark_receive_id: oc_legacy\n"
        "  lark_receive_id_type: chat_id\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.notifier.lark_targets == []
    ts = cfg.notifier.effective_targets()
    assert len(ts) == 1
    assert ts[0].receive_id == "oc_legacy"


def test_load_new_yaml_with_list_fields(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "notifier:\n"
        "  lark_webhook_urls:\n"
        "    - https://a\n"
        "    - https://b\n"
        "  lark_targets:\n"
        "    - {receive_id: oc_a, receive_id_type: chat_id}\n"
        "    - {receive_id: ou_b, receive_id_type: open_id}\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.notifier.effective_webhook_urls() == ["https://a", "https://b"]
    ts = cfg.notifier.effective_targets()
    assert [(t.receive_id, t.receive_id_type) for t in ts] == [
        ("oc_a", "chat_id"),
        ("ou_b", "open_id"),
    ]
```

- [ ] **Step 1.1.2** 跑测试确认失败

  Run: `.venv/bin/pytest tests/test_storage.py -v`

  Expected: 多个用例 FAIL，主要是 `ImportError: cannot import name 'LarkTargetCfg'` 或 `AttributeError: 'NotifierCfg' object has no attribute 'effective_webhook_urls'`

### Step 1.2: 实现 `LarkTargetCfg` + list 字段 + helper

- [ ] **Step 1.2.1** 修改 `app/storage/config.py`，整体改为：

```python
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
```

- [ ] **Step 1.2.2** 跑测试

  Run: `.venv/bin/pytest tests/test_storage.py -v`

  Expected: 全部 PASS。

### Step 1.3: Commit

- [ ] **Step 1.3.1**

```bash
git add app/storage/config.py tests/test_storage.py
git commit -m "feat(config): NotifierCfg 加 lark_webhook_urls / lark_targets list 字段

新增 LarkTargetCfg model；NotifierCfg 加 effective_webhook_urls /
effective_targets helper，解析规则为 list 字段优先，list 为空时
fallback 到单字段。完全向后兼容 v0.1.0 yaml。"
```

---

## Task 2: `LarkWebhookNotifier` 多 URL

**Files:**
- Modify: `app/notifier/lark_webhook.py`
- Test: `tests/test_notifier.py` (重写)

### Step 2.1: 重写 `tests/test_notifier.py`

- [ ] **Step 2.1.1** 整体替换为：

```python
from unittest.mock import MagicMock, patch

from app.notifier.lark_webhook import LarkWebhookNotifier


URL_A = "https://example.invalid/webhook/aaa"
URL_B = "https://example.invalid/webhook/bbb"
URL_C = "https://example.invalid/webhook/ccc"


def _mock_resp(json_data: dict, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    return resp


# ---------- 单 URL（兼容原 v0.1.0 行为）----------

def test_send_text_single_url_success():
    n = LarkWebhookNotifier([URL_A])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"StatusCode": 0, "msg": "success"})
        r = n.send_text("hello")
    assert r.ok is True
    assert post.call_count == 1
    sent_payload = post.call_args.kwargs["json"]
    assert sent_payload == {"msg_type": "text", "content": {"text": "hello"}}


def test_send_text_single_url_server_error():
    n = LarkWebhookNotifier([URL_A])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 9499, "msg": "bad webhook"})
        r = n.send_text("hello")
    assert r.ok is False


def test_send_text_single_url_network_error():
    n = LarkWebhookNotifier([URL_A])
    with patch("app.notifier.lark_webhook.requests.post", side_effect=Exception("boom")):
        r = n.send_text("hello")
    assert r.ok is False
    assert "boom" in r.message


# ---------- 空 list ----------

def test_send_with_empty_url_list():
    n = LarkWebhookNotifier([])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        r = n.send_text("hello")
    assert r.ok is False
    assert "no webhook urls" in r.message.lower()
    post.assert_not_called()


# ---------- 多 URL ----------

def test_send_text_multi_urls_all_success():
    n = LarkWebhookNotifier([URL_A, URL_B, URL_C])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 0, "msg": "success"})
        r = n.send_text("hello")
    assert r.ok is True
    assert post.call_count == 3
    called_urls = [c.args[0] for c in post.call_args_list]
    assert called_urls == [URL_A, URL_B, URL_C]


def test_send_text_multi_urls_one_network_fail_does_not_block_others():
    """1 个抛 Exception，其他 2 个仍然被调用；总体 ok=False。"""
    n = LarkWebhookNotifier([URL_A, URL_B, URL_C])

    def side_effect(url, **kwargs):
        if url == URL_B:
            raise Exception("network timeout")
        return _mock_resp({"code": 0, "msg": "success"})

    with patch("app.notifier.lark_webhook.requests.post", side_effect=side_effect) as post:
        r = n.send_text("hello")

    assert post.call_count == 3
    assert r.ok is False
    # message 应能定位是哪个 URL 失败（含 url 尾段 + 错误简述）
    assert "1/3" in r.message
    assert "bbb" in r.message
    assert "timeout" in r.message.lower()


def test_send_text_multi_urls_one_server_error():
    """1 个返回 code != 0，其他 2 个 OK。"""
    n = LarkWebhookNotifier([URL_A, URL_B, URL_C])

    def side_effect(url, **kwargs):
        if url == URL_B:
            return _mock_resp({"code": 9499, "msg": "invalid webhook"})
        return _mock_resp({"code": 0, "msg": "success"})

    with patch("app.notifier.lark_webhook.requests.post", side_effect=side_effect):
        r = n.send_text("hello")
    assert r.ok is False
    assert "1/3" in r.message
    assert "bbb" in r.message


def test_send_text_multi_urls_all_fail():
    n = LarkWebhookNotifier([URL_A, URL_B])
    with patch("app.notifier.lark_webhook.requests.post", side_effect=Exception("boom")):
        r = n.send_text("hello")
    assert r.ok is False
    assert "all 2" in r.message.lower() or "2/2" in r.message


# ---------- send_messages 行为不变（payload 只 build 一次） ----------

def test_send_messages_single_payload_dispatched_to_each_url():
    n = LarkWebhookNotifier([URL_A, URL_B])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 0, "msg": "ok"})
        n.send_messages(["m"])
    # 2 个 URL 都收到同一份 payload
    payloads = [c.kwargs["json"] for c in post.call_args_list]
    assert payloads == [
        {"msg_type": "text", "content": {"text": "m"}},
        {"msg_type": "text", "content": {"text": "m"}},
    ]


def test_send_messages_few_concat_to_each_url():
    n = LarkWebhookNotifier([URL_A, URL_B])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 0, "msg": "ok"})
        n.send_messages(["a", "b", "c"], batch_threshold=5)
    payloads = [c.kwargs["json"] for c in post.call_args_list]
    assert all(p["content"]["text"] == "a\n---\nb\n---\nc" for p in payloads)


def test_send_messages_batch_prefix_applied_each_url():
    n = LarkWebhookNotifier([URL_A, URL_B])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        post.return_value = _mock_resp({"code": 0, "msg": "ok"})
        n.send_messages([f"m{i}" for i in range(5)], batch_threshold=5)
    payloads = [c.kwargs["json"] for c in post.call_args_list]
    assert all(p["content"]["text"].startswith("【批量 5 条】") for p in payloads)


def test_send_messages_empty_short_circuits():
    n = LarkWebhookNotifier([URL_A])
    with patch("app.notifier.lark_webhook.requests.post") as post:
        r = n.send_messages([])
    assert r.ok is True
    post.assert_not_called()
```

- [ ] **Step 2.1.2** 跑测试确认失败

  Run: `.venv/bin/pytest tests/test_notifier.py -v`

  Expected: 全部 FAIL（构造器签名不匹配 / message 不含期望内容）。

### Step 2.2: 重写 `app/notifier/lark_webhook.py`

- [ ] **Step 2.2.1** 整体替换为：

```python
"""飞书自定义机器人 Webhook 发送：支持多个 URL，best-effort 部分失败。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import requests

log = logging.getLogger(__name__)


@dataclass
class NotifyResult:
    ok: bool
    message: str = ""


def _url_tail(url: str, n: int = 12) -> str:
    return url[-n:] if len(url) > n else url


class LarkWebhookNotifier:
    def __init__(self, webhook_urls: Sequence[str], timeout: float = 10.0) -> None:
        # 过滤空字符串，构造完即 immutable
        self.webhook_urls: list[str] = [u for u in webhook_urls if u]
        self.timeout = timeout

    def _post(self, payload: dict) -> NotifyResult:
        if not self.webhook_urls:
            log.error("lark webhook send skipped: no webhook urls configured")
            return NotifyResult(ok=False, message="no webhook urls configured")

        failures: list[str] = []
        for url in self.webhook_urls:
            tail = _url_tail(url)
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                data = resp.json()
            except Exception as e:
                log.error(
                    "lark webhook send failed: url_tail=%s err=%s payload_keys=%s",
                    tail, e, list(payload),
                )
                failures.append(f"hook[..{tail}]={e}")
                continue

            ok = (data.get("StatusCode") == 0) or (data.get("code") == 0)
            if not ok:
                log.error(
                    "lark webhook server error: url_tail=%s code=%s msg=%s",
                    tail, data.get("code"), data.get("msg"),
                )
                failures.append(f"hook[..{tail}]=code={data.get('code')}")

        n = len(self.webhook_urls)
        if not failures:
            return NotifyResult(ok=True, message="ok")
        if len(failures) == n:
            return NotifyResult(
                ok=False,
                message=f"all {n} targets failed: {'; '.join(failures)}",
            )
        return NotifyResult(
            ok=False,
            message=f"{len(failures)}/{n} targets failed: {'; '.join(failures)}",
        )

    def send_text(self, text: str) -> NotifyResult:
        return self._post({"msg_type": "text", "content": {"text": text}})

    def send_messages(self, messages: Sequence[str], batch_threshold: int = 5) -> NotifyResult:
        """把一帧的多条新消息合并成单条飞书消息（再扇出到所有 URL）。"""
        if not messages:
            return NotifyResult(ok=True, message="no messages")
        n = len(messages)
        if n == 1:
            return self.send_text(messages[0])
        body = "\n---\n".join(messages)
        if n >= batch_threshold:
            text = f"【批量 {n} 条】如刚刚滚动过页面可忽略\n\n{body}"
        else:
            text = body
        return self.send_text(text)
```

- [ ] **Step 2.2.2** 跑测试确认通过

  Run: `.venv/bin/pytest tests/test_notifier.py -v`

  Expected: 全部 PASS。

### Step 2.3: Commit

- [ ] **Step 2.3.1**

```bash
git add app/notifier/lark_webhook.py tests/test_notifier.py
git commit -m "feat(notifier): LarkWebhookNotifier 支持多 URL 扇出

构造器接收 Sequence[str]；_post 内 build 一次 payload 后遍历
URL，每个 URL 独立 try/except，错误日志带 url 尾段。NotifyResult
聚合 ok = 全部成功，message 形如 \"1/3 targets failed: hook[..xxx]=...\"
方便上层日志定位。"
```

---

## Task 3: `LarkImageNotifier` 多 target

**Files:**
- Modify: `app/notifier/lark_image.py`
- Test: `tests/test_lark_image.py` (重写)

### Step 3.1: 重写 `tests/test_lark_image.py`

- [ ] **Step 3.1.1** 整体替换为：

```python
"""LarkImageNotifier 单测：mock requests.post，验证多 target 扇出 + token 缓存。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from PIL import Image

from app.notifier.lark_image import LarkImageNotifier
from app.storage.config import LarkTargetCfg


T_A = LarkTargetCfg(receive_id="oc_a", receive_id_type="chat_id")
T_B = LarkTargetCfg(receive_id="ou_b", receive_id_type="open_id")
T_C = LarkTargetCfg(receive_id="user@example.com", receive_id_type="email")


def _make_notifier(targets=None) -> LarkImageNotifier:
    return LarkImageNotifier(
        app_id="cli_xxx",
        app_secret="sec_xxx",
        targets=targets if targets is not None else [T_A],
    )


def _mock_resp(json_data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    return resp


def _png() -> Image.Image:
    return Image.new("RGB", (10, 10), (255, 0, 0))


def _fake_post_factory(send_message_side_effect=None):
    """返回一个 side_effect 函数：按 URL 返回不同响应。

    send_message_side_effect 是一个把 (call_idx, target_receive_id, body) → 响应字典 的函数；
    None 时一律返回 success。
    """
    state = {"send_idx": 0}

    def side_effect(url, **kwargs):
        if "tenant_access_token" in url:
            return _mock_resp({"code": 0, "tenant_access_token": "t-abc", "expire": 7200})
        if "im/v1/images" in url:
            return _mock_resp({"code": 0, "data": {"image_key": "img_v3_xxx"}})
        if "im/v1/messages" in url:
            idx = state["send_idx"]
            state["send_idx"] += 1
            body = kwargs.get("json", {})
            if send_message_side_effect is not None:
                return send_message_side_effect(idx, body.get("receive_id"), body)
            return _mock_resp({"code": 0, "data": {"message_id": f"om_msg_{idx}"}})
        raise AssertionError(f"unexpected URL: {url}")

    return side_effect


# ---------- 单 target（兼容原 v0.1.0 行为）----------

def test_send_image_single_target_happy_path():
    n = _make_notifier(targets=[T_A])
    with patch("app.notifier.lark_image.requests.post", side_effect=_fake_post_factory()) as post:
        r = n.send_image(_png())
    assert r.ok is True

    calls = [c.args[0] for c in post.call_args_list]
    assert sum(1 for u in calls if "tenant_access_token" in u) == 1
    assert sum(1 for u in calls if "im/v1/images" in u) == 1
    msg_calls = [c for c in post.call_args_list if "im/v1/messages" in c.args[0]]
    assert len(msg_calls) == 1
    assert "receive_id_type=chat_id" in msg_calls[0].args[0]
    body = msg_calls[0].kwargs["json"]
    assert body["receive_id"] == "oc_a"
    content = json.loads(body["content"])
    assert content["image_key"] == "img_v3_xxx"


def test_token_cached_across_consecutive_send_image():
    n = _make_notifier(targets=[T_A])
    with patch("app.notifier.lark_image.requests.post", side_effect=_fake_post_factory()) as post:
        n.send_image(_png())
        n.send_image(_png())
    token_calls = [c for c in post.call_args_list if "tenant_access_token" in c.args[0]]
    assert len(token_calls) == 1


def test_expired_token_triggers_refresh():
    n = _make_notifier(targets=[T_A])
    fake_post = MagicMock(side_effect=_fake_post_factory())
    with patch("app.notifier.lark_image.requests.post", fake_post):
        n.send_image(_png())
        n._token_expires_at = float("-inf")
        n.send_image(_png())
    token_calls = [c for c in fake_post.call_args_list if "tenant_access_token" in c.args[0]]
    assert len(token_calls) == 2


def test_token_endpoint_business_error():
    n = _make_notifier(targets=[T_A])

    def s(url, **kwargs):
        return _mock_resp({"code": 99991663, "msg": "invalid app_id"})

    with patch("app.notifier.lark_image.requests.post", side_effect=s):
        r = n.send_image(_png())
    assert r.ok is False
    assert "99991663" in r.message or "invalid app_id" in r.message


def test_upload_business_error_aborts_send():
    """upload 失败，整体失败且不调用任何 send_message。"""
    n = _make_notifier(targets=[T_A, T_B])

    def s(url, **kwargs):
        if "tenant_access_token" in url:
            return _mock_resp({"code": 0, "tenant_access_token": "t-x", "expire": 7200})
        if "im/v1/images" in url:
            return _mock_resp({"code": 230002, "msg": "image too large"})
        raise AssertionError(f"send_message should not be called, url={url}")

    with patch("app.notifier.lark_image.requests.post", side_effect=s) as post:
        r = n.send_image(_png())
    assert r.ok is False
    # send_message URL 完全没被调过
    assert not any("im/v1/messages" in c.args[0] for c in post.call_args_list)


def test_network_exception_returns_failure():
    n = _make_notifier(targets=[T_A])
    with patch("app.notifier.lark_image.requests.post", side_effect=Exception("boom")):
        r = n.send_image(_png())
    assert r.ok is False
    assert "boom" in r.message


# ---------- 多 target ----------

def test_send_image_multi_targets_all_success_upload_once():
    """3 个 target 全成功：token 1 次、upload 1 次、send_message 3 次。"""
    n = _make_notifier(targets=[T_A, T_B, T_C])
    with patch("app.notifier.lark_image.requests.post", side_effect=_fake_post_factory()) as post:
        r = n.send_image(_png())
    assert r.ok is True

    token_n = sum(1 for c in post.call_args_list if "tenant_access_token" in c.args[0])
    upload_n = sum(1 for c in post.call_args_list if "im/v1/images" in c.args[0])
    msg_calls = [c for c in post.call_args_list if "im/v1/messages" in c.args[0]]
    assert (token_n, upload_n, len(msg_calls)) == (1, 1, 3)

    # 每个 target 都用了自己的 receive_id 和 receive_id_type
    used = [
        (
            c.kwargs["json"]["receive_id"],
            c.args[0].split("receive_id_type=")[-1],
        )
        for c in msg_calls
    ]
    assert used == [
        ("oc_a", "chat_id"),
        ("ou_b", "open_id"),
        ("user@example.com", "email"),
    ]


def test_send_image_multi_targets_one_send_fail_does_not_block_others():
    """3 个 target，第 2 个 send_message 业务错误：upload 仍 1 次，send_message 3 次，ok=False。"""
    def send_side_effect(idx, receive_id, body):
        if receive_id == "ou_b":
            return _mock_resp({"code": 230020, "msg": "bot not in chat"})
        return _mock_resp({"code": 0, "data": {"message_id": "om"}})

    n = _make_notifier(targets=[T_A, T_B, T_C])
    fake = _fake_post_factory(send_message_side_effect=send_side_effect)
    with patch("app.notifier.lark_image.requests.post", side_effect=fake) as post:
        r = n.send_image(_png())

    upload_n = sum(1 for c in post.call_args_list if "im/v1/images" in c.args[0])
    msg_n = sum(1 for c in post.call_args_list if "im/v1/messages" in c.args[0])
    assert upload_n == 1
    assert msg_n == 3
    assert r.ok is False
    assert "1/3" in r.message
    assert "ou_b" in r.message


def test_send_image_multi_targets_network_exception_on_one_continues():
    """第 1 个 send_message 抛网络异常，其他 2 个仍然发出。"""
    def send_side_effect(idx, receive_id, body):
        if idx == 0:
            raise Exception("network timeout")
        return _mock_resp({"code": 0, "data": {"message_id": "om"}})

    n = _make_notifier(targets=[T_A, T_B, T_C])
    fake = _fake_post_factory(send_message_side_effect=send_side_effect)
    with patch("app.notifier.lark_image.requests.post", side_effect=fake) as post:
        r = n.send_image(_png())

    msg_n = sum(1 for c in post.call_args_list if "im/v1/messages" in c.args[0])
    assert msg_n == 3
    assert r.ok is False
    assert "timeout" in r.message.lower()


def test_send_image_empty_targets_short_circuits():
    n = _make_notifier(targets=[])
    with patch("app.notifier.lark_image.requests.post") as post:
        r = n.send_image(_png())
    assert r.ok is False
    assert "target" in r.message.lower() or "credential" in r.message.lower()
    post.assert_not_called()


def test_send_image_missing_credentials_short_circuits():
    n = LarkImageNotifier(app_id="", app_secret="", targets=[T_A])
    with patch("app.notifier.lark_image.requests.post") as post:
        r = n.send_image(_png())
    assert r.ok is False
    post.assert_not_called()
```

- [ ] **Step 3.1.2** 跑测试确认失败

  Run: `.venv/bin/pytest tests/test_lark_image.py -v`

  Expected: 全部 FAIL（构造器签名不匹配 / `LarkTargetCfg` 找不到属性等）。

### Step 3.2: 重写 `app/notifier/lark_image.py`

- [ ] **Step 3.2.1** 整体替换为：

```python
"""飞书自建应用图片消息发送：tenant_access_token 缓存 + 上传图 + 多目标扇出。

只用于 mode=image_diff。与 LarkWebhookNotifier 平级、不共享代码。
"""
from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import dataclass
from threading import Lock
from typing import Sequence

import requests
from PIL import Image

from app.storage.config import LarkTargetCfg

log = logging.getLogger(__name__)

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
UPLOAD_URL = "https://open.feishu.cn/open-apis/im/v1/images"
MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
TOKEN_REFRESH_BUFFER_SECONDS = 300  # 剩余 < 5min 视为过期


@dataclass
class NotifyResult:
    ok: bool
    message: str = ""


class LarkImageNotifier:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        targets: Sequence[LarkTargetCfg],
        timeout: float = 10.0,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        # 过滤 receive_id 为空的非法 target
        self.targets: list[LarkTargetCfg] = [t for t in targets if t.receive_id]
        self.timeout = timeout
        self._token: str = ""
        self._token_expires_at: float = float("-inf")
        self._token_lock = Lock()

    def _credentials_ok(self) -> bool:
        return bool(self.app_id and self.app_secret and self.targets)

    def _get_token(self) -> str:
        with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
                return self._token
            resp = requests.post(
                TOKEN_URL,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=self.timeout,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(
                    f"token fetch failed code={data.get('code')} msg={data.get('msg')}"
                )
            self._token = data["tenant_access_token"]
            self._token_expires_at = time.monotonic() + int(data.get("expire", 7200))
            return self._token

    def _upload_image(self, token: str, image: Image.Image) -> str:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        resp = requests.post(
            UPLOAD_URL,
            headers={"Authorization": f"Bearer {token}"},
            data={"image_type": "message"},
            files={"image": ("diff.png", buf, "image/png")},
            timeout=self.timeout,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"upload image failed code={data.get('code')} msg={data.get('msg')}"
            )
        return data["data"]["image_key"]

    def _send_message(self, token: str, image_key: str, target: LarkTargetCfg) -> None:
        resp = requests.post(
            f"{MESSAGE_URL}?receive_id_type={target.receive_id_type}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "receive_id": target.receive_id,
                "msg_type": "image",
                "content": json.dumps({"image_key": image_key}),
            },
            timeout=self.timeout,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"send message failed code={data.get('code')} msg={data.get('msg')}"
            )

    def send_image(self, image: Image.Image) -> NotifyResult:
        if not self._credentials_ok():
            log.error(
                "lark image send skipped: app_id_set=%s secret_set=%s targets=%d",
                bool(self.app_id), bool(self.app_secret), len(self.targets),
            )
            return NotifyResult(
                ok=False,
                message="missing credentials or no targets configured",
            )

        # 1) token + 2) upload，任一失败则整体失败
        try:
            token = self._get_token()
            image_key = self._upload_image(token, image)
        except Exception as e:
            log.error("lark image prep failed: %s", e)
            return NotifyResult(ok=False, message=str(e))

        # 3) 扇出 send_message，每个 target 独立 try/except
        failures: list[str] = []
        for t in self.targets:
            try:
                self._send_message(token, image_key, t)
            except Exception as e:
                log.error(
                    "lark image send_message failed: receive_id=%s type=%s err=%s",
                    t.receive_id, t.receive_id_type, e,
                )
                failures.append(f"{t.receive_id}={e}")

        n = len(self.targets)
        if not failures:
            return NotifyResult(ok=True, message="ok")
        if len(failures) == n:
            return NotifyResult(
                ok=False,
                message=f"all {n} targets failed: {'; '.join(failures)}",
            )
        return NotifyResult(
            ok=False,
            message=f"{len(failures)}/{n} targets failed: {'; '.join(failures)}",
        )
```

- [ ] **Step 3.2.2** 跑测试

  Run: `.venv/bin/pytest tests/test_lark_image.py -v`

  Expected: 全部 PASS。

### Step 3.3: Commit

- [ ] **Step 3.3.1**

```bash
git add app/notifier/lark_image.py tests/test_lark_image.py
git commit -m "feat(notifier): LarkImageNotifier 支持多 target 扇出

构造器接收 Sequence[LarkTargetCfg]；send_image 内 1 次 token + 1 次
upload 后遍历 targets 调 _send_message，每个 target 独立 try/except。
NotifyResult 聚合规则同 webhook 版本：失败时 message 形如
\"1/3 targets failed: ou_b=...\"。"
```

---

## Task 4: `pipeline_factory` 改用 `effective_*`

**Files:**
- Modify: `app/core/pipeline_factory.py`
- Test: `tests/test_pipeline_factory.py`

### Step 4.1: 扩充测试

- [ ] **Step 4.1.1** 在 `tests/test_pipeline_factory.py` 末尾追加：

```python
from app.notifier.lark_webhook import LarkWebhookNotifier
from app.notifier.lark_image import LarkImageNotifier
from app.storage.config import LarkTargetCfg


def test_ocr_mode_injects_all_effective_webhook_urls(tmp_path: Path):
    cfg = AppConfig(
        mode="ocr",
        notifier=NotifierCfg(
            lark_webhook_urls=["https://a", "https://b", "https://c"],
        ),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert isinstance(pipe.notifier, LarkWebhookNotifier)
    assert pipe.notifier.webhook_urls == ["https://a", "https://b", "https://c"]


def test_ocr_mode_falls_back_to_single_webhook_url(tmp_path: Path):
    """list 为空、单字段非空：注入 1 元素 list。"""
    cfg = AppConfig(
        mode="ocr",
        notifier=NotifierCfg(lark_webhook_url="https://legacy"),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert pipe.notifier.webhook_urls == ["https://legacy"]


def test_image_diff_mode_injects_all_effective_targets(tmp_path: Path):
    _purge_paddle_modules()
    cfg = AppConfig(
        mode="image_diff",
        notifier=NotifierCfg(
            lark_app_id="cli_x",
            lark_app_secret="sec_x",
            lark_targets=[
                LarkTargetCfg(receive_id="oc_a", receive_id_type="chat_id"),
                LarkTargetCfg(receive_id="ou_b", receive_id_type="open_id"),
            ],
        ),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert isinstance(pipe.notifier, LarkImageNotifier)
    assert [(t.receive_id, t.receive_id_type) for t in pipe.notifier.targets] == [
        ("oc_a", "chat_id"),
        ("ou_b", "open_id"),
    ]


def test_image_diff_mode_falls_back_to_single_receive_id(tmp_path: Path):
    _purge_paddle_modules()
    cfg = AppConfig(
        mode="image_diff",
        notifier=NotifierCfg(
            lark_app_id="cli_x",
            lark_app_secret="sec_x",
            lark_receive_id="oc_legacy",
            lark_receive_id_type="chat_id",
        ),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert len(pipe.notifier.targets) == 1
    assert pipe.notifier.targets[0].receive_id == "oc_legacy"


def test_image_diff_mode_raises_when_no_effective_targets(tmp_path: Path):
    """有 app_id/app_secret 但 list 和单字段都空 → 报错。"""
    _purge_paddle_modules()
    cfg = AppConfig(
        mode="image_diff",
        notifier=NotifierCfg(lark_app_id="cli_x", lark_app_secret="sec_x"),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    try:
        build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    except ValueError as e:
        assert "target" in str(e).lower() or "receive_id" in str(e).lower()
        return
    raise AssertionError("expected ValueError for no effective targets")
```

- [ ] **Step 4.1.2** 同时**修订**已有的 `test_image_diff_mode_raises_on_missing_credentials`：把断言文本兼容新的报错文案（接受 `lark_app_id` 或 `target` 字样）：

```python
def test_image_diff_mode_raises_on_missing_credentials(tmp_path: Path):
    cfg = AppConfig(mode="image_diff", notifier=NotifierCfg())
    history = HistoryStore(tmp_path / "h.ndjson")
    try:
        build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    except ValueError as e:
        msg = str(e).lower()
        assert "lark_app_id" in msg or "credential" in msg or "target" in msg
        return
    raise AssertionError("expected ValueError for missing credentials")
```

- [ ] **Step 4.1.3** 跑测试确认失败

  Run: `.venv/bin/pytest tests/test_pipeline_factory.py -v`

  Expected: 上面新加的 4 个用例 FAIL（属性不存在 / 行为不匹配）。

### Step 4.2: 改 `app/core/pipeline_factory.py`

- [ ] **Step 4.2.1** 整体替换为：

```python
"""按 config.mode 构造对应 pipeline。

抽离这层是为了：
1. 单测可以在没有 Qt 的情况下验证 mode 分发与 import 隔离。
2. image_diff 模式下不通过任何路径 import 到 paddleocr。
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from app.core.image_pipeline import ImagePipeline
from app.core.pipeline import Pipeline
from app.diff.image_detector import ImageDiffDetector
from app.notifier.lark_image import LarkImageNotifier
from app.notifier.lark_webhook import LarkWebhookNotifier
from app.ocr.engine import PaddleOcrEngine
from app.storage.config import AppConfig
from app.storage.history import HistoryStore

PipelineLike = Union[Pipeline, ImagePipeline]


def build_pipeline(
    config: AppConfig,
    history: HistoryStore,
    frames_dir: Path,
) -> PipelineLike:
    if config.mode == "image_diff":
        nc = config.notifier
        targets = nc.effective_targets()
        if not (nc.lark_app_id and nc.lark_app_secret and targets):
            raise ValueError(
                "image_diff mode requires notifier.lark_app_id / lark_app_secret "
                "and at least one target (lark_targets or lark_receive_id)"
            )
        ic = config.image_diff
        detector = ImageDiffDetector(
            pixel_diff_threshold=ic.pixel_diff_threshold,
            change_ratio_threshold=ic.change_ratio_threshold,
            min_interval_seconds=ic.min_interval_seconds,
            bbox_padding=ic.bbox_padding,
        )
        notifier = LarkImageNotifier(
            app_id=nc.lark_app_id,
            app_secret=nc.lark_app_secret,
            targets=targets,
        )
        return ImagePipeline(
            detector=detector,
            notifier=notifier,
            history=history,
            frames_dir=frames_dir,
        )

    # ocr mode
    ocr = PaddleOcrEngine(lang=config.ocr.lang)
    notifier = LarkWebhookNotifier(config.notifier.effective_webhook_urls())
    return Pipeline(ocr=ocr, notifier=notifier, history=history, config=config)
```

- [ ] **Step 4.2.2** 跑测试

  Run: `.venv/bin/pytest tests/test_pipeline_factory.py -v`

  Expected: 全部 PASS。

### Step 4.3: Commit

- [ ] **Step 4.3.1**

```bash
git add app/core/pipeline_factory.py tests/test_pipeline_factory.py
git commit -m "feat(core): pipeline_factory 改用 effective_webhook_urls / effective_targets

调用 NotifierCfg 的 helper 把单字段 + list 合并后注入 notifier，
image_diff 模式 credentials check 同步用 effective_targets 判定。"
```

---

## Task 5: `tools/replay_runner.py` + `tests/test_pipeline_replay.py` 跟随签名变更

这两个文件直接构造 `LarkWebhookNotifier`，必须更新成 list 签名才能让全量测试继续通过。

**Files:**
- Modify: `tools/replay_runner.py`
- Modify: `tests/test_pipeline_replay.py`

### Step 5.1: 修 `tools/replay_runner.py`

- [ ] **Step 5.1.1** 把 `app/notifier/lark_webhook.py` 那行实例化改成 list：

```python
# 原代码：
#         notifier=LarkWebhookNotifier(args.webhook),
# 改为：
        notifier=LarkWebhookNotifier([args.webhook]),
```

精确替换 `tools/replay_runner.py` 第 57 行附近：

旧：
```python
        notifier=LarkWebhookNotifier(args.webhook),
```

新：
```python
        notifier=LarkWebhookNotifier([args.webhook]),
```

### Step 5.2: 修 `tests/test_pipeline_replay.py`

- [ ] **Step 5.2.1** `_RecordingNotifier.__init__` 改成 list 签名：

旧：
```python
class _RecordingNotifier(LarkWebhookNotifier):
    def __init__(self):
        super().__init__(webhook_url="https://example.invalid/dummy")
        self.sent_payloads: list[str] = []
```

新：
```python
class _RecordingNotifier(LarkWebhookNotifier):
    def __init__(self):
        super().__init__(webhook_urls=["https://example.invalid/dummy"])
        self.sent_payloads: list[str] = []
```

- [ ] **Step 5.2.2** 跑全量 notifier 相关测试 + replay 测试

  Run: `.venv/bin/pytest tests/test_notifier.py tests/test_lark_image.py tests/test_pipeline_factory.py tests/test_pipeline_replay.py -v`

  Expected: 全部 PASS。

### Step 5.3: Commit

- [ ] **Step 5.3.1**

```bash
git add tools/replay_runner.py tests/test_pipeline_replay.py
git commit -m "chore: replay_runner 与 pipeline_replay 测试跟随 LarkWebhookNotifier 签名

单 URL 改为单元素 list 传入。"
```

---

## Task 6: `settings_window` UI 多行 webhook URLs

**Files:**
- Modify: `app/ui/settings_window.py`
- Test: `tests/test_settings_window.py` (新建)

> UI 整体跑测要起 QApplication，但我们只测纯函数解析/格式化。把按行解析逻辑抽成模块顶层函数，方便头测试。

### Step 6.1: 抽离 parse/format helper + 写测试

- [ ] **Step 6.1.1** 新建 `tests/test_settings_window.py`：

```python
"""settings_window 纯函数 helper 单测：URL 多行文本解析 / 渲染。"""
from app.ui.settings_window import (
    format_webhook_urls_for_textarea,
    parse_webhook_urls_from_textarea,
)


def test_parse_empty_returns_empty_list():
    assert parse_webhook_urls_from_textarea("") == []
    assert parse_webhook_urls_from_textarea("   \n  \n") == []


def test_parse_strips_whitespace_and_drops_blank_lines():
    text = "  https://a  \n\nhttps://b\n   \nhttps://c\n"
    assert parse_webhook_urls_from_textarea(text) == [
        "https://a",
        "https://b",
        "https://c",
    ]


def test_parse_dedupes_preserving_order():
    text = "https://a\nhttps://b\nhttps://a\n"
    assert parse_webhook_urls_from_textarea(text) == ["https://a", "https://b"]


def test_format_empty_list_returns_empty_string():
    assert format_webhook_urls_for_textarea([], "") == ""


def test_format_merges_list_and_legacy_single_field():
    """加载时 list + 单字段（若不在 list 里）合并展示。"""
    out = format_webhook_urls_for_textarea(
        webhook_urls=["https://a", "https://b"],
        webhook_url_legacy="https://legacy",
    )
    assert out == "https://a\nhttps://b\nhttps://legacy"


def test_format_skips_legacy_when_already_in_list():
    out = format_webhook_urls_for_textarea(
        webhook_urls=["https://a"],
        webhook_url_legacy="https://a",
    )
    assert out == "https://a"


def test_format_legacy_only():
    out = format_webhook_urls_for_textarea(
        webhook_urls=[],
        webhook_url_legacy="https://legacy",
    )
    assert out == "https://legacy"
```

- [ ] **Step 6.1.2** 跑测试确认失败

  Run: `.venv/bin/pytest tests/test_settings_window.py -v`

  Expected: `ImportError: cannot import name 'parse_webhook_urls_from_textarea'`。

### Step 6.2: 修 `app/ui/settings_window.py`

- [ ] **Step 6.2.1** 整体替换为：

```python
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
```

- [ ] **Step 6.2.2** 跑测试

  Run: `.venv/bin/pytest tests/test_settings_window.py -v`

  Expected: 全部 PASS。

### Step 6.3: Commit

- [ ] **Step 6.3.1**

```bash
git add app/ui/settings_window.py tests/test_settings_window.py
git commit -m "feat(ui): 设置窗口飞书 tab 支持多行 webhook URLs

QLineEdit → QPlainTextEdit，每行一个 URL；加载时合并 list 字段
和旧 lark_webhook_url；保存时按行 split/strip/dedupe 写入
lark_webhook_urls，旧字段清空。测试按钮聚合显示 N/N 成功 或
失败明细。抽出 parse_webhook_urls_from_textarea /
format_webhook_urls_for_textarea 两个纯函数 helper 便于单测。"
```

---

## Task 7: 全量验证 + README + 收尾

### Step 7.1: 跑全量测试

- [ ] **Step 7.1.1**

  Run: `.venv/bin/pytest`

  Expected: 全部 PASS（原 61 + 新增）。

### Step 7.2: README 多群配置段落

- [ ] **Step 7.2.1** 修改 `README.md`，在「关键参数 (config.yaml)」上方插入新章节：

定位 README 中现有这一行：

```
## 关键参数（`config.yaml`）
```

在它**之前**插入：

```markdown
## 多群通知

两种模式都支持把同一帧推送到多个飞书目标，部分失败不阻断其他目标，错误打日志。

### OCR 模式（多 webhook）

```yaml
notifier:
  lark_webhook_urls:
    - https://open.feishu.cn/open-apis/bot/v2/hook/aaa
    - https://open.feishu.cn/open-apis/bot/v2/hook/bbb
```

也可直接在 GUI 设置 → 飞书 tab 里每行一个 URL，「发送测试消息」会对所有 URL 都发一次并显示聚合结果。

### image_diff 模式（多 receive_id）

同一个自建应用 `lark_app_id` / `lark_app_secret` 可对接多个 `receive_id`（不同 `receive_id_type` 可混用，应用需要分别拉进对应群/加好友）：

```yaml
mode: image_diff
notifier:
  lark_app_id: cli_xxxx
  lark_app_secret: xxxx
  lark_targets:
    - {receive_id: oc_chat_xxx, receive_id_type: chat_id}
    - {receive_id: ou_open_yyy, receive_id_type: open_id}
    - {receive_id: user@example.com, receive_id_type: email}
```

`image_diff` 模式下 1 帧只上传 1 次图，复用同一个 `image_key` 发送给所有 target，节省 OpenAPI 调用。

### 向后兼容

v0.1.0 的旧字段 `lark_webhook_url` / `lark_receive_id` 仍然可读，会被当作单元素 list 处理。GUI 首次打开时会把旧字段合并到多行文本框，保存后写入新字段并清空旧字段。
```

- [ ] **Step 7.2.2** Commit

```bash
git add README.md
git commit -m "docs: README 加多群通知配置段落"
```

### Step 7.3: 手动 smoke（仅描述，不强制执行）

- [ ] **Step 7.3.1** 在有 GUI 的环境验证（可选，跑不了的话至少在 PR description 里写明）：

  1. `.venv/bin/python -m app` 启动
  2. 托盘 → 设置 → 飞书 tab，填两个测试 webhook URL（每行一个）
  3. 点「发送测试消息」，应在 2 个群都看到测试消息，状态行显示 `✓ 2/2 全部成功`
  4. 把其中一个 URL 改成 `https://example.invalid/x`，再点测试，状态行显示 `✗ 1/2 targets failed: hook[..x]=...`
  5. 关掉设置窗口、再打开，文本框应回显 2 个 URL；查看 `~/.config/screen-ocr-watchdog/config.yaml`，应能看到 `lark_webhook_urls` 列表

### Step 7.4: 推 PR

- [ ] **Step 7.4.1**

```bash
git push -u origin feat/multi-target-notify
gh pr create --base main --head feat/multi-target-notify \
  --title "feat: 多群通知支持（webhook 多 URL + image_diff 多 receive_id）" \
  --body "$(cat <<'EOF'
## Summary

- `NotifierCfg` 加 `lark_webhook_urls` / `lark_targets` list 字段 + `effective_*` helper，向后兼容 v0.1.0 单字段
- `LarkWebhookNotifier` 构造器签名改为 `webhook_urls: Sequence[str]`，遍历发送、聚合 `NotifyResult`，部分失败 best-effort
- `LarkImageNotifier` 构造器签名改为 `targets: Sequence[LarkTargetCfg]`，1 帧只上传 1 次图、扇出 N 次 `send_message`
- 设置窗口飞书 tab 单行 → 多行 `QPlainTextEdit`，「发送测试消息」聚合显示结果
- README 加多群配置示例
- 详细设计：`docs/superpowers/specs/2026-05-23-multi-target-notify-design.md`

## Test Plan

- [x] `pytest` 全量通过（含新增 storage / notifier / lark_image / pipeline_factory / settings_window 多群用例）
- [ ] Linux GUI 手动验证：2 URL 全成功 / 1 URL 故意填错 → 状态行显示 1/2 失败
- [ ] CI Windows 构建产物存在

## Release

合并后打 `v0.2.0` tag，触发 Windows CI 自动生成 release。
EOF
)"
```

---

## Self-Review 结果

**1. Spec 覆盖：**
- 配置 schema（list 字段 + helper）→ Task 1 ✓
- LarkWebhookNotifier 多 URL → Task 2 ✓
- LarkImageNotifier 多 target + upload 复用 → Task 3 ✓
- pipeline_factory 调用 effective_* → Task 4 ✓
- UI 多行 webhook → Task 6 ✓
- 向后兼容（旧 yaml + UI 自动迁移）→ Task 1 + Task 6 ✓
- 测试覆盖 → 每个 Task 内含 TDD ✓
- README → Task 7 ✓
- 调用点跟随签名变更（replay_runner + test_pipeline_replay）→ Task 5 ✓

**2. Placeholder 扫描：** 无 TBD / TODO；所有步骤都给了完整代码或精确编辑指令。

**3. 类型/签名一致性：**
- `LarkTargetCfg` 在 Task 1 定义、Task 3/4/6 引用 ✓
- `webhook_urls` 属性名跨 Task 2/4/6 一致 ✓
- `targets` 属性名跨 Task 3/4 一致 ✓
- `effective_webhook_urls` / `effective_targets` 方法名跨 Task 1/4 一致 ✓
- `parse_webhook_urls_from_textarea` / `format_webhook_urls_for_textarea` 跨 Task 6 一致 ✓
