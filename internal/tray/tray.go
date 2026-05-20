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
