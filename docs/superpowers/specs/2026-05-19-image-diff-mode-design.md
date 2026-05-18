# Image-diff 模式设计

**日期**：2026-05-19
**状态**：设计已确认，待实现
**背景**：Windows exe 在 PaddleOCR 第一次 init 时触发 Cython 运行期编译失败（路径 `_MEI*/Cython/Utility/CppSupport.cpp`），traceback 暂未拿到（已加 file logging，下次复现可看 `%LOCALAPPDATA%\screen-ocr-watchdog\Logs\app.log`）。在根因修复前需要一个**完全绕开 OCR 链路**的可用模式：纯截图 → 画面 diff → 把"新增/变化区域"裁切后作为图片推送到飞书群。

> 注意：此功能不修 Cython 错误本身，只是提供一个能跑的兜底模式。OCR 模式根因待 traceback 到手后单独修。

---

## 一、配置形态

`config.yaml` 加一个顶层 `mode` 字段和一个 `image_diff` 节，飞书凭证扩到 `notifier` 里：

```yaml
mode: ocr            # ocr | image_diff
region: {...}        # 不变
interval_seconds: 5  # 不变
ocr: {...}           # 不变，仅 mode=ocr 生效
diff: {...}          # 不变，文本去重，仅 mode=ocr 生效

image_diff:                       # 仅 mode=image_diff 生效
  pixel_diff_threshold: 30        # 灰度像素差 ≥ 30 才算"变了"
  change_ratio_threshold: 0.005   # 变化像素占比 ≥ 0.5% 才触发
  min_interval_seconds: 5         # 两次推送最小间隔（节流硬上限）
  bbox_padding: 8                 # diff bbox 四周向外扩 8px 避免裁太紧

notifier:
  lark_webhook_url: ""            # 原文本通道，mode=ocr 时用
  lark_app_id: ""                 # 新增：自建应用 app_id
  lark_app_secret: ""             # 新增：自建应用 app_secret
  lark_receive_id: ""             # 新增：群 chat_id 或个人 open_id 等
  lark_receive_id_type: "chat_id" # chat_id | open_id | user_id | union_id | email
```

要点：

- `mode=ocr` 走老链路，零行为变化（向后兼容旧 config 文件——缺 `mode` 时默认 `ocr`）。
- `mode=image_diff` 时，整个 OCR 链（paddleocr import、PaddleOCR init、卡片聚合、文本去重）一概不进入——这才能真正绕开 Cython 编译路径。
- 飞书自建应用凭证只在 `mode=image_diff` 时校验/使用；老的 webhook 路径不受影响。

---

## 二、模块拆分

新增两个模块 + 一个 pipeline，老入口改一处分发。

```
app/
  diff/
    image_detector.py       # 新增：image diff 检测，输出 bbox + 裁切图
  notifier/
    lark_image.py           # 新增：自建应用 token 缓存 + 上传图 + 发 image 消息
  core/
    image_pipeline.py       # 新增：image_diff 模式专用 pipeline（capture → diff → notify）
  __main__.py               # 改：根据 config.mode 选不同 pipeline，OCR 链路 lazy import
```

### 职责切分

- **`ImageDiffDetector`**：状态机持有"上一次推送过的画面"（**不是上一帧**）。每来一张新图：
  1. 与基线做 grayscale + `abs(diff) ≥ pixel_diff_threshold` 二值化
  2. 统计变化像素占比，若 < `change_ratio_threshold` → 返回 None
  3. 否则用 `Image.getbbox()` 取最小包围矩形，四周加 `bbox_padding`，裁切，返回 `(bbox, cropped_image)`
  4. 把当前画面记为新基线（推进）

  **节流是这个状态机的天然产物**：聊天区静止时基线不更新，鼠标抖一下 diff ratio 不超 0.5% → 不推；真有新消息出现 → bbox 出来 → 推一次 → 基线推进到含新消息的画面。`min_interval_seconds` 是兜底硬限：即使 diff 超阈，距上次推送 < 该值也不推（仍推进基线吗？——**不推进**，保留下一帧再次评估的机会，避免节流期间真出新消息被"基线已更新"吃掉）。

- **`LarkImageNotifier`**：封装：
  - tenant_access_token 缓存到内存（TTL 以飞书 server 返回的 `expire` 字段为准，按"剩余 < 5min 视为过期"提前续）
  - `POST open-apis/im/v1/images` 上传 `image_type=message` 拿 `image_key`
  - `POST open-apis/im/v1/messages?receive_id_type=...` 发 `msg_type=image` 消息

  和老的 `LarkWebhookNotifier` 平级，不共享代码。

