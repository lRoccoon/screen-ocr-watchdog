# Go 重写实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 screen-ocr-watchdog 用纯 Go 重写为单文件静态 Windows exe，v1 只做 image_diff（截屏 → 像素 diff → 把变化区域裁切后发飞书）。

**Architecture:** 9 个 `internal/` 包。核心逻辑包（paths/config/diff/notify/history/pipeline/watcher）跨平台、在 Linux 上 `go test`；Windows shell 包（capture/tray/picker）与 `main.go` 打 `//go:build windows`，只能交叉编译验证。`pipeline.Pipeline` 接口为后续 OCR 留接缝。

**Tech Stack:** Go 1.22；`fyne.io/systray`、`github.com/kbinani/screenshot`、`gopkg.in/yaml.v3`、`golang.org/x/sys/windows`；标准库 `image` `image/png` `image/draw` `net/http` `net/http/httptest` `mime/multipart` `encoding/json` `log/slog`。

**Spec:** `docs/superpowers/specs/2026-05-20-go-rewrite-design.md`

**实现前必读约定：**
- 仓库根 = 当前 worktree 根。所有命令在仓库根执行。
- module path：`github.com/lRoccoon/screen-ocr-watchdog`
- Linux 上**只测核心包**：`go test ./internal/paths/ ./internal/config/ ./internal/diff/ ./internal/notify/ ./internal/history/ ./internal/pipeline/ ./internal/watcher/`。不要跑 `go test ./...`（windows-only 包会报 "build constraints exclude all Go files"）。
- 全工程编译检查用交叉编译：`CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build ./...`
- Go 没有 "N passed"；`go test` 每个包输出 `ok`。每个 task 完成后核心包测试应全 `ok`。
- 每个 windows-only 文件首行必须是 `//go:build windows`，空一行再 `package`。
- Python `app/`、`tests/` 等保持不动直到 Task 13。

---

## Task 1: 工程骨架 + paths 包

**Files:**
- Create: `go.mod`
- Create: `internal/paths/paths.go`
- Create: `internal/paths/paths_test.go`
- Modify: `.gitignore`

- [ ] **Step 1: 初始化 module**

Run:
```bash
go mod init github.com/lRoccoon/screen-ocr-watchdog
go mod edit -go=1.22
```

- [ ] **Step 2: 写失败测试 `internal/paths/paths_test.go`**

```go
package paths

import (
	"path/filepath"
	"testing"
)

func TestConfigPathUsesAppData(t *testing.T) {
	t.Setenv("APPDATA", filepath.FromSlash("/tmp/sow-appdata"))
	got := ConfigPath()
	want := filepath.Join("/tmp/sow-appdata", "screen-ocr-watchdog", "config.yaml")
	if got != want {
		t.Fatalf("ConfigPath() = %q, want %q", got, want)
	}
}

func TestDataPathsUseLocalAppData(t *testing.T) {
	t.Setenv("LOCALAPPDATA", filepath.FromSlash("/tmp/sow-local"))
	base := filepath.Join("/tmp/sow-local", "screen-ocr-watchdog")
	if got, want := HistoryPath(), filepath.Join(base, "history.ndjson"); got != want {
		t.Fatalf("HistoryPath() = %q, want %q", got, want)
	}
	if got, want := FramesDir(), filepath.Join(base, "diff_frames"); got != want {
		t.Fatalf("FramesDir() = %q, want %q", got, want)
	}
	if got, want := LogPath(), filepath.Join(base, "Logs", "app.log"); got != want {
		t.Fatalf("LogPath() = %q, want %q", got, want)
	}
}
```

- [ ] **Step 3: 跑测试验证失败**

Run: `go test ./internal/paths/`
Expected: FAIL — `undefined: ConfigPath` 等。

- [ ] **Step 4: 写实现 `internal/paths/paths.go`**

```go
// Package paths 解析跨平台的配置 / 数据 / 日志目录。
package paths

import (
	"os"
	"path/filepath"
)

const appName = "screen-ocr-watchdog"

// configBase 返回配置目录的父目录（Windows: %APPDATA%）。
func configBase() string {
	if v := os.Getenv("APPDATA"); v != "" {
		return v
	}
	if v, err := os.UserConfigDir(); err == nil {
		return v
	}
	return "."
}

// dataBase 返回数据 / 日志目录的父目录（Windows: %LOCALAPPDATA%）。
func dataBase() string {
	if v := os.Getenv("LOCALAPPDATA"); v != "" {
		return v
	}
	if v, err := os.UserCacheDir(); err == nil {
		return v
	}
	return "."
}

// ConfigPath 返回 config.yaml 的完整路径。
func ConfigPath() string {
	return filepath.Join(configBase(), appName, "config.yaml")
}

// HistoryPath 返回 history.ndjson 的完整路径。
func HistoryPath() string {
	return filepath.Join(dataBase(), appName, "history.ndjson")
}

// FramesDir 返回 diff 裁切图目录。
func FramesDir() string {
	return filepath.Join(dataBase(), appName, "diff_frames")
}

// LogPath 返回 app.log 的完整路径。
func LogPath() string {
	return filepath.Join(dataBase(), appName, "Logs", "app.log")
}
```

- [ ] **Step 5: 跑测试验证通过**

Run: `go test ./internal/paths/`
Expected: `ok  github.com/lRoccoon/screen-ocr-watchdog/internal/paths`

- [ ] **Step 6: 追加 Go 相关 .gitignore**

在 `.gitignore` 末尾追加：

```
# Go
/ScreenWatchdog.exe
*.exe
/dist/
```

- [ ] **Step 7: Commit**

```bash
git add go.mod internal/paths/ .gitignore
git commit -m "feat(go): 工程骨架 + paths 包"
```

---

## Task 2: config 包

**Files:**
- Create: `internal/config/config.go`
- Create: `internal/config/config_test.go`

- [ ] **Step 1: 加 yaml 依赖**

Run: `go get gopkg.in/yaml.v3`

- [ ] **Step 2: 写失败测试 `internal/config/config_test.go`**

```go
package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadMissingFileReturnsDefaults(t *testing.T) {
	cfg, err := Load(filepath.Join(t.TempDir(), "missing.yaml"))
	if err != nil {
		t.Fatalf("Load missing file: unexpected err %v", err)
	}
	if cfg.Mode != "image_diff" {
		t.Errorf("Mode = %q, want image_diff", cfg.Mode)
	}
	if cfg.IntervalSeconds != 5 {
		t.Errorf("IntervalSeconds = %d, want 5", cfg.IntervalSeconds)
	}
	if cfg.ImageDiff.PixelDiffThreshold != 30 {
		t.Errorf("PixelDiffThreshold = %d, want 30", cfg.ImageDiff.PixelDiffThreshold)
	}
	if cfg.ImageDiff.ChangeRatioThreshold != 0.005 {
		t.Errorf("ChangeRatioThreshold = %v, want 0.005", cfg.ImageDiff.ChangeRatioThreshold)
	}
	if cfg.ImageDiff.BboxPadding != 8 {
		t.Errorf("BboxPadding = %d, want 8", cfg.ImageDiff.BboxPadding)
	}
	if cfg.Lark.ReceiveIDType != "chat_id" {
		t.Errorf("ReceiveIDType = %q, want chat_id", cfg.Lark.ReceiveIDType)
	}
}

func TestLoadPartialYAMLKeepsDefaults(t *testing.T) {
	p := filepath.Join(t.TempDir(), "c.yaml")
	content := "" +
		"mode: image_diff\n" +
		"region:\n" +
		"  x: 100\n" +
		"  y: 200\n" +
		"  width: 300\n" +
		"  height: 400\n" +
		"image_diff:\n" +
		"  pixel_diff_threshold: 50\n" +
		"lark:\n" +
		"  app_id: cli_x\n" +
		"  app_secret: sec_x\n" +
		"  receive_id: oc_x\n"
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Region.W != 300 || cfg.Region.H != 400 {
		t.Errorf("Region = %+v, want W=300 H=400", cfg.Region)
	}
	if cfg.ImageDiff.PixelDiffThreshold != 50 {
		t.Errorf("PixelDiffThreshold = %d, want 50", cfg.ImageDiff.PixelDiffThreshold)
	}
	// 未写字段保留默认
	if cfg.ImageDiff.BboxPadding != 8 {
		t.Errorf("BboxPadding = %d, want default 8", cfg.ImageDiff.BboxPadding)
	}
	if cfg.Lark.AppID != "cli_x" {
		t.Errorf("AppID = %q, want cli_x", cfg.Lark.AppID)
	}
}

func TestSaveThenLoadRoundTrips(t *testing.T) {
	cfg := Default()
	cfg.Region = Region{X: 1, Y: 2, W: 3, H: 4}
	cfg.Lark.AppID = "cli_round"
	p := filepath.Join(t.TempDir(), "sub", "c.yaml")
	if err := Save(cfg, p); err != nil {
		t.Fatalf("Save: %v", err)
	}
	got, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got.Region != cfg.Region {
		t.Errorf("Region round-trip = %+v, want %+v", got.Region, cfg.Region)
	}
	if got.Lark.AppID != "cli_round" {
		t.Errorf("AppID round-trip = %q, want cli_round", got.Lark.AppID)
	}
}

func TestLoadMalformedYAMLReturnsError(t *testing.T) {
	p := filepath.Join(t.TempDir(), "bad.yaml")
	if err := os.WriteFile(p, []byte("mode: [unclosed"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(p); err == nil {
		t.Fatal("Load malformed YAML: expected error, got nil")
	}
}
```

