"""Envoltorios ctypes mínimos de la API Win32. Solo se importa en Windows.

Nada de esto toca otros procesos: solo afecta a la ventana propia de la aplicación,
consulta monitores y registra atajos de teclado globales del sistema (RegisterHotKey).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
try:
    shcore = ctypes.WinDLL("shcore")
    shcore.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, ctypes.c_int,
                                        ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
    shcore.GetDpiForMonitor.restype = ctypes.c_long  # HRESULT
except (OSError, AttributeError):  # Windows 7 / 8.0
    shcore = None

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020   # Los clics atraviesan la ventana
WS_EX_TOOLWINDOW = 0x00000080    # No aparece en la barra de tareas ni en Alt+Tab
WS_EX_LAYERED = 0x00080000       # Ventana con transparencia por píxel
WS_EX_NOACTIVATE = 0x08000000    # Nunca roba el foco al juego

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
HWND_TOPMOST = wintypes.HWND(-1)

WM_HOTKEY = 0x0312
MONITORINFOF_PRIMARY = 0x1
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
user32.SetWindowLongW.restype = wintypes.LONG
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), MONITORENUMPROC,
                                       wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL


def make_click_through(hwnd: int) -> bool:
    """Añade los estilos que hacen la ventana transparente al ratón y sin foco.

    Devuelve True si la ventana es "layered" (Qt la crea así con WA_TranslucentBackground),
    requisito para que WS_EX_TRANSPARENT deje pasar los clics a la ventana de debajo.
    """
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    return bool(style & WS_EX_LAYERED)


def set_window_pos(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    """Coloca la ventana en coordenadas FÍSICAS (el proceso es DPI-aware por monitor v2)."""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_NOOWNERZORDER)


def bring_topmost(hwnd: int) -> None:
    """Reafirma 'siempre encima' sin mover, redimensionar ni activar la ventana."""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _monitor_scale(hmon) -> float:
    if shcore is None:
        return 1.0
    dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
    # MDT_EFFECTIVE_DPI = 0
    if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
        return dpi_x.value / 96.0
    return 1.0


def enum_monitors() -> list[dict]:
    """Lista los monitores con su rectángulo en píxeles físicos del escritorio virtual."""
    result: list[dict] = []

    def _callback(hmon, _hdc, _rect, _lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            result.append({
                "device": info.szDevice,
                "x": r.left, "y": r.top,
                "width": r.right - r.left, "height": r.bottom - r.top,
                "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                "scale": _monitor_scale(hmon),
            })
        return True

    callback = MONITORENUMPROC(_callback)  # Referencia viva durante la llamada
    user32.EnumDisplayMonitors(None, None, callback, 0)
    return result


def register_hotkey(hotkey_id: int, modifiers: int, vk: int) -> int:
    """Registra un atajo global asociado al hilo actual. Devuelve 0 o el código de error."""
    if user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
        return 0
    return ctypes.get_last_error() or -1


def unregister_hotkey(hotkey_id: int) -> None:
    user32.UnregisterHotKey(None, hotkey_id)
