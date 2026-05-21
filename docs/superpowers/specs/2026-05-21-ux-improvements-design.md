# 三项体验改进设计

**日期**：2026-05-21
**状态**：设计已确认，待写实现计划
**分支**：`rewrite/go`（Go 重写后续）

## 背景

Go 单文件版本经 Windows 实测后，用户反馈三个体验问题：

1. **框选区域无反馈**——当前 picker 只是整屏一层均匀半透明遮罩，拖拽时看不到选区位置/范围，只能凭感觉选，且松手即生效、无确认。
2. **发送的是"全量内容"**——用户监控的是聊天区域，新消息从底部弹出；区域满后每来一条消息整体上滚，几乎所有像素都变，变化包围盒被撑满 ≈ 整个监控区域。用户期望只发"新增的那一条"。
3. **托盘只有蓝色**——运行/暂停/异常三态无法从图标区分。

三项相互独立，合并为一个 spec 一次实现。全部纯 Go、`CGO_ENABLED=0`；核心算法（需求 2）Linux 可单测，Windows GUI 层（需求 1、3）只能 Windows 编译。

---

## 需求 1：框选遮罩 + 屏上按钮确认

重写 `internal/picker/picker.go`，从"均匀半透明窗口"改为"GDI 自绘 + 状态机"。

### 交互

- 全屏分层窗口盖**半透明灰色蒙版**。
- 选区内抠成**完全透明**，露出真实桌面 100%，即用户要的"移除蒙版"。
- 拖拽时**实时刷新**：选区跟随鼠标，画亮色（lime）边框 + `宽 × 高 px` 尺寸标签。
- 松手进入**预览态**：选区附近画 `✓ 确认` / `✗ 取消` 两个按钮；鼠标点击触发；另附 `Enter`=确认、`Esc`=取消。
- 预览态下从灰色蒙版区起拖 = 重新框选。

### 状态机

三态：`idle`（首次拖拽前）、`dragging`（按住拖拽中）、`preview`（松手后有有效选区）。

| 消息 | idle | dragging | preview |
|---|---|---|---|
| `WM_LBUTTONDOWN` | 起拖→dragging，`SetCapture` | — | 命中 ✓→确认退出；命中 ✗→取消退出；否则起拖→dragging |
| `WM_MOUSEMOVE` | — | 更新终点，`InvalidateRect` 重绘 | — |
| `WM_LBUTTONUP` | — | `ReleaseCapture`；选区有效→preview，否则→idle；重绘 | — |
| `WM_KEYDOWN` Esc | 取消退出 | 取消退出 | 取消退出 |
| `WM_KEYDOWN` Enter | — | — | 确认退出 |

### 实现要点

- 窗口：`WS_POPUP` + `WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW`，覆盖主屏（`SM_CXSCREEN/SM_CYSCREEN`，沿用现有单主屏范围，不扩多屏）。
- `SetLayeredWindowAttributes(hwnd, colorKey, alpha, LWA_COLORKEY|LWA_ALPHA)`：`colorKey = RGB(255,0,255)` 品红，`alpha ≈ 120/255`。
- `WM_PAINT`（每次 `InvalidateRect` 触发）：
  1. `FillRect` 整个 client 用灰色画刷 → 半透明蒙版；
  2. 有选区时 `FillRect` 选区内部用 colorKey 画刷 → 抠成透明洞；
  3. 用 lime 画笔 + `NULL_BRUSH` `Rectangle` 画选区边框；
  4. `SetBkMode(TRANSPARENT)` + 白字 `TextOutW` 画 `W × H` 标签；
  5. preview 态：画两个按钮（填充背景 + 居中文字），按钮矩形存包级变量供命中检测。
- 窗口铺满主屏且原点 `(0,0)`，鼠标消息 `lParam` 的 client 坐标即屏幕坐标，选区可直接作结果。
- 新增依赖 `gdi32.dll`，新增 proc：`BeginPaint`/`EndPaint`/`FillRect`/`CreateSolidBrush`/`GetStockObject`/`CreatePen`/`SelectObject`/`Rectangle`/`DeleteObject`/`SetBkMode`/`SetTextColor`/`TextOutW`/`GetClientRect`/`InvalidateRect`。GDI 对象用完 `DeleteObject` 释放。
- 窗口类只注册一次的现有 `classRegistered` 守卫保留。

### 已知权衡

colorKey 透明区会**点击穿透**到桌面，因此重新框选必须从灰色蒙版区起拖（从上次选区内部起拖会穿透）。要换"不穿透"就得放弃"真实桌面 100%"效果（改 `UpdateLayeredWindow` 逐像素 alpha，复杂度大增）。取当前方案，`✗`/`Esc` 始终可取消，限制可接受。拖拽过程中按住鼠标已 `SetCapture`，光标移过透明洞仍能收到 `WM_MOUSEMOVE`/`WM_LBUTTONUP`，只有"新起一次按下"受影响。

### 对外接口

`Pick() (x, y, w, h int, ok bool, err error)` 签名不变，`main.go` 的 `pickRegion()` 无需改动。

---

## 需求 2：只发新增聊天区域（滚动位移检测）

聊天区域满后每条新消息使整体上滚 `d` 像素，新增内容 = 当前帧底部 `d` 像素那一条。检测出 `d`，只裁底部条发送。

