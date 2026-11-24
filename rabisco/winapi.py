"""Integração com o Windows: atalho global, janela sempre no topo, cantos arredondados e autostart."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer

from .config import APP_NAME, ENTRY_SCRIPT, IS_WIN, log_error

if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]

    WM_HOTKEY = 0x0312
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
    HWND_TOPMOST, HWND_NOTOPMOST = -1, -2

    def win_set_topmost(hwnd: int, on: bool) -> None:
        user32.SetWindowPos(hwnd, HWND_TOPMOST if on else HWND_NOTOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def win_style_window(hwnd: int) -> None:
        """Cantos arredondados + borda sutil nativos do Windows 11 (no-op no 10)."""
        try:
            dwm = ctypes.WinDLL("dwmapi")
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))
            border = ctypes.c_uint(0x00443A3A)  # COLORREF 0x00BBGGRR
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 34, ctypes.byref(border), ctypes.sizeof(border))
        except (OSError, AttributeError):
            pass

    def is_win11() -> bool:
        try:
            return sys.getwindowsversion().build >= 22000
        except AttributeError:
            return False


def parse_hotkey(spec: str):
    """'Ctrl+Alt+K' -> (mods, vk) para RegisterHotKey."""
    if not IS_WIN:
        return None
    named = {"SPACE": 0x20, "ESPACO": 0x20, "TAB": 0x09, "ENTER": 0x0D, "INSERT": 0x2D,
             "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
             ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0, "'": 0xDE}
    mods, vk = 0, None
    for part in spec.replace(" ", "").split("+"):
        p = part.upper()
        if p in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif p == "ALT":
            mods |= MOD_ALT
        elif p == "SHIFT":
            mods |= MOD_SHIFT
        elif p in ("WIN", "META", "SUPER"):
            mods |= MOD_WIN
        elif len(p) == 1 and p.isalnum():
            vk = ord(p)
        elif p[:1] == "F" and p[1:].isdigit() and 1 <= int(p[1:]) <= 24:
            vk = 0x6F + int(p[1:])
        elif p in named:
            vk = named[p]
    if vk is None or not mods:
        return None
    return mods | MOD_NOREPEAT, vk


class GlobalHotkey(QAbstractNativeEventFilter):
    HOTKEY_ID = 0xB15C

    def __init__(self, spec: str, callback):
        super().__init__()
        self.callback = callback
        self.ok = False
        parsed = parse_hotkey(spec)
        if parsed:
            self.ok = bool(user32.RegisterHotKey(None, self.HOTKEY_ID, parsed[0], parsed[1]))

    def nativeEventFilter(self, event_type, message):
        if self.ok:
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    QTimer.singleShot(0, self.callback)
                    return True, 0
            except (TypeError, ValueError, OverflowError):
                pass
        return False, 0

    def unregister(self) -> None:
        if self.ok:
            user32.UnregisterHotKey(None, self.HOTKEY_ID)
            self.ok = False


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _autostart_command() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe" and exe.with_name("pythonw.exe").exists():
        exe = exe.with_name("pythonw.exe")
    if ENTRY_SCRIPT.exists():
        return f'"{exe}" "{ENTRY_SCRIPT}" --hidden'
    return f'"{exe}" -m rabisco --hidden'


def get_autostart() -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    if not IS_WIN:
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError as e:
        log_error(f"autostart: {e}")
