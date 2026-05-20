# Go 重写设计

**日期**：2026-05-20
**状态**：设计已确认，待实现
**分支**：`rewrite/go`（从 `feat/image-diff-mode` HEAD 切出）

## 背景

Python + PySide6 + PaddleOCR 版本用 PyInstaller 打 Windows exe，连续 5 轮卡在打包依赖问题（Cython 数据文件、paddleocr 的 `_import_file` 动态加载、shapely / albumentations 等传递依赖不进 bundle）。根因是 PyInstaller 对 paddleocr 动态加载链路的静态分析盲区，属于 Python 打包生态的固有摩擦。

决定：用 Go 全面重写，产出**完全静态的单文件 Windows 二进制**，彻底摆脱解释器 + 动态依赖的打包困境。

**关键约束（用户明确）**：必须是完全静态的单文件二进制；不用 Python 等动态语言。

**OCR 决策**：v1 砍掉 OCR，只做 image_diff（截屏 → 像素 diff → 把变化区域裁切后发飞书）。Go 无 PaddleOCR 绑定。**后续会加 OCR 能力**——届时只能走云 OCR API（百度/腾讯/阿里，纯 HTTP，不破坏静态二进制）；Tesseract 走 cgo 会把原生依赖打包问题带回来，不采用。架构必须为后续 OCR 留干净接缝。

---

## 一、架构 / 工程布局 / 技术栈

### 产物

- Go 1.22+，纯 Go 无 cgo。
- 构建：`CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags="-H windowsgui -s -w" -o ScreenWatchdog.exe .`
  - `-H windowsgui`：无控制台窗口（等价 PyInstaller 的 `--windowed`）
  - `-s -w`：strip 符号，减小体积
- 单个 `.exe`，约 10-15 MB，零运行期依赖，可在 Linux 开发机一条命令交叉编译。
- CI 可选：保留一个约 15 行的 Go build workflow，或直接本机交叉编译。

### 工程布局

Go module 放仓库根；Python `app/` 在实现期保留作移植参照，最后一个 commit 删除。

```
go.mod
main.go                  入口：载配置 → 起托盘 → 起 watcher        [//go:build windows]
internal/
  config/    config.go   YAML schema + Load/Save
  paths/     paths.go     %APPDATA% / %LOCALAPPDATA% 路径解析
  capture/   capture.go   区域截屏（kbinani/screenshot）        [//go:build windows]
  diff/      detector.go  图像 diff 检测（移植 Python ImageDiffDetector）
  notify/    lark.go      飞书自建应用：token 缓存 + 上传图 + 发 image
  history/   history.go   JSONL 历史 + diff_frames 文件夹
  pipeline/  pipeline.go  Pipeline 接口 + ImagePipeline + New 工厂
  watcher/   watcher.go   定时循环：capture → pipeline.Process
  tray/      tray.go      systray 图标 + 菜单                   [//go:build windows]
  picker/    picker.go    Win32 全屏拖拽框选遮罩                [//go:build windows]
app/                      Python 旧码，移植期保留，完工删
```

### 技术栈

Windows 上全是纯 Go（走 `golang.org/x/sys` 系统调用，不链非系统 DLL）：

| 用途 | 库 |
|---|---|
| 托盘 | `fyne.io/systray` |
| 截屏 | `kbinani/screenshot` |
| 配置 | `gopkg.in/yaml.v3` |
| 框选遮罩 | `golang.org/x/sys/windows`（裸 Win32，只一个窗口不引重型 GUI 框架） |
| 图像/HTTP/JSON/日志 | 标准库 `image` `image/png` `net/http` `mime/multipart` `encoding/json` `log/slog` |

### 命名

仓库名带 "ocr" 已名不副实（工具 v1 不做 OCR），但改 GitHub 仓库名是另一桩事——v1 不动，README 说明即可。

---

## 二、组件 / 数据流 / OCR 接缝

`diff` / `notify` / `history` 是积木，`pipeline` 把它们拼起来，`watcher` 只认 `pipeline`。

### 组件契约

