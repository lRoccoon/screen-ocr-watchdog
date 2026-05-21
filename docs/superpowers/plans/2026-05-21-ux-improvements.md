# 三项体验改进 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Go 版 screen-ocr-watchdog 加三项体验改进——框选遮罩抠洞+按钮确认、聊天滚动 diff 只发新增区域、托盘三态配色。

**Architecture:** 需求 2 是纯算法（`internal/diff`），Linux 可 TDD；需求 1、3 是 Windows GUI 层（`//go:build windows`），靠交叉编译 + Windows 实测验证。三项互不依赖，按"先核心算法、再托盘、最后 picker"顺序实现。

**Tech Stack:** Go 1.25，`CGO_ENABLED=0`，纯 Go；Win32 经 `golang.org/x/sys/windows` 懒加载 user32/gdi32/kernel32；托盘 `fyne.io/systray`。

**对应设计文档：** `docs/superpowers/specs/2026-05-21-ux-improvements-design.md`

---

## 文件结构

| 文件 | 职责 | 改动 |
|---|---|---|
| `internal/diff/scroll.go` | 滚动位移检测算法 | 新建 |
| `internal/diff/scroll_test.go` | 滚动检测单测 + 共享测试辅助 | 新建 |
| `internal/diff/detector.go` | `Detect` 接入滚动分支 | 改 |
| `internal/diff/detector_test.go` | 新增滚动场景用例 | 改 |
| `tools/genicons/main.go` | 一次性图标生成程序 | 新建 |
| `internal/tray/icon_{running,paused,error}.ico` | 三态图标 | 新建（由 genicons 产出） |
| `internal/tray/icon.ico` | 旧单图标 | 删除 |
| `internal/tray/tray.go` | `SetState` 切换三态图标 | 改 |
| `internal/picker/picker.go` | GDI 自绘 + 状态机 + 按钮 | 整体重写 |

`main.go`、`config.go`、`pipeline.go`、`notify`、`history`、`watcher`、`capture` 不改。

---

## Task 1: 滚动位移检测 `detectScrollShift`

**Files:**
- Create: `internal/diff/scroll.go`
- Test: `internal/diff/scroll_test.go`

聊天满后每条新消息使内容整体上滚 `d` 像素。`detectScrollShift` 在候选位移区间滑动匹配，找残差最小的 `d`；并用"重叠区残差足够小"+"重叠区有垂直纹理"两道守卫排除误判（纯色/低纹理区任意位移都会"完美匹配"）。

- [ ] **Step 1: 写失败测试**

创建 `internal/diff/scroll_test.go`：

```go
package diff

import (
	"image"
	"image/color"
	"testing"
)

// rowPattern 造一张每行灰度各异、相邻行差异很大的测试图（模拟有文字纹理的真实内容）：
// 第 y 行灰度 = (y*37) % 256（37 与 256 互质 → 行值不重复）。
func rowPattern(w, h int) *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := 0; y < h; y++ {
		v := uint8((y * 37) % 256)
		for x := 0; x < w; x++ {
			img.Set(x, y, color.RGBA{v, v, v, 255})
		}
	}
	return img
}

// scrollUp 把 src 整体上滚 d 像素：cur[y]=src[y+d]（y<h-d），底部 d 行填新内容。
func scrollUp(src *image.RGBA, d int) *image.RGBA {
	b := src.Bounds()
	w, h := b.Dx(), b.Dy()
	dst := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			if y < h-d {
				dst.Set(x, y, src.At(x, y+d))
			} else {
				v := uint8(200 + (y % 50))
				dst.Set(x, y, color.RGBA{v, v, v, 255})
			}
		}
	}
	return dst
}

func TestDetectScrollShiftFindsShift(t *testing.T) {
	base := rowPattern(120, 100)
	shift, ok := detectScrollShift(base, scrollUp(base, 20))
	if !ok {
		t.Fatal("detectScrollShift: ok=false, want true")
	}
	if shift != 20 {
		t.Fatalf("shift = %d, want 20", shift)
	}
}

func TestDetectScrollShiftRejectsLocalChange(t *testing.T) {
	base := rowPattern(120, 100)
	cur := rowPattern(120, 100)
	for y := 80; y < 95; y++ { // 局部小块变化，非滚动
		for x := 10; x < 30; x++ {
			cur.Set(x, y, color.RGBA{0, 0, 0, 255})
		}
	}
	if shift, ok := detectScrollShift(base, cur); ok {
		t.Fatalf("local change misdetected as scroll: shift=%d", shift)
	}
}

func TestDetectScrollShiftRejectsUniformImage(t *testing.T) {
	// 纯色图：任意位移都"完美匹配"，纹理守卫应拒绝。solid/white 定义在 detector_test.go。
	if shift, ok := detectScrollShift(solid(120, 100, white), solid(120, 100, white)); ok {
		t.Fatalf("uniform image misdetected as scroll: shift=%d", shift)
	}
}

func TestDetectScrollShiftRejectsJitter(t *testing.T) {
	base := rowPattern(120, 100)
	if shift, ok := detectScrollShift(base, scrollUp(base, 2)); ok { // 2 < scrollMinShift
		t.Fatalf("2px jitter misdetected as scroll: shift=%d", shift)
	}
}
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `go test ./internal/diff/ -run TestDetectScrollShift -v`
Expected: 编译失败，`undefined: detectScrollShift`

- [ ] **Step 3: 实现 `scroll.go`**

创建 `internal/diff/scroll.go`：

```go
package diff

