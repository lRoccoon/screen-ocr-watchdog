package history

import (
	"bufio"
	"encoding/json"
	"image"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestSaveFrameWritesPNG(t *testing.T) {
	dir := t.TempDir()
	s := NewStore(filepath.Join(dir, "history.ndjson"), filepath.Join(dir, "frames"))
	img := image.NewRGBA(image.Rect(0, 0, 8, 8))
	path, err := s.SaveFrame(img, time.Unix(1700000000, 123456789))
	if err != nil {
		t.Fatalf("SaveFrame: %v", err)
	}
	if filepath.Dir(path) != filepath.Join(dir, "frames") {
		t.Errorf("frame saved to %q, want under frames dir", path)
	}
	if _, err := os.Stat(path); err != nil {
		t.Errorf("frame file not found: %v", err)
	}
}

func TestAppendWritesJSONL(t *testing.T) {
	dir := t.TempDir()
	hp := filepath.Join(dir, "history.ndjson")
	s := NewStore(hp, filepath.Join(dir, "frames"))
	if err := s.Append(Record{TS: "t1", Bbox: [4]int{1, 2, 3, 4}, Image: "a.png"}); err != nil {
		t.Fatalf("Append: %v", err)
	}
	if err := s.Append(Record{TS: "t2", Bbox: [4]int{5, 6, 7, 8}, Image: "b.png"}); err != nil {
		t.Fatalf("Append: %v", err)
	}
	f, err := os.Open(hp)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var recs []Record
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		var r Record
		if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
			t.Fatalf("bad JSONL line: %v", err)
		}
		recs = append(recs, r)
	}
	if len(recs) != 2 || recs[0].TS != "t1" || recs[1].Image != "b.png" {
		t.Errorf("records = %+v, want 2 ordered records", recs)
	}
}
