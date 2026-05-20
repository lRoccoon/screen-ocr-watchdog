# screen-ocr-watchdog

每 N 秒截屏指定区域 → 与上一次推送过的画面做像素 diff → 把"变化区域"裁切后推送到飞书指定会话。

适用场景：在线直播课聊天区监控、固定位置的看板 / 告警面板监听等。

> 历史：本项目原为 Python + PaddleOCR 实现，因 PyInstaller 打包 paddleocr 依赖
> 长期受阻，已用纯 Go 重写为单文件静态 Windows exe。v1 不含 OCR（纯 image_diff），
> 后续会以云 OCR API 形式补回 OCR 能力。

## 构建

```bash
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags="-H windowsgui -s -w" -o ScreenWatchdog.exe .
```

可在 Linux / macOS 上交叉编译。产物是单个 `.exe`，无运行期依赖。

CI：推 `v*` tag 或手动触发 `build-windows` workflow，下载 artifact `ScreenWatchdog`。

## 使用

1. 双击 `ScreenWatchdog.exe`，托盘出现图标。
2. 右键托盘 → "重新框选区域"，拖拽选择要监控的屏幕区域。
3. 右键托盘 → "打开配置文件"，填入飞书自建应用凭证（见下），保存。
4. 配置生效需重启 exe（或重新框选区域触发重载）。

配置文件位置：`%APPDATA%\screen-ocr-watchdog\config.yaml`

## 配置

```yaml
mode: image_diff
region: {x: 0, y: 0, width: 0, height: 0}   # 由"重新框选区域"自动写入
interval_seconds: 5
image_diff:
  pixel_diff_threshold: 30        # 灰度像素差 >= 30 才算"变了"
  change_ratio_threshold: 0.005   # 变化像素占比 >= 0.5% 才触发推送
  min_interval_seconds: 5         # 两次推送最小间隔
  bbox_padding: 8                 # 变化区域 bbox 四周外扩像素
lark:
  app_id: cli_xxxx                # 飞书开放平台自建应用 app_id
  app_secret: xxxx
  receive_id: oc_xxxx             # 目标会话 chat_id（或 open_id / email 等）
  receive_id_type: chat_id        # chat_id | open_id | user_id | union_id | email
```

飞书自定义机器人 webhook 不能发图片，所以必须用**自建应用**：在
[飞书开放平台](https://open.feishu.cn) 创建自建应用，开通 `im:message`、
`im:resource` 权限，把 app_id / app_secret 填入配置，并把应用拉进目标群。

## 数据目录

- 配置：`%APPDATA%\screen-ocr-watchdog\config.yaml`
- 历史：`%LOCALAPPDATA%\screen-ocr-watchdog\history.ndjson`
- 截图：`%LOCALAPPDATA%\screen-ocr-watchdog\diff_frames\`
- 日志：`%LOCALAPPDATA%\screen-ocr-watchdog\Logs\app.log`

运行期出错时，先看 `app.log`。

## 项目结构

```
main.go              入口（Windows）
internal/
  config/   YAML 配置
  paths/    跨平台路径解析
  capture/  区域截屏（Windows）
  diff/     像素 diff 检测
  notify/   飞书自建应用发图
  history/  JSONL 历史 + 截图落盘
  pipeline/ Pipeline 接缝（为后续 OCR 预留）
  watcher/  定时 capture→process 循环
  tray/     系统托盘（Windows）
  picker/   全屏框选遮罩（Windows）
```

## 测试

```bash
go test ./internal/paths/ ./internal/config/ ./internal/diff/ ./internal/notify/ ./internal/history/ ./internal/pipeline/ ./internal/watcher/
```

`capture` / `tray` / `picker` 为 Windows-only，需在真 Windows 上验证。