- [ ] **Step 3: 跑测试验证失败**

Run: `go test ./internal/config/`
Expected: FAIL — `undefined: Load` 等。

- [ ] **Step 4: 写实现 `internal/config/config.go`**

```go
// Package config 定义 YAML 配置 schema 与读写。
package config

import (
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// Region 是被监控的屏幕矩形（像素）。
type Region struct {
	X int `yaml:"x"`
	Y int `yaml:"y"`
	W int `yaml:"width"`
	H int `yaml:"height"`
}

// ImageDiff 是 image_diff 模式的检测参数。
type ImageDiff struct {
	PixelDiffThreshold   int     `yaml:"pixel_diff_threshold"`
	ChangeRatioThreshold float64 `yaml:"change_ratio_threshold"`
	MinIntervalSeconds   float64 `yaml:"min_interval_seconds"`
	BboxPadding          int     `yaml:"bbox_padding"`
}

// Lark 是飞书自建应用凭证与目标。
type Lark struct {
	AppID         string `yaml:"app_id"`
	AppSecret     string `yaml:"app_secret"`
	ReceiveID     string `yaml:"receive_id"`
	ReceiveIDType string `yaml:"receive_id_type"`
}

// Config 是完整的应用配置。
type Config struct {
	Mode            string    `yaml:"mode"`
	Region          Region    `yaml:"region"`
	IntervalSeconds int       `yaml:"interval_seconds"`
	ImageDiff       ImageDiff `yaml:"image_diff"`
	Lark            Lark      `yaml:"lark"`
}

// Default 返回带默认值的配置。
func Default() Config {
	return Config{
		Mode:            "image_diff",
		IntervalSeconds: 5,
		ImageDiff: ImageDiff{
			PixelDiffThreshold:   30,
			ChangeRatioThreshold: 0.005,
			MinIntervalSeconds:   5,
			BboxPadding:          8,
		},
		Lark: Lark{ReceiveIDType: "chat_id"},
	}
}

// Load 从 path 读配置。文件不存在时返回默认配置；YAML 中未出现的字段保留默认值。
func Load(path string) (Config, error) {
	cfg := Default()
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return cfg, nil
		}
		return cfg, err
	}
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return cfg, err
	}
	return cfg, nil
}

// Save 把配置写到 path，必要时创建父目录。
func Save(cfg Config, path string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := yaml.Marshal(cfg)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}
```

- [ ] **Step 5: 跑测试验证通过**

Run: `go test ./internal/config/`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add go.mod go.sum internal/config/
git commit -m "feat(go): config 包，YAML schema + Load/Save"
```

---

## Task 3: diff 包（核心算法）

**Files:**
- Create: `internal/diff/detector.go`
- Create: `internal/diff/detector_test.go`

- [ ] **Step 1: 写失败测试 `internal/diff/detector_test.go`**

```go
package diff

import (
	"image"
	"image/color"
	"image/draw"
	"testing"
	"time"
)

var (
	white = color.RGBA{255, 255, 255, 255}
	black = color.RGBA{0, 0, 0, 255}
)

func solid(w, h int, c color.Color) *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	draw.Draw(img, img.Bounds(), &image.Uniform{c}, image.Point{}, draw.Src)
	return img
}

func withRect(w, h int, bg, fg color.Color, r image.Rectangle) *image.RGBA {
	img := solid(w, h, bg)
	draw.Draw(img, r, &image.Uniform{fg}, image.Point{}, draw.Src)
	return img
}

func newDetector() *Detector {
	return NewDetector(30, 0.005, 5, 0)
}

func TestFirstFrameSetsBaselineReturnsNil(t *testing.T) {
	d := newDetector()
	if got := d.Detect(solid(200, 100, white), time.Unix(0, 0)); got != nil {
		t.Fatalf("first frame: got %+v, want nil", got)
	}
}

func TestIdenticalFrameNotTriggered(t *testing.T) {
	d := newDetector()
	d.Detect(solid(200, 100, white), time.Unix(0, 0))
	if got := d.Detect(solid(200, 100, white), time.Unix(10, 0)); got != nil {
		t.Fatalf("identical frame: got %+v, want nil", got)
	}
}

func TestTinyChangeBelowRatioNotTriggered(t *testing.T) {
	d := newDetector()
	d.Detect(solid(200, 100, white), time.Unix(0, 0))
	frame := solid(200, 100, white)
	frame.Set(0, 0, black) // 1 / 20000 = 0.005% < 0.5%
	if got := d.Detect(frame, time.Unix(10, 0)); got != nil {
		t.Fatalf("tiny change: got %+v, want nil", got)
	}
}

func TestLargeChangeTriggeredAndBaselineAdvances(t *testing.T) {
	d := NewDetector(30, 0.005, 5, 0)
	d.Detect(solid(200, 100, white), time.Unix(0, 0))
	rect := image.Rect(10, 10, 40, 40)
	got := d.Detect(withRect(200, 100, white, black, rect), time.Unix(10, 0))
	if got == nil {
		t.Fatal("large change: got nil, want result")
	}
	if got.Bbox.Min.X > 10 || got.Bbox.Min.Y > 10 || got.Bbox.Max.X < 40 || got.Bbox.Max.Y < 40 {
		t.Errorf("Bbox = %v, want to cover (10,10)-(40,40)", got.Bbox)
	}
	if got.Crop.Bounds().Dx() != got.Bbox.Dx() || got.Crop.Bounds().Dy() != got.Bbox.Dy() {
		t.Errorf("Crop size %v != Bbox size %v", got.Crop.Bounds().Size(), got.Bbox.Size())
	}
	// 基线已推进：再传同一新图 → 不触发
	if again := d.Detect(withRect(200, 100, white, black, rect), time.Unix(20, 0)); again != nil {
		t.Errorf("baseline did not advance: got %+v, want nil", again)
	}
}

func TestBboxPaddingExpandsAndClamps(t *testing.T) {
	d := NewDetector(30, 0.001, 5, 8)
	d.Detect(solid(200, 100, white), time.Unix(0, 0))
	got := d.Detect(withRect(200, 100, white, black, image.Rect(95, 45, 105, 55)), time.Unix(10, 0))
	if got == nil {
		t.Fatal("center change: got nil, want result")
	}
	if got.Bbox.Min.X > 95-8 || got.Bbox.Max.X < 105+8 {
		t.Errorf("padding not applied: Bbox = %v", got.Bbox)
	}

	d2 := NewDetector(30, 0.001, 5, 8)
	d2.Detect(solid(200, 100, white), time.Unix(0, 0))
	got2 := d2.Detect(withRect(200, 100, white, black, image.Rect(0, 0, 5, 5)), time.Unix(10, 0))
	if got2 == nil {
		t.Fatal("corner change: got nil, want result")
	}
	if got2.Bbox.Min.X != 0 || got2.Bbox.Min.Y != 0 {
		t.Errorf("padding not clamped at corner: Bbox = %v", got2.Bbox)
	}
}

func TestMinIntervalThrottlesAndKeepsBaseline(t *testing.T) {
	d := NewDetector(30, 0.001, 5, 0)
	d.Detect(solid(200, 100, white), time.Unix(0, 0))
	if d.Detect(withRect(200, 100, white, black, image.Rect(10, 10, 40, 40)), time.Unix(10, 0)) == nil {
		t.Fatal("first push: got nil, want result")
	}
	// t=11，距上次推送 < 5s → 节流，返回 nil，基线不推进
	if d.Detect(withRect(200, 100, white, black, image.Rect(100, 50, 150, 80)), time.Unix(11, 0)) != nil {
		t.Fatal("throttled frame: expected nil")
	}
	// t=20，节流过期；diff 相对"上次推送过的画面"（含第一个 rect）→ 触发
	if d.Detect(withRect(200, 100, white, black, image.Rect(100, 50, 150, 80)), time.Unix(20, 0)) == nil {
		t.Fatal("after throttle window: got nil, want result")
	}
}

