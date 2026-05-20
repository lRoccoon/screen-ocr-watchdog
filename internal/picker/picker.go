//go:build windows

// Package picker 提供 Windows 全屏拖拽框选遮罩。
package picker

import (
	"fmt"
	"runtime"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	user32   = windows.NewLazySystemDLL("user32.dll")
	kernel32 = windows.NewLazySystemDLL("kernel32.dll")

	pRegisterClassExW      = user32.NewProc("RegisterClassExW")
	pCreateWindowExW       = user32.NewProc("CreateWindowExW")
	pDefWindowProcW        = user32.NewProc("DefWindowProcW")
	pDestroyWindow         = user32.NewProc("DestroyWindow")
	pGetMessageW           = user32.NewProc("GetMessageW")
	pTranslateMessage      = user32.NewProc("TranslateMessage")
	pDispatchMessageW      = user32.NewProc("DispatchMessageW")
	pPostQuitMessage       = user32.NewProc("PostQuitMessage")
	pGetSystemMetrics      = user32.NewProc("GetSystemMetrics")
	pSetLayeredWindowAttrs = user32.NewProc("SetLayeredWindowAttributes")
	pSetCapture            = user32.NewProc("SetCapture")
	pReleaseCapture        = user32.NewProc("ReleaseCapture")
	pGetModuleHandleW      = kernel32.NewProc("GetModuleHandleW")
	pLoadCursorW           = user32.NewProc("LoadCursorW")
)

const (
	wsExLayered    = 0x00080000
	wsExTopmost    = 0x00000008
	wsExToolwindow = 0x00000080
	wsPopup        = 0x80000000

	swShow = 5

	smCXScreen = 0
	smCYScreen = 1

	lwaAlpha = 0x00000002

	wmDestroy     = 0x0002
	wmLButtonDown = 0x0201
	wmLButtonUp   = 0x0202
	wmKeyDown     = 0x0100

	vkEscape = 0x1B

	idcCross = 32515
)

type wndclassexw struct {
	cbSize        uint32
	style         uint32
	lpfnWndProc   uintptr
	cbClsExtra    int32
	cbWndExtra    int32
	hInstance     windows.Handle
	hIcon         windows.Handle
	hCursor       windows.Handle
	hbrBackground windows.Handle
	lpszMenuName  *uint16
	lpszClassName *uint16
	hIconSm       windows.Handle
}

type point struct{ X, Y int32 }

type msg struct {
	hwnd    windows.Handle
	message uint32
	wParam  uintptr
	lParam  uintptr
	time    uint32
	pt      point
}

// pick 内部状态在单次 Pick 调用内有效（Pick 串行调用，无并发）。
var (
	startX, startY  int32
	endX, endY      int32
	dragging        bool
	picked          bool
	cancelled       bool
	pickHWND        windows.Handle
	classRegistered bool
)

func loword(l uintptr) int32 { return int32(int16(l & 0xffff)) }
func hiword(l uintptr) int32 { return int32(int16((l >> 16) & 0xffff)) }

// wndProc 全参数用 uintptr —— syscall.NewCallback 要求参数为 uintptr 尺寸。
func wndProc(hwnd, message, wParam, lParam uintptr) uintptr {
	switch message {
	case wmLButtonDown:
		startX, startY = loword(lParam), hiword(lParam)
		dragging = true
		pSetCapture.Call(hwnd)
		return 0
	case wmLButtonUp:
		if dragging {
			endX, endY = loword(lParam), hiword(lParam)
			dragging = false
			picked = true
			pReleaseCapture.Call()
			pPostQuitMessage.Call(0)
		}
		return 0
	case wmKeyDown:
		if wParam == vkEscape {
			cancelled = true
			pPostQuitMessage.Call(0)
		}
		return 0
	case wmDestroy:
		pPostQuitMessage.Call(0)
		return 0
	}
	ret, _, _ := pDefWindowProcW.Call(hwnd, message, wParam, lParam)
	return ret
}

// Pick 弹出全屏遮罩让用户拖拽选区，返回选中矩形的 x,y,w,h。
// ok=false 表示用户按 ESC 取消或选区无效。
func Pick() (x, y, w, h int, ok bool, err error) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()

	picked, cancelled, dragging = false, false, false

	hInstance, _, _ := pGetModuleHandleW.Call(0)
	className, _ := syscall.UTF16PtrFromString("SOWRegionPicker")

	// 窗口类只注册一次：Win32 不允许重复注册同名类，重复注册会返回
	// ERROR_CLASS_ALREADY_EXISTS，导致第二次 Pick（再次框选）失败。
	// 同时 syscall.NewCallback 的回调 thunk 数量有限，也应只生成一次。
	if !classRegistered {
		cursor, _, _ := pLoadCursorW.Call(0, uintptr(idcCross))
		wc := wndclassexw{
			cbSize:        uint32(unsafe.Sizeof(wndclassexw{})),
			lpfnWndProc:   syscall.NewCallback(wndProc),
			hInstance:     windows.Handle(hInstance),
			hCursor:       windows.Handle(cursor),
			lpszClassName: className,
		}
		if ret, _, e := pRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc))); ret == 0 {
			return 0, 0, 0, 0, false, fmt.Errorf("picker: RegisterClassExW: %v", e)
		}
		classRegistered = true
	}

	cx, _, _ := pGetSystemMetrics.Call(smCXScreen)
	cy, _, _ := pGetSystemMetrics.Call(smCYScreen)

	hwnd, _, e := pCreateWindowExW.Call(
		uintptr(wsExLayered|wsExTopmost|wsExToolwindow),
		uintptr(unsafe.Pointer(className)),
		0,
		uintptr(wsPopup),
		0, 0, cx, cy,
		0, 0, hInstance, 0,
	)
	if hwnd == 0 {
		return 0, 0, 0, 0, false, fmt.Errorf("picker: CreateWindowExW: %v", e)
	}
	pickHWND = windows.Handle(hwnd)

	// 半透明遮罩：约 25% 不透明黑
	pSetLayeredWindowAttrs.Call(hwnd, 0, uintptr(64), uintptr(lwaAlpha))
	user32.NewProc("ShowWindow").Call(hwnd, swShow)

	var m msg
	for {
		ret, _, _ := pGetMessageW.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(ret) <= 0 {
			break
		}
		pTranslateMessage.Call(uintptr(unsafe.Pointer(&m)))
		pDispatchMessageW.Call(uintptr(unsafe.Pointer(&m)))
	}
	pDestroyWindow.Call(uintptr(pickHWND))

	if cancelled || !picked {
		return 0, 0, 0, 0, false, nil
	}
	x0, x1 := int(startX), int(endX)
	if x0 > x1 {
		x0, x1 = x1, x0
	}
	y0, y1 := int(startY), int(endY)
	if y0 > y1 {
		y0, y1 = y1, y0
	}
	w, h = x1-x0, y1-y0
	if w < 10 || h < 10 {
		return 0, 0, 0, 0, false, nil
	}
	return x0, y0, w, h, true, nil
}
