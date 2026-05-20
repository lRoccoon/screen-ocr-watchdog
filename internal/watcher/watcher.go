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