| 组件 | 契约 |
|---|---|
| `config.Config` | YAML 结构体 + `Load(path)` / `Save(path)`。字段：`Mode`（v1 仅 `image_diff`，`ocr` 预留）、`Region{X,Y,W,H}`、`IntervalSeconds`、`ImageDiff{PixelDiffThreshold, ChangeRatioThreshold, MinIntervalSeconds, BboxPadding}`、`Lark{AppID, AppSecret, ReceiveID, ReceiveIDType}` |
| `capture.Capturer` | `Capture() (image.Image, error)`，按 `Region` 截屏 |
| `diff.Detector` | 状态机。`Detect(frame image.Image, now time.Time) *Result`（`Result{Bbox, Crop}` 或 nil）。基线 = 上次推送过的帧。逻辑照搬 Python `ImageDiffDetector`：灰度 → 逐像素阈值二值化 → 变化像素占比 → 过阈则 getbbox + padding + 裁切 → 节流（距上次推送 < `MinIntervalSeconds` 则不推、**不推进基线**）→ 帧尺寸与基线不一致则重置基线返回 nil |
| `notify.LarkClient` | `SendImage(img image.Image) error`。内部：缓存 tenant_access_token（按 server `expire` 字段，剩余 < 5min 视为过期）、`uploadImage`（multipart `image_type=message`）、`sendImageMessage`（`msg_type=image`，`content` 为 `{"image_key":...}` 的 JSON 串）。`SendText` 留到 OCR 回归时再加 |
| `history.Store` | `Append(record)` 写 JSONL（含 ts、bbox、image 路径）+ 把裁切 PNG 存到 `diff_frames/<ts>.png` |
| `pipeline.Pipeline` | **接缝接口**：`Process(frame image.Image) error`。v1 实现 `ImagePipeline`（detect → 存 PNG + history → notify.SendImage）。将来 `OcrPipeline`（云 OCR API → notify SendText → history）是另一实现 |
| `pipeline.New(cfg *config.Config, store *history.Store, framesDir string) (Pipeline, error)` | 工厂：按 `cfg.Mode` 返回对应 Pipeline。v1 只认 `image_diff`；`image_diff` 模式下校验 Lark 三凭证非空，缺则返回 error |
| `watcher.Watcher` | 定时循环。每 tick：`capture.Capture()` → `pipeline.Process(frame)`。在 goroutine 跑，`Pause` / `Resume` / `Stop` 走 channel。每 tick `defer recover()` 防单帧 panic 杀死循环。**watcher 不知道 pipeline 是 diff 还是 ocr** |
| `tray` | systray 图标 + 菜单：暂停/恢复、打开配置文件、打开截图目录、重新框选区域、退出。图标状态：running / paused / error |
| `picker` | Win32 全屏半透明遮罩 + 鼠标拖拽选区，选完把 `Region` 写回 config |

### 数据流（image_diff 模式）

```
main → 载 config → 起 tray → 起 watcher goroutine
  每 IntervalSeconds 秒：
    capture.Capture()  ──▶  pipeline.Process(frame)
                                  ImagePipeline 内部：
                                  ├─ diff.Detect() == nil ? → 丢弃
                                  ├─ 有 Result → 存 PNG + history.Append
                                  └─ notify.SendImage(crop)
  任何错误 → slog 写 %LOCALAPPDATA%\screen-ocr-watchdog\Logs\app.log + 托盘图标变红
```

### OCR 接缝怎么用（后续）

将来加 OCR，只需：① `config.Mode` 多一个合法值 `ocr`；② 新增 `internal/ocr/` 调云 OCR API；③ 新增 `pipeline.OcrPipeline`；④ `pipeline.New` 工厂多一个分支；⑤ `notify.LarkClient` 加 `SendText`。`watcher`、`capture`、`config` 主体、`tray`、`picker`、`history` **不用改**。与 Python 版已验证的 `pipeline_factory` 同构。

---

## 三、错误处理 / 测试 / 构建 / 迁移

### 错误处理

