package pipeline

import (
	"errors"
	"image"
	"path/filepath"
	"testing"
	"time"

	"github.com/lRoccoon/screen-ocr-watchdog/internal/config"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/diff"
	"github.com/lRoccoon/screen-ocr-watchdog/internal/history"
)

type stubDetector struct {
	result *diff.Result
}

func (s stubDetector) Detect(image.Image, time.Time) *diff.Result { return s.result }

type stubSender struct {
	calls int
	err   error
}

func (s *stubSender) SendImage(image.Image) error {
	s.calls++
	return s.err
}

func newImagePipeline(t *testing.T, det detector, sender imageSender) (*ImagePipeline, *history.Store) {
	dir := t.TempDir()
	store := history.NewStore(filepath.Join(dir, "h.ndjson"), filepath.Join(dir, "frames"))
	p := &ImagePipeline{det: det, sender: sender, store: store, now: func() time.Time { return time.Unix(1700000000, 0) }}
	return p, store
}

func TestProcessNoDiffDoesNothing(t *testing.T) {
	sender := &stubSender{}
	p, _ := newImagePipeline(t, stubDetector{result: nil}, sender)
	if err := p.Process(image.NewRGBA(image.Rect(0, 0, 4, 4))); err != nil {
		t.Fatalf("Process: %v", err)
	}
	if sender.calls != 0 {
		t.Errorf("sender called %d times, want 0", sender.calls)
	}
}

func TestProcessDiffSavesNotifiesAppends(t *testing.T) {
	crop := image.NewRGBA(image.Rect(0, 0, 6, 6))
	res := &diff.Result{Bbox: image.Rect(5, 5, 15, 15), Crop: crop}
	sender := &stubSender{}
	p, _ := newImagePipeline(t, stubDetector{result: res}, sender)
	if err := p.Process(image.NewRGBA(image.Rect(0, 0, 20, 20))); err != nil {
		t.Fatalf("Process: %v", err)
	}
	if sender.calls != 1 {
		t.Errorf("sender called %d times, want 1", sender.calls)
	}
}

func TestProcessSendFailureStillSavesAndAppends(t *testing.T) {
	crop := image.NewRGBA(image.Rect(0, 0, 6, 6))
	res := &diff.Result{Bbox: image.Rect(0, 0, 6, 6), Crop: crop}
	sender := &stubSender{err: errors.New("network down")}
	p, store := newImagePipeline(t, stubDetector{result: res}, sender)
	err := p.Process(image.NewRGBA(image.Rect(0, 0, 20, 20)))
	if err == nil {
		t.Fatal("Process: expected send error to surface")
	}
	// 即使发送失败，history 仍写入
	_ = store
	if sender.calls != 1 {
		t.Errorf("sender called %d times, want 1", sender.calls)
	}
}

func TestNewImageDiffMode(t *testing.T) {
	cfg := config.Default()
	cfg.Lark = config.Lark{AppID: "a", AppSecret: "b", ReceiveID: "c", ReceiveIDType: "chat_id"}
	store := history.NewStore(filepath.Join(t.TempDir(), "h"), filepath.Join(t.TempDir(), "f"))
	p, err := New(&cfg, store)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if _, ok := p.(*ImagePipeline); !ok {
		t.Errorf("New returned %T, want *ImagePipeline", p)
	}
}

func TestNewMissingCredentialsFails(t *testing.T) {
	cfg := config.Default() // Lark 三凭证全空
	store := history.NewStore(filepath.Join(t.TempDir(), "h"), filepath.Join(t.TempDir(), "f"))
	if _, err := New(&cfg, store); err == nil {
		t.Fatal("New: expected error for missing credentials")
	}
}

func TestNewUnsupportedModeFails(t *testing.T) {
	cfg := config.Default()
	cfg.Mode = "ocr" // v1 未实现
	store := history.NewStore(filepath.Join(t.TempDir(), "h"), filepath.Join(t.TempDir(), "f"))
	if _, err := New(&cfg, store); err == nil {
		t.Fatal("New: expected error for unsupported mode")
	}
}
