package config

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/lRoccoon/screen-ocr-watchdog/internal/notify"
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

// ---------- EffectiveTargets ----------

func TestEffectiveTargetsListTakesPriority(t *testing.T) {
	l := Lark{
		Targets: []notify.Target{
			{ReceiveID: "oc_a", ReceiveIDType: "chat_id"},
			{ReceiveID: "ou_b", ReceiveIDType: "open_id"},
		},
		ReceiveID:     "legacy",
		ReceiveIDType: "chat_id",
	}
	got := l.EffectiveTargets()
	if len(got) != 2 || got[0].ReceiveID != "oc_a" || got[1].ReceiveID != "ou_b" {
		t.Errorf("EffectiveTargets = %+v, want [oc_a/chat_id, ou_b/open_id]", got)
	}
}

func TestEffectiveTargetsFallbackToSingleField(t *testing.T) {
	l := Lark{ReceiveID: "oc_legacy", ReceiveIDType: "chat_id"}
	got := l.EffectiveTargets()
	if len(got) != 1 || got[0].ReceiveID != "oc_legacy" || got[0].ReceiveIDType != "chat_id" {
		t.Errorf("EffectiveTargets = %+v, want [oc_legacy/chat_id]", got)
	}
}

func TestEffectiveTargetsFallbackDefaultsTypeChatID(t *testing.T) {
	l := Lark{ReceiveID: "oc_legacy"} // ReceiveIDType 为空
	got := l.EffectiveTargets()
	if len(got) != 1 || got[0].ReceiveIDType != "chat_id" {
		t.Errorf("EffectiveTargets = %+v, want default type chat_id", got)
	}
}

func TestEffectiveTargetsBothEmptyReturnsNil(t *testing.T) {
	if got := (Lark{}).EffectiveTargets(); got != nil {
		t.Errorf("EffectiveTargets = %+v, want nil", got)
	}
}

func TestEffectiveTargetsDropsBlankReceiveIDsInList(t *testing.T) {
	l := Lark{Targets: []notify.Target{
		{ReceiveID: "oc_a", ReceiveIDType: "chat_id"},
		{ReceiveID: "", ReceiveIDType: "chat_id"},
	}}
	got := l.EffectiveTargets()
	if len(got) != 1 || got[0].ReceiveID != "oc_a" {
		t.Errorf("EffectiveTargets = %+v, want only [oc_a]", got)
	}
}

func TestEffectiveTargetsListEntryDefaultsTypeChatID(t *testing.T) {
	l := Lark{Targets: []notify.Target{
		{ReceiveID: "oc_a"}, // ReceiveIDType 为空
	}}
	got := l.EffectiveTargets()
	if len(got) != 1 || got[0].ReceiveIDType != "chat_id" {
		t.Errorf("EffectiveTargets = %+v, want default type chat_id", got)
	}
}

func TestLoadV1YAMLWithSingleReceiveIDFallsBack(t *testing.T) {
	p := filepath.Join(t.TempDir(), "v1.yaml")
	content := "" +
		"mode: image_diff\n" +
		"lark:\n" +
		"  app_id: cli_x\n" +
		"  app_secret: sec_x\n" +
		"  receive_id: oc_legacy\n" +
		"  receive_id_type: chat_id\n"
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if len(cfg.Lark.Targets) != 0 {
		t.Errorf("Targets = %+v, want empty (legacy yaml)", cfg.Lark.Targets)
	}
	got := cfg.Lark.EffectiveTargets()
	if len(got) != 1 || got[0].ReceiveID != "oc_legacy" {
		t.Errorf("EffectiveTargets = %+v, want [oc_legacy]", got)
	}
}

func TestLoadNewYAMLWithTargetsList(t *testing.T) {
	p := filepath.Join(t.TempDir(), "new.yaml")
	content := "" +
		"mode: image_diff\n" +
		"lark:\n" +
		"  app_id: cli_x\n" +
		"  app_secret: sec_x\n" +
		"  targets:\n" +
		"    - receive_id: oc_a\n" +
		"      receive_id_type: chat_id\n" +
		"    - receive_id: ou_b\n" +
		"      receive_id_type: open_id\n"
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	got := cfg.Lark.EffectiveTargets()
	if len(got) != 2 || got[0].ReceiveID != "oc_a" || got[1].ReceiveID != "ou_b" {
		t.Errorf("EffectiveTargets = %+v, want [oc_a, ou_b]", got)
	}
	if got[0].ReceiveIDType != "chat_id" || got[1].ReceiveIDType != "open_id" {
		t.Errorf("EffectiveTargets types = %+v, want [chat_id, open_id]", got)
	}
}
