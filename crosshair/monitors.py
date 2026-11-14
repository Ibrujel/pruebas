"""Enumeración de monitores en píxeles físicos (multi-monitor y escalado DPI)."""
from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtGui import QGuiApplication

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    from . import win32


@dataclass(frozen=True)
class Monitor:
    id: str          # En Windows, el nombre de dispositivo GDI (p. ej. \\.\DISPLAY1)
    x: int           # Rectángulo en píxeles FÍSICOS del escritorio virtual
    y: int
    width: int
    height: int
    primary: bool
    scale: float     # Escalado de Windows (1.0 = 100 %, 1.5 = 150 %...)

    @property
    def center(self) -> tuple[int, int]:
        # Los juegos suelen dibujar su mira en el píxel (ancho/2, alto/2).
        return self.x + self.width // 2, self.y + self.height // 2

    def describe(self, index: int) -> str:
        tag = " (principal)" if self.primary else ""
        return f"Monitor {index + 1}{tag}: {self.width}×{self.height} @ {round(self.scale * 100)} %"


def _qt_monitors() -> list[Monitor]:
    """Alternativa portable: Qt da geometría lógica; se convierte a física con el DPR."""
    primary = QGuiApplication.primaryScreen()
    monitors = []
    for i, screen in enumerate(QGuiApplication.screens()):
        g = screen.geometry()
        dpr = screen.devicePixelRatio()
        monitors.append(Monitor(
            id=screen.name() or f"screen{i}",
            x=round(g.x() * dpr), y=round(g.y() * dpr),
            width=round(g.width() * dpr), height=round(g.height() * dpr),
            primary=screen is primary, scale=dpr,
        ))
    return monitors


def list_monitors() -> list[Monitor]:
    monitors: list[Monitor] = []
    if IS_WINDOWS:
        try:
            monitors = [Monitor(id=m["device"], x=m["x"], y=m["y"], width=m["width"], height=m["height"],
                                primary=m["primary"], scale=m["scale"]) for m in win32.enum_monitors()]
        except OSError:
            monitors = []
    if not monitors:
        monitors = _qt_monitors()
    # Principal primero y luego de izquierda a derecha.
    return sorted(monitors, key=lambda m: (not m.primary, m.x, m.y))


def find_monitor(monitor_id: str) -> Monitor:
    """Devuelve el monitor pedido o, si ya no existe (o id vacío), el principal."""
    monitors = list_monitors()
    if not monitors:  # Caso extremo (sin pantallas): un monitor ficticio 1080p.
        return Monitor("", 0, 0, 1920, 1080, True, 1.0)
    for m in monitors:
        if monitor_id and m.id == monitor_id:
            return m
    return monitors[0]
