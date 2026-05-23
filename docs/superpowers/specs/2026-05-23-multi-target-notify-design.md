# 多群通知支持 — 设计

## 背景

v0.1.0 两条飞书通知路径都只支持 1 个目标：

- `LarkWebhookNotifier`（OCR 模式）：1 个 `lark_webhook_url`
- `LarkImageNotifier`（image_diff 模式）：1 个 `lark_receive_id` + `lark_receive_id_type`

需求：同一帧的检测结果能同时推送到多个飞书群（OCR 文本到多个 webhook，image_diff 图片到多个 receive_id）。

## 目标 / 非目标

**目标**

- OCR 模式：支持配置多个 webhook URL，同一条/批消息逐个发送
- image_diff 模式：同一个自建应用 + 多个 receive_id（可不同 receive_id_type），上传图复用同一 image_key
- 部分失败 best-effort：单个目标失败不阻断其他目标，错误反映到 tray
- 向后兼容 v0.1.0 配置：单字段 yaml 升级后零改动可用，UI 自动迁移

**非目标**

- image_diff 凭证的 UI（README 已声明 yaml-only，保持现状）
- 并发发送、自动重试、超时降级
- 每个目标独立节流 / batch_threshold
- history.ndjson 按目标分桶

## 配置 schema

`app/storage/config.py`：

```python
class LarkTargetCfg(BaseModel):
    receive_id: str = ""
    receive_id_type: Literal["chat_id","open_id","user_id","union_id","email"] = "chat_id"

class NotifierCfg(BaseModel):
    # 新（list 为主）
    lark_webhook_urls: list[str] = Field(default_factory=list)
    lark_targets: list[LarkTargetCfg] = Field(default_factory=list)
    # 旧（list 为空时 fallback，向后兼容 v0.1.0）
    lark_webhook_url: str = ""
    lark_receive_id: str = ""
    lark_receive_id_type: Literal[...] = "chat_id"
    # 不变
    lark_app_id: str = ""
    lark_app_secret: str = ""
    attach_screenshot: bool = False

    def effective_webhook_urls(self) -> list[str]:
        """list 非空用 list；否则单字段非空用 [单字段]；否则空 list。"""

    def effective_targets(self) -> list[LarkTargetCfg]:
        """同上。"""
```

**解析规则**：list 字段优先；list 为空则单字段（非空时）回退为单元素列表；都空返回空列表。

**例**（升级后推荐 yaml）：

```yaml
notifier:
  lark_webhook_urls:
    - https://open.feishu.cn/.../hook/aaa
    - https://open.feishu.cn/.../hook/bbb
  lark_app_id: cli_xxx
  lark_app_secret: xxx
  lark_targets:
    - {receive_id: oc_xxx, receive_id_type: chat_id}
    - {receive_id: ou_yyy, receive_id_type: open_id}
```

## 组件设计

### `LarkWebhookNotifier`（`app/notifier/lark_webhook.py`）

- 构造器：`LarkWebhookNotifier(webhook_urls: Sequence[str], timeout: float = 10.0)`
- `send_text` / `send_messages`：内部 build payload 一次，循环遍历 `webhook_urls`，每个 URL 独立 try / except，收集 `(url_tail, ok, msg)`
- 空 list：直接返回 `NotifyResult(ok=False, message="no webhook urls configured")`
- 聚合返回：`ok = 全部成功`；message 形如 `"2/3 失败: hook[..aaa]=timeout; hook[..bbb]=code=19021"`

### `LarkImageNotifier`（`app/notifier/lark_image.py`）

- 构造器：`LarkImageNotifier(app_id, app_secret, targets: Sequence[LarkTargetCfg], timeout=10.0)`
- `send_image` 流程：
  1. 凭证缺失 / `targets` 为空 → 直接返回 `ok=False`
  2. `_get_token()` 拿 1 次 token
  3. `_upload_image(token, image)` 拿 1 次 `image_key`
  4. 对每个 target 调 `_send_message(token, image_key, target)`，独立 try / except
- token 和 image_key 全部目标共享；upload 失败 → 直接整体失败（无 image_key 后续也不可能成功）
- 聚合 message：与 webhook 同语义

### `pipeline_factory.py`

构造 notifier 时改成调 `cfg.notifier.effective_webhook_urls()` / `effective_targets()`。

