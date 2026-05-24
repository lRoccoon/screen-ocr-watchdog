package notify

import (
	"encoding/json"
	"image"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

func tinyImage() image.Image {
	return image.NewRGBA(image.Rect(0, 0, 4, 4))
}

// fakeLark 是一个假冒飞书 API 的 httptest server，记录各端点命中次数。
type fakeLark struct {
	server     *httptest.Server
	mu         sync.Mutex
	tokenHits  int
	uploadHits int
	msgHits    int
	tokenCode  int
	uploadCode int
	// 按 receive_id 决定 send_message 端点返回 code；查无对应项时返回 0。
	msgCodeByReceiveID map[string]int
	msgReceiveIDs      []string
	msgReceiveTypes    []string
}

func newFakeLark() *fakeLark {
	f := &fakeLark{msgCodeByReceiveID: map[string]int{}}
	mux := http.NewServeMux()
	mux.HandleFunc("/open-apis/auth/v3/tenant_access_token/internal", func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		f.tokenHits++
		code := f.tokenCode
		f.mu.Unlock()
		_ = json.NewEncoder(w).Encode(map[string]any{
			"code": code, "msg": "x",
			"tenant_access_token": "t-abc", "expire": 7200,
		})
	})
	mux.HandleFunc("/open-apis/im/v1/images", func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		f.uploadHits++
		code := f.uploadCode
		f.mu.Unlock()
		_ = json.NewEncoder(w).Encode(map[string]any{
			"code": code, "msg": "x",
			"data": map[string]any{"image_key": "img_v3_xxx"},
		})
	})
	mux.HandleFunc("/open-apis/im/v1/messages", func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var p struct {
			ReceiveID string `json:"receive_id"`
		}
		_ = json.Unmarshal(body, &p)
		f.mu.Lock()
		f.msgHits++
		f.msgReceiveIDs = append(f.msgReceiveIDs, p.ReceiveID)
		f.msgReceiveTypes = append(f.msgReceiveTypes, r.URL.Query().Get("receive_id_type"))
		code := f.msgCodeByReceiveID[p.ReceiveID]
		f.mu.Unlock()
		_ = json.NewEncoder(w).Encode(map[string]any{"code": code, "msg": "ok"})
	})
	f.server = httptest.NewServer(mux)
	return f
}

func newClientFor(f *fakeLark, targets []Target) *LarkClient {
	c := NewLarkClient("cli_x", "sec_x", targets)
	c.baseURL = f.server.URL
	return c
}

// ---------- 单 target（兼容原 v1 行为）----------

func TestSendImageSingleTargetHappyPath(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := newClientFor(f, []Target{{ReceiveID: "oc_x", ReceiveIDType: "chat_id"}})
	if err := c.SendImage(tinyImage()); err != nil {
		t.Fatalf("SendImage: %v", err)
	}
	if f.tokenHits != 1 || f.uploadHits != 1 || f.msgHits != 1 {
		t.Errorf("hits: token=%d upload=%d msg=%d, want 1/1/1", f.tokenHits, f.uploadHits, f.msgHits)
	}
	if f.msgReceiveIDs[0] != "oc_x" {
		t.Errorf("msg receive_id = %q, want oc_x", f.msgReceiveIDs[0])
	}
	if f.msgReceiveTypes[0] != "chat_id" {
		t.Errorf("msg receive_id_type = %q, want chat_id", f.msgReceiveTypes[0])
	}
}

func TestTokenCachedAcrossCalls(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := newClientFor(f, []Target{{ReceiveID: "oc_x", ReceiveIDType: "chat_id"}})
	_ = c.SendImage(tinyImage())
	_ = c.SendImage(tinyImage())
	if f.tokenHits != 1 {
		t.Errorf("tokenHits = %d, want 1 (cached)", f.tokenHits)
	}
}

func TestExpiredTokenRefreshed(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := newClientFor(f, []Target{{ReceiveID: "oc_x", ReceiveIDType: "chat_id"}})
	_ = c.SendImage(tinyImage())
	c.tokenExpiresAt = time.Now().Add(-time.Hour)
	_ = c.SendImage(tinyImage())
	if f.tokenHits != 2 {
		t.Errorf("tokenHits = %d, want 2 (refresh)", f.tokenHits)
	}
}

func TestTokenBusinessErrorFails(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	f.tokenCode = 99991663
	c := newClientFor(f, []Target{{ReceiveID: "oc_x", ReceiveIDType: "chat_id"}})
	err := c.SendImage(tinyImage())
	if err == nil || !strings.Contains(err.Error(), "99991663") {
		t.Fatalf("err = %v, want to contain 99991663", err)
	}
}

