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
		targets := l.EffectiveTargets()
		if l.AppID == "" || l.AppSecret == "" || len(targets) == 0 {
			return nil, fmt.Errorf("image_diff mode requires lark.app_id/app_secret and at least one target (lark.targets or lark.receive_id)")
		}
		det := diff.NewDetector(
			cfg.ImageDiff.PixelDiffThreshold,
			cfg.ImageDiff.ChangeRatioThreshold,
			cfg.ImageDiff.MinIntervalSeconds,
			cfg.ImageDiff.BboxPadding,
		)
		sender := notify.NewLarkClient(l.AppID, l.AppSecret, targets)
		return &ImagePipeline{det: det, sender: sender, store: store, now: time.Now}, nil
	default:
		return nil, fmt.Errorf("unsupported mode: %q", cfg.Mode)
	}
}
