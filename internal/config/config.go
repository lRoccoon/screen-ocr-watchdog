// Package config 定义 YAML 配置 schema 与读写。
package config

import (
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"

	"github.com/lRoccoon/screen-ocr-watchdog/internal/notify"
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

// Lark 是飞书自建应用凭证与目标。Targets 为主；ReceiveID/ReceiveIDType
// 是 v1 单目标的旧字段，作为 Targets 为空时的 fallback 保留向后兼容。
type Lark struct {
	AppID     string          `yaml:"app_id"`
	AppSecret string          `yaml:"app_secret"`
	Targets   []notify.Target `yaml:"targets"`

	// 旧（Targets 为空时 fallback）
	ReceiveID     string `yaml:"receive_id"`
	ReceiveIDType string `yaml:"receive_id_type"`
}

// EffectiveTargets 解析生效的发送目标列表：
// Targets 非空时优先用 Targets，过滤掉 receive_id 为空的项并补默认 type；
// 否则 ReceiveID 非空时回退为单元素列表；都空返回 nil。
func (l Lark) EffectiveTargets() []notify.Target {
	if len(l.Targets) > 0 {
		out := make([]notify.Target, 0, len(l.Targets))
		for _, t := range l.Targets {
			if t.ReceiveID == "" {
				continue
			}
			if t.ReceiveIDType == "" {
				t.ReceiveIDType = "chat_id"
			}
			out = append(out, t)
		}
		return out
	}
	if l.ReceiveID != "" {
		rt := l.ReceiveIDType
		if rt == "" {
			rt = "chat_id"
		}
		return []notify.Target{{ReceiveID: l.ReceiveID, ReceiveIDType: rt}}
	}
	return nil
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
