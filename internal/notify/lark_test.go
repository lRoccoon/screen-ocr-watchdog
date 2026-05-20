package notify

import (
	"encoding/json"
	"image"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func tinyImage() image.Image {
	return image.NewRGBA(image.Rect(0, 0, 4, 4))
}

// fakeLark 是一个假冒飞书 API 的 httptest server，记录各端点命中次数。
type fakeLark struct {
	server     *httptest.Server
	tokenHits  int
	uploadHits int
	msgHits    int
	tokenCode  int // 注入 token 端点返回的 code
	uploadCode int // 注入上传端点返回的 code
}

func newFakeLark() *fakeLark {
	f := &fakeLark{}
	mux := http.NewServeMux()
	mux.HandleFunc("/open-apis/auth/v3/tenant_access_token/internal", func(w http.ResponseWriter, r *http.Request) {
		f.tokenHits++
		json.NewEncoder(w).Encode(map[string]any{
			"code": f.tokenCode, "msg": "x",
			"tenant_access_token": "t-abc", "expire": 7200,
		})
	})
	mux.HandleFunc("/open-apis/im/v1/images", func(w http.ResponseWriter, r *http.Request) {
		f.uploadHits++
		json.NewEncoder(w).Encode(map[string]any{
			"code": f.uploadCode, "msg": "x",
			"data": map[string]any{"image_key": "img_v3_xxx"},
		})
	})
	mux.HandleFunc("/open-apis/im/v1/messages", func(w http.ResponseWriter, r *http.Request) {
		f.msgHits++
		json.NewEncoder(w).Encode(map[string]any{"code": 0, "msg": "ok"})
	})
	f.server = httptest.NewServer(mux)
	return f
}

func newClientFor(f *fakeLark) *LarkClient {
	c := NewLarkClient("cli_x", "sec_x", "oc_x", "chat_id")
	c.baseURL = f.server.URL
	return c
}

func TestSendImageHappyPath(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := newClientFor(f)
	if err := c.SendImage(tinyImage()); err != nil {
		t.Fatalf("SendImage: %v", err)
	}
	if f.tokenHits != 1 || f.uploadHits != 1 || f.msgHits != 1 {
		t.Errorf("hits: token=%d upload=%d msg=%d, want 1/1/1", f.tokenHits, f.uploadHits, f.msgHits)
	}
}

func TestTokenCachedAcrossCalls(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := newClientFor(f)
	_ = c.SendImage(tinyImage())
	_ = c.SendImage(tinyImage())
	if f.tokenHits != 1 {
		t.Errorf("tokenHits = %d, want 1 (cached)", f.tokenHits)
	}
}

func TestExpiredTokenRefreshed(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := newClientFor(f)
	_ = c.SendImage(tinyImage())
	c.tokenExpiresAt = time.Now().Add(-time.Hour) // 强制过期
	_ = c.SendImage(tinyImage())
	if f.tokenHits != 2 {
		t.Errorf("tokenHits = %d, want 2 (refresh)", f.tokenHits)
	}
}

func TestTokenBusinessErrorFails(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	f.tokenCode = 99991663
	c := newClientFor(f)
	err := c.SendImage(tinyImage())
	if err == nil || !strings.Contains(err.Error(), "99991663") {
		t.Fatalf("err = %v, want to contain 99991663", err)
	}
}

func TestUploadBusinessErrorFails(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	f.uploadCode = 230002
	c := newClientFor(f)
	err := c.SendImage(tinyImage())
	if err == nil || !strings.Contains(err.Error(), "230002") {
		t.Fatalf("err = %v, want to contain 230002", err)
	}
}

func TestMissingCredentialsShortCircuits(t *testing.T) {
	f := newFakeLark()
	defer f.server.Close()
	c := NewLarkClient("", "", "oc_x", "chat_id")
	c.baseURL = f.server.URL
	err := c.SendImage(tinyImage())
	if err == nil {
		t.Fatal("expected error for missing credentials")
	}
	if f.tokenHits != 0 {
		t.Errorf("tokenHits = %d, want 0 (short-circuit)", f.tokenHits)
	}
}

func TestNetworkErrorFails(t *testing.T) {
	c := NewLarkClient("cli_x", "sec_x", "oc_x", "chat_id")
	c.baseURL = "http://127.0.0.1:0" // 无法连接
	if err := c.SendImage(tinyImage()); err == nil {
		t.Fatal("expected network error")
	}
}