import "image"

const (
	scrollMinShift       = 4    // 小于此视为抖动，不算滚动
	scrollMaxShiftRatio  = 0.75 // 候选位移上限 = 区域高 * 此比例（保证重叠区足够大）
	scrollMatchThreshold = 8.0  // 重叠区灰度均差 ≤ 此值才可能判为滚动
	scrollMinTexture     = 4.0  // 重叠区垂直纹理下限（纯色区任意位移都"匹配"，需此守卫）
	scrollSampleStep     = 2    // 采样步长（行/列）
)

// detectScrollShift 检测 cur 相对 baseline 的垂直上滚像素数。
// 内容上滚 d 意味着 cur 行 [0,H-d) 与 baseline 行 [d,H) 重合。
// 返回 (d, true) 表示判定为滚动；否则 (0, false)。
// baseline、cur 必须同尺寸、0 基点（Detect 内已 toRGBA 保证）。
func detectScrollShift(baseline, cur *image.RGBA) (int, bool) {
	b := cur.Bounds()
	w, h := b.Dx(), b.Dy()
	maxShift := int(float64(h) * scrollMaxShiftRatio)
	if w == 0 || h == 0 || maxShift < scrollMinShift {
		return 0, false
	}
	bestShift := 0
	bestResidual := -1.0
	for d := scrollMinShift; d <= maxShift; d++ {
		res := overlapResidual(baseline, cur, d, w, h)
		if bestResidual < 0 || res < bestResidual {
			bestResidual, bestShift = res, d
		}
	}
	if bestResidual < 0 || bestResidual > scrollMatchThreshold {
		return 0, false
	}
	if overlapTexture(cur, bestShift, w, h) < scrollMinTexture {
		return 0, false // 重叠区无垂直纹理 → 匹配无意义
	}
	return bestShift, true
}

// overlapResidual 计算位移 d 下重叠区的采样灰度绝对差均值。
func overlapResidual(baseline, cur *image.RGBA, d, w, h int) float64 {
	sum, n := 0, 0
	for y := 0; y < h-d; y += scrollSampleStep {
		for x := 0; x < w; x += scrollSampleStep {
			sum += absInt(grayAt(cur, x, y) - grayAt(baseline, x, y+d))
			n++
		}
	}
	if n == 0 {
		return scrollMatchThreshold + 1
	}
	return float64(sum) / float64(n)
}

// overlapTexture 计算位移 d 下 cur 重叠区相邻行的采样灰度绝对差均值（垂直纹理强度）。
func overlapTexture(cur *image.RGBA, d, w, h int) float64 {
	sum, n := 0, 0
	for y := 0; y < h-d-1; y += scrollSampleStep {
		for x := 0; x < w; x += scrollSampleStep {
			sum += absInt(grayAt(cur, x, y) - grayAt(cur, x, y+1))
			n++
		}
	}
	if n == 0 {
		return 0
	}
	return float64(sum) / float64(n)
}
```

注：`grayAt`、`absInt` 已在 `internal/diff/detector.go` 定义，同包直接用。

- [ ] **Step 4: 运行测试，确认通过**

Run: `go test ./internal/diff/ -run TestDetectScrollShift -v`
Expected: 4 个用例全 PASS

- [ ] **Step 5: 跑整包，确认未破坏既有测试**

Run: `go test ./internal/diff/`
Expected: ok（既有 detector 用例 + 新滚动用例全过）

- [ ] **Step 6: 提交**

```bash
git add internal/diff/scroll.go internal/diff/scroll_test.go
git commit -m "feat(diff): 滚动位移检测 detectScrollShift"
```

---

## Task 2: `Detect` 接入滚动分支

**Files:**
- Modify: `internal/diff/detector.go:64-69`
- Test: `internal/diff/detector_test.go`（新增用例）

检测到变化、通过比例阈值与节流后，先试滚动检测：是滚动则裁底部 `shift` 行（全宽），否则退回现有"变化包围盒"裁切。

- [ ] **Step 1: 写失败测试**

在 `internal/diff/detector_test.go` 末尾追加（`rowPattern`、`scrollUp` 来自同包的 `scroll_test.go`）：

```go
func TestScrollChangeSendsBottomStrip(t *testing.T) {
	d := NewDetector(30, 0.005, 5, 8)
	base := rowPattern(120, 100)
	if d.Detect(base, time.Unix(0, 0)) != nil {
		t.Fatal("first frame: want nil")
	}
	got := d.Detect(scrollUp(base, 25), time.Unix(10, 0))
	if got == nil {
		t.Fatal("scroll frame: got nil, want result")
	}
	if got.Crop.Bounds().Dy() != 25 {
		t.Errorf("crop height = %d, want 25 (bottom strip)", got.Crop.Bounds().Dy())
	}
	if got.Crop.Bounds().Dx() != 120 {
		t.Errorf("crop width = %d, want 120 (full width)", got.Crop.Bounds().Dx())
	}
	if got.Bbox != image.Rect(0, 75, 120, 100) {
		t.Errorf("bbox = %v, want (0,75)-(120,100)", got.Bbox)
	}
}
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `go test ./internal/diff/ -run TestScrollChangeSendsBottomStrip -v`
Expected: FAIL——当前走包围盒分支，`crop height` ≈ 100 而非 25