### UI（`app/ui/settings_window.py`）

- 飞书 tab：`QLineEdit` → `QPlainTextEdit`（placeholder：`"每行一个 webhook URL"`）
- 加载策略：`urls = list(cfg.lark_webhook_urls)`；若 `cfg.lark_webhook_url` 非空且不在 urls 中，append 进去。一次性渲染成多行文本
- 保存策略：按行 split → strip → 丢空 → 写入 `lark_webhook_urls`；同时清空 `lark_webhook_url`
- 「发送测试消息」按钮：对文本框内 **每条** URL 发一次 `[Screen OCR Watchdog] 测试消息`，状态行展示 `"3/3 成功"` 或 `"2/3 成功（失败：hook[..bbb]）"`

## 数据流

```
config.yaml ── load_config ──▶ NotifierCfg (list + 单字段)
                                    │
                                    ▼ effective_*()
                               生效目标列表
                                    │
                                    ▼
                            Notifier.__init__(targets=...)
                                    │
                                    ▼  send_text / send_image
                       逐目标 try → collect (ok, msg)
                                    │
                                    ▼
                            NotifyResult(ok=AND, message=摘要)
                                    │
                                    ▼ 上层 pipeline
                            ok=False 时走 _on_error → tray 提示
```

## 错误处理 & 日志

- 单目标失败行：`log.error("lark webhook send failed: url_tail=%s err=%s", url[-12:], err)` / `log.error("lark image send_message failed: receive_id=%s type=%s err=%s", ...)`
- 全部失败 / upload 失败：上层 `_on_error` → tray 标题「全部 N 个目标推送失败」
- 部分失败：上层 `_on_error` → tray 标题「N/M 目标推送失败」，但 history.ndjson 仍然记一条（与现有行为一致，不按目标分桶）

## 测试

`tests/` 全部走 monkeypatch / fake transport，不打真实飞书：

- `test_lark_webhook.py`：
  - 3 URL 全成功 → `ok=True`
  - 1 URL 网络失败 + 2 成功 → `ok=False`，message 含失败 URL 的 tail，其他 2 个仍调用一次（计数验证）
  - URL list 为空 → `ok=False, message="no webhook urls configured"`
  - 兼容性：构造器接收 `Sequence[str]`，单元素 list 与之前 1 URL 行为完全一致
- `test_lark_image.py`：
  - 3 target 全成功 → token 调 1 次、upload 调 1 次、send_message 调 3 次，`ok=True`
  - upload 失败 → 整体 fail，0 次 send_message
  - 1 target 发失败 + 2 成功 → upload 仍 1 次，send_message 3 次，`ok=False`，message 含失败 receive_id
  - targets 空 → `ok=False, message="no targets configured"`
- `test_storage.py`（扩充）：
  - 旧 yaml（只有 `lark_webhook_url`）加载后 `effective_webhook_urls()` 返回 `[那个 URL]`
  - 新 yaml（只有 `lark_webhook_urls`）加载后 `effective_webhook_urls()` 返回 list
  - 两者同时存在 → list 优先（单字段被忽略）
  - 全空 → `[]`
- `test_pipeline_factory.py`（扩充）：
  - OCR 模式注入的 `LarkWebhookNotifier.webhook_urls` 长度 = 配置生效列表长度
  - image_diff 模式注入的 `LarkImageNotifier.targets` 长度 = 配置生效列表长度

## 向后兼容性

- v0.1.0 用户 yaml 不改：load 后 `effective_*` 返回单元素 list，行为一致
- v0.1.0 UI 升级：首次打开设置窗口时，原 `lark_webhook_url` 自动展示到多行文本框；保存后写入 `lark_webhook_urls`，原单字段清空
- 包发布：v0.2.0（minor，新功能）

## 实施顺序（信息性，详细拆分由 writing-plans 处理）

1. `config.py`：加 list 字段 + `effective_*` 方法 + 配套测试
2. `lark_webhook.py`：构造器签名升级 + 聚合逻辑 + 测试
3. `lark_image.py`：同上，注意 upload 复用
4. `pipeline_factory.py`：调用 `effective_*`
5. `settings_window.py`：QPlainTextEdit + 加载 / 保存 / 测试按钮
6. `__main__.py` / 其他直接构造 notifier 的位置：跟随签名变更
7. 文档：README 多群配置段落
