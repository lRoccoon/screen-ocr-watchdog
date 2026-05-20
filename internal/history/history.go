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
