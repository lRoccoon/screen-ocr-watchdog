// Package notify 实现飞书自建应用的图片消息发送。
package notify

import (
	"bytes"
	"encoding/json"
	"fmt"
	"image"
	"image/png"
	"mime/multipart"
	"net/http"
	"strings"
	"sync"
	"time"
)

const tokenRefreshBuffer = 5 * time.Minute

// Target 是一个飞书发送目标。
type Target struct {
	ReceiveID     string `yaml:"receive_id"`
	ReceiveIDType string `yaml:"receive_id_type"`
}

// LarkClient 通过飞书自建应用上传图片并发 image 消息到一个或多个目标。
type LarkClient struct {
	appID     string
	appSecret string
	targets   []Target

	baseURL    string
	httpClient *http.Client

	mu             sync.Mutex
	token          string
	tokenExpiresAt time.Time
}

// NewLarkClient 构造客户端。targets 为空时 SendImage 会直接报错。
func NewLarkClient(appID, appSecret string, targets []Target) *LarkClient {
	return &LarkClient{
		appID:      appID,
		appSecret:  appSecret,
		targets:    append([]Target(nil), targets...),
		baseURL:    "https://open.feishu.cn",
		httpClient: &http.Client{Timeout: 10 * time.Second},
	}
}

// SendImage 上传图片一次，扇出发送到所有 targets。
// 1 帧只调 1 次 token、1 次 upload，复用 image_key 调 N 次 send_message。
// 部分失败不阻断其他 target；返回值聚合：全成功 nil；否则报错并描述
// 失败的 receive_id。
func (c *LarkClient) SendImage(img image.Image) error {
	if c.appID == "" || c.appSecret == "" || len(c.targets) == 0 {
		return fmt.Errorf("lark: missing credentials or no targets configured")
	}
	token, err := c.getToken()
	if err != nil {
		return fmt.Errorf("lark: get token: %w", err)
	}
	imageKey, err := c.uploadImage(token, img)
	if err != nil {
		return fmt.Errorf("lark: upload image: %w", err)
	}
	var failures []string
	for _, t := range c.targets {
		if err := c.sendImageMessage(token, imageKey, t); err != nil {
			failures = append(failures, fmt.Sprintf("%s=%v", t.ReceiveID, err))
		}
	}
	n := len(c.targets)
	if len(failures) == 0 {
		return nil
	}
	if len(failures) == n {
		return fmt.Errorf("lark: all %d targets failed: %s", n, strings.Join(failures, "; "))
	}
	return fmt.Errorf("lark: %d/%d targets failed: %s", len(failures), n, strings.Join(failures, "; "))
}

func (c *LarkClient) getToken() (string, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.token != "" && time.Now().Before(c.tokenExpiresAt.Add(-tokenRefreshBuffer)) {
		return c.token, nil
	}
	reqBody, _ := json.Marshal(map[string]string{"app_id": c.appID, "app_secret": c.appSecret})
	resp, err := c.httpClient.Post(
		c.baseURL+"/open-apis/auth/v3/tenant_access_token/internal",
		"application/json", bytes.NewReader(reqBody))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	var r struct {
		Code   int    `json:"code"`
		Msg    string `json:"msg"`
		Token  string `json:"tenant_access_token"`
		Expire int    `json:"expire"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		return "", err
	}
	if r.Code != 0 {
		return "", fmt.Errorf("token endpoint code=%d msg=%s", r.Code, r.Msg)
	}
	c.token = r.Token
	c.tokenExpiresAt = time.Now().Add(time.Duration(r.Expire) * time.Second)
	return c.token, nil
}

func (c *LarkClient) uploadImage(token string, img image.Image) (string, error) {
	var pngBuf bytes.Buffer
	if err := png.Encode(&pngBuf, img); err != nil {
		return "", err
	}
	var body bytes.Buffer
	mw := multipart.NewWriter(&body)
	if err := mw.WriteField("image_type", "message"); err != nil {
		return "", err
	}
	fw, err := mw.CreateFormFile("image", "diff.png")
	if err != nil {
		return "", err
	}
	if _, err := fw.Write(pngBuf.Bytes()); err != nil {
		return "", err
	}
	if err := mw.Close(); err != nil {
		return "", err
	}
	req, err := http.NewRequest(http.MethodPost, c.baseURL+"/open-apis/im/v1/images", &body)
	if err != nil {
		return "", err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	var r struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
		Data struct {
			ImageKey string `json:"image_key"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		return "", err
	}
	if r.Code != 0 {
		return "", fmt.Errorf("upload endpoint code=%d msg=%s", r.Code, r.Msg)
	}
	return r.Data.ImageKey, nil
}

func (c *LarkClient) sendImageMessage(token, imageKey string, t Target) error {
	content, _ := json.Marshal(map[string]string{"image_key": imageKey})
	reqBody, _ := json.Marshal(map[string]string{
		"receive_id": t.ReceiveID,
		"msg_type":   "image",
		"content":    string(content),
	})
	url := c.baseURL + "/open-apis/im/v1/messages?receive_id_type=" + t.ReceiveIDType
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(reqBody))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	var r struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		return err
	}
	if r.Code != 0 {
		return fmt.Errorf("message endpoint code=%d msg=%s", r.Code, r.Msg)
	}
	return nil
}