- [ ] **Step 3: 修改 `Detect`**

`internal/diff/detector.go` 中，把现有的：

```go
	padded := padRect(bbox, d.bboxPadding, cur.Bounds())
	crop := cropRGBA(cur, padded)
	d.baseline = cur
	d.lastPushed = now
	d.hasPushed = true
	return &Result{Bbox: padded, Crop: crop}
```

替换为：

```go
	// 滚动场景（如聊天满后整体上滚）：变化包围盒会被撑满 ≈ 整个区域。
	// 检测出上滚像素数 → 只裁底部那条新增内容；否则退回包围盒裁切。
	var resultBbox image.Rectangle
	if shift, ok := detectScrollShift(d.baseline, cur); ok {
		cb := cur.Bounds()
		resultBbox = image.Rect(0, cb.Max.Y-shift, cb.Max.X, cb.Max.Y)
	} else {
		resultBbox = padRect(bbox, d.bboxPadding, cur.Bounds())
	}
	crop := cropRGBA(cur, resultBbox)
	d.baseline = cur
	d.lastPushed = now
	d.hasPushed = true
	return &Result{Bbox: resultBbox, Crop: crop}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `go test ./internal/diff/`
Expected: ok（新用例 + 既有用例全过——既有用例的纯色背景+小色块在纹理守卫处被拒，仍走包围盒分支，行为不变）

- [ ] **Step 5: 提交**

```bash
git add internal/diff/detector.go internal/diff/detector_test.go
git commit -m "feat(diff): Detect 滚动场景只裁底部新增条"
```

---

## Task 3: 生成托盘三态图标

**Files:**
- Create: `tools/genicons/main.go`
- 产物: `internal/tray/icon_running.ico`、`icon_paused.ico`、`icon_error.ico`

一次性 Go 程序，生成绿/黄/红实心圆图标，PNG-in-ICO 格式（与现有 `icon.ico` 一致，16×16 + 24×24）。

- [ ] **Step 1: 写生成程序**

创建 `tools/genicons/main.go`：

```go
// Command genicons 生成托盘三态图标（绿/黄/红实心圆，PNG-in-ICO）。
// 一次性运行：从仓库根执行 `go run ./tools/genicons`，产物提交进仓库。
package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"os"
)

func main() {
	states := []struct {
		name string
		c    color.RGBA
	}{
		{"running", color.RGBA{0x3C, 0xB3, 0x71, 0xFF}}, // 绿
		{"paused", color.RGBA{0xE0, 0xA8, 0x10, 0xFF}},  // 黄
		{"error", color.RGBA{0xD0, 0x3A, 0x3A, 0xFF}},   // 红
	}
	sizes := []int{16, 24}
	for _, s := range states {
		var pngs [][]byte
		for _, sz := range sizes {
			pngs = append(pngs, pngCircle(sz, s.c))
		}
		path := "internal/tray/icon_" + s.name + ".ico"
		if err := os.WriteFile(path, buildICO(pngs, sizes), 0o644); err != nil {
			panic(err)
		}
		fmt.Println("wrote", path)
	}
}

// pngCircle 画一个填满 size×size 的实心圆，圆外透明。
func pngCircle(size int, c color.RGBA) []byte {
	img := image.NewRGBA(image.Rect(0, 0, size, size))
	r := float64(size) / 2
	for y := 0; y < size; y++ {
		for x := 0; x < size; x++ {
			dx, dy := float64(x)+0.5-r, float64(y)+0.5-r
			if dx*dx+dy*dy <= r*r {
				img.Set(x, y, c)
			}
		}
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		panic(err)
	}
	return buf.Bytes()
}