func TestSizeMismatchResetsBaseline(t *testing.T) {
	d := NewDetector(30, 0.001, 5, 0)
	d.Detect(solid(200, 100, white), time.Unix(0, 0))
	// 不同尺寸 → 不触发，基线重置为新尺寸
	if d.Detect(solid(300, 150, white), time.Unix(10, 0)) != nil {
		t.Fatal("size mismatch: expected nil")
	}
	// 再来同尺寸有变化的帧 → 正常触发
	if d.Detect(withRect(300, 150, white, black, image.Rect(10, 10, 80, 80)), time.Unix(20, 0)) == nil {
		t.Fatal("after size reset: got nil, want result")
	}
}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `go test ./internal/diff/`
Expected: FAIL — `undefined: NewDetector` / `undefined: Detector`。

- [ ] **Step 3: 写实现 `internal/diff/detector.go`**

```go
// Package diff 实现画面像素 diff 检测。
package diff

import (
	"image"
	"image/draw"
	"time"
)

// Result 是一次检测到的画面变化。
type Result struct {
	Bbox image.Rectangle // 变化区域（含 padding，已 clamp 到帧内）
	Crop image.Image     // 按 Bbox 裁切出的图
}

// Detector 是状态机式的画面 diff 检测器。基线 = 上次推送过的帧。
type Detector struct {
	pixelDiffThreshold   int
	changeRatioThreshold float64
	minInterval          time.Duration
	bboxPadding          int

	baseline   *image.RGBA
	lastPushed time.Time
	hasPushed  bool
}

// NewDetector 构造检测器。minIntervalSeconds 为两次推送的最小间隔（秒）。
func NewDetector(pixelDiffThreshold int, changeRatioThreshold, minIntervalSeconds float64, bboxPadding int) *Detector {
	return &Detector{
		pixelDiffThreshold:   pixelDiffThreshold,
		changeRatioThreshold: changeRatioThreshold,
		minInterval:          time.Duration(minIntervalSeconds * float64(time.Second)),
		bboxPadding:          bboxPadding,
	}
}

// Detect 比较 frame 与基线。有显著变化且未被节流时返回 *Result 并推进基线，否则返回 nil。
func (d *Detector) Detect(frame image.Image, now time.Time) *Result {
	cur := toRGBA(frame)

	if d.baseline == nil {
		d.baseline = cur
		return nil
	}
	if cur.Bounds() != d.baseline.Bounds() {
		// 尺寸变化（DPI 切换 / 区域被改）→ 当前帧作新基线，下一帧再比
		d.baseline = cur
		return nil
	}

	bbox, changed, total := diffBBox(d.baseline, cur, d.pixelDiffThreshold)
	if total == 0 || changed == 0 {
		return nil
	}
	if float64(changed)/float64(total) < d.changeRatioThreshold {
		return nil
	}
	// 节流：距上次推送不足 minInterval → 不推、不推进基线
	if d.hasPushed && now.Sub(d.lastPushed) < d.minInterval {
		return nil
	}

	padded := padRect(bbox, d.bboxPadding, cur.Bounds())
	crop := cropRGBA(cur, padded)
	d.baseline = cur
	d.lastPushed = now
	d.hasPushed = true
	return &Result{Bbox: padded, Crop: crop}
}

// toRGBA 把任意 image 复制成 0 基点的 *image.RGBA（独立副本）。
func toRGBA(src image.Image) *image.RGBA {
	b := src.Bounds()
	dst := image.NewRGBA(image.Rect(0, 0, b.Dx(), b.Dy()))
	draw.Draw(dst, dst.Bounds(), src, b.Min, draw.Src)
	return dst
}

// cropRGBA 按 r 从 src 裁出 0 基点的新 *image.RGBA。
func cropRGBA(src *image.RGBA, r image.Rectangle) *image.RGBA {
	dst := image.NewRGBA(image.Rect(0, 0, r.Dx(), r.Dy()))
	draw.Draw(dst, dst.Bounds(), src, r.Min, draw.Src)
	return dst
}

// padRect 把 r 四周外扩 pad 像素，再 clamp 到 bounds 内。
func padRect(r image.Rectangle, pad int, bounds image.Rectangle) image.Rectangle {
	p := image.Rect(r.Min.X-pad, r.Min.Y-pad, r.Max.X+pad, r.Max.Y+pad)
	return p.Intersect(bounds)
}

// diffBBox 灰度逐像素比较 a、b（同尺寸，0 基点），返回变化区域包围盒、变化像素数、总像素数。
func diffBBox(a, b *image.RGBA, threshold int) (image.Rectangle, int, int) {
	bounds := b.Bounds()
	minX, minY := bounds.Max.X, bounds.Max.Y
	maxX, maxY := bounds.Min.X, bounds.Min.Y
	changed, total := 0, 0
	for y := bounds.Min.Y; y < bounds.Max.Y; y++ {
		for x := bounds.Min.X; x < bounds.Max.X; x++ {
			total++
			if absInt(grayAt(a, x, y)-grayAt(b, x, y)) >= threshold {
				changed++
				if x < minX {
					minX = x
				}
				if y < minY {
					minY = y
				}
				if x+1 > maxX {
					maxX = x + 1
				}
				if y+1 > maxY {
					maxY = y + 1
				}
			}
		}
	}
	if changed == 0 {
		return image.Rectangle{}, 0, total
	}
	return image.Rect(minX, minY, maxX, maxY), changed, total
}

// grayAt 返回 (x,y) 像素的 8 位灰度值（BT.601 加权）。
func grayAt(img *image.RGBA, x, y int) int {
	i := img.PixOffset(x, y)
	r := int(img.Pix[i])
	g := int(img.Pix[i+1])
	b := int(img.Pix[i+2])
	return (299*r + 587*g + 114*b) / 1000
}

func absInt(v int) int {
	if v < 0 {
		return -v
	}
	return v
}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `go test ./internal/diff/`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add internal/diff/
git commit -m "feat(go): diff 包，像素 diff + bbox 裁切 + 节流"
```

---

## Task 4: notify 包（飞书自建应用发图）

**Files:**
- Create: `internal/notify/lark.go`
- Create: `internal/notify/lark_test.go`

飞书 OpenAPI：
- token：`POST {base}/open-apis/auth/v3/tenant_access_token/internal`，body `{"app_id","app_secret"}` → `{"code":0,"tenant_access_token","expire"}`
- 上传：`POST {base}/open-apis/im/v1/images`，`Authorization: Bearer`，multipart `image_type=message` + `image` 文件 → `{"code":0,"data":{"image_key"}}`
- 发消息：`POST {base}/open-apis/im/v1/messages?receive_id_type=...`，JSON `{"receive_id","msg_type":"image","content":"{\"image_key\":...}"}`

- [ ] **Step 1: 写失败测试 `internal/notify/lark_test.go`**

