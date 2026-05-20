package paths

import (
	"path/filepath"
	"testing"
)

func TestConfigPathUsesAppData(t *testing.T) {
	t.Setenv("APPDATA", filepath.FromSlash("/tmp/sow-appdata"))
	got := ConfigPath()
	want := filepath.Join("/tmp/sow-appdata", "screen-ocr-watchdog", "config.yaml")
	if got != want {
		t.Fatalf("ConfigPath() = %q, want %q", got, want)
	}
}

func TestDataPathsUseLocalAppData(t *testing.T) {
	t.Setenv("LOCALAPPDATA", filepath.FromSlash("/tmp/sow-local"))
	base := filepath.Join("/tmp/sow-local", "screen-ocr-watchdog")
	if got, want := HistoryPath(), filepath.Join(base, "history.ndjson"); got != want {
		t.Fatalf("HistoryPath() = %q, want %q", got, want)
	}
	if got, want := FramesDir(), filepath.Join(base, "diff_frames"); got != want {
		t.Fatalf("FramesDir() = %q, want %q", got, want)
	}
	if got, want := LogPath(), filepath.Join(base, "Logs", "app.log"); got != want {
		t.Fatalf("LogPath() = %q, want %q", got, want)
	}
}