// buildICO 把多张 PNG 包进 .ico（ICONDIR + ICONDIRENTRY[] + PNG 数据）。
func buildICO(pngs [][]byte, sizes []int) []byte {
	var buf bytes.Buffer
	n := len(pngs)
	binary.Write(&buf, binary.LittleEndian, uint16(0)) // reserved
	binary.Write(&buf, binary.LittleEndian, uint16(1)) // type = icon
	binary.Write(&buf, binary.LittleEndian, uint16(n)) // count
	offset := 6 + 16*n
	for i, p := range pngs {
		buf.WriteByte(byte(sizes[i]))                           // width
		buf.WriteByte(byte(sizes[i]))                           // height
		buf.WriteByte(0)                                        // 调色板色数
		buf.WriteByte(0)                                        // reserved
		binary.Write(&buf, binary.LittleEndian, uint16(1))      // 颜色平面数
		binary.Write(&buf, binary.LittleEndian, uint16(32))     // 位深
		binary.Write(&buf, binary.LittleEndian, uint32(len(p))) // 数据字节数
		binary.Write(&buf, binary.LittleEndian, uint32(offset)) // 数据偏移
		offset += len(p)
	}
	for _, p := range pngs {
		buf.Write(p)
	}
	return buf.Bytes()
}
```

- [ ] **Step 2: 运行生成程序**

从仓库根运行：`go run ./tools/genicons`
Expected: 输出 `wrote internal/tray/icon_running.ico` 等三行

- [ ] **Step 3: 验证产物格式**

Run: `file internal/tray/icon_running.ico internal/tray/icon_paused.ico internal/tray/icon_error.ico`
Expected: 每个都是 `MS Windows icon resource ... 16x16 ... 24x24`

- [ ] **Step 4: 提交**

```bash
git add tools/genicons/main.go internal/tray/icon_running.ico internal/tray/icon_paused.ico internal/tray/icon_error.ico
git commit -m "feat(tray): genicons 生成绿/黄/红三态图标"
```

---

## Task 4: `tray.go` 三态切换图标

**Files:**
- Modify: `internal/tray/tray.go`
- Delete: `internal/tray/icon.ico`

把单图标改为嵌入三态图标，`SetState` 时切换。

- [ ] **Step 1: 重写 `tray.go`**

把 `internal/tray/tray.go` 整体替换为：

```go
//go:build windows

// Package tray 提供 Windows 系统托盘图标与菜单。
package tray

import (
	_ "embed"

	"fyne.io/systray"
)

//go:embed icon_running.ico
var iconRunning []byte

//go:embed icon_paused.ico
var iconPaused []byte

//go:embed icon_error.ico
var iconError []byte

// Callbacks 是托盘菜单各项被点击时调用的回调。
type Callbacks struct {
	OnTogglePause func()
	OnPickRegion  func()
	OnOpenConfig  func()
	OnOpenFrames  func()
	OnQuit        func()
}

// State 是托盘显示的运行状态。
type State int

const (
	StateRunning State = iota
	StatePaused
	StateError
)

var pauseItem *systray.MenuItem

// Run 启动托盘（阻塞，必须在 main goroutine 调用）。
// onReady 在托盘就绪后调用，用于启动 watcher 等。
func Run(cb Callbacks, onReady func()) {
	systray.Run(func() {
		systray.SetIcon(iconRunning)
		systray.SetTitle("Screen Watchdog")
		systray.SetTooltip("Screen Watchdog")

		pauseItem = systray.AddMenuItem("暂停", "暂停/恢复监控")
		pickItem := systray.AddMenuItem("重新框选区域", "拖拽选择监控区域")
		systray.AddSeparator()
		cfgItem := systray.AddMenuItem("打开配置文件", "")
		framesItem := systray.AddMenuItem("打开截图目录", "")
		systray.AddSeparator()
		quitItem := systray.AddMenuItem("退出", "")

		go func() {
			for {
				select {
				case <-pauseItem.ClickedCh:
					cb.OnTogglePause()
				case <-pickItem.ClickedCh:
					cb.OnPickRegion()
				case <-cfgItem.ClickedCh:
					cb.OnOpenConfig()
				case <-framesItem.ClickedCh:
					cb.OnOpenFrames()
				case <-quitItem.ClickedCh:
					cb.OnQuit()
					systray.Quit()
					return
				}
			}
		}()

		onReady()
	}, func() {})
}

// SetState 更新托盘图标 + tooltip + 暂停项文案以反映状态。
func SetState(s State, detail string) {
	switch s {
	case StateRunning:
		systray.SetIcon(iconRunning)
		systray.SetTooltip("Screen Watchdog · 运行中")
		if pauseItem != nil {
			pauseItem.SetTitle("暂停")
		}
	case StatePaused:
		systray.SetIcon(iconPaused)
		systray.SetTooltip("Screen Watchdog · 已暂停")
		if pauseItem != nil {
			pauseItem.SetTitle("恢复")
		}
	case StateError:
		systray.SetIcon(iconError)
		systray.SetTooltip("Screen Watchdog · 错误: " + detail)
	}
}
```

- [ ] **Step 2: 删除旧图标**

Run: `git rm internal/tray/icon.ico`

- [ ] **Step 3: 交叉编译验证**

Run: `CGO_ENABLED=0 GOOS=windows go build ./...`
Expected: 无输出（编译通过）；`//go:embed` 能找到三个 `.ico`

