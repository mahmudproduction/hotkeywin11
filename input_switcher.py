"""Переключатель звука, как переключатель языка.

Win+J — устройства вывода. Win+Alt+J — устройства ввода.
Удерживайте Win и нажимайте J: выделение идёт по списку.
Отпустите Win — выделенное устройство становится текущим.
"""

from __future__ import annotations

import ctypes
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)


def enable_dpi() -> None:
    try:
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


enable_dpi()

import tkinter as tk
from tkinter import font as tkfont

from incl.audio_input import (
    InputDevice,
    current_input_id,
    current_output_id,
    list_input_devices,
    list_output_devices,
    set_default_input,
    set_default_output,
)

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "log" / "input_switcher.log"
MUTEX_NAME = "Local\\WinJInputSwitcher"
STOP_NAME = "Local\\WinJInputSwitcherStop"

HOTKEY_OUTPUT = 1
HOTKEY_INPUT = 2
MOD_ALT = 0x0001
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_J = 0x4A
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
WM_HOTKEY = 0x0312
WM_TRAY = 0x8014
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 0x1
NIF_ICON = 0x2
NIF_TIP = 0x4
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0
ERROR_ALREADY_EXISTS = 183
ERROR_CLASS_ALREADY_EXISTS = 1410
PM_NOREMOVE = 0
PM_REMOVE = 1
TAP_COMMIT_MS = 220
LINGER_MS = 850

KEY_COLOR = "#010101"
CARD = "#2c2c2c"
SELECTED = "#3d3d3d"
TEXT = "#ffffff"
SUBTEXT = "#c8c8c8"
ACCENT = "#4cc2ff"
FAIL = "#ff8f8f"

STOP = None
MUTEX = None
_CONSOLE_HANDLER = None



class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeout", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def _bind() -> None:
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL

    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadIconW.restype = wintypes.HICON
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    user32.TrackPopupMenu.restype = ctypes.c_int
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wintypes.UINT
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL


_bind()


def log(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")
    except OSError:
        pass


def log_exc() -> None:
    log(traceback.format_exc().rstrip())


def _request_stop(*_args):
    if STOP:
        kernel32.SetEvent(STOP)
    return 1


def install_stop_signals() -> None:
    global _CONSOLE_HANDLER
    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _request_stop)
    handler = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)(_request_stop)
    _CONSOLE_HANDLER = handler
    kernel32.SetConsoleCtrlHandler(handler, True)


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def win_held() -> bool:
    return key_down(VK_LWIN) or key_down(VK_RWIN)


def chord_blocked() -> bool:
    return key_down(VK_SHIFT) or key_down(VK_CONTROL)


def foreground_text() -> str:
    hwnd = user32.GetForegroundWindow()
    title = ctypes.create_unicode_buffer(512)
    kind = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, 512)
    user32.GetClassNameW(hwnd, kind, 256)
    return f"{kind.value} | {title.value}"


def work_area() -> RECT:
    point = POINT()
    user32.GetCursorPos(ctypes.byref(point))
    monitor = user32.MonitorFromPoint(point, 2)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return info.rcWork
    rect = RECT()
    rect.right = user32.GetSystemMetrics(0)
    rect.bottom = user32.GetSystemMetrics(1)
    return rect


def ellipsize(face: tkfont.Font, text: str, width: int) -> str:
    if face.measure(text) <= width:
        return text
    mark = "…"
    trimmed = text
    while trimmed and face.measure(trimmed + mark) > width:
        trimmed = trimmed[:-1]
    return (trimmed + mark) if trimmed else mark


class SwitcherWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.font = tkfont.Font(family="Segoe UI", size=15)
        self.font_sub = tkfont.Font(family="Segoe UI", size=10)
        self.canvas = tk.Canvas(root, bg=KEY_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack()
        self._hwnd = 0
        self.visible = False

    def hwnd(self) -> int:
        self.root.update_idletasks()
        wid = int(self.root.winfo_id())
        parent = user32.GetParent(wid)
        self._hwnd = int(parent or wid)
        return self._hwnd

    def _style(self) -> None:
        handle = self.hwnd()
        extra = user32.GetWindowLongPtrW(handle, GWL_EXSTYLE)
        extra |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
        user32.SetWindowLongPtrW(handle, GWL_EXSTYLE, extra)

    def _round(self, x1: int, y1: int, x2: int, y2: int, radius: int, fill: str) -> None:
        radius = max(1, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
        canvas = self.canvas
        canvas.create_arc(
            x1, y1, x1 + 2 * radius, y1 + 2 * radius,
            start=90, extent=90, fill=fill, outline=fill,
        )
        canvas.create_arc(
            x2 - 2 * radius, y1, x2, y1 + 2 * radius,
            start=0, extent=90, fill=fill, outline=fill,
        )
        canvas.create_arc(
            x1, y2 - 2 * radius, x1 + 2 * radius, y2,
            start=180, extent=90, fill=fill, outline=fill,
        )
        canvas.create_arc(
            x2 - 2 * radius, y2 - 2 * radius, x2, y2,
            start=270, extent=90, fill=fill, outline=fill,
        )
        canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill)
        canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=fill)

    def show(self, devices: list[InputDevice], index: int, failed: bool = False, heading: str = "Вывод") -> None:
        self.canvas.delete("all")
        title_h = self.font.metrics("linespace")
        sub_h = self.font_sub.metrics("linespace")
        rows: list[tuple[str, str, bool]] = []
        if not devices:
            empty = "Нет активных устройств вывода" if heading == "Вывод" else "Нет активных устройств ввода"
            rows.append((empty, "", False))
        else:
            for pos, device in enumerate(devices):
                subtitle = device.subtitle
                if failed and pos == index:
                    subtitle = "Не удалось переключить"
                rows.append((device.title, subtitle, pos == index))

        text_limit = 460
        widest = self.font_sub.measure(heading)
        for title, subtitle, _selected in rows:
            widest = max(widest, self.font.measure(title), self.font_sub.measure(subtitle))
        widest = min(max(widest, 240), text_limit)
        card_w = widest + 56
        prepared = [
            (ellipsize(self.font, title, widest), ellipsize(self.font_sub, subtitle, widest), selected)
            for title, subtitle, selected in rows
        ]
        heights = []
        for _title, subtitle, _selected in prepared:
            heights.append(16 + title_h + (2 + sub_h if subtitle else 0) + 8)

        head_h = self.font_sub.metrics("linespace")
        card_h = 14 + head_h + 6 + sum(heights) + max(0, len(heights) - 1) * 4 + 8
        self._round(0, 0, card_w, card_h, 14, CARD)
        self.canvas.create_text(24, 12, anchor="nw", text=heading, font=self.font_sub, fill=ACCENT)
        y = 14 + head_h + 2
        for (title, subtitle, selected), row_h in zip(prepared, heights):
            if selected:
                self._round(6, y, card_w - 6, y + row_h, 8, SELECTED)
                self.canvas.create_rectangle(10, y + 10, 13, y + row_h - 10, fill=ACCENT, outline=ACCENT)
            color = FAIL if failed and selected else TEXT
            self.canvas.create_text(24, y + 8, anchor="nw", text=title, font=self.font, fill=color)
            if subtitle:
                sub_color = FAIL if failed and selected else SUBTEXT
                self.canvas.create_text(
                    24, y + 8 + title_h + 2, anchor="nw", text=subtitle, font=self.font_sub, fill=sub_color
                )
            y += row_h + 4

        self.canvas.configure(width=card_w, height=card_h)
        self.root.update_idletasks()
        self._style()
        area = work_area()
        x = area.left + max(0, (area.right - area.left - card_w) // 2)
        y_pos = area.top + max(0, (area.bottom - area.top - card_h) // 2)
        self.root.geometry(f"{card_w}x{card_h}+{x}+{y_pos}")
        user32.SetWindowPos(
            self.hwnd(),
            ctypes.c_void_p(-1),
            x,
            y_pos,
            card_w,
            card_h,
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        self.visible = True

    def hide(self) -> None:
        if self._hwnd:
            user32.ShowWindow(self._hwnd, SW_HIDE)
        self.root.withdraw()
        self.visible = False


class HotkeyHost(threading.Thread):
    def __init__(self, events: queue.Queue, stop_handle) -> None:
        super().__init__(name="winj-hotkey", daemon=False)
        self.events = events
        self.stop_handle = stop_handle
        self.ready = threading.Event()
        self.ok = False
        self.tid = 0
        self.hwnd = None
        self._wndproc = WNDPROC(self._on_message)
        self._class = "WinJInputSwitcherHost"
        self._nid = None
        self._taskbar_msg = 0

    def run(self) -> None:
        try:
            self.tid = kernel32.GetCurrentThreadId()
            self._create()
        except Exception:
            log_exc()
            self.ok = False
        probe = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(probe), None, 0, 0, PM_NOREMOVE)
        self.ready.set()
        if not self.ok:
            return
        self._loop()
        self._cleanup()

    def _create(self) -> None:
        module = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = module
        window_class.lpszClassName = self._class
        atom = user32.RegisterClassW(ctypes.byref(window_class))
        if not atom and ctypes.get_last_error() not in (0, ERROR_CLASS_ALREADY_EXISTS):
            log(f"RegisterClassW не удался: {ctypes.get_last_error()}")
        self.hwnd = user32.CreateWindowExW(
            WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
            self._class,
            "WinJInputSwitcher",
            0x80000000,
            0,
            0,
            0,
            0,
            None,
            None,
            module,
            None,
        )
        if not self.hwnd:
            log(f"окно трея не создано: {ctypes.get_last_error()}")
        else:
            self._taskbar_msg = user32.RegisterWindowMessageW("TaskbarCreated")
            self._add_icon()
        ctypes.set_last_error(0)
        output_ok = bool(user32.RegisterHotKey(None, HOTKEY_OUTPUT, MOD_WIN | MOD_NOREPEAT, VK_J))
        if output_ok:
            log("Win+J вывод зарегистрирован")
        else:
            log(f"Win+J не зарегистрирован: {ctypes.get_last_error()}")
        ctypes.set_last_error(0)
        input_ok = bool(
            user32.RegisterHotKey(None, HOTKEY_INPUT, MOD_WIN | MOD_ALT | MOD_NOREPEAT, VK_J)
        )
        if input_ok:
            log("Win+Alt+J ввод зарегистрирован")
        else:
            log(f"Win+Alt+J не зарегистрирован: {ctypes.get_last_error()}")
        self.ok = output_ok and input_ok

    def _add_icon(self) -> None:
        icon = user32.LoadIconW(None, 32512)
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = icon
        nid.szTip = "Win+J вывод, Win+Alt+J ввод"
        if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            self._nid = nid
        else:
            log(f"значок в трее не добавлен: {ctypes.get_last_error()}")

    def _on_message(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY or (self._taskbar_msg and msg == self._taskbar_msg):
            if msg == self._taskbar_msg:
                self._add_icon()
                return 0
            if (lparam & 0xFFFF) in (WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU):
                self._menu(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self, hwnd) -> None:
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, 0, 1, "Выход")
        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(hwnd)
        command = user32.TrackPopupMenu(
            menu,
            TPM_RETURNCMD | TPM_NONOTIFY,
            point.x,
            point.y,
            0,
            hwnd,
            None,
        )
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if command == 1:
            kernel32.SetEvent(self.stop_handle)
            user32.PostQuitMessage(0)

    def _loop(self) -> None:
        message = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == 0 or result == -1:
                break
            if message.message == WM_HOTKEY:
                if message.wParam == HOTKEY_OUTPUT and not key_down(VK_MENU):
                    self.events.put(("cycle", "output"))
                elif message.wParam == HOTKEY_INPUT:
                    self.events.put(("cycle", "input"))
                continue
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def _cleanup(self) -> None:
        user32.UnregisterHotKey(None, HOTKEY_OUTPUT)
        user32.UnregisterHotKey(None, HOTKEY_INPUT)
        self.ok = False
        if self._nid is not None and self.hwnd:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            self._nid = None
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.ui = SwitcherWindow(root)
        self.events: queue.Queue = queue.Queue()
        self.host: HotkeyHost | None = None
        self.devices: list[InputDevice] = []
        self.index = -1
        self.mode = "output"
        self.state = "idle"
        self.held = False
        self.up_ticks = 0
        self.commit_timer = None
        self.hide_timer = None
        self.stopped = False
        self.stop = None

    def start(self, stop_handle) -> None:
        self.stop = stop_handle
        self.host = HotkeyHost(self.events, stop_handle)
        self.host.start()
        if not self.host.ready.wait(3) or not self.host.ok:
            self._fail("Не удалось назначить Win+J или Win+Alt+J. Возможно, сочетание уже занято.")
            return
        log("переключатель запущен")
        self.root.after(30, self.poll)

    def preview(self) -> None:
        before = foreground_text()
        self._open_on_next("output")
        after = foreground_text()
        print(f"FG_BEFORE {before}", flush=True)
        print(f"FG_AFTER {after}", flush=True)
        print("PREVIEW", flush=True)
        self.root.after(6000, self.shutdown)

    def poll(self) -> None:
        if self.stopped:
            return
        try:
            self._drain()
            self._watch_win()
            if self.stop and kernel32.WaitForSingleObject(self.stop, 0) == 0:
                self.shutdown()
                return
        except Exception:
            log_exc()
        if not self.stopped:
            self.root.after(30, self.poll)

    def _drain(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return
            if isinstance(event, tuple) and event and event[0] == "cycle":
                self.on_cycle(event[1])

    def _watch_win(self) -> None:
        if self.state != "browsing":
            self.up_ticks = 0
            return
        if win_held():
            self.held = True
            self.up_ticks = 0
            return
        if self.held:
            self.up_ticks += 1
            if self.up_ticks >= 2:
                self.commit()

    def on_cycle(self, kind: str) -> None:
        if chord_blocked():
            return
        self._cancel_commit()
        self._cancel_hide()
        if self.state != "browsing" or self.mode != kind:
            self._open_on_next(kind)
        else:
            self._step()
        self.up_ticks = 0
        if win_held():
            self.held = True
        else:
            self.held = False
            self.commit_timer = self.root.after(TAP_COMMIT_MS, self._commit_if_browsing)

    def _heading(self) -> str:
        return "Вывод" if self.mode == "output" else "Ввод"

    def _open_on_next(self, kind: str) -> None:
        self.mode = kind
        try:
            if kind == "output":
                self.devices = list_output_devices()
                current = current_output_id()
            else:
                self.devices = list_input_devices()
                current = current_input_id()
        except Exception:
            log_exc()
            self.devices = []
            current = None
        if not self.devices:
            self.index = -1
        else:
            ids = [device.id for device in self.devices]
            if current in ids:
                self.index = (ids.index(current) + 1) % len(self.devices)
            else:
                self.index = 0
        self.state = "browsing"
        self.ui.show(self.devices, self.index, heading=self._heading())

    def _step(self) -> None:
        if not self.devices:
            return
        self.index = (self.index + 1) % len(self.devices)
        self.ui.show(self.devices, self.index, heading=self._heading())

    def _commit_if_browsing(self) -> None:
        self.commit_timer = None
        if self.state != "browsing":
            return
        if win_held():
            self.held = True
            return
        self.commit()

    def commit(self) -> None:
        if self.state != "browsing":
            return
        self._cancel_commit()
        self.held = False
        self.up_ticks = 0
        self.state = "shown"
        failed = False
        if self.devices and 0 <= self.index < len(self.devices):
            device = self.devices[self.index]
            try:
                if self.mode == "output":
                    set_default_output(device.id)
                    log(f"вывод: {device.full_name}")
                else:
                    set_default_input(device.id)
                    log(f"ввод: {device.full_name}")
            except Exception:
                log_exc()
                failed = True
                self.ui.show(self.devices, self.index, failed=True, heading=self._heading())
        linger = 1600 if failed else LINGER_MS
        self.hide_timer = self.root.after(linger, self._to_idle)

    def _to_idle(self) -> None:
        self.hide_timer = None
        self.state = "idle"
        self.held = False
        self.ui.hide()

    def _cancel_commit(self) -> None:
        if self.commit_timer is not None:
            self.root.after_cancel(self.commit_timer)
            self.commit_timer = None

    def _cancel_hide(self) -> None:
        if self.hide_timer is not None:
            self.root.after_cancel(self.hide_timer)
            self.hide_timer = None

    def _fail(self, text: str) -> None:
        log(text)
        user32.MessageBoxW(None, text, "Звук", 0x10)
        self.shutdown()

    def shutdown(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        self._cancel_commit()
        self._cancel_hide()
        try:
            self.ui.hide()
        except tk.TclError:
            pass
        host = self.host
        if host is not None and host.tid:
            user32.PostThreadMessageW(host.tid, WM_QUIT, 0, 0)
            if host.is_alive():
                host.join(2)
        log("переключатель остановлен")
        try:
            self.root.quit()
        except tk.TclError:
            pass



def startup_link() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "HotkeyWin11.lnk"
    )


def install_startup() -> Path:
    link = startup_link()
    link.parent.mkdir(parents=True, exist_ok=True)
    legacy = link.parent / "Win+J устройства ввода.lnk"
    if legacy.exists() and legacy != link:
        legacy.unlink()
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    if pythonw.exists():
        python = pythonw
    script = Path(__file__).resolve()
    env = os.environ.copy()
    env["HOTKEY_LINK"] = str(link)
    env["HOTKEY_PYTHON"] = str(python)
    env["HOTKEY_ARGS"] = f'"{script}"'
    env["HOTKEY_WORKDIR"] = str(script.parent)
    env["HOTKEY_DESC"] = "Win+J — вывод, Win+Alt+J — ввод"
    command = (
        "$shell = New-Object -ComObject WScript.Shell; "
        "$sc = $shell.CreateShortcut($env:HOTKEY_LINK); "
        "$sc.TargetPath = $env:HOTKEY_PYTHON; "
        "$sc.Arguments = $env:HOTKEY_ARGS; "
        "$sc.WorkingDirectory = $env:HOTKEY_WORKDIR; "
        "$sc.WindowStyle = 7; "
        "$sc.Description = $env:HOTKEY_DESC; "
        "$sc.Save()"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not link.exists():
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or "не удалось создать ярлык автозагрузки")
        log(f"автозагрузка: {link}")
    return link


def remove_startup() -> bool:
    link = startup_link()
    if not link.exists():
        return False
    link.unlink()
    log(f"автозагрузка удалена: {link}")
    return True


def acquire_mutex() -> bool:
    global MUTEX
    MUTEX = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def request_exit() -> None:
    handle = kernel32.OpenEventW(0x0002, False, STOP_NAME)
    if handle:
        kernel32.SetEvent(handle)
        kernel32.CloseHandle(handle)


def _print_devices(title: str, devices, current: str | None) -> None:
    print(title)
    for number, device in enumerate(devices, start=1):
        mark = "  ← текущее" if device.id == current else ""
        print(f"{number}. {device.full_name}{mark}")
    print(f"всего: {len(devices)}")


def check() -> None:
    _print_devices("Вывод:", list_output_devices(), current_output_id())
    print()
    _print_devices("Ввод:", list_input_devices(), current_input_id())


def run(preview: bool) -> None:
    global STOP
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.configure(bg=KEY_COLOR)
    root.attributes("-topmost", True)
    root.attributes("-transparentcolor", KEY_COLOR)
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.shutdown)
    if preview:
        root.after(0, app.preview)
    else:
        STOP = kernel32.CreateEventW(None, True, False, STOP_NAME)
        kernel32.ResetEvent(STOP)
        install_stop_signals()
        root.after(0, lambda: app.start(STOP))
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.shutdown()
    finally:
        app.shutdown()


def main() -> None:
    sys.excepthook = lambda kind, value, trace: (
        None
        if issubclass(kind, KeyboardInterrupt)
        else sys.__excepthook__(kind, value, trace)
    )
    try:
        if "--exit" in sys.argv:
            request_exit()
            return
        if "--remove-startup" in sys.argv:
            print("Автозагрузка убрана." if remove_startup() else "Ярлыка автозагрузки нет.")
            return
        if "--startup" in sys.argv:
            print(f"Автозагрузка: {install_startup()}")
        if "--check" in sys.argv:
            check()
            return
        preview = "--preview" in sys.argv
        if not preview and not acquire_mutex():
            print("Переключатель уже запущен.")
            return
        run(preview)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()