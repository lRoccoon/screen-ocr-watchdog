# Image-diff 模式实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 加一个与 OCR 互斥的 `image_diff` 模式：纯截图 → 画面 diff → 把变化区域裁切后作为 image 消息推送到飞书（自建应用通道）。

**Architecture:** `config.mode = ocr | image_diff` 单选。OCR 模式走老链路完全不变；image_diff 模式走全新独立链路（ImageDiffDetector + LarkImageNotifier + ImagePipeline），不 import paddleocr，与 OCR 模式零代码耦合。一个 `pipeline_factory` 按 mode 拼装具体 pipeline，AppController 不感知差异。

**Tech Stack:** Python 3.11 / Pydantic v2 / Pillow（PIL）做 grayscale + ImageChops.difference + getbbox + histogram，无需 numpy/opencv / requests / pytest + unittest.mock。

**Spec:** `docs/superpowers/specs/2026-05-19-image-diff-mode-design.md`

**项目惯例（实现前必读）：**
- 测试扁平在 `tests/` 下，不嵌子目录
- HTTP 测试用 `unittest.mock.patch("module.dotted.requests.post")`，参考 `tests/test_notifier.py`
- pytest 配置在 `pyproject.toml`：`testpaths = ["tests"]`，`addopts = "-q"`
- 跑测试：`.venv/bin/pytest -q`（项目根目录）
- pydantic v2：用 `model_validate`、`model_dump`，字段加 `Field(default_factory=...)`

---

## Task 1: 扩展 config schema（mode + image_diff + notifier 凭证）

**Files:**
- Modify: `app/storage/config.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: 写失败测试 — 默认 mode、image_diff 默认值、notifier 新字段**

在 `tests/test_storage.py` 文件末尾追加：

```python
def test_config_default_mode_is_ocr():
    """旧 config 文件不带 mode 字段时，默认走 ocr 模式（向后兼容）。"""
    cfg = AppConfig()
    assert cfg.mode == "ocr"


def test_config_image_diff_defaults():
    cfg = AppConfig()
    assert cfg.image_diff.pixel_diff_threshold == 30
    assert cfg.image_diff.change_ratio_threshold == 0.005
    assert cfg.image_diff.min_interval_seconds == 5
    assert cfg.image_diff.bbox_padding == 8


def test_config_notifier_lark_app_defaults():
    cfg = AppConfig()
    assert cfg.notifier.lark_app_id == ""
    assert cfg.notifier.lark_app_secret == ""
    assert cfg.notifier.lark_receive_id == ""
    assert cfg.notifier.lark_receive_id_type == "chat_id"