- [ ] **Step 4: 提交**

```bash
git add internal/tray/tray.go
git commit -m "feat(tray): 运行/暂停/异常三态切换图标"
```

---

## Task 5: `picker.go` 重写——遮罩抠洞 + 按钮确认

**Files:**
- Rewrite: `internal/picker/picker.go`

从"均匀半透明窗口"改为"GDI 自绘 + 三态状态机"。`Pick()` 签名不变，`main.go` 无需改。Windows-only，无单测，靠交叉编译 + 实测验证。

- [ ] **Step 1: 整体重写 `picker.go`**

把 `internal/picker/picker.go` 整体替换为：

```go
//go:build windows

// Package picker 提供 Windows 全屏拖拽框选遮罩：半透明灰色蒙版 +
// 选区抠透明洞 + 实时边框/尺寸标签 + 屏上确认/取消按钮。
package picker

import (
	"fmt"
	"runtime"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	user32   = windows.NewLazySystemDLL("user32.dll")
	gdi32    = windows.NewLazySystemDLL("gdi32.dll")
	kernel32 = windows.NewLazySystemDLL("kernel32.dll")

	pRegisterClassExW      = user32.NewProc("RegisterClassExW")
	pCreateWindowExW       = user32.NewProc("CreateWindowExW")
	pDefWindowProcW        = user32.NewProc("DefWindowProcW")
	pDestroyWindow         = user32.NewProc("DestroyWindow")
	pGetMessageW           = user32.NewProc("GetMessageW")
	pTranslateMessage      = user32.NewProc("TranslateMessage")
	pDispatchMessageW      = user32.NewProc("DispatchMessageW")
	pPostQuitMessage       = user32.NewProc("PostQuitMessage")
	pGetSystemMetrics      = user32.NewProc("GetSystemMetrics")
	pSetLayeredWindowAttrs = user32.NewProc("SetLayeredWindowAttributes")
	pSetCapture            = user32.NewProc("SetCapture")
	pReleaseCapture        = user32.NewProc("ReleaseCapture")
	pLoadCursorW           = user32.NewProc("LoadCursorW")
	pShowWindow            = user32.NewProc("ShowWindow")
	pSetForegroundWindow   = user32.NewProc("SetForegroundWindow")
	pInvalidateRect        = user32.NewProc("InvalidateRect")
	pBeginPaint            = user32.NewProc("BeginPaint")
	pEndPaint              = user32.NewProc("EndPaint")
	pFillRect              = user32.NewProc("FillRect")
	pGetClientRect         = user32.NewProc("GetClientRect")

	pCreateSolidBrush = gdi32.NewProc("CreateSolidBrush")
	pCreatePen        = gdi32.NewProc("CreatePen")
	pSelectObject     = gdi32.NewProc("SelectObject")
	pDeleteObject     = gdi32.NewProc("DeleteObject")
	pRectangle        = gdi32.NewProc("Rectangle")
	pSetBkMode        = gdi32.NewProc("SetBkMode")
	pSetTextColor     = gdi32.NewProc("SetTextColor")
	pTextOutW         = gdi32.NewProc("TextOutW")
	pGetStockObject   = gdi32.NewProc("GetStockObject")

	pGetModuleHandleW = kernel32.NewProc("GetModuleHandleW")
)

const (
	wsExLayered    = 0x00080000
	wsExTopmost    = 0x00000008
	wsExToolwindow = 0x00000080
	wsPopup        = 0x80000000

	swShow = 5

	smCXScreen = 0
	smCYScreen = 1

	lwaColorKey = 0x00000001
	lwaAlpha    = 0x00000002

	wmDestroy     = 0x0002
	wmPaint       = 0x000F
	wmEraseBkgnd  = 0x0014
	wmKeyDown     = 0x0100
	wmMouseMove   = 0x0200
	wmLButtonDown = 0x0201
	wmLButtonUp   = 0x0202

	vkReturn = 0x0D
	vkEscape = 0x1B

	idcCross = 32515

	psSolid       = 0
	transparentBk = 1
	nullBrushObj  = 5

	// 颜色：COLORREF = 0x00BBGGRR
	colKey     = 0x00FF00FF // 品红，colorkey 透明色（选区抠洞）
	colMask    = 0x00141414 // 深灰蒙版
	colBorder  = 0x0050E030 // 亮绿边框
	colWhite   = 0x00FFFFFF
	colConfirm = 0x004CA64C // 确认按钮底（绿）
	colCancel  = 0x003A3AD0 // 取消按钮底（红）

	maskAlpha = 150 // 蒙版/UI 不透明度（0-255）

	minSize   = 10 // 选区最小边长（px）
	btnW      = 110
	btnH      = 36
	btnGap    = 14
	btnMargin = 12
)

const (
	stateIdle = iota
	stateDragging
	statePreview
)

type wndclassexw struct {
	cbSize        uint32
	style         uint32
	lpfnWndProc   uintptr
	cbClsExtra    int32
	cbWndExtra    int32
	hInstance     windows.Handle
	hIcon         windows.Handle
	hCursor       windows.Handle
	hbrBackground windows.Handle
	lpszMenuName  *uint16
	lpszClassName *uint16
	hIconSm       windows.Handle
}

type point struct{ X, Y int32 }

type rect struct{ left, top, right, bottom int32 }

type msg struct {
	hwnd    windows.Handle
	message uint32
	wParam  uintptr
	lParam  uintptr
	time    uint32
	pt      point
}

type paintstruct struct {
	hdc         windows.Handle
	fErase      int32
	rcPaint     rect
	fRestore    int32
	fIncUpdate  int32
	rgbReserved [32]byte
}

// 单次 Pick 调用内的状态（Pick 串行调用，无并发）。
var (
	pickState       int
	startPt, curPt  point
	selRect         rect
	confirmRect     rect
	cancelRect      rect
	picked          bool
	cancelled       bool
	pickHWND        windows.Handle
	classRegistered bool
)

func loword(l uintptr) int32 { return int32(int16(l & 0xffff)) }
func hiword(l uintptr) int32 { return int32(int16((l >> 16) & 0xffff)) }

// normRect 把两个对角点规范化为 left<=right、top<=bottom 的矩形。
func normRect(a, b point) rect {
	r := rect{a.X, a.Y, b.X, b.Y}
	if r.left > r.right {
		r.left, r.right = r.right, r.left
	}
	if r.top > r.bottom {
		r.top, r.bottom = r.bottom, r.top
	}
	return r
}

func ptInRect(x, y int32, r rect) bool {
	return x >= r.left && x < r.right && y >= r.top && y < r.bottom
}

// invalidate 触发重绘；bErase=FALSE，全部内容由 WM_PAINT 自绘，减少闪烁。
func invalidate(hwnd uintptr) { pInvalidateRect.Call(hwnd, 0, 0) }

// drawText 用当前 DC 字体在 (x,y) 输出 UTF-16 文本。
func drawText(hdc uintptr, x, y int, s string) {
	u16, err := syscall.UTF16FromString(s)
	if err != nil || len(u16) <= 1 {
		return
	}
	pTextOutW.Call(hdc, uintptr(x), uintptr(y),
		uintptr(unsafe.Pointer(&u16[0])), uintptr(len(u16)-1))
}

// layoutButtons 按选区位置算出确认/取消按钮矩形（优先放选区下方，无处则放上方）。
func layoutButtons(sel, client rect) {
	total := int32(btnW*2 + btnGap)
	x := sel.left
	if x+total > client.right {
		x = client.right - total
	}
	if x < 0 {
		x = 0
	}
	y := sel.bottom + btnMargin
	if y+btnH > client.bottom {
		y = sel.top - btnMargin - btnH
	}
	if y < 0 {
		y = 0
	}
	confirmRect = rect{x, y, x + btnW, y + btnH}
	cancelRect = rect{x + btnW + btnGap, y, x + btnW + btnGap + btnW, y + btnH}
}

// drawButton 画一个填色按钮 + 居中文字。
func drawButton(hdc uintptr, r rect, bg uintptr, label string) {
	brush, _, _ := pCreateSolidBrush.Call(bg)
	pFillRect.Call(hdc, uintptr(unsafe.Pointer(&r)), brush)
	pDeleteObject.Call(brush)
	pSetBkMode.Call(hdc, transparentBk)
	pSetTextColor.Call(hdc, colWhite)
	drawText(hdc, int(r.left)+22, int(r.top)+9, label)
}

// onPaint 自绘整窗：蒙版 → 选区抠洞 → 边框 → 尺寸标签 →（预览态）按钮。
func onPaint(hwnd uintptr) {
	var ps paintstruct
	hdc, _, _ := pBeginPaint.Call(hwnd, uintptr(unsafe.Pointer(&ps)))
	defer pEndPaint.Call(hwnd, uintptr(unsafe.Pointer(&ps)))

	var client rect
	pGetClientRect.Call(hwnd, uintptr(unsafe.Pointer(&client)))

	// 1. 整屏半透明灰色蒙版
	maskBrush, _, _ := pCreateSolidBrush.Call(colMask)
	pFillRect.Call(hdc, uintptr(unsafe.Pointer(&client)), maskBrush)
	pDeleteObject.Call(maskBrush)

	if pickState == stateIdle {
		return
	}

	sel := selRect
	if pickState == stateDragging {
		sel = normRect(startPt, curPt)
	}

	// 2. 选区填 colorkey 色 → 被分层窗口抠成全透明洞
	keyBrush, _, _ := pCreateSolidBrush.Call(colKey)
	pFillRect.Call(hdc, uintptr(unsafe.Pointer(&sel)), keyBrush)
	pDeleteObject.Call(keyBrush)

	// 3. 选区亮绿边框
	pen, _, _ := pCreatePen.Call(psSolid, 2, colBorder)
	nullBrush, _, _ := pGetStockObject.Call(nullBrushObj)
	oldPen, _, _ := pSelectObject.Call(hdc, pen)
	oldBrush, _, _ := pSelectObject.Call(hdc, nullBrush)
	pRectangle.Call(hdc, uintptr(sel.left), uintptr(sel.top), uintptr(sel.right), uintptr(sel.bottom))
	pSelectObject.Call(hdc, oldPen)
	pSelectObject.Call(hdc, oldBrush)
	pDeleteObject.Call(pen)

	// 4. 尺寸标签（画在选区上方蒙版区，避免落进透明洞看不清）
	pSetBkMode.Call(hdc, transparentBk)
	pSetTextColor.Call(hdc, colWhite)
	labelY := int(sel.top) - 20
	if labelY < 0 {
		labelY = int(sel.top) + 4
	}
	drawText(hdc, int(sel.left)+2, labelY,
		fmt.Sprintf("%d × %d", sel.right-sel.left, sel.bottom-sel.top))

	// 5. 预览态：画确认/取消按钮
	if pickState == statePreview {
		layoutButtons(sel, client)
		drawButton(hdc, confirmRect, colConfirm, "确认")
		drawButton(hdc, cancelRect, colCancel, "取消")
	}
}

// wndProc 全参数用 uintptr —— syscall.NewCallback 要求参数为 uintptr 尺寸。
func wndProc(hwnd, message, wParam, lParam uintptr) uintptr {
	switch message {
	case wmEraseBkgnd:
		return 1 // 背景全部由 WM_PAINT 自绘，跳过擦除以减少闪烁
	case wmPaint:
		onPaint(hwnd)
		return 0
	case wmLButtonDown:
		x, y := loword(lParam), hiword(lParam)
		if pickState == statePreview {
			if ptInRect(x, y, confirmRect) {
				picked = true
				pPostQuitMessage.Call(0)
				return 0
			}
			if ptInRect(x, y, cancelRect) {
				cancelled = true
				pPostQuitMessage.Call(0)
				return 0
			}
		}
		// idle，或预览态在按钮外按下 → 起一次新拖拽
		startPt = point{x, y}
		curPt = startPt
		pickState = stateDragging
		pSetCapture.Call(hwnd)
		invalidate(hwnd)
		return 0
	case wmMouseMove:
		if pickState == stateDragging {
			curPt = point{loword(lParam), hiword(lParam)}
			invalidate(hwnd)
		}
		return 0
	case wmLButtonUp:
		if pickState == stateDragging {
			curPt = point{loword(lParam), hiword(lParam)}
			pReleaseCapture.Call()
			selRect = normRect(startPt, curPt)
			if selRect.right-selRect.left >= minSize && selRect.bottom-selRect.top >= minSize {
				pickState = statePreview
			} else {
				pickState = stateIdle
			}
			invalidate(hwnd)
		}
		return 0
	case wmKeyDown:
		switch wParam {
		case vkEscape:
			cancelled = true
			pPostQuitMessage.Call(0)
		case vkReturn:
			if pickState == statePreview {
				picked = true
				pPostQuitMessage.Call(0)
			}
		}
		return 0
	case wmDestroy:
		pPostQuitMessage.Call(0)
		return 0
	}
	ret, _, _ := pDefWindowProcW.Call(hwnd, message, wParam, lParam)
	return ret
}

// Pick 弹出全屏遮罩让用户拖拽选区，确认后返回选中矩形的 x,y,w,h。
// ok=false 表示用户取消（✗ / Esc）或选区无效。
func Pick() (x, y, w, h int, ok bool, err error) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()

	pickState = stateIdle
	picked, cancelled = false, false
	startPt, curPt = point{}, point{}
	selRect, confirmRect, cancelRect = rect{}, rect{}, rect{}

	hInstance, _, _ := pGetModuleHandleW.Call(0)
	className, _ := syscall.UTF16PtrFromString("SOWRegionPicker")

	// 窗口类只注册一次：Win32 不允许重复注册同名类（返回 ERROR_CLASS_ALREADY_EXISTS），
	// 且 syscall.NewCallback 的回调 thunk 数量有限，也应只生成一次。
	if !classRegistered {
		cursor, _, _ := pLoadCursorW.Call(0, uintptr(idcCross))
		wc := wndclassexw{
			cbSize:        uint32(unsafe.Sizeof(wndclassexw{})),
			lpfnWndProc:   syscall.NewCallback(wndProc),
			hInstance:     windows.Handle(hInstance),
			hCursor:       windows.Handle(cursor),
			lpszClassName: className,
		}
		if ret, _, e := pRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc))); ret == 0 {
			return 0, 0, 0, 0, false, fmt.Errorf("picker: RegisterClassExW: %v", e)
		}
		classRegistered = true
	}

	cx, _, _ := pGetSystemMetrics.Call(smCXScreen)
	cy, _, _ := pGetSystemMetrics.Call(smCYScreen)

	hwnd, _, e := pCreateWindowExW.Call(
		uintptr(wsExLayered|wsExTopmost|wsExToolwindow),
		uintptr(unsafe.Pointer(className)),
		0,
		uintptr(wsPopup),
		0, 0, cx, cy,
		0, 0, hInstance, 0,
	)
	if hwnd == 0 {
		return 0, 0, 0, 0, false, fmt.Errorf("picker: CreateWindowExW: %v", e)
	}
	pickHWND = windows.Handle(hwnd)

	// 分层窗口：colorkey 色全透明（选区洞），其余像素按 maskAlpha 半透明（蒙版/UI）。
	pSetLayeredWindowAttrs.Call(hwnd, colKey, uintptr(maskAlpha), uintptr(lwaColorKey|lwaAlpha))
	pShowWindow.Call(hwnd, swShow)
	pSetForegroundWindow.Call(hwnd) // 取前台焦点，确保收到 Esc/Enter 键盘消息

	var m msg
	for {
		ret, _, _ := pGetMessageW.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(ret) <= 0 {
			break
		}
		pTranslateMessage.Call(uintptr(unsafe.Pointer(&m)))
		pDispatchMessageW.Call(uintptr(unsafe.Pointer(&m)))
	}
	pDestroyWindow.Call(uintptr(pickHWND))

	if cancelled || !picked {
		return 0, 0, 0, 0, false, nil
	}
	r := selRect
	w, h = int(r.right-r.left), int(r.bottom-r.top)
	if w < minSize || h < minSize {
		return 0, 0, 0, 0, false, nil
	}
	return int(r.left), int(r.top), w, h, true, nil
}
```

