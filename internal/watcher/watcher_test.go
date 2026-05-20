package watcher

import (
	"errors"
	"image"
	"sync"
	"testing"
	"time"
)

type stubCapturer struct {
	img image.Image
	err error
}

func (s stubCapturer) Capture() (image.Image, error) { return s.img, s.err }

type stubProcessor struct {
	mu    sync.Mutex
	calls int
	err   error
}

func (s *stubProcessor) Process(image.Image) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	return s.err
}

func (s *stubProcessor) count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls
}

func TestTickCaptureErrorReportsError(t *testing.T) {
	var gotErr error
	w := New(stubCapturer{err: errors.New("no display")}, &stubProcessor{}, time.Second,
		func(e error) { gotErr = e })
	w.tick()
	if gotErr == nil {
		t.Fatal("capture error not reported to onError")
	}
}

func TestTickProcessErrorReportsError(t *testing.T) {
	var gotErr error
	proc := &stubProcessor{err: errors.New("send failed")}
	w := New(stubCapturer{img: image.NewRGBA(image.Rect(0, 0, 4, 4))}, proc, time.Second,
		func(e error) { gotErr = e })
	w.tick()
	if proc.count() != 1 {
		t.Errorf("processor calls = %d, want 1", proc.count())
	}
	if gotErr == nil {
		t.Fatal("process error not reported to onError")
	}
}

func TestTickHappyPathNoError(t *testing.T) {
	called := false
	proc := &stubProcessor{}
	w := New(stubCapturer{img: image.NewRGBA(image.Rect(0, 0, 4, 4))}, proc, time.Second,
		func(error) { called = true })
	w.tick()
	if proc.count() != 1 {
		t.Errorf("processor calls = %d, want 1", proc.count())
	}
	if called {
		t.Error("onError called on happy path")
	}
}

func TestPauseSkipsTick(t *testing.T) {
	proc := &stubProcessor{}
	w := New(stubCapturer{img: image.NewRGBA(image.Rect(0, 0, 4, 4))}, proc, 10*time.Millisecond, func(error) {})
	w.Pause()
	w.Start()
	time.Sleep(50 * time.Millisecond)
	w.Stop()
	if proc.count() != 0 {
		t.Errorf("processor called %d times while paused, want 0", proc.count())
	}
}

func TestStartResumeRunsTicks(t *testing.T) {
	proc := &stubProcessor{}
	w := New(stubCapturer{img: image.NewRGBA(image.Rect(0, 0, 4, 4))}, proc, 10*time.Millisecond, func(error) {})
	w.Start()
	time.Sleep(60 * time.Millisecond)
	w.Stop()
	if proc.count() == 0 {
		t.Error("processor never called after Start")
	}
}
