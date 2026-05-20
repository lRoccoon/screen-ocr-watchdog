package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadMissingFileReturnsDefaults(t *testing.T) {
	cfg, err := Load(filepath.Join(t.TempDir(), "missing.yaml"))
	if err != nil {
		t.Fatalf("Load missing file: unexpected err %v", err)
	}
	if cfg.Mode != "image_diff" {
		t.Errorf("Mode = %q, want image_diff", cfg.Mode)
	}
	if cfg.IntervalSeconds != 5 {
		t.Errorf("IntervalSeconds = %d, want 5", cfg.IntervalSeconds)
	}
	if cfg.ImageDiff.PixelDiffThreshold != 30 {
		t.Errorf("PixelDiffThreshold = %d, want 30", cfg.ImageDiff.PixelDiffThreshold)
	}
	if cfg.ImageDiff.ChangeRatioThreshold != 0.005 {
		t.Errorf("ChangeRatioThreshold = %v, want 0.005", cfg.ImageDiff.ChangeRatioThreshold)
	}
	if cfg.ImageDiff.BboxPadding != 8 {
		t.Errorf("BboxPadding = %d, want 8", cfg.ImageDiff.BboxPadding)
	}
	if cfg.Lark.ReceiveIDType != "chat_id" {
		t.Errorf("ReceiveIDType = %q, want chat_id", cfg.Lark.ReceiveIDType)
	}
}

func TestLoadPartialYAMLKeepsDefaults(t *testing.T) {
	p := filepath.Join(t.TempDir(), "c.yaml")
	content := "" +
		"mode: image_diff\n" +
		"region:\n" +
		"  x: 100\n" +
		"  y: 200\n" +
		"  width: 300\n" +
		"  height: 400\n" +
		"image_diff:\n" +
		"  pixel_diff_threshold: 50\n" +
		"lark:\n" +
		"  app_id: cli_x\n" +
		"  app_secret: sec_x\n" +
		"  receive_id: oc_x\n"
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Region.W != 300 || cfg.Region.H != 400 {
		t.Errorf("Region = %+v, want W=300 H=400", cfg.Region)
	}
	if cfg.ImageDiff.PixelDiffThreshold != 50 {
		t.Errorf("PixelDiffThreshold = %d, want 50", cfg.ImageDiff.PixelDiffThreshold)
	}
	// 未写字段保留默认
	if cfg.ImageDiff.BboxPadding != 8 {
		t.Errorf("BboxPadding = %d, want default 8", cfg.ImageDiff.BboxPadding)
	}
	if cfg.Lark.AppID != "cli_x" {
		t.Errorf("AppID = %q, want cli_x", cfg.Lark.AppID)
	}
}

func TestSaveThenLoadRoundTrips(t *testing.T) {
	cfg := Default()
	cfg.Region = Region{X: 1, Y: 2, W: 3, H: 4}
	cfg.Lark.AppID = "cli_round"
	p := filepath.Join(t.TempDir(), "sub", "c.yaml")
	if err := Save(cfg, p); err != nil {
		t.Fatalf("Save: %v", err)
	}
	got, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got.Region != cfg.Region {
		t.Errorf("Region round-trip = %+v, want %+v", got.Region, cfg.Region)
	}
	if got.Lark.AppID != "cli_round" {
		t.Errorf("AppID round-trip = %q, want cli_round", got.Lark.AppID)
	}
}

func TestLoadMalformedYAMLReturnsError(t *testing.T) {
	p := filepath.Join(t.TempDir(), "bad.yaml")
	if err := os.WriteFile(p, []byte("mode: [unclosed"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(p); err == nil {
		t.Fatal("Load malformed YAML: expected error, got nil")
	}
}