- [ ] **Step 2: 交叉编译验证**

Run: `CGO_ENABLED=0 GOOS=windows go build ./...`
Expected: 无输出（编译通过）

- [ ] **Step 3: 格式检查**

Run: `gofmt -l internal/picker/picker.go`
Expected: 无输出（已是 gofmt 规范）。若有输出，运行 `gofmt -w internal/picker/picker.go`

- [ ] **Step 4: 提交**

```bash
git add internal/picker/picker.go
git commit -m "feat(picker): 灰色蒙版抠洞 + 实时选区 + 屏上按钮确认"
```

---

## Task 6: 全量验证

**Files:** 无（仅验证）

- [ ] **Step 1: 核心包测试**

Run: `go test ./internal/...`
Expected: 各包 ok（`internal/diff` 含新滚动用例；Windows-only 包 picker/tray/capture 在 Linux 下无测试文件，跳过即可）

- [ ] **Step 2: Windows 交叉编译**

Run: `CGO_ENABLED=0 GOOS=windows go build -ldflags="-H windowsgui -s -w" -o ScreenWatchdog.exe .`
Expected: 生成 `ScreenWatchdog.exe`

- [ ] **Step 3: 确认产物**

Run: `file ScreenWatchdog.exe`
Expected: `PE32+ executable (GUI) x86-64`