def test_config_load_image_diff_yaml(tmp_path):
    """加载手写的 image_diff 配置 YAML。"""
    p = tmp_path / "c.yaml"
    p.write_text(
        "mode: image_diff\n"
        "image_diff:\n"
        "  pixel_diff_threshold: 50\n"
        "  change_ratio_threshold: 0.01\n"
        "notifier:\n"
        "  lark_app_id: cli_xxx\n"
        "  lark_app_secret: sec_xxx\n"
        "  lark_receive_id: oc_abc\n"
        "  lark_receive_id_type: chat_id\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.mode == "image_diff"
    assert cfg.image_diff.pixel_diff_threshold == 50
    assert cfg.image_diff.change_ratio_threshold == 0.01
    # 没写的字段保留默认
    assert cfg.image_diff.min_interval_seconds == 5
    assert cfg.notifier.lark_app_id == "cli_xxx"
    assert cfg.notifier.lark_receive_id_type == "chat_id"
```

- [ ] **Step 2: 跑测试验证失败**

```bash
.venv/bin/pytest tests/test_storage.py -v
```

期望：4 个新 test 全部 FAIL，错误是 `AttributeError: 'AppConfig' object has no attribute 'mode'` 或 `'image_diff'`。

- [ ] **Step 3: 修改 `app/storage/config.py`**

把整个文件替换为：

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


class NotifierCfg(BaseModel):
    lark_webhook_url: str = ""
    attach_screenshot: bool = False
    # image_diff 模式专用：自建应用凭证
    lark_app_id: str = ""
    lark_app_secret: str = ""
    lark_receive_id: str = ""
    lark_receive_id_type: Literal["chat_id", "open_id", "user_id", "union_id", "email"] = "chat_id"


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

- [ ] **Step 4: 跑测试验证全绿（包括旧测试）**

```bash
.venv/bin/pytest tests/test_storage.py -v
```

期望：4 个新 test PASS，5 个旧 test 也全部 PASS（向后兼容）。

- [ ] **Step 5: 跑全套回归确认没破其他模块**

```bash
.venv/bin/pytest -q
```

期望：41 passed（原 37 + 新 4）。

- [ ] **Step 6: Commit**

```bash
git add app/storage/config.py tests/test_storage.py
git commit -m "feat(config): 加 mode/image_diff/notifier 凭证字段，向后兼容默认 ocr"
```

---

## Task 2: ImageDiffDetector — 状态机式画面 diff

**Files:**
- Create: `app/diff/image_detector.py`
- Create: `tests/test_image_detector.py`

算法：grayscale → ImageChops.difference → point() 二值化 → histogram 统计变化像素占比 → 过阈则 getbbox + padding + crop，并把基线推进为当前帧。节流：距上次推送 < `min_interval_seconds` 则不推、且**不**推进基线，等下一帧再判。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_image_detector.py`：

```python
"""ImageDiffDetector 单测：用 PIL 构造合成图，覆盖各分支。"""
from __future__ import annotations

from PIL import Image, ImageDraw

from app.diff.image_detector import ImageDiffDetector


W, H = 200, 100


def _solid(color=(255, 255, 255)) -> Image.Image:
    return Image.new("RGB", (W, H), color)


def _with_rect(color=(255, 255, 255), rect=(10, 10, 40, 40), fill=(0, 0, 0)) -> Image.Image:
    img = _solid(color)
    ImageDraw.Draw(img).rectangle(rect, fill=fill)
    return img


def test_first_frame_sets_baseline_returns_none():
    d = ImageDiffDetector()
    assert d.detect(_solid(), now=0.0) is None


def test_identical_frame_not_triggered():
    d = ImageDiffDetector()
    d.detect(_solid(), now=0.0)
    assert d.detect(_solid(), now=10.0) is None


def test_tiny_change_below_ratio_not_triggered():
    """单个像素改变远低于 0.5% 占比阈值。"""
    d = ImageDiffDetector(change_ratio_threshold=0.005)
    d.detect(_solid(), now=0.0)
    img = _solid()
    img.putpixel((0, 0), (0, 0, 0))  # 1 / 20000 = 0.005% < 0.5%
    assert d.detect(img, now=10.0) is None


def test_large_change_triggered_and_baseline_advances():
    d = ImageDiffDetector(pixel_diff_threshold=30, change_ratio_threshold=0.005, bbox_padding=0)
    d.detect(_solid(), now=0.0)
    result = d.detect(_with_rect(), now=10.0)
    assert result is not None
    bbox, crop = result
    # bbox 应覆盖刚画的矩形 (10,10,40,40)
    assert bbox[0] <= 10 and bbox[1] <= 10
    assert bbox[2] >= 40 and bbox[3] >= 40
    assert crop.size == (bbox[2] - bbox[0], bbox[3] - bbox[1])

    # 立刻再传同样的新图，基线已推进，diff=0 → 不触发
    assert d.detect(_with_rect(), now=20.0) is None


def test_bbox_padding_expands_and_clamps_to_bounds():
    d = ImageDiffDetector(pixel_diff_threshold=30, change_ratio_threshold=0.001, bbox_padding=8)
    d.detect(_solid(), now=0.0)
    # 在画面正中央画一个小变化
    result = d.detect(_with_rect(rect=(95, 45, 105, 55)), now=10.0)
    assert result is not None
    bbox, _ = result
    # padding 让 bbox 向外扩 8px
    assert bbox[0] <= 95 - 8 + 1  # 允许 ±1 容差（getbbox 边界包含语义）
    assert bbox[2] >= 105 + 8 - 1

    # 在角落画变化，padding 不能越界
    d2 = ImageDiffDetector(pixel_diff_threshold=30, change_ratio_threshold=0.001, bbox_padding=8)
    d2.detect(_solid(), now=0.0)
    result2 = d2.detect(_with_rect(rect=(0, 0, 5, 5)), now=10.0)
    assert result2 is not None
    bbox2, _ = result2
    assert bbox2[0] == 0
    assert bbox2[1] == 0


def test_min_interval_throttles_and_keeps_baseline():
    """节流期内即使 diff 超阈也不推，且基线不推进——等下一帧再评估。"""
    d = ImageDiffDetector(min_interval_seconds=5.0, pixel_diff_threshold=30, change_ratio_threshold=0.001)
    # 首帧建立基线
    d.detect(_solid(), now=0.0)
    # 第二帧触发，推送时刻 t=10
    assert d.detect(_with_rect(), now=10.0) is not None
    # 第三帧 t=11，距上次 < 5s 节流 → 返回 None，基线"应当"仍是上一次推送过的画面
    assert d.detect(_with_rect(rect=(100, 50, 150, 80)), now=11.0) is None
    # 第四帧 t=20，节流过期；diff 是相对于"上次推送过的画面"（含第一个 rect）
    # 第三帧的新 rect 在第四帧也存在 → diff 超阈 → 推送
    assert d.detect(_with_rect(rect=(100, 50, 150, 80)), now=20.0) is not None
```

- [ ] **Step 2: 跑测试验证失败**

```bash
.venv/bin/pytest tests/test_image_detector.py -v
```

期望：所有 test FAIL，错误 `ModuleNotFoundError: No module named 'app.diff.image_detector'`。

- [ ] **Step 3: 写实现**

`app/diff/` 目录已存在（有 `__init__.py` 和 `detector.py`）。创建 `app/diff/image_detector.py`：

```python
"""画面像素 diff 检测器：状态机持有"上次推送过的画面"作为基线。

每帧：grayscale → 与基线像素差二值化（阈值）→ histogram 统计变化占比。
超阈则 getbbox + padding + crop，并把基线推进为当前帧；不超阈或被节流则返回 None。
"""
from __future__ import annotations

import time
from typing import Optional, Tuple

from PIL import Image, ImageChops, ImageOps

Bbox = Tuple[int, int, int, int]


class ImageDiffDetector:
    def __init__(
        self,
        pixel_diff_threshold: int = 30,
        change_ratio_threshold: float = 0.005,
        min_interval_seconds: float = 5.0,
        bbox_padding: int = 8,
    ) -> None:
        self.pixel_diff_threshold = pixel_diff_threshold
        self.change_ratio_threshold = change_ratio_threshold
        self.min_interval_seconds = min_interval_seconds
        self.bbox_padding = bbox_padding
        self._baseline: Optional[Image.Image] = None
        self._last_pushed_ts: float = float("-inf")

    def detect(
        self,
        frame: Image.Image,
        now: Optional[float] = None,
    ) -> Optional[Tuple[Bbox, Image.Image]]:
        cur = now if now is not None else time.monotonic()

        if self._baseline is None:
            self._baseline = frame.copy()
            return None

        gray_base = ImageOps.grayscale(self._baseline)
        gray_cur = ImageOps.grayscale(frame)
        diff = ImageChops.difference(gray_base, gray_cur)
        thr = self.pixel_diff_threshold
        mask = diff.point(lambda p: 255 if p >= thr else 0)

        bbox = mask.getbbox()
        if bbox is None:
            return None

        hist = mask.histogram()
        changed = sum(hist[1:])  # bin 0 = 未变；其他全是 255
        total = mask.width * mask.height
        if total == 0 or (changed / total) < self.change_ratio_threshold:
            return None

        # 节流：距上次推送不足 min_interval，不推、不推进基线
        if cur - self._last_pushed_ts < self.min_interval_seconds:
            return None

        x0, y0, x1, y1 = bbox
        pad = self.bbox_padding
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(frame.width, x1 + pad)
        y1 = min(frame.height, y1 + pad)
        crop = frame.crop((x0, y0, x1, y1))

        self._baseline = frame.copy()
        self._last_pushed_ts = cur
        return (x0, y0, x1, y1), crop
```

- [ ] **Step 4: 跑测试验证全绿**

```bash
.venv/bin/pytest tests/test_image_detector.py -v
```

期望：7 个 test 全部 PASS。

- [ ] **Step 5: 跑全套回归**

```bash
.venv/bin/pytest -q
```

期望：48 passed。

- [ ] **Step 6: Commit**

```bash
git add app/diff/image_detector.py tests/test_image_detector.py
git commit -m "feat(diff): ImageDiffDetector 像素 diff + bbox 裁切 + 节流"
```

---

## Task 3: LarkImageNotifier — 自建应用 token + 上传图 + 发 image 消息

**Files:**
- Create: `app/notifier/lark_image.py`
- Create: `tests/test_lark_image.py`

飞书 OpenAPI：
- token: `POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal` body `{"app_id":..., "app_secret":...}` → `{"code":0, "tenant_access_token":"t-...", "expire":7200}`
- 上传: `POST https://open.feishu.cn/open-apis/im/v1/images` 带 Authorization header，`multipart/form-data` 字段 `image_type=message` + `image=<file>` → `{"code":0, "data":{"image_key":"img_v3_..."}}`
- 发消息: `POST https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id` body `{"receive_id":"...", "msg_type":"image", "content":"{\"image_key\":\"img_v3_...\"}"}`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_lark_image.py`：

```python
"""LarkImageNotifier 单测：mock requests.post，验证三段流程参数 + token 缓存。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from PIL import Image

from app.notifier.lark_image import LarkImageNotifier


def _make_notifier() -> LarkImageNotifier:
    return LarkImageNotifier(
        app_id="cli_xxx",
        app_secret="sec_xxx",
        receive_id="oc_abc",
        receive_id_type="chat_id",
    )


def _mock_resp(json_data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    return resp


def _png() -> Image.Image:
    return Image.new("RGB", (10, 10), (255, 0, 0))


def _fake_post_factory():
    """返回一个 side_effect 函数：按 URL 返回不同响应。"""
    def side_effect(url, **kwargs):
        if "tenant_access_token" in url:
            return _mock_resp({"code": 0, "tenant_access_token": "t-abc", "expire": 7200})
        if "im/v1/images" in url:
            return _mock_resp({"code": 0, "data": {"image_key": "img_v3_xxx"}})
        if "im/v1/messages" in url:
            return _mock_resp({"code": 0, "data": {"message_id": "om_msg_1"}})
        raise AssertionError(f"unexpected URL: {url}")
    return side_effect


def test_send_image_happy_path():
    n = _make_notifier()
    with patch("app.notifier.lark_image.requests.post", side_effect=_fake_post_factory()) as post:
        r = n.send_image(_png())
    assert r.ok is True
    calls = [c.args[0] for c in post.call_args_list]
    assert any("tenant_access_token" in u for u in calls)
    assert any("im/v1/images" in u for u in calls)
    assert any("im/v1/messages?receive_id_type=chat_id" in u for u in calls)

    # 验证发消息 body
    msg_call = next(c for c in post.call_args_list if "im/v1/messages" in c.args[0])
    body = msg_call.kwargs["json"]
    assert body["receive_id"] == "oc_abc"
    assert body["msg_type"] == "image"
    content = json.loads(body["content"])
    assert content["image_key"] == "img_v3_xxx"


def test_token_cached_second_call_skips_token_endpoint():
    n = _make_notifier()
    with patch("app.notifier.lark_image.requests.post", side_effect=_fake_post_factory()) as post:
        n.send_image(_png())
        n.send_image(_png())
    token_calls = [c for c in post.call_args_list if "tenant_access_token" in c.args[0]]
    assert len(token_calls) == 1, f"token endpoint should be called once, got {len(token_calls)}"


def test_expired_token_triggers_refresh():
    """手动把 _token_expires_at 设到过去，下次 send_image 应触发 token 重新拉取。

    避免 patch time.monotonic 污染全局；直接操控状态字段更稳。
    """
    n = _make_notifier()
    fake_post = MagicMock(side_effect=_fake_post_factory())
    with patch("app.notifier.lark_image.requests.post", fake_post):
        n.send_image(_png())
        n._token_expires_at = float("-inf")  # 强制过期
        n.send_image(_png())
    token_calls = [c for c in fake_post.call_args_list if "tenant_access_token" in c.args[0]]
    assert len(token_calls) == 2, "expired token should be refreshed"


def test_token_endpoint_business_error():
    n = _make_notifier()
    def s(url, **kwargs):
        return _mock_resp({"code": 99991663, "msg": "invalid app_id"})
    with patch("app.notifier.lark_image.requests.post", side_effect=s):
        r = n.send_image(_png())
    assert r.ok is False
    assert "99991663" in r.message or "invalid app_id" in r.message


def test_upload_business_error():
    n = _make_notifier()
    def s(url, **kwargs):
        if "tenant_access_token" in url:
            return _mock_resp({"code": 0, "tenant_access_token": "t-x", "expire": 7200})
        return _mock_resp({"code": 230002, "msg": "image too large"})
    with patch("app.notifier.lark_image.requests.post", side_effect=s):
        r = n.send_image(_png())
    assert r.ok is False
    assert "230002" in r.message or "image too large" in r.message


def test_network_exception_returns_failure():
    n = _make_notifier()
    with patch("app.notifier.lark_image.requests.post", side_effect=Exception("boom")):
        r = n.send_image(_png())
    assert r.ok is False
    assert "boom" in r.message


def test_missing_credentials_short_circuits():
    n = LarkImageNotifier(app_id="", app_secret="", receive_id="oc_abc", receive_id_type="chat_id")
    with patch("app.notifier.lark_image.requests.post") as post:
        r = n.send_image(_png())
    assert r.ok is False
    assert "credential" in r.message.lower() or "app_id" in r.message.lower()
    post.assert_not_called()
```

- [ ] **Step 2: 跑测试验证失败**

```bash
.venv/bin/pytest tests/test_lark_image.py -v
```

期望：所有 test FAIL，错误 `ModuleNotFoundError: No module named 'app.notifier.lark_image'`。

- [ ] **Step 3: 写实现**

创建 `app/notifier/lark_image.py`：

```python
"""飞书自建应用图片消息发送：tenant_access_token 缓存 + 上传图 + 发 image 消息。

只用于 mode=image_diff。与 LarkWebhookNotifier 平级、不共享代码。
"""
from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import dataclass
from threading import Lock

import requests
from PIL import Image

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
        receive_id: str,
        receive_id_type: str = "chat_id",
        timeout: float = 10.0,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type
        self.timeout = timeout
        self._token: str = ""
        self._token_expires_at: float = float("-inf")
        self._token_lock = Lock()

    def _credentials_ok(self) -> bool:
        return bool(self.app_id and self.app_secret and self.receive_id)

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

    def _send_message(self, token: str, image_key: str) -> None:
        resp = requests.post(
            f"{MESSAGE_URL}?receive_id_type={self.receive_id_type}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "receive_id": self.receive_id,
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
            log.error("lark image send skipped: missing app_id/app_secret/receive_id")
            return NotifyResult(ok=False, message="missing credentials (app_id/app_secret/receive_id)")
        try:
            token = self._get_token()
            image_key = self._upload_image(token, image)
            self._send_message(token, image_key)
            return NotifyResult(ok=True, message="ok")
        except Exception as e:
            log.error(
                "lark image notify failed: %s | receive_id=%s receive_id_type=%s",
                e, self.receive_id, self.receive_id_type,
            )
            return NotifyResult(ok=False, message=str(e))
```

- [ ] **Step 4: 跑测试验证全绿**

```bash
.venv/bin/pytest tests/test_lark_image.py -v
```

期望：7 个 test 全部 PASS。

- [ ] **Step 5: 跑全套回归**

```bash
.venv/bin/pytest -q
```

期望：55 passed。

- [ ] **Step 6: Commit**

```bash
git add app/notifier/lark_image.py tests/test_lark_image.py
git commit -m "feat(notifier): LarkImageNotifier 自建应用 token 缓存 + 上传图 + 发 image 消息"
```

---

## Task 4: ImagePipeline — 串 detector → notifier → 写盘 + history

**Files:**
- Create: `app/core/image_pipeline.py`
- Create: `tests/test_image_pipeline.py`

ImagePipeline.process_image(image) 与 OCR 的 Pipeline.process_image(image) 同名，鸭子类型让 WatchdogRunner 无差别调用。返回的 `ImageFrameResult.new_messages` 保留为空 list（让 AppController._on_frame_done 的 `if fr.new_messages` 自然走 false 分支）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_image_pipeline.py`：

```python
"""ImagePipeline 单测：detector + notifier 全部用 stub，验证编排行为。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from app.core.image_pipeline import ImagePipeline, ImageFrameResult
from app.notifier.lark_image import NotifyResult
from app.storage.history import HistoryStore


def _img(size=(20, 20), color=(255, 255, 255)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_no_diff_returns_empty_result_no_calls(tmp_path: Path):
    detector = MagicMock()
    detector.detect.return_value = None
    notifier = MagicMock()
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = ImagePipeline(detector=detector, notifier=notifier, history=history, frames_dir=tmp_path / "frames")

    result = pipe.process_image(_img())

    assert isinstance(result, ImageFrameResult)
    assert result.new_messages == []
    assert result.diff_bbox is None
    notifier.send_image.assert_not_called()
    assert list((tmp_path / "frames").glob("*.png")) == []
    assert not (tmp_path / "h.ndjson").exists() or (tmp_path / "h.ndjson").read_text() == ""


def test_diff_triggers_save_notify_history(tmp_path: Path):
    crop = _img((10, 10), (0, 0, 0))
    detector = MagicMock()
    detector.detect.return_value = ((5, 5, 15, 15), crop)
    notifier = MagicMock()
    notifier.send_image.return_value = NotifyResult(ok=True, message="ok")
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = ImagePipeline(detector=detector, notifier=notifier, history=history, frames_dir=tmp_path / "frames")

    result = pipe.process_image(_img())

    assert result.diff_bbox == (5, 5, 15, 15)
    assert result.image_path is not None
    assert Path(result.image_path).exists()
    assert Path(result.image_path).parent == tmp_path / "frames"
    notifier.send_image.assert_called_once_with(crop)
    assert result.notify_result is not None and result.notify_result.ok
    # history 写了一条带 bbox 的记录
    h = history.tail(10)
    assert len(h) == 1
    assert "(5, 5, 15, 15)" in h[0]["text"] or "5, 5, 15, 15" in h[0]["text"]


def test_diff_notify_failure_still_writes_history_and_image(tmp_path: Path):
    crop = _img((10, 10), (0, 0, 0))
    detector = MagicMock()
    detector.detect.return_value = ((0, 0, 10, 10), crop)
    notifier = MagicMock()
    notifier.send_image.return_value = NotifyResult(ok=False, message="network err")
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = ImagePipeline(detector=detector, notifier=notifier, history=history, frames_dir=tmp_path / "frames")

    result = pipe.process_image(_img())

    assert result.notify_result is not None and result.notify_result.ok is False
    # 即使发送失败也存图、写历史，便于排查
    assert Path(result.image_path).exists()
    assert len(history.tail(10)) == 1
```

- [ ] **Step 2: 跑测试验证失败**

```bash
.venv/bin/pytest tests/test_image_pipeline.py -v
```

期望：所有 test FAIL，`ModuleNotFoundError: No module named 'app.core.image_pipeline'`。

- [ ] **Step 3: 写实现**

创建 `app/core/image_pipeline.py`：

```python
"""image_diff 模式 pipeline：capture → detector → 写图 + history + notifier。

与 app.core.pipeline.Pipeline 鸭子类型对齐：都暴露 process_image(image)。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

from app.diff.image_detector import ImageDiffDetector
from app.notifier.lark_image import LarkImageNotifier, NotifyResult
from app.storage.history import HistoryStore

log = logging.getLogger(__name__)


@dataclass
class ImageFrameResult:
    # 字段名与 app.core.pipeline.FrameResult 的 new_messages 对齐，
    # 让 AppController._on_frame_done 的 `if fr.new_messages` 检查自然走 false 分支。
    new_messages: list = field(default_factory=list)
    diff_bbox: Optional[Tuple[int, int, int, int]] = None
    image_path: Optional[str] = None
    notify_result: Optional[NotifyResult] = None


class ImagePipeline:
    def __init__(
        self,
        detector: ImageDiffDetector,
        notifier: LarkImageNotifier,
        history: HistoryStore,
        frames_dir: Path,
    ) -> None:
        self.detector = detector
        self.notifier = notifier
        self.history = history
        self.frames_dir = frames_dir
        self.frames_dir.mkdir(parents=True, exist_ok=True)

    def process_image(self, image: Image.Image) -> ImageFrameResult:
        out = self.detector.detect(image)
        if out is None:
            return ImageFrameResult()
        bbox, crop = out

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        image_path = self.frames_dir / f"{ts}.png"
        crop.save(image_path)

        notify_result = self.notifier.send_image(crop)
        if not notify_result.ok:
            log.error(
                "image diff notify failed: msg=%s bbox=%s image=%s",
                notify_result.message, bbox, image_path,
            )

        # 即使发送失败也写历史，便于排查
        self.history.append(fingerprint=f"img_{ts}", text=f"image_diff bbox={bbox}")

        return ImageFrameResult(
            diff_bbox=bbox,
            image_path=str(image_path),
            notify_result=notify_result,
        )
```

- [ ] **Step 4: 跑测试验证全绿**

```bash
.venv/bin/pytest tests/test_image_pipeline.py -v
```

期望：3 个 test 全部 PASS。

- [ ] **Step 5: 跑全套回归**

```bash
.venv/bin/pytest -q
```

期望：58 passed。

- [ ] **Step 6: Commit**

```bash
git add app/core/image_pipeline.py tests/test_image_pipeline.py
git commit -m "feat(core): ImagePipeline 串 detector + notifier + 写图/history"
```

---

## Task 5: pipeline_factory + AppController 用 factory 按 mode 分发

**Files:**
- Create: `app/core/pipeline_factory.py`
- Create: `tests/test_pipeline_factory.py`
- Modify: `app/__main__.py`

把"按 mode 构造 pipeline + notifier + 截屏目标"抽到独立模块，便于不依赖 Qt 单测，同时保证 image_diff 模式下 paddleocr 不会被 import。AppController 只问 factory 要"成品"。

- [ ] **Step 1: 写失败测试 — pipeline_factory 行为 + 不 import paddleocr**

创建 `tests/test_pipeline_factory.py`：

```python
"""pipeline_factory 单测：mode 分发 + 确认 image_diff 不 import paddleocr。"""
from __future__ import annotations

import sys
from pathlib import Path

from app.core.image_pipeline import ImagePipeline
from app.core.pipeline import Pipeline
from app.core.pipeline_factory import build_pipeline
from app.storage.config import AppConfig, ImageDiffCfg, NotifierCfg
from app.storage.history import HistoryStore


def _purge_paddle_modules() -> None:
    for k in [m for m in list(sys.modules) if m.startswith("paddle")]:
        del sys.modules[k]


def test_image_diff_mode_builds_image_pipeline(tmp_path: Path):
    _purge_paddle_modules()
    cfg = AppConfig(
        mode="image_diff",
        image_diff=ImageDiffCfg(),
        notifier=NotifierCfg(
            lark_app_id="cli_x",
            lark_app_secret="sec_x",
            lark_receive_id="oc_x",
        ),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert isinstance(pipe, ImagePipeline)


def test_image_diff_mode_does_not_import_paddleocr(tmp_path: Path):
    _purge_paddle_modules()
    cfg = AppConfig(
        mode="image_diff",
        notifier=NotifierCfg(lark_app_id="x", lark_app_secret="y", lark_receive_id="z"),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    paddle_mods = [m for m in sys.modules if m.startswith("paddle")]
    assert paddle_mods == [], f"image_diff mode should not import paddle*, got {paddle_mods}"


def test_ocr_mode_builds_pipeline(tmp_path: Path):
    cfg = AppConfig(
        mode="ocr",
        notifier=NotifierCfg(lark_webhook_url="https://example.invalid/x"),
    )
    history = HistoryStore(tmp_path / "h.ndjson")
    pipe = build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    assert isinstance(pipe, Pipeline)


def test_image_diff_mode_raises_on_missing_credentials(tmp_path: Path):
    cfg = AppConfig(mode="image_diff", notifier=NotifierCfg())  # 三个字段全空
    history = HistoryStore(tmp_path / "h.ndjson")
    try:
        build_pipeline(cfg, history=history, frames_dir=tmp_path / "frames")
    except ValueError as e:
        assert "lark_app_id" in str(e) or "credential" in str(e).lower()
        return
    raise AssertionError("expected ValueError for missing credentials")
```

- [ ] **Step 2: 跑测试验证失败**

```bash
.venv/bin/pytest tests/test_pipeline_factory.py -v
```

期望：所有 test FAIL，`ModuleNotFoundError: No module named 'app.core.pipeline_factory'`。

- [ ] **Step 3: 写 pipeline_factory 实现**

创建 `app/core/pipeline_factory.py`：

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
        if not (nc.lark_app_id and nc.lark_app_secret and nc.lark_receive_id):
            raise ValueError(
                "image_diff mode requires notifier.lark_app_id / lark_app_secret / lark_receive_id"
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
            receive_id=nc.lark_receive_id,
            receive_id_type=nc.lark_receive_id_type,
        )
        return ImagePipeline(
            detector=detector,
            notifier=notifier,
            history=history,
            frames_dir=frames_dir,
        )

    # ocr mode
    ocr = PaddleOcrEngine(lang=config.ocr.lang)
    notifier = LarkWebhookNotifier(config.notifier.lark_webhook_url)
    return Pipeline(ocr=ocr, notifier=notifier, history=history, config=config)
```

注意 `from app.ocr.engine import PaddleOcrEngine` 这一行只 import 类，不实例化；类构造里也不 import paddleocr（看 `engine.py:21-23` lazy）。所以 image_diff 路径仍然不会触发 paddle import。但 test 仍然要 guard 这个不变量。

- [ ] **Step 4: 跑 factory 测试验证全绿**

```bash
.venv/bin/pytest tests/test_pipeline_factory.py -v
```

期望：4 个 test 全部 PASS。

- [ ] **Step 5: 改 `app/__main__.py` 用 factory**

把当前 `app/__main__.py` 中 `_build_ocr()` 函数和 `restart_runner()` 中 OCR 链路构造删掉，改成调 `build_pipeline()`。

具体 edits（基于当前文件内容）：

**Edit 1** — 顶部 import 加 factory，删 `_build_ocr` 相关的 OCR import 已不必须的部分（保留 `OcrEngine` / `PaddleOcrEngine` 不行，因为 factory 内部用，但 __main__ 不再直接用），删 `Pipeline` 直接 import（factory 返回的是 PipelineLike）：

把现有 import 块：
```python
from app.capture.mss_capturer import MssCapturer
from app.core.pipeline import FrameResult, Pipeline
from app.core.scheduler import WatchdogRunner
from app.notifier.lark_webhook import LarkWebhookNotifier
from app.ocr.engine import OcrEngine, PaddleOcrEngine
from app.ocr.postprocess import OcrBlock
from app.paths import config_path, history_path, log_dir
```

改为：
```python
from app.capture.mss_capturer import MssCapturer
from app.core.pipeline_factory import build_pipeline
from app.core.scheduler import WatchdogRunner
from app.paths import config_path, history_path, log_dir
```

**Edit 2** — 删掉整段 `_build_ocr()` 函数（包含 `_NoopOcr` 那段）。

**Edit 3** — 删掉 `AppController.__init__` 里的 `self.ocr = _build_ocr()` 这一行。

**Edit 4** — `restart_runner` 内部用 factory：

替换原来这段：
```python
r = self.config.region
capturer = MssCapturer(r.x, r.y, r.width, r.height)
notifier = LarkWebhookNotifier(self.config.notifier.lark_webhook_url)
pipeline = Pipeline(ocr=self.ocr, notifier=notifier, history=self.history, config=self.config)
self.runner = WatchdogRunner(
    pipeline=pipeline,
    ...
)
```

为：
```python
r = self.config.region
capturer = MssCapturer(r.x, r.y, r.width, r.height)
from app.paths import user_data_dir_path  # 见 Edit 5
frames_dir = user_data_dir_path() / "diff_frames"
pipeline = build_pipeline(self.config, history=self.history, frames_dir=frames_dir)
self.runner = WatchdogRunner(
    pipeline=pipeline,
    ...
)
```

**Edit 5** — `app/paths.py` 加一个返回 user_data_dir 根目录（不带子文件）的 helper，便于 image_diff frames 落到一致目录。打开 `app/paths.py`，在末尾追加：

```python
def user_data_dir_path() -> Path:
    """user data dir 根（history.ndjson 所在目录），用于派生其他数据子目录如 diff_frames。"""
    from platformdirs import user_data_dir
    return Path(user_data_dir(APP_NAME, APP_AUTHOR))
```

**Edit 6** — `FrameResult` 不再从 `app.core.pipeline` import 到 __main__ 顶层；signal slot `_on_frame_done(self, fr: FrameResult)` 的类型注解改成 `_on_frame_done(self, fr: object)`（OCR 模式给 FrameResult、image_diff 模式给 ImageFrameResult，两者都有 `new_messages` 属性）。同时把方法体里 `m.text for m in fr.new_messages` 保留——OCR 模式 new_messages 是 Message dataclass 有 .text；image_diff 模式 new_messages 是空 list，循环不执行。

具体替换：把这一行
```python
def _on_frame_done(self, fr: FrameResult) -> None:
```
改为
```python
def _on_frame_done(self, fr: object) -> None:
```

- [ ] **Step 6: 跑全套回归验证 __main__ 改动没破东西**

注意：跑 pytest 时 `app/__main__.py` 不会被任何 test 直接 import（只有 conftest 和测试本身导入 app 子模块）；所以改 __main__ 后 pytest 不会触发。但要做一个语法 check + 静态 import check：

```bash
.venv/bin/python -c "import ast; ast.parse(open('app/__main__.py').read()); print('syntax ok')"
.venv/bin/python -c "from app.core.pipeline_factory import build_pipeline; print('factory import ok')"
.venv/bin/python -c "from app.paths import user_data_dir_path; print(user_data_dir_path())"
.venv/bin/pytest -q
```

期望：syntax ok / factory import ok / 路径输出 / 62 passed。

- [ ] **Step 7: Commit**

```bash
git add app/core/pipeline_factory.py app/__main__.py app/paths.py tests/test_pipeline_factory.py
git commit -m "feat(core): pipeline_factory 按 mode 分发，AppController 不感知差异"
```

---

## Task 6: README 加 image_diff 模式段落

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README.md 的 "关键参数" 段落上方插入新段落**

在 `## 关键参数（config.yaml）` 这一行**之前**插入：

````markdown
## image_diff 模式（不依赖 OCR）

如果 PaddleOCR 在你的环境上跑不起来，或场景只关心"画面有没有变化"（比如告警面板、看板监听），可以切到不走 OCR 的纯图像 diff 模式：

```yaml
mode: image_diff
notifier:
  lark_app_id: cli_xxxx          # 飞书开放平台创建的自建应用 app_id
  lark_app_secret: xxxx          # 自建应用 app_secret
  lark_receive_id: oc_xxxx       # 目标群 chat_id（或个人 open_id / email 等）
  lark_receive_id_type: chat_id  # chat_id | open_id | user_id | union_id | email
image_diff:
  pixel_diff_threshold: 30       # 灰度像素差 >= 30 才算"变了"
  change_ratio_threshold: 0.005  # 变化像素占总像素 >= 0.5% 才触发推送
  min_interval_seconds: 5        # 两次推送之间最小间隔
  bbox_padding: 8                # diff bbox 四周向外扩 N 像素
```

工作流程：
1. 与"上次推送过的画面"做 grayscale + abs diff + threshold
2. 变化像素占比超阈 → 取最小包围矩形 + padding → 裁切
3. 通过自建应用 OpenAPI 上传图获取 image_key → 发 image 消息到目标 receive_id
4. 同时把裁切图存到 `<user_data_dir>/diff_frames/<ts>.png` 便于排查

注意：飞书自定义机器人 webhook 不能直接发图片，所以这条路径必须用**自建应用** + tenant_access_token。在 [飞书开放平台](https://open.feishu.cn) 创建自建应用，开通 `im:message`、`im:resource` 权限，把 app_id/app_secret 填到 config，并把应用拉进目标群即可。

````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: 新增 image_diff 模式说明段落"
```

---

## 完成验证

最后一步：
```bash
.venv/bin/pytest -q
```

期望：62 passed。

然后人工 sanity check：
```bash
.venv/bin/python -c "from app.core.pipeline_factory import build_pipeline; from app.storage.config import AppConfig, NotifierCfg; from app.storage.history import HistoryStore; from pathlib import Path; import tempfile; td = Path(tempfile.mkdtemp()); cfg = AppConfig(mode='image_diff', notifier=NotifierCfg(lark_app_id='x', lark_app_secret='y', lark_receive_id='z')); pipe = build_pipeline(cfg, HistoryStore(td/'h'), td/'frames'); print(type(pipe).__name__)"
```

期望输出：`ImagePipeline`

如果你想本地端到端跑（需要真实飞书自建应用）：在 `~/.config/screen-ocr-watchdog/config.yaml` 写好 image_diff 配置，启动 `.venv/bin/python -m app`，框选屏幕上一个会变的区域（比如打开一个时钟），等 ≥ `min_interval_seconds` 看群里有没有收到截图。
