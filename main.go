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
	cfg       config.Config
	store     *history.Store
	watch     *watcher.Watcher
	paused    bool
	configErr error // 非 nil 表示 config.yaml 解析失败
}

func main() {
	setupLogging()

	cfg, err := config.Load(paths.ConfigPath())
	if err != nil {
		slog.Error("load config failed", "err", err)
	}
	c := &controller{
		cfg:       cfg,
		store:     history.NewStore(paths.HistoryPath(), paths.FramesDir()),
		configErr: err,
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
	if c.configErr != nil {
		// config.yaml 损坏：明确提示，区别于"未配置区域"
		tray.SetState(tray.StateError, "配置文件损坏，请检查 config.yaml: "+c.configErr.Error())
		return
	}
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
