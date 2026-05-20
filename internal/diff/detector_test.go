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
