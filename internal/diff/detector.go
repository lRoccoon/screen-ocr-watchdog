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