- **`ImagePipeline`**：极薄一层，串 detector → notifier，写一行 history `type=image, bbox=..., image_path=...`，把裁切图存到 `user_data_dir/diff_frames/<ts>.png`。

- **`__main__.py`**：`_build_ocr()` / `LarkWebhookNotifier` / `Pipeline` 的构造统统延后到 `restart_runner` 里按 `config.mode` 分发；module 顶层不再 `from app.ocr.engine import PaddleOcrEngine`（避免 image_diff 模式也连带 import paddleocr 触发 Cython）。

### 关键决策

1. **detector 与"上次推送过的画面"对比，不是"上一帧"**。后者会丢消息：消息出现后画面静止 → 下一帧 diff=0 → 误以为没变化。前者天然带去重，符合"只推真正新增"的语义。
2. **裁切图存本地**也存（即使飞书发送失败），跟 OCR 模式 history 写盘的语义保持一致。
3. **不抽公共基类**（`Pipeline` / `ImagePipeline` 不共享接口）——YAGNI。两条链数据流不同，强行抽基类只会让 scheduler 那一行 `pipeline.process_image()` 加一层泛型，反而更绕。`WatchdogRunner` 已经只调一个方法，鸭子类型就够。

---

## 三、错误处理 / 测试 / 边界

### 错误处理

| 场景 | 行为 |
|---|---|
| `mode=image_diff` 但 `lark_app_id / lark_app_secret / lark_receive_id` 任一为空 | 启动 runner 时立刻 raise → `_on_error` → tray 变红 + 写日志，不进入 capture 循环 |
| 飞书 token 获取失败（网络/凭证错） | 一次上传/发送失败 throw，scheduler catch 走老路径写日志 + tray，不阻塞下一帧 |
| 上传 image 成功但发 message 失败 | 已上传的 image_key 不复用（飞书 image_key 时效短，下次重新上传），跟丢一次推送等价 |
| token 临近过期被多线程同时刷新 | watchdog 是单线程 runner，不存在并发；token 刷新仍走 lock 作为保险 |
| diff bbox 几乎覆盖整张图（拖滚动条/切窗口） | 仍然推——这就是用户想要的"画面有大变化"信号；不做特殊回退 |
| 飞书 image_key 上传 30002 等业务错误 | 跟 webhook 失败同等处理：记录 `(code, msg)` 到日志，本帧丢弃，不重试 |

### 测试策略

- `tests/diff/test_image_detector.py`：
  - 相同图 → 不触发
  - 局部小变化（< `change_ratio_threshold`）→ 不触发
  - 局部大变化 → 触发，bbox 包含变化区域，基线推进
  - 触发后立即再传同样的新图 → 不触发（基线已是新图）
  - `bbox_padding` 行为：向外扩 N px，不越界
  - `min_interval_seconds` 期间即使 diff 超阈也不推、且基线不推进

- `tests/notifier/test_lark_image.py`：
  - 用 `pytest-mock` mock `requests.post`，验证：
    - token 缓存命中第二次不调获取接口
    - 上传图 + 发消息两段流程参数正确（`receive_id_type` query / `msg_type=image` / `content` JSON 字符串里包 `image_key`）
    - token 过期（飞书返回特定错误码）→ 自动刷新并重试一次

- `tests/test_main_dispatch.py`：mock 掉 Qt + paddleocr，验证 `mode=image_diff` 时 import 链路上**不会** `from paddleocr import ...`（用 `sys.modules` 监测）。

- **不写 paddleocr 的回归**——它跟 image_diff 完全解耦。

### 已知边界 / 不做的事

- **不做** region picker 二次改造，复用 OCR 模式那套
- **不做** image_diff 模式下推送时附带"老 webhook 文本"做双通道兜底
- **不做** `重新框选区域` 后立即拍一张做基线——首帧自动作基线即可，第一次跑可能漏一张图，可接受
- **不做** PaddleOCR 在 image_diff 模式下"懒安装"——`requirements.txt` 仍保留 paddle 系（避免动 CI），只是运行期不 import；将来若要彻底脱 paddle 依赖另起一版
- **不做** 把 PyInstaller 打包配置在本次一起改——根因待 Windows traceback 落地后单独 PR

---

## 四、向后兼容

- 旧 `config.yaml` 缺 `mode` 字段 → 默认 `ocr`，行为完全不变
- 旧 `config.yaml` 缺 `image_diff` 节 → 仅当用户切到 `mode=image_diff` 时才校验该节，否则忽略
- 旧 `config.yaml` 缺 `notifier.lark_app_*` 字段 → 同上，仅 image_diff 模式校验
- 老 `LarkWebhookNotifier` 不动，`Pipeline` 不动，`tests/` 现有 37 个 case 应继续全绿