| 场景 | 行为 |
|---|---|
| `mode=image_diff` 但 Lark 三凭证任一为空 | `pipeline.New` 返回 error → 不启动 watcher → 托盘红 + 写日志 |
| 截屏失败 | 记日志、托盘红，**不杀循环**，下一 tick 继续 |
| Lark API 失败（网络 / token / 上传 / 业务错误码） | 记日志（带 bbox / path 上下文）、托盘红；裁切图**仍存本地 + 写 history**；下一 tick 继续 |
| `Region` 未配置（W 或 H == 0） | 启动时不起 watcher，托盘提示"右键 → 重新框选区域" |
| 单帧 panic | watcher goroutine 每 tick `defer recover()`，记日志，不让一帧崩掉整个 watcher |
| config 文件损坏（YAML parse 失败） | 启动时 Load 失败 → 写日志 + 托盘红 + tooltip，不起 watcher |
| diff bbox 几乎覆盖整屏（滚动/切窗口） | 仍然推——这是"画面大变化"的预期信号，不做特殊回退 |

**日志**：`log/slog` 写文件到 `%LOCALAPPDATA%\screen-ocr-watchdog\Logs\app.log`。`-H windowsgui` 无控制台，文件日志是排查运行期问题的唯一手段。

### 测试策略

**Linux 开发机能测**（纯逻辑，无 OS GUI 依赖，无 `//go:build windows` 标签）：

- `config` — YAML Load/Save、默认值、round-trip、缺字段向后兼容
- `diff.Detector` — 用 Go `image.NewRGBA` 合成图，照搬 Python 那 7 个用例（首帧建基线 / 相同帧不触发 / 微变低于占比阈值不触发 / 大变触发且基线推进 / bbox padding 扩展并 clamp / 节流期不推且基线不推进 / 尺寸不一致重置基线）
- `notify.LarkClient` — `net/http/httptest.Server` 假冒飞书 API，验三段流程、token 缓存命中、token 过期刷新、token/上传业务错误、网络异常、凭证缺失短路
- `history.Store` — temp dir，Append 后断言 JSONL + PNG 写入
- `pipeline.ImagePipeline` — stub `diff` / stub `notify`（接口），验编排：无 diff 不调 notify、有 diff 全流程、notify 失败仍写图 + history

**Linux 测不了、必须真 Windows 上验**：

- `capture`（要真显示器）、`tray`（要桌面）、`picker`（裸 Win32，`golang.org/x/sys/windows` 在 `GOOS=linux` 下不编译）
- 这三个包打 `//go:build windows` 标签；纯逻辑核心包不带标签，任何 OS 都能 `go test`
- `main.go` 引用 tray/picker/capture，故 `main.go` 也带 `//go:build windows`；非 Windows 下整个 app 不构建，但核心逻辑包独立可测

**可执行的验证**：

- Linux：`go test ./internal/config/... ./internal/diff/... ./internal/notify/... ./internal/history/... ./internal/pipeline/...` 全绿
- Linux：`CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build ./...` 确认含 Win32 的全工程**能编译**
- Windows（用户做）：跑 exe，手动验 tray / picker / capture。**`picker` 的全屏拖拽遮罩大概率需 1-2 轮 Windows 实测调对**——这是 Linux 开发 Windows GUI 的固有限制。

### 构建产物

```
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags="-H windowsgui -s -w" -o ScreenWatchdog.exe .
```

单个 `.exe`，约 10-15 MB，零运行期依赖，真·双击即用。对比 PyInstaller 版 300-500 MB + 上千文件 + 5 轮缺依赖。

### 迁移 / 分支

- 分支 `rewrite/go`（已从 `feat/image-diff-mode` HEAD 切出）。
- 实现期 Python `app/` 不动，作移植参照。
- **最后一个 commit** 删：`app/`、`tests/`（Python）、`requirements*.txt`、`pyproject.toml`；`.github/workflows/build-windows.yml` 换成 Go 版；`README.md` 重写。
- 旧 Python 的 spec / plan 文档留作历史，不删。

---

## 四、不做的事（YAGNI）

- v1 不做 OCR（接缝留好，后续单独加）
- v1 不做设置窗口、历史查看窗口（config.yaml + 文件夹替代）
- 不做 macOS / Linux GUI 支持（Windows-only 工具）
- 不做 `notify.SendText`（OCR 回归时再加，Go 加函数零成本）
- 不做自动更新、不做安装器（单 exe 直接分发）