### 算法

新增 `internal/diff/scroll.go`：

```
detectScrollShift(baseline, cur *image.RGBA) (shift int, ok bool)
```

- 前提：`baseline`、`cur` 同尺寸、`0` 基点（`Detect` 内已 `toRGBA`）。
- 内容上滚 `d` 意味着 `cur[y] ≈ baseline[y+d]`，重叠区为 `cur` 行 `[0, H-d)` 对 `baseline` 行 `[d, H)`。
- 对候选位移 `d ∈ [minShift, H-1]`：在重叠区按行/列步长采样，计算灰度绝对差均值 `residual(d)`。
- 取 `d* = argmin residual`。当 `residual(d*) ≤ scrollMatchThreshold` 且 `d* ≥ minShift` → 判定为滚动，返回 `(d*, true)`；否则返回 `(0, false)`。
- 常量（非配置，YAGNI）：`minShift = 4`（px，滤抖动）、`scrollMatchThreshold = 8`（0–255 灰度均差；真实像素级滚动残差近 0，非滚动界面在任意 `d` 都远大于此，阈值严格可避免误判）、采样步长 `sampleStep = 2`。
- 灰度复用 `detector.go` 现有 `grayAt`。

### 接入 detector

`Detect` 在通过变化比例阈值 + 节流之后、产出 crop 之前插入分支：

```
if shift, ok := detectScrollShift(d.baseline, cur); ok {
    top := cur.Bounds().Max.Y - shift          // 底部 shift 行
    bbox = image.Rect(0, top, W, H)            // 全宽底部条
    crop = cropRGBA(cur, bbox)
} else {
    bbox  = padRect(diff 包围盒, d.bboxPadding, cur.Bounds())  // 现有逻辑
    crop  = cropRGBA(cur, bbox)
}
```

- 滚动时变化比例 ≈ 1.0，必然通过现有 `changeRatioThreshold`，无需额外放行。
- 不滚动 / 中间编辑 / `d*` 无强匹配 → `ok=false` → 退回现有"变化包围盒"裁切，行为不变。
- 整屏换内容（如切了会话）→ 各 `d` 残差都大 → `ok=false` → 退回包围盒，此时包围盒≈整屏 → 等效"发整个区域"。
- 基线推进、`lastPushed`、`hasPushed` 等逻辑不变；`Result{Bbox, Crop}` 结构不变，`Bbox` 在滚动分支即底部条矩形。
- 无新增配置项；`pipeline.go`、`history` 记录格式、`notify` 均不改。

### 测试

`internal/diff/scroll_test.go` + 扩充 `detector_test.go`：

- 构造基线，再造"上滚 N 像素 + 底部新内容"的当前帧 → 断言 `detectScrollShift` 返回 `N`、`ok=true`，且 `Detect` 的 `Crop` 高度 = `N`、宽 = 区域宽。
- 非滚动（局部小块变化）帧 → `ok=false`，`Detect` 仍走包围盒分支。
- 整屏随机变化帧 → `ok=false`。
- 抖动 1–2 px → `ok=false`（`< minShift`）。

---

## 需求 3：托盘三态配色

`internal/tray/` 加 3 个图标，`SetState` 时切换。

- 新增 `icon_running.ico`（绿）、`icon_paused.ico`（黄）、`icon_error.ico`（红），沿用现有 `icon.ico` 的 PNG-in-ICO 格式与多尺寸（16×16 + 24×24）。
- 图标内容：状态色实心圆 + 透明背景（简洁，后续可换设计）。由一个一次性生成程序 `tools/genicons/main.go` 产出（纯 Go，标准库 `image/png` + 手写 ICO 头），生成后 `.ico` 提交进仓库。
- `tray.go`：三个 `//go:embed` 变量分别嵌入三图标；`Run` 启动时先 `SetIcon(iconRunning)`；`SetState` 的 `switch` 各分支追加 `systray.SetIcon(对应图标)`。tooltip / 暂停项文案逻辑保留。
- 旧 `icon.ico` 删除。

---

## 影响文件汇总

| 文件 | 改动 |
|---|---|
| `internal/picker/picker.go` | 大改：GDI 自绘 + 状态机 + 按钮 |
| `internal/diff/scroll.go` | 新增：滚动位移检测 |
| `internal/diff/detector.go` | 小改：`Detect` 插入滚动分支 |
| `internal/diff/scroll_test.go` | 新增 |
| `internal/diff/detector_test.go` | 扩充 |
| `internal/tray/tray.go` | 小改：嵌入 3 图标，`SetState` 切换 |
| `internal/tray/icon_{running,paused,error}.ico` | 新增 |
| `internal/tray/icon.ico` | 删除 |
| `tools/genicons/main.go` | 新增：一次性图标生成程序 |

`main.go`、`config.go`、`pipeline.go`、`notify`、`history`、`watcher`、`capture` 不改。

## 验证

- 核心：`go test ./internal/diff/...`（含新滚动检测）在 Linux 通过。
- 全量：`CGO_ENABLED=0 GOOS=windows go build ./...` 通过。
- GUI（需求 1、3）：Windows 实测——框选遮罩/抠洞/按钮确认、托盘三态变色。