- [ ] **Step 4: 清理产物**

Run: `rm -f ScreenWatchdog.exe`（`.exe` 已在 `.gitignore`，无需提交）

> Windows 实测（不在本计划自动化范围）：框选遮罩抠洞、拖拽实时边框/尺寸、✓/✗ 按钮与 Esc/Enter、托盘三态变色、聊天滚动只推底部新增条。

---

## Self-Review

**Spec coverage：**
- 需求 1（遮罩抠洞 + 按钮确认）→ Task 5 ✓
- 需求 2（滚动 diff 只发新增区域）→ Task 1 + Task 2 ✓
- 需求 3（托盘三态配色）→ Task 3 + Task 4 ✓
- spec「影响文件汇总」九个条目均有对应任务 ✓
- spec「验证」→ Task 6 ✓

**Placeholder 扫描：** 无 TBD/TODO；每个改代码的步骤都给了完整代码与确切命令。

**类型一致性：** `detectScrollShift(baseline, cur *image.RGBA) (int, bool)` 在 Task 1 定义、Task 2 调用，签名一致；`Result{Bbox, Crop}`、`grayAt`、`absInt`、`padRect`、`cropRGBA` 均为既有符号；tray 的 `iconRunning/iconPaused/iconError` 与 genicons 产出的 `icon_running/paused/error.ico` 文件名一致；picker 的 `stateIdle/stateDragging/statePreview`、`confirmRect/cancelRect` 等定义与使用一致。
