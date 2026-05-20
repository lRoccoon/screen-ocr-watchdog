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
