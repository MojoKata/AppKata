"""The window on Windows (requirement 15.13). AppKata draws its own header bar, so the frameless
window gets back what a normal window has: the minimize, maximize and resize styles (taskbar
clicks, Win+arrow keys, Aero Snap), no visible frame, a maximized size that fits the screen, and
Windows 11's Snap Layouts when the pointer rests on the Maximize button."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QRectF

WM_NCCALCSIZE, WM_NCHITTEST = 0x0083, 0x0084
WM_NCMOUSEMOVE, WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCMOUSELEAVE = 0x00A0, 0x00A1, 0x00A2, 0x02A2
HTMAXBUTTON = 9
GWL_STYLE = -16
WS_THICKFRAME, WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_SYSMENU = 0x00040000, 0x00020000, 0x00010000, 0x00080000
SWP_FRAMECHANGED, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x20, 0x2, 0x1, 0x4, 0x10


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class WinFrame(QAbstractNativeEventFilter):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.hwnd = int(win.winId())
        self.user32 = ctypes.windll.user32
        self.user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.user32.MonitorFromWindow.restype = wintypes.HANDLE
        self.user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        style = self.user32.GetWindowLongPtrW(self.hwnd, GWL_STYLE)
        self.user32.SetWindowLongPtrW(self.hwnd, GWL_STYLE, style | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
        self.user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0,
                                 SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def _max_button(self) -> QRectF:
        r = self.win.property("maxButtonRect")
        return r if isinstance(r, QRectF) else QRectF()

    def _client_point(self, lparam: int):
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        pt = wintypes.POINT(x, y)
        self.user32.ScreenToClient(self.hwnd, ctypes.byref(pt))
        dpr = self.win.devicePixelRatio() or 1.0
        return pt.x / dpr, pt.y / dpr

    def _over_max(self, lparam: int) -> bool:
        x, y = self._client_point(lparam)
        return self._max_button().contains(x, y)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) != b"windows_generic_MSG":
            return False, 0
        msg = wintypes.MSG.from_address(int(message))
        if int(msg.hWnd or 0) != self.hwnd:
            return False, 0
        m = msg.message
        if m == WM_NCCALCSIZE and msg.wParam:
            if self.user32.IsZoomed(self.hwnd):       # maximized: keep the content within the screen's work area
                params = NCCALCSIZE_PARAMS.from_address(msg.lParam)
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                if self.user32.GetMonitorInfoW(self.user32.MonitorFromWindow(self.hwnd, 2), ctypes.byref(mi)):
                    r, w = params.rgrc[0], mi.rcWork
                    r.left, r.top = max(r.left, w.left), max(r.top, w.top)
                    r.right, r.bottom = min(r.right, w.right), min(r.bottom, w.bottom)
                    params.rgrc[0] = r
            return True, 0                            # the whole window is AppKata's: no frame
        if m == WM_NCHITTEST and self._over_max(msg.lParam):
            return True, HTMAXBUTTON                  # Snap Layouts on Windows 11
        if m == WM_NCMOUSEMOVE:
            self.win.setProperty("maxHover", msg.wParam == HTMAXBUTTON)
        elif m == WM_NCMOUSELEAVE:
            self.win.setProperty("maxHover", False)
        elif m == WM_NCLBUTTONDOWN and msg.wParam == HTMAXBUTTON:
            return True, 0
        elif m == WM_NCLBUTTONUP and msg.wParam == HTMAXBUTTON:
            self.win.setProperty("maxHover", False)
            if self.user32.IsZoomed(self.hwnd):
                self.win.showNormal()
            else:
                self.win.showMaximized()
            return True, 0
        return False, 0
