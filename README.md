# screen-ocr-watchdog

每 N 秒截屏指定区域 → PaddleOCR 识别 → 卡片聚合 + 行级 diff + 模糊匹配去重 → 把"新出现的消息"自动推送到飞书指定群。

适用场景：在线直播课聊天区监控、固定位置的看板/告警面板监听等。

## 总体流程

```
Tray ──▶ Scheduler(5s) ──▶ Capturer ──▶ PaddleOCR ──▶ aggregate_cards
                                                            │
                                                            ▼
                                                      DiffDetector (LRU 20 帧)
                                                            │ (new msgs)
                                                            ▼
                                                  Lark Webhook + history.ndjson
```

## 项目结构

```
app/                 主程序
  core/              scheduler + pipeline
  capture/           mss 截屏
  ocr/               PaddleOCR 引擎 + 卡片聚合后处理
  diff/              归一化 + 模糊匹配检测
  notifier/          飞书 webhook
  storage/           config / history
  ui/                PySide6 托盘 / 设置 / 框选 / 历史
  paths.py           跨平台数据/配置路径
tests/               pytest 单元 + 回放测试
tests/fixtures/      回放夹具 (滚动场景 OCR 序列)
tools/
  fake_chat_page/    Linux 端到端验证用的假聊天页
  replay_runner.py   离线回放：可对接真实飞书 webhook
.github/workflows/
  build-windows.yml  Windows 单文件 exe 打包流水线
```

## 安装

要求 Python 3.11。

```fish
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-dev.txt   # 含 pytest / pyinstaller
```

Linux 跑 GUI 需要的系统库（headless 服务器跑算法/CLI 不需要）：

```bash
sudo apt install -y libegl1 libxkbcommon0 libxkbcommon-x11-0 \
    libdbus-1-3 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 \
    libxcb-image0 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
    libxcb-sync1 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1
```

## 启动 GUI

```fish
.venv/bin/python -m app
```

首次启动会提示框选监控区域并填写飞书 Webhook URL。配置写入：

- Linux: `~/.config/screen-ocr-watchdog/config.yaml`
- Windows: `%APPDATA%\screen-ocr-watchdog\config.yaml`

## 测试

```fish
.venv/bin/pytest             # 单元 + 回放测试，应为 37 passed
```

## Linux 端到端验证（无需 Windows 机器）

1. 启动假聊天页：
   ```fish
   .venv/bin/python -m http.server 8000 --directory tools/fake_chat_page
   ```
2. 浏览器打开 `http://localhost:8000`，右侧聊天区会每 8 秒追加一条消息（参考截屏样式）
3. 启动 watchdog：`.venv/bin/python -m app`
4. 托盘 → 重新框选区域 → 拖框选中浏览器聊天区
5. 设置 → 飞书 → 填一个你自己的测试群 Webhook → 点"发送测试消息"
6. 等 30 秒，观察飞书群是否每 8 秒收到一条新消息

无 GUI 也可以用 `tools/replay_runner.py` 离线联调飞书：
```fish
.venv/bin/python -m tools.replay_runner \
    --fixture tests/fixtures/replay_basic.json \
    --webhook https://open.feishu.cn/open-apis/bot/v2/hook/xxx
```

## Windows 打包

不需要本地 Windows 环境，全部在 GitHub Actions 跑：

- 开发期：仓库 Actions 页面手动触发 `build-windows / workflow_dispatch`，下载 artifact `ScreenOcrWatchdog-exe`
- 发布：推送 `v*` tag，自动 attach 到 release

打包采用 `pyinstaller --onefile --windowed`，PaddleOCR 中文模型首次启动时由库自动下载到用户缓存目录（不打入 exe，控制体积）。

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

## 关键参数（`config.yaml`）

```yaml
region: {x: 1700, y: 100, width: 220, height: 800}
interval_seconds: 5
ocr:
  lang: ch
  card_gap: 12            # 卡片间最小 y 间距，<= 此值视为同一卡片
diff:
  fuzzy_threshold: 2      # 编辑距离阈值（短文本自动禁用模糊匹配）
  lru_frames: 20          # 去重窗口（≈ 100 秒）
  batch_threshold: 5      # ≥ N 条新消息时合并并加"批量"前缀
notifier:
  lark_webhook_url: ""
  attach_screenshot: false
```