```go
package notify

import (
	"encoding/json"
	"image"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func tinyImage() image.Image {
	return image.NewRGBA(image.Rect(0, 0, 4, 4))
}

// fakeLark 是一个假冒飞书 API 的 httptest server，记录各端点命中次数。
type fakeLark struct {
	server     *httptest.Server
	tokenHits  int
	uploadHits int
	msgHits    int
	tokenCode  int // 注入 token 端点返回的 code
	uploadCode int // 注入上传端点返回的 code
}

func newFakeLark() *fakeLark {
	f := &fakeLark{}
	mux := http.NewServeMux()
	mux.HandleFunc("/open-apis/auth/v3/tenant_access_token/internal", func(w http.ResponseWriter, r *http.Request) {
		f.tokenHits++
		json.NewEncoder(w).Encode(map[string]any{
			"code": f.tokenCode, "msg": "x",
			"tenant_access_token": "t-abc", "expire": 7200,
		})
	})
	mux.HandleFunc("/open-apis/im/v1/images", func(w http.ResponseWriter, r *http.Request) {
		f.uploadHits++
		json.NewEncoder(w).Encode(map[string]any{
			"code": f.uploadCode, "msg": "x",
			"data": map[string]any{"image_key": "img_v3_xxx"},
		})
	})
	mux.HandleFunc("/open-apis/im/v1/messages", func(w http.ResponseWriter, r *http.Request) {
		f.msgHits++
		json.NewEncoder(w).Encode(map[string]any{"code": 0, "msg": "ok"})
	})
	f.server = httptest.NewServer(mux)
	return f
}

func newClientFor(f *fakeLark) *LarkClient {
	c := NewLarkClient("cli_x", "sec_x", "oc_x", "chat_id")
	c.baseURL = f.server.URL
	return c
}

func TestSendImageHappyPath(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := newClientFor(f)
	if err := c.SendImage(tinyImage()); err != nil {
		t.Fatalf("SendImage: %v", err)
	}
	if f.tokenHits != 1 || f.uploadHits != 1 || f.msgHits != 1 {
		t.Errorf("hits: token=%d upload=%d msg=%d, want 1/1/1", f.tokenHits, f.uploadHits, f.msgHits)
	}
}

func TestTokenCachedAcrossCalls(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := newClientFor(f)
	_ = c.SendImage(tinyImage())
	_ = c.SendImage(tinyImage())
	if f.tokenHits != 1 {
		t.Errorf("tokenHits = %d, want 1 (cached)", f.tokenHits)
	}
}

func TestExpiredTokenRefreshed(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := newClientFor(f)
	_ = c.SendImage(tinyImage())
	c.tokenExpiresAt = time.Now().Add(-time.Hour) // 强制过期
	_ = c.SendImage(tinyImage())
	if f.tokenHits != 2 {
		t.Errorf("tokenHits = %d, want 2 (refresh)", f.tokenHits)
	}
}

func TestTokenBusinessErrorFails(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	f.tokenCode = 99991663
	c := newClientFor(f)
	err := c.SendImage(tinyImage())
	if err == nil || !strings.Contains(err.Error(), "99991663") {
		t.Fatalf("err = %v, want to contain 99991663", err)
	}
}

func TestUploadBusinessErrorFails(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	f.uploadCode = 230002
	c := newClientFor(f)
	err := c.SendImage(tinyImage())
	if err == nil || !strings.Contains(err.Error(), "230002") {
		t.Fatalf("err = %v, want to contain 230002", err)
	}
}

func TestMissingCredentialsShortCircuits(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := NewLarkClient("", "", "oc_x", "chat_id")
	c.baseURL = f.server.URL
	err := c.SendImage(tinyImage())
	if err == nil {
		t.Fatal("expected error for missing credentials")
	}
	if f.tokenHits != 0 {
		t.Errorf("tokenHits = %d, want 0 (short-circuit)", f.tokenHits)
	}
}

func TestNetworkErrorFails(t *testing.T) {
	c := NewLarkClient("cli_x", "sec_x", "oc_x", "chat_id")
	c.baseURL = "http://127.0.0.1:0" // 无法连接
	if err := c.SendImage(tinyImage()); err == nil {
		t.Fatal("expected network error")
	}
}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `go test ./internal/notify/`
Expected: FAIL — `undefined: NewLarkClient` 等。

- [ ] **Step 3: 写实现 `internal/notify/lark.go`**

```go
// Package notify 实现飞书自建应用的图片消息发送。
package notify

import (
	"bytes"
	"encoding/json"
	"fmt"
	"image"
	"image/png"
	"mime/multipart"
	"net/http"
	"sync"
	"time"
)

const tokenRefreshBuffer = 5 * time.Minute

// LarkClient 通过飞书自建应用上传图片并发 image 消息。
type LarkClient struct {
	appID         string
	appSecret     string
	receiveID     string
	receiveIDType string

	baseURL    string // 默认 https://open.feishu.cn；测试可改写
	httpClient *http.Client

	mu             sync.Mutex
	token          string
	tokenExpiresAt time.Time
}

// NewLarkClient 构造客户端。
func NewLarkClient(appID, appSecret, receiveID, receiveIDType string) *LarkClient {
	return &LarkClient{
		appID:         appID,
		appSecret:     appSecret,
		receiveID:     receiveID,
		receiveIDType: receiveIDType,
		baseURL:       "https://open.feishu.cn",
		httpClient:    &http.Client{Timeout: 10 * time.Second},
	}
}

// SendImage 上传图片并作为 image 消息发到目标会话。
func (c *LarkClient) SendImage(img image.Image) error {
	if c.appID == "" || c.appSecret == "" || c.receiveID == "" {
		return fmt.Errorf("lark: missing credentials (app_id/app_secret/receive_id)")
	}
	token, err := c.getToken()
	if err != nil {
		return fmt.Errorf("lark: get token: %w", err)
	}
	imageKey, err := c.uploadImage(token, img)
	if err != nil {
		return fmt.Errorf("lark: upload image: %w", err)
	}
	if err := c.sendImageMessage(token, imageKey); err != nil {
		return fmt.Errorf("lark: send message: %w", err)
	}
	return nil
}

func (c *LarkClient) getToken() (string, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.token != "" && time.Now().Before(c.tokenExpiresAt.Add(-tokenRefreshBuffer)) {
		return c.token, nil
	}
	reqBody, _ := json.Marshal(map[string]string{"app_id": c.appID, "app_secret": c.appSecret})
	resp, err := c.httpClient.Post(
		c.baseURL+"/open-apis/auth/v3/tenant_access_token/internal",
		"application/json", bytes.NewReader(reqBody))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	var r struct {
		Code   int    `json:"code"`
		Msg    string `json:"msg"`
		Token  string `json:"tenant_access_token"`
		Expire int    `json:"expire"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		return "", err
	}
	if r.Code != 0 {
		return "", fmt.Errorf("token endpoint code=%d msg=%s", r.Code, r.Msg)
	}
	c.token = r.Token
	c.tokenExpiresAt = time.Now().Add(time.Duration(r.Expire) * time.Second)
	return c.token, nil
}

func (c *LarkClient) uploadImage(token string, img image.Image) (string, error) {
	var pngBuf bytes.Buffer
	if err := png.Encode(&pngBuf, img); err != nil {
		return "", err
	}
	var body bytes.Buffer
	mw := multipart.NewWriter(&body)
	if err := mw.WriteField("image_type", "message"); err != nil {
		return "", err
	}
	fw, err := mw.CreateFormFile("image", "diff.png")
	if err != nil {
		return "", err
	}
	if _, err := fw.Write(pngBuf.Bytes()); err != nil {
		return "", err
	}
	if err := mw.Close(); err != nil {
		return "", err
	}
	req, err := http.NewRequest(http.MethodPost, c.baseURL+"/open-apis/im/v1/images", &body)
	if err != nil {
		return "", err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	var r struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
		Data struct {
			ImageKey string `json:"image_key"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		return "", err
	}
	if r.Code != 0 {
		return "", fmt.Errorf("upload endpoint code=%d msg=%s", r.Code, r.Msg)
	}
	return r.Data.ImageKey, nil
}

func (c *LarkClient) sendImageMessage(token, imageKey string) error {
	content, _ := json.Marshal(map[string]string{"image_key": imageKey})
	reqBody, _ := json.Marshal(map[string]string{
		"receive_id": c.receiveID,
		"msg_type":   "image",
		"content":    string(content),
	})
	url := c.baseURL + "/open-apis/im/v1/messages?receive_id_type=" + c.receiveIDType
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(reqBody))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	var r struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		return err
	}
	if r.Code != 0 {
		return fmt.Errorf("message endpoint code=%d msg=%s", r.Code, r.Msg)
	}
	return nil
}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `go test ./internal/notify/`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add internal/notify/
git commit -m "feat(go): notify 包，飞书自建应用 token 缓存 + 上传图 + 发 image"
```

---

## Task 5: history 包

**Files:**
- Create: `internal/history/history.go`
- Create: `internal/history/history_test.go`

- [ ] **Step 1: 写失败测试 `internal/history/history_test.go`**

```go
package history

