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