func TestUploadBusinessErrorAbortsSend(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	f.uploadCode = 230002
	c := newClientFor(f, []Target{
		{ReceiveID: "oc_a", ReceiveIDType: "chat_id"},
		{ReceiveID: "ou_b", ReceiveIDType: "open_id"},
	})
	err := c.SendImage(tinyImage())
	if err == nil || !strings.Contains(err.Error(), "230002") {
		t.Fatalf("err = %v, want to contain 230002", err)
	}
	if f.msgHits != 0 {
		t.Errorf("send_message hits = %d, want 0 (upload failed)", f.msgHits)
	}
}

func TestMissingCredentialsShortCircuits(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := NewLarkClient("", "", []Target{{ReceiveID: "oc_x", ReceiveIDType: "chat_id"}})
	c.baseURL = f.server.URL
	err := c.SendImage(tinyImage())
	if err == nil {
		t.Fatal("expected error for missing credentials")
	}
	if f.tokenHits != 0 {
		t.Errorf("tokenHits = %d, want 0 (short-circuit)", f.tokenHits)
	}
}

func TestEmptyTargetsShortCircuits(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := NewLarkClient("cli_x", "sec_x", nil)
	c.baseURL = f.server.URL
	err := c.SendImage(tinyImage())
	if err == nil {
		t.Fatal("expected error for empty targets")
	}
	if !strings.Contains(err.Error(), "target") {
		t.Errorf("err = %v, want to contain 'target'", err)
	}
	if f.tokenHits != 0 {
		t.Errorf("tokenHits = %d, want 0 (short-circuit)", f.tokenHits)
	}
}

func TestNetworkErrorFails(t *testing.T) {
	c := NewLarkClient("cli_x", "sec_x", []Target{{ReceiveID: "oc_x", ReceiveIDType: "chat_id"}})
	c.baseURL = "http://127.0.0.1:0"
	if err := c.SendImage(tinyImage()); err == nil {
		t.Fatal("expected network error")
	}
}

// ---------- 多 target ----------

func TestSendImageMultiTargetsAllSuccessUploadOnce(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := newClientFor(f, []Target{
		{ReceiveID: "oc_a", ReceiveIDType: "chat_id"},
		{ReceiveID: "ou_b", ReceiveIDType: "open_id"},
		{ReceiveID: "user@example.com", ReceiveIDType: "email"},
	})
	if err := c.SendImage(tinyImage()); err != nil {
		t.Fatalf("SendImage: %v", err)
	}
	if f.tokenHits != 1 || f.uploadHits != 1 {
		t.Errorf("token=%d upload=%d, want 1/1", f.tokenHits, f.uploadHits)
	}
	if f.msgHits != 3 {
		t.Errorf("msgHits = %d, want 3", f.msgHits)
	}
	if got := strings.Join(f.msgReceiveIDs, ","); got != "oc_a,ou_b,user@example.com" {
		t.Errorf("receive_ids = %q, want oc_a,ou_b,user@example.com", got)
	}
	if got := strings.Join(f.msgReceiveTypes, ","); got != "chat_id,open_id,email" {
		t.Errorf("receive_id_types = %q, want chat_id,open_id,email", got)
	}
}

func TestSendImageMultiTargetsPartialFailDoesNotBlockOthers(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	f.msgCodeByReceiveID["ou_b"] = 230020 // 第 2 个 target 业务错误
	c := newClientFor(f, []Target{
		{ReceiveID: "oc_a", ReceiveIDType: "chat_id"},
		{ReceiveID: "ou_b", ReceiveIDType: "open_id"},
		{ReceiveID: "user@example.com", ReceiveIDType: "email"},
	})
	err := c.SendImage(tinyImage())
	if err == nil {
		t.Fatal("expected partial-fail error")
	}
	if !strings.Contains(err.Error(), "1/3") {
		t.Errorf("err = %v, want to contain 1/3", err)
	}
	if !strings.Contains(err.Error(), "ou_b") {
		t.Errorf("err = %v, want to contain ou_b", err)
	}
	if f.uploadHits != 1 {
		t.Errorf("uploadHits = %d, want 1 (upload reused)", f.uploadHits)
	}
	if f.msgHits != 3 {
		t.Errorf("msgHits = %d, want 3 (all targets attempted)", f.msgHits)
	}
}

func TestSendImageMultiTargetsAllFail(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	f.msgCodeByReceiveID["oc_a"] = 230020
	f.msgCodeByReceiveID["ou_b"] = 230020
	c := newClientFor(f, []Target{
		{ReceiveID: "oc_a", ReceiveIDType: "chat_id"},
		{ReceiveID: "ou_b", ReceiveIDType: "open_id"},
	})
	err := c.SendImage(tinyImage())
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "all 2") {
		t.Errorf("err = %v, want to contain 'all 2'", err)
	}
}