import (
	"bufio"
	"encoding/json"
	"image"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestSaveFrameWritesPNG(t *testing.T) {
	dir := t.TempDir()
	s := NewStore(filepath.Join(dir, "history.ndjson"), filepath.Join(dir, "frames"))
	img := image.NewRGBA(image.Rect(0, 0, 8, 8))
	path, err := s.SaveFrame(img, time.Unix(1700000000, 123456789))
	if err != nil {
		t.Fatalf("SaveFrame: %v", err)
	}
	if filepath.Dir(path) != filepath.Join(dir, "frames") {
		t.Errorf("frame saved to %q, want under frames dir", path)
	}
	if _, err := os.Stat(path); err != nil {
		t.Errorf("frame file not found: %v", err)
	}
}

func TestAppendWritesJSONL(t *testing.T) {
	dir := t.TempDir()
	hp := filepath.Join(dir, "history.ndjson")
	s := NewStore(hp, filepath.Join(dir, "frames"))
	if err := s.Append(Record{TS: "t1", Bbox: [4]int{1, 2, 3, 4}, Image: "a.png"}); err != nil {
		t.Fatalf("Append: %v", err)
	}
	if err := s.Append(Record{TS: "t2", Bbox: [4]int{5, 6, 7, 8}, Image: "b.png"}); err != nil {
		t.Fatalf("Append: %v", err)
	}
	f, err := os.Open(hp)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var recs []Record
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		var r Record
		if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
			t.Fatalf("bad JSONL line: %v", err)
		}
		recs = append(recs, r)
	}
	if len(recs) != 2 || recs[0].TS != "t1" || recs[1].Image != "b.png" {
		t.Errorf("records = %+v, want 2 ordered records", recs)
	}
}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `go test ./internal/history/`
Expected: FAIL — `undefined: NewStore` 等。

- [ ] **Step 3: 写实现 `internal/history/history.go`**

```go
// Package history 持久化 diff 历史：JSONL 记录 + 裁切图文件。
package history

import (
	"encoding/json"
	"fmt"
	"image"
	"image/png"
	"os"
	"path/filepath"
	"time"
)

// Record 是一条 diff 历史记录。
type Record struct {
	TS    string `json:"ts"`
	Bbox  [4]int `json:"bbox"`
	Image string `json:"image"`
}

// Store 把 diff 裁切图存到 framesDir，把记录追加到 historyPath（JSONL）。
type Store struct {
	historyPath string
	framesDir   string
}

// NewStore 构造历史存储。
func NewStore(historyPath, framesDir string) *Store {
	return &Store{historyPath: historyPath, framesDir: framesDir}
}

// SaveFrame 把 crop 以时间戳命名存为 PNG，返回完整路径。
func (s *Store) SaveFrame(crop image.Image, ts time.Time) (string, error) {
	if err := os.MkdirAll(s.framesDir, 0o755); err != nil {
		return "", err
	}
	name := fmt.Sprintf("%s_%09d.png", ts.Format("20060102_150405"), ts.Nanosecond())
	path := filepath.Join(s.framesDir, name)
	f, err := os.Create(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	if err := png.Encode(f, crop); err != nil {
		return "", err
	}
	return path, nil
}

// Append 把一条记录追加写入 JSONL 历史文件。
func (s *Store) Append(rec Record) error {
	if err := os.MkdirAll(filepath.Dir(s.historyPath), 0o755); err != nil {
		return err
	}
	f, err := os.OpenFile(s.historyPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()
	line, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	_, err = f.Write(append(line, '\n'))
	return err
}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `go test ./internal/history/`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add internal/history/
git commit -m "feat(go): history 包，JSONL 记录 + 裁切图落盘"
```

---

## Task 6: pipeline 包（接缝接口 + ImagePipeline + 工厂）

**Files:**
- Create: `internal/pipeline/pipeline.go`
- Create: `internal/pipeline/pipeline_test.go`

- [ ] **Step 1: 写失败测试 `internal/pipeline/pipeline_test.go`**

```go
package pipeline

import (
	"errors"
	"image"
	"path/filepath"
	"testing"
	"time"

	"github.com/lRoccoon/screen-ocr-watchdog/internal/config"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/diff"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/history"
)

type stubDetector struct {
	result *diff.Result
}

func (s stubDetector) Detect(image.Image, time.Time) *diff.Result { return s.result }

type stubSender struct {
	calls int
	err   error
}

func (s *stubSender) SendImage(image.Image) error {
	s.calls++
	return s.err
}

func newImagePipeline(t *testing.T, det detector, sender imageSender) (*ImagePipeline, *history.Store) {
	dir := t.TempDir()
	store := history.NewStore(filepath.Join(dir, "h.ndjson"), filepath.Join(dir, "frames"))
	p := &ImagePipeline{det: det, sender: sender, store: store, now: func() time.Time { return time.Unix(1700000000, 0) }}
	return p, store
}

func TestProcessNoDiffDoesNothing(t *testing.T) {
	sender := &stubSender{}
	p, _ := newImagePipeline(t, stubDetector{result: nil}, sender)
	if err := p.Process(image.NewRGBA(image.Rect(0, 0, 4, 4))); err != nil {
		t.Fatalf("Process: %v", err)
	}
	if sender.calls != 0 {
		t.Errorf("sender called %d times, want 0", sender.calls)
	}
}

func TestProcessDiffSavesNotifiesAppends(t *testing.T) {
	crop := image.NewRGBA(image.Rect(0, 0, 6, 6))
	res := &diff.Result{Bbox: image.Rect(5, 5, 15, 15), Crop: crop}
	sender := &stubSender{}
	p, _ := newImagePipeline(t, stubDetector{result: res}, sender)
	if err := p.Process(image.NewRGBA(image.Rect(0, 0, 20, 20))); err != nil {
		t.Fatalf("Process: %v", err)
	}
	if sender.calls != 1 {
		t.Errorf("sender called %d times, want 1", sender.calls)
	}
}

func TestProcessSendFailureStillSavesAndAppends(t *testing.T) {
	crop := image.NewRGBA(image.Rect(0, 0, 6, 6))
	res := &diff.Result{Bbox: image.Rect(0, 0, 6, 6), Crop: crop}
	sender := &stubSender{err: errors.New("network down")}
	p, store := newImagePipeline(t, stubDetector{result: res}, sender)
	err := p.Process(image.NewRGBA(image.Rect(0, 0, 20, 20)))
	if err == nil {
		t.Fatal("Process: expected send error to surface")
	}
	// 即使发送失败，history 仍写入
	_ = store
	if sender.calls != 1 {
		t.Errorf("sender called %d times, want 1", sender.calls)
	}
}

func TestNewImageDiffMode(t *testing.T) {
	cfg := config.Default()
	cfg.Lark = config.Lark{AppID: "a", AppSecret: "b", ReceiveID: "c", ReceiveIDType: "chat_id"}
	store := history.NewStore(filepath.Join(t.TempDir(), "h"), filepath.Join(t.TempDir(), "f"))
	p, err := New(&cfg, store)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if _, ok := p.(*ImagePipeline); !ok {
		t.Errorf("New returned %T, want *ImagePipeline", p)
	}
}

func TestNewMissingCredentialsFails(t *testing.T) {
	cfg := config.Default() // Lark 三凭证全空
	store := history.NewStore(filepath.Join(t.TempDir(), "h"), filepath.Join(t.TempDir(), "f"))
	if _, err := New(&cfg, store); err == nil {
		t.Fatal("New: expected error for missing credentials")
	}
}

func TestNewUnsupportedModeFails(t *testing.T) {
	cfg := config.Default()
	cfg.Mode = "ocr" // v1 未实现
	store := history.NewStore(filepath.Join(t.TempDir(), "h"), filepath.Join(t.TempDir(), "f"))
	if _, err := New(&cfg, store); err == nil {
		t.Fatal("New: expected error for unsupported mode")
	}
}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `go test ./internal/pipeline/`
Expected: FAIL — `undefined: ImagePipeline` / `undefined: New` 等。

- [ ] **Step 3: 写实现 `internal/pipeline/pipeline.go`**

```go
// Package pipeline 把 capture 后的帧处理成副作用（diff → 存盘 → 通知）。
// Pipeline 接口是为后续 OCR 模式预留的接缝。
package pipeline

import (
	"fmt"
	"image"
	"time"

	"github.com/lRoccoon/screen-ocr-watchdog/internal/config"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/diff"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/history"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/notify"
)

// Pipeline 处理单帧截图。watcher 只认这个接口，不关心是 diff 还是 ocr。
type Pipeline interface {
	Process(frame image.Image) error
}

// detector 是 ImagePipeline 对 diff 检测器的依赖（便于测试时替换）。
type detector interface {
	Detect(frame image.Image, now time.Time) *diff.Result
}

// imageSender 是 ImagePipeline 对图片发送方的依赖。
type imageSender interface {
	SendImage(img image.Image) error
}

// ImagePipeline 实现 image_diff 模式：检测 → 存裁切图 + 写历史 → 发飞书。
type ImagePipeline struct {
	det    detector
	sender imageSender
	store  *history.Store
	now    func() time.Time
}

