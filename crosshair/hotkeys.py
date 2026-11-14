"""Atajos de teclado globales.

* Windows: RegisterHotKey (API oficial del sistema). NO instala ganchos de teclado de
  bajo nivel ni lee pulsaciones de otras teclas: el sistema solo avisa cuando se pulsa
  exactamente una combinación registrada. Es lo menos intrusivo posible.
* Linux (X11) / macOS: se usa `pynput` si está instalado (opcional).
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    from . import win32

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODIFIERS = {"CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL, "ALT": MOD_ALT, "SHIFT": MOD_SHIFT,
              "WIN": MOD_WIN, "META": MOD_WIN, "SUPER": MOD_WIN, "CMD": MOD_WIN}

# Nombre de tecla (en mayúsculas, alias incluidos) -> (código virtual Win32, nombre pynput)
_KEYS: dict[str, tuple[int, str]] = {}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    _KEYS[_c] = (ord(_c), _c.lower())
for _n in range(1, 25):
    _KEYS[f"F{_n}"] = (0x6F + _n, f"<f{_n}>")
for _n in range(10):
    _KEYS[f"NUM{_n}"] = (0x60 + _n, str(_n))
for _names, _vk, _pyn in [
    (("LEFT",), 0x25, "<left>"), (("UP",), 0x26, "<up>"), (("RIGHT",), 0x27, "<right>"),
    (("DOWN",), 0x28, "<down>"), (("PGUP", "PAGEUP", "PRIOR"), 0x21, "<page_up>"),
    (("PGDOWN", "PAGEDOWN", "NEXT"), 0x22, "<page_down>"), (("HOME",), 0x24, "<home>"),
    (("END",), 0x23, "<end>"), (("INS", "INSERT"), 0x2D, "<insert>"), (("DEL", "DELETE"), 0x2E, "<delete>"),
    (("SPACE",), 0x20, "<space>"), (("PAUSE",), 0x13, "<pause>"), (("SCROLLLOCK",), 0x91, "<scroll_lock>"),
]:
    for _name in _names:
        _KEYS[_name] = (_vk, _pyn)


def parse_hotkey(text: str) -> tuple[int, str] | None:
    """'Ctrl+Alt+PgDown' -> (máscara de modificadores, 'PGDOWN'). None si no es válido."""
    tokens = [t.strip().upper() for t in text.split("+") if t.strip()]
    if not tokens:
        return None
    mods, keypad = 0, False
    for tok in tokens[:-1]:
        if tok == "NUM":          # Qt escribe las teclas del teclado numérico como "Num+5"
            keypad = True
        elif tok in _MODIFIERS:
            mods |= _MODIFIERS[tok]
        else:
            return None
    key = tokens[-1]
    if keypad and key.isdigit():
        key = "NUM" + key
    return (mods, key) if key in _KEYS else None


class HotkeyManager(QObject):
    """Interfaz común. `triggered` emite el nombre de la acción (siempre en el hilo de Qt)."""

    triggered = Signal(str)
    backend = "ninguno"

    def register_all(self, mapping: dict[str, str]) -> dict[str, str]:
        """Registra {acción: combinación}. Devuelve {acción: motivo} de los que fallaron."""
        self.unregister_all()
        failures: dict[str, str] = {}
        seen: dict[tuple[int, str], str] = {}
        for action, text in mapping.items():
            if not text:
                continue  # Atajo desactivado
            parsed = parse_hotkey(text)
            if parsed is None:
                failures[action] = f"combinación no reconocida: {text}"
            elif parsed in seen:
                failures[action] = f"duplicado de «{seen[parsed]}»"
            else:
                seen[parsed] = action
                error = self._register(action, *parsed)
                if error:
                    failures[action] = error
        return failures

    def _register(self, action: str, mods: int, key: str) -> str | None:
        return "no hay soporte de atajos globales en esta plataforma"

    def unregister_all(self) -> None:
        pass


class _WinMessageFilter(QAbstractNativeEventFilter):
    """Recibe WM_HOTKEY del bucle de mensajes de Qt (RegisterHotKey con hwnd=NULL)."""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        et = bytes(event_type.data()) if hasattr(event_type, "data") else bytes(event_type)
        if et in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = win32.wintypes.MSG.from_address(int(message))
            if msg.message == win32.WM_HOTKEY:
                self._callback(int(msg.wParam))
                return True, 0
        return False, 0


class WindowsHotkeyManager(HotkeyManager):
    backend = "Windows RegisterHotKey"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ids: dict[int, str] = {}
        self._filter = _WinMessageFilter(self._on_hotkey)
        QCoreApplication.instance().installNativeEventFilter(self._filter)

    def _register(self, action, mods, key):
        hotkey_id = 0xB000 + len(self._ids) + 1
        error = win32.register_hotkey(hotkey_id, mods | MOD_NOREPEAT, _KEYS[key][0])
        if error == 0:
            self._ids[hotkey_id] = action
            return None
        if error == win32.ERROR_HOTKEY_ALREADY_REGISTERED:
            return "ya la usa otra aplicación"
        return f"error de Windows {error}"

    def unregister_all(self):
        for hotkey_id in self._ids:
            win32.unregister_hotkey(hotkey_id)
        self._ids.clear()

    def _on_hotkey(self, hotkey_id: int):
        action = self._ids.get(hotkey_id)
        if action:
            self.triggered.emit(action)


class PynputHotkeyManager(HotkeyManager):
    backend = "pynput"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listener = None
        self._pending: dict[str, str] = {}

    def register_all(self, mapping):
        self._pending = {}
        failures = super().register_all(mapping)
        if self._pending:
            from pynput import keyboard
            # El callback corre en el hilo de pynput; emitir la señal es seguro (cola de Qt).
            self._listener = keyboard.GlobalHotKeys(
                {combo: (lambda a=action: self.triggered.emit(a)) for combo, action in self._pending.items()})
            self._listener.start()
        return failures

    def _register(self, action, mods, key):
        parts = [name for bit, name in ((MOD_CONTROL, "<ctrl>"), (MOD_ALT, "<alt>"),
                                        (MOD_SHIFT, "<shift>"), (MOD_WIN, "<cmd>")) if mods & bit]
        self._pending["+".join(parts + [_KEYS[key][1]])] = action
        return None

    def unregister_all(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


def create_hotkey_manager(parent=None) -> HotkeyManager:
    if IS_WINDOWS:
        return WindowsHotkeyManager(parent)
    try:
        import pynput  # noqa: F401
        return PynputHotkeyManager(parent)
    except Exception:  # No instalado o sin servidor gráfico compatible
        return HotkeyManager(parent)