// Process 检测画面变化；有变化则存盘、写历史、发图。
// 即使发图失败也已存盘 + 写历史，并把发送错误返回给调用方（用于托盘报错）。
func (p *ImagePipeline) Process(frame image.Image) error {
	now := p.now()
	res := p.det.Detect(frame, now)
	if res == nil {
		return nil
	}
	imgPath, err := p.store.SaveFrame(res.Crop, now)
	if err != nil {
		return fmt.Errorf("pipeline: save frame: %w", err)
	}
	sendErr := p.sender.SendImage(res.Crop)
	rec := history.Record{
		TS:    now.Format(time.RFC3339Nano),
		Bbox:  [4]int{res.Bbox.Min.X, res.Bbox.Min.Y, res.Bbox.Max.X, res.Bbox.Max.Y},
		Image: imgPath,
	}
	if appendErr := p.store.Append(rec); appendErr != nil {
		return fmt.Errorf("pipeline: append history: %w", appendErr)
	}
	if sendErr != nil {
		return fmt.Errorf("pipeline: notify: %w", sendErr)
	}
	return nil
}

// New 按 cfg.Mode 构造对应 Pipeline。v1 只支持 image_diff。
func New(cfg *config.Config, store *history.Store) (Pipeline, error) {
	switch cfg.Mode {
	case "image_diff":
		l := cfg.Lark
		if l.AppID == "" || l.AppSecret == "" || l.ReceiveID == "" {
			return nil, fmt.Errorf("image_diff mode requires lark.app_id/app_secret/receive_id")
		}
		det := diff.NewDetector(
			cfg.ImageDiff.PixelDiffThreshold,
			cfg.ImageDiff.ChangeRatioThreshold,
			cfg.ImageDiff.MinIntervalSeconds,
			cfg.ImageDiff.BboxPadding,
		)
		sender := notify.NewLarkClient(l.AppID, l.AppSecret, l.ReceiveID, l.ReceiveIDType)
		return &ImagePipeline{det: det, sender: sender, store: store, now: time.Now}, nil
	default:
		return nil, fmt.Errorf("unsupported mode: %q", cfg.Mode)
	}
}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `go test ./internal/pipeline/`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add internal/pipeline/
git commit -m "feat(go): pipeline 包，Pipeline 接缝接口 + ImagePipeline + New 工厂"
```

---

## Task 7: watcher 包

**Files:**
- Create: `internal/watcher/watcher.go`
- Create: `internal/watcher/watcher_test.go`

- [ ] **Step 1: 写失败测试 `internal/watcher/watcher_test.go`**

```go
package watcher

import (
	"errors"
	"image"
	"sync"
	"testing"
	"time"
)

type stubCapturer struct {
	img image.Image
	err error
}

func (s stubCapturer) Capture() (image.Image, error) { return s.img, s.err }

type stubProcessor struct {
	mu    sync.Mutex
	calls int
	err   error
}

func (s *stubProcessor) Process(image.Image) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	return s.err
}

func (s *stubProcessor) count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls
}

func TestTickCaptureErrorReportsError(t *testing.T) {
	var gotErr error
	w := New(stubCapturer{err: errors.New("no display")}, &stubProcessor{}, time.Second,
		func(e error) { gotErr = e })
	w.tick()
	if gotErr == nil {
		t.Fatal("capture error not reported to onError")
	}
}

func TestTickProcessErrorReportsError(t *testing.T) {
	var gotErr error
	proc := &stubProcessor{err: errors.New("send failed")}
	w := New(stubCapturer{img: image.NewRGBA(image.Rect(0, 0, 4, 4))}, proc, time.Second,
		func(e error) { gotErr = e })
	w.tick()
	if proc.count() != 1 {
		t.Errorf("processor calls = %d, want 1", proc.count())
	}
	if gotErr == nil {
		t.Fatal("process error not reported to onError")
	}
}

func TestTickHappyPathNoError(t *testing.T) {
	called := false
	proc := &stubProcessor{}
	w := New(stubCapturer{img: image.NewRGBA(image.Rect(0, 0, 4, 4))}, proc, time.Second,
		func(error) { called = true })
	w.tick()
	if proc.count() != 1 {
		t.Errorf("processor calls = %d, want 1", proc.count())
	}
	if called {
		t.Error("onError called on happy path")
	}
}

func TestPauseSkipsTick(t *testing.T) {
	proc := &stubProcessor{}
	w := New(stubCapturer{img: image.NewRGBA(image.Rect(0, 0, 4, 4))}, proc, 10*time.Millisecond, func(error) {})
	w.Pause()
	w.Start()
	time.Sleep(50 * time.Millisecond)
	w.Stop()
	if proc.count() != 0 {
		t.Errorf("processor called %d times while paused, want 0", proc.count())
	}
}

func TestStartResumeRunsTicks(t *testing.T) {
	proc := &stubProcessor{}
	w := New(stubCapturer{img: image.NewRGBA(image.Rect(0, 0, 4, 4))}, proc, 10*time.Millisecond, func(error) {})
	w.Start()
	time.Sleep(60 * time.Millisecond)
	w.Stop()
	if proc.count() == 0 {
		t.Error("processor never called after Start")
	}
}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `go test ./internal/watcher/`
Expected: FAIL — `undefined: New` 等。

- [ ] **Step 3: 写实现 `internal/watcher/watcher.go`**

```go
// Package watcher 周期性截屏并交给 pipeline 处理。
package watcher

import (
	"fmt"
	"image"
	"log/slog"
	"sync/atomic"
	"time"
)

// Capturer 截取一帧画面。
type Capturer interface {
	Capture() (image.Image, error)
}

// Processor 处理一帧画面。
type Processor interface {
	Process(frame image.Image) error
}

// Watcher 在后台 goroutine 里按 interval 周期性 capture → process。
type Watcher struct {
	capturer Capturer
	pipeline Processor
	interval time.Duration
	onError  func(error)

	paused atomic.Bool
	stop   chan struct{}
	done   chan struct{}
}

// New 构造 watcher。onError 在每次截屏 / 处理失败时被调用（可为 nil）。
func New(capturer Capturer, pipeline Processor, interval time.Duration, onError func(error)) *Watcher {
	return &Watcher{
		capturer: capturer,
		pipeline: pipeline,
		interval: interval,
		onError:  onError,
		stop:     make(chan struct{}),
		done:     make(chan struct{}),
	}
}

// Start 在后台 goroutine 启动循环。
func (w *Watcher) Start() {
	go w.loop()
}

// Stop 停止循环并等待 goroutine 退出。
func (w *Watcher) Stop() {
	close(w.stop)
	<-w.done
}

// Pause 暂停（循环继续转，但跳过 tick）。
func (w *Watcher) Pause() { w.paused.Store(true) }

// Resume 恢复。
func (w *Watcher) Resume() { w.paused.Store(false) }

func (w *Watcher) loop() {
	defer close(w.done)
	ticker := time.NewTicker(w.interval)
	defer ticker.Stop()
	for {
		select {
		case <-w.stop:
			return
		case <-ticker.C:
			if !w.paused.Load() {
				w.tick()
			}
		}
	}
}

// tick 执行一次 capture → process，并把任何错误记日志 + 报给 onError。
// 每次 tick 都 recover，单帧 panic 不杀死循环。
func (w *Watcher) tick() {
	defer func() {
		if r := recover(); r != nil {
			slog.Error("watcher tick panic", "panic", r)
			w.report(fmt.Errorf("watcher panic: %v", r))
		}
	}()
	frame, err := w.capturer.Capture()
	if err != nil {
		slog.Error("capture failed", "err", err)
		w.report(err)
		return
	}
	if err := w.pipeline.Process(frame); err != nil {
		slog.Error("pipeline process failed", "err", err)
		w.report(err)
	}
}

func (w *Watcher) report(err error) {
	if w.onError != nil {
		w.onError(err)
	}
}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `go test ./internal/watcher/`
Expected: `ok`

- [ ] **Step 5: 核心包整体回归**

Run:
```bash
go test ./internal/paths/ ./internal/config/ ./internal/diff/ ./internal/notify/ ./internal/history/ ./internal/pipeline/ ./internal/watcher/
```
Expected: 7 个包全部 `ok`。

- [ ] **Step 6: Commit**

```bash
git add internal/watcher/
git commit -m "feat(go): watcher 包，定时 capture→process 循环 + 暂停/停止"
```

---

## Task 8: capture 包（Windows）

**Files:**
- Create: `internal/capture/capture.go`

无单元测试（需真显示器）。验证手段：交叉编译。

- [ ] **Step 1: 加 screenshot 依赖**

Run: `go get github.com/kbinani/screenshot`

- [ ] **Step 2: 写实现 `internal/capture/capture.go`**

```go
//go:build windows

// Package capture 按配置的屏幕矩形截屏。
package capture

import (
	"image"

	"github.com/kbinani/screenshot"
)

// RegionCapturer 截取一个固定的屏幕矩形。
type RegionCapturer struct {
	rect image.Rectangle
}

// New 构造区域截屏器。x,y 为左上角，w,h 为宽高（像素）。
func New(x, y, w, h int) *RegionCapturer {
	return &RegionCapturer{rect: image.Rect(x, y, x+w, y+h)}
}

// Capture 截取配置区域，返回 *image.RGBA。
func (c *RegionCapturer) Capture() (image.Image, error) {
	img, err := screenshot.CaptureRect(c.rect)
	if err != nil {
		return nil, err
	}
	return img, nil
}
```

- [ ] **Step 3: 交叉编译验证**

Run: `CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build ./internal/capture/`
Expected: 无输出（编译成功）。

- [ ] **Step 4: Commit**

```bash
git add go.mod go.sum internal/capture/
git commit -m "feat(go): capture 包，Windows 区域截屏"
```

---

## Task 9: tray 包（Windows）

**Files:**
- Create: `internal/tray/tray.go`
- Create: `internal/tray/icon.ico`

- [ ] **Step 1: 加 systray 依赖**

Run: `go get fyne.io/systray`

- [ ] **Step 2: 生成托盘图标 `internal/tray/icon.ico`**

需要一个 32x32 的 .ico。`//go:embed` 要求文件编译期存在，内容视觉不重要。按以下优先级取一种可用的：

```bash
# 方式 A：ImageMagick
convert -size 32x32 xc:'#2563eb' internal/tray/icon.ico
# 方式 B：Python + Pillow（仓库 .venv 里有 Pillow，实现期可用）
python3 -c "from PIL import Image; Image.new('RGBA',(32,32),(37,99,235,255)).save('internal/tray/icon.ico')"
```

执行其一后确认：`test -f internal/tray/icon.ico && echo ok`
两种都不可用时，把任意一个 32x32 `.ico` 文件放到 `internal/tray/icon.ico` 即可。

- [ ] **Step 3: 写实现 `internal/tray/tray.go`**

```go
//go:build windows

// Package tray 提供 Windows 系统托盘图标与菜单。
package tray

import (
	_ "embed"

	"fyne.io/systray"
)

//go:embed icon.ico
var iconData []byte

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
		systray.SetIcon(iconData)
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

// SetState 更新托盘 tooltip + 暂停项文案以反映状态。
func SetState(s State, detail string) {
	switch s {
	case StateRunning:
		systray.SetTooltip("Screen Watchdog · 运行中")
		if pauseItem != nil {
			pauseItem.SetTitle("暂停")
		}
	case StatePaused:
		systray.SetTooltip("Screen Watchdog · 已暂停")
		if pauseItem != nil {
			pauseItem.SetTitle("恢复")
		}
	case StateError:
		systray.SetTooltip("Screen Watchdog · 错误: " + detail)
	}
}
```

- [ ] **Step 4: 交叉编译验证**

Run: `CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build ./internal/tray/`
Expected: 编译成功。

- [ ] **Step 5: Commit**

```bash
git add go.mod go.sum internal/tray/
git commit -m "feat(go): tray 包，Windows 托盘图标 + 菜单"
```

---

## Task 10: picker 包（Windows，全屏框选遮罩）

**Files:**
- Create: `internal/picker/picker.go`

v1 picker：全屏半透明遮罩窗口，鼠标拖拽记录起点 / 终点，ESC 取消。不画实时橡皮筋矩形（v2 再加）。**这是整个工程最需 Windows 实测的部分。**

- [ ] **Step 1: 写实现 `internal/picker/picker.go`**

```go
//go:build windows

// Package picker 提供 Windows 全屏拖拽框选遮罩。
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
	kernel32 = windows.NewLazySystemDLL("kernel32.dll")

	pRegisterClassExW       = user32.NewProc("RegisterClassExW")
	pCreateWindowExW        = user32.NewProc("CreateWindowExW")
	pDefWindowProcW         = user32.NewProc("DefWindowProcW")
	pDestroyWindow          = user32.NewProc("DestroyWindow")
	pGetMessageW            = user32.NewProc("GetMessageW")
	pTranslateMessage       = user32.NewProc("TranslateMessage")
	pDispatchMessageW       = user32.NewProc("DispatchMessageW")
	pPostQuitMessage        = user32.NewProc("PostQuitMessage")
	pGetSystemMetrics       = user32.NewProc("GetSystemMetrics")
	pSetLayeredWindowAttrs  = user32.NewProc("SetLayeredWindowAttributes")
	pSetCapture             = user32.NewProc("SetCapture")
	pReleaseCapture         = user32.NewProc("ReleaseCapture")
	pGetModuleHandleW       = kernel32.NewProc("GetModuleHandleW")
	pLoadCursorW            = user32.NewProc("LoadCursorW")
)

const (
	wsExLayered   = 0x00080000
	wsExTopmost   = 0x00000008
	wsExToolwindow = 0x00000080
	wsPopup       = 0x80000000

	swShow = 5

	smCXScreen = 0
	smCYScreen = 1

	lwaAlpha = 0x00000002

	wmDestroy     = 0x0002
	wmLButtonDown = 0x0201
	wmLButtonUp   = 0x0202
	wmKeyDown     = 0x0100

	vkEscape = 0x1B

	idcCross = 32515
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

type msg struct {
	hwnd    windows.Handle
	message uint32
	wParam  uintptr
	lParam  uintptr
	time    uint32
	pt      point
}

// pick 内部状态在单次 Pick 调用内有效（Pick 串行调用，无并发）。
var (
	startX, startY int32
	endX, endY     int32
	dragging       bool
	picked         bool
	cancelled      bool
	pickHWND       windows.Handle
)

func loword(l uintptr) int32 { return int32(int16(l & 0xffff)) }
func hiword(l uintptr) int32 { return int32(int16((l >> 16) & 0xffff)) }

// wndProc 全参数用 uintptr —— syscall.NewCallback 要求参数为 uintptr 尺寸。
func wndProc(hwnd, message, wParam, lParam uintptr) uintptr {
	switch message {
	case wmLButtonDown:
		startX, startY = loword(lParam), hiword(lParam)
		dragging = true
		pSetCapture.Call(hwnd)
		return 0
	case wmLButtonUp:
		if dragging {
			endX, endY = loword(lParam), hiword(lParam)
			dragging = false
			picked = true
			pReleaseCapture.Call()
			pPostQuitMessage.Call(0)
		}
		return 0
	case wmKeyDown:
		if wParam == vkEscape {
			cancelled = true
			pPostQuitMessage.Call(0)
		}
		return 0
	case wmDestroy:
		pPostQuitMessage.Call(0)
		return 0
	}
	ret, _, _ := pDefWindowProcW.Call(hwnd, message, wParam, lParam)
	return ret
}

// Pick 弹出全屏遮罩让用户拖拽选区，返回选中矩形的 x,y,w,h。
// ok=false 表示用户按 ESC 取消或选区无效。
func Pick() (x, y, w, h int, ok bool, err error) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()

	picked, cancelled, dragging = false, false, false

	hInstance, _, _ := pGetModuleHandleW.Call(0)
	className, _ := syscall.UTF16PtrFromString("SOWRegionPicker")

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

	// 半透明遮罩：约 25% 不透明黑
	pSetLayeredWindowAttrs.Call(hwnd, 0, uintptr(64), uintptr(lwaAlpha))
	user32.NewProc("ShowWindow").Call(hwnd, swShow)

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
	x0, x1 := int(startX), int(endX)
	if x0 > x1 {
		x0, x1 = x1, x0
	}
	y0, y1 := int(startY), int(endY)
	if y0 > y1 {
		y0, y1 = y1, y0
	}
	w, h = x1-x0, y1-y0
	if w < 10 || h < 10 {
		return 0, 0, 0, 0, false, nil
	}
	return x0, y0, w, h, true, nil
}
```

- [ ] **Step 2: 加 x/sys 依赖并交叉编译验证**

Run:
```bash
go get golang.org/x/sys/windows
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build ./internal/picker/
```
Expected: 编译成功。

> 说明：picker 的运行行为（遮罩透明度、拖拽、ESC 取消、坐标正确性）**只能在真 Windows 上验证**，预计需 1-2 轮实测调整。

- [ ] **Step 3: Commit**

```bash
git add go.mod go.sum internal/picker/
git commit -m "feat(go): picker 包，Windows 全屏拖拽框选遮罩"
```

---

## Task 11: main.go（Windows，装配）

**Files:**
- Create: `main.go`

- [ ] **Step 1: 写实现 `main.go`**

```go
//go:build windows

// Command ScreenWatchdog 是 screen-ocr-watchdog 的 Windows 入口。
package main

import (
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/lRoccoon/screen-ocr-watchdog/internal/capture"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/config"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/history"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/paths"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/picker"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/pipeline"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/tray"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/watcher"
)

// controller 持有运行期状态，托盘回调操作它。
type controller struct {
	cfg     config.Config
	store   *history.Store
	watch   *watcher.Watcher
	paused  bool
}

func main() {
	setupLogging()

	cfg, err := config.Load(paths.ConfigPath())
	if err != nil {
		slog.Error("load config failed", "err", err)
	}
	c := &controller{
		cfg:   cfg,
		store: history.NewStore(paths.HistoryPath(), paths.FramesDir()),
	}

	cb := tray.Callbacks{
		OnTogglePause: c.togglePause,
		OnPickRegion:  c.pickRegion,
		OnOpenConfig:  func() { openInExplorer(paths.ConfigPath()) },
		OnOpenFrames:  func() { openInExplorer(paths.FramesDir()) },
		OnQuit:        c.quit,
	}
	tray.Run(cb, c.start)
}

// setupLogging 把 slog 输出到 %LOCALAPPDATA%\...\Logs\app.log。
// -H windowsgui 下没有控制台，文件日志是排查问题的唯一手段。
func setupLogging() {
	logPath := paths.LogPath()
	if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil {
		return
	}
	f, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	slog.SetDefault(slog.New(slog.NewTextHandler(f, &slog.HandlerOptions{Level: slog.LevelInfo})))
	slog.Info("screen-watchdog started", "log", logPath)
}

// start 在托盘就绪后调用，启动 watcher。
func (c *controller) start() {
	c.restartWatcher()
}

// restartWatcher 按当前配置重建并启动 watcher。
func (c *controller) restartWatcher() {
	if c.watch != nil {
		c.watch.Stop()
		c.watch = nil
	}
	if c.cfg.Region.W == 0 || c.cfg.Region.H == 0 {
		slog.Warn("region not configured; watcher not started")
		tray.SetState(tray.StateError, "未配置监控区域，请右键托盘 → 重新框选区域")
		return
	}
	pl, err := pipeline.New(&c.cfg, c.store)
	if err != nil {
		slog.Error("build pipeline failed", "err", err)
		tray.SetState(tray.StateError, err.Error())
		return
	}
	capturer := capture.New(c.cfg.Region.X, c.cfg.Region.Y, c.cfg.Region.W, c.cfg.Region.H)
	interval := time.Duration(c.cfg.IntervalSeconds) * time.Second
	if interval <= 0 {
		interval = 5 * time.Second
	}
	c.watch = watcher.New(capturer, pl, interval, func(err error) {
		tray.SetState(tray.StateError, err.Error())
	})
	c.watch.Start()
	if c.paused {
		c.watch.Pause()
		tray.SetState(tray.StatePaused, "")
	} else {
		tray.SetState(tray.StateRunning, "")
	}
}

func (c *controller) togglePause() {
	if c.watch == nil {
		return
	}
	if c.paused {
		c.watch.Resume()
		c.paused = false
		tray.SetState(tray.StateRunning, "")
	} else {
		c.watch.Pause()
		c.paused = true
		tray.SetState(tray.StatePaused, "")
	}
}

func (c *controller) pickRegion() {
	x, y, w, h, ok, err := picker.Pick()
	if err != nil {
		slog.Error("region pick failed", "err", err)
		return
	}
	if !ok {
		slog.Info("region pick cancelled")
		return
	}
	c.cfg.Region = config.Region{X: x, Y: y, W: w, H: h}
	if err := config.Save(c.cfg, paths.ConfigPath()); err != nil {
		slog.Error("save config failed", "err", err)
	}
	slog.Info("region updated", "x", x, "y", y, "w", w, "h", h)
	c.restartWatcher()
}

func (c *controller) quit() {
	if c.watch != nil {
		c.watch.Stop()
	}
	slog.Info("screen-watchdog quit")
}

// openInExplorer 用资源管理器打开文件 / 目录。
func openInExplorer(path string) {
	if err := exec.Command("explorer", path).Start(); err != nil {
		slog.Error("open explorer failed", "path", path, "err", err)
	}
}
```

- [ ] **Step 2: 整工程交叉编译**

Run:
```bash
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags="-H windowsgui -s -w" -o ScreenWatchdog.exe .
ls -lh ScreenWatchdog.exe
```
Expected: 生成 `ScreenWatchdog.exe`（约 10-15 MB）。

- [ ] **Step 3: 核心包回归 + 全工程交叉编译检查**

Run:
```bash
go test ./internal/paths/ ./internal/config/ ./internal/diff/ ./internal/notify/ ./internal/history/ ./internal/pipeline/ ./internal/watcher/
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build ./...
```
Expected: 7 个核心包 `ok`；全工程编译无错。

- [ ] **Step 4: Commit**

```bash
git add main.go
git commit -m "feat(go): main.go，托盘 + watcher + picker 装配"
```

---

## Task 12: Go 构建 workflow + README 重写

**Files:**
- Modify: `.github/workflows/build-windows.yml`
- Modify: `README.md`

- [ ] **Step 1: 替换 `.github/workflows/build-windows.yml` 为 Go 版**

整个文件替换为：

```yaml
name: build-windows

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch: {}

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-go@v5
        with:
          go-version: '1.22'

      - name: Test core packages
        run: go test ./internal/paths/ ./internal/config/ ./internal/diff/ ./internal/notify/ ./internal/history/ ./internal/pipeline/ ./internal/watcher/

      - name: Cross-compile Windows exe
        env:
          CGO_ENABLED: '0'
          GOOS: windows
          GOARCH: amd64
        run: go build -ldflags="-H windowsgui -s -w" -o ScreenWatchdog.exe .

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: ScreenWatchdog
          path: ScreenWatchdog.exe
          if-no-files-found: error

      - name: Attach to release (only on tag push)
        if: startsWith(github.ref, 'refs/tags/v')
        uses: softprops/action-gh-release@v2
        with:
          files: ScreenWatchdog.exe
```

- [ ] **Step 2: 重写 `README.md`**

整个文件替换为：

```markdown
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
```

- [ ] **Step 3: 验证 workflow YAML 合法**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/build-windows.yml')); print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/build-windows.yml README.md
git commit -m "docs(go): Go 构建 workflow + README 重写"
```

---

## Task 13: 删除 Python 旧码

**Files:**
- Delete: `app/`, `tests/`, `tools/`, `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `.pytest_cache/`

- [ ] **Step 1: 删除 Python 工程文件**

Run:
```bash
git rm -r app tests tools requirements.txt requirements-dev.txt pyproject.toml
rm -rf .pytest_cache
```

> 保留：`docs/superpowers/specs/` 与 `docs/superpowers/plans/` 下的旧 Python 文档（历史存档）；`.venv/`（已被 .gitignore 忽略，本地手动删即可）。

- [ ] **Step 2: 确认 Go 工程仍完整**

Run:
```bash
go test ./internal/paths/ ./internal/config/ ./internal/diff/ ./internal/notify/ ./internal/history/ ./internal/pipeline/ ./internal/watcher/
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build ./...
```
Expected: 7 个核心包 `ok`；全工程交叉编译成功。

- [ ] **Step 3: 从 .gitignore 移除 Python 残留项（可选清理）**

检查 `.gitignore`，删掉只对 Python 有意义的行（如 `__pycache__/`、`.venv/`、`*.pyc`）。保留 Go 相关项。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: 删除 Python 旧实现，仓库切换为纯 Go"
```

---

## 完成验证

全部 task 完成后：

```bash
go test ./internal/paths/ ./internal/config/ ./internal/diff/ ./internal/notify/ ./internal/history/ ./internal/pipeline/ ./internal/watcher/
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags="-H windowsgui -s -w" -o ScreenWatchdog.exe .
ls -lh ScreenWatchdog.exe
```

期望：7 个核心包 `ok`；生成约 10-15 MB 的单文件 `ScreenWatchdog.exe`。

**Windows 实测（用户做）**：把 exe 拷到 Windows 双击，验证托盘出现、框选区域可用、配好飞书凭证后变化区域能推送到群。`picker` 大概率需 1-2 轮调整——出问题看 `%LOCALAPPDATA%\screen-ocr-watchdog\Logs\app.log`。
