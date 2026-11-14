"""Ventana superpuesta: transparente, siempre encima, sin foco y que deja pasar los clics.

Claves de rendimiento:
  * La ventana es pequeña (solo el tamaño de la mira), no ocupa toda la pantalla, así
    el compositor (DWM) apenas tiene trabajo y no interfiere con el "flip" del juego.
  * No hay bucle de dibujo: solo se repinta cuando cambia el perfil o la posición.
  * Un temporizador cada 2 s reafirma "siempre encima" (coste despreciable).

Claves de nitidez (DPI):
  * La mira se dibuja en píxeles FÍSICOS: se deshace el escalado DPI de Qt en el pintor.
  * En Windows la ventana se coloca con SetWindowPos en coordenadas físicas y en cada
    pintado se lee su origen real con GetWindowRect, así el píxel central coincide
    exactamente con el centro del monitor aunque el escalado sea 125 % o 150 %.
"""
from __future__ import annotations

import math
import sys

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from .config import Profile
from .monitors import find_monitor
from .renderer import render_crosshair

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    from . import win32

MARGIN = 6  # Margen de seguridad (px físicos) alrededor de la mira


class OverlayWindow(QWidget):
    def __init__(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool                        # Sin botón en la barra de tareas
            | Qt.WindowType.WindowTransparentForInput   # Clics atraviesan la ventana
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)  # Alfa por píxel
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("Crosshair Overlay")

        self._image = None
        self._radius = 0
        self._opacity = 1.0
        self._center = QPoint(0, 0)                 # Centro de la mira en px físicos
        self._desired: tuple[int, int, int, int] | None = None

        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setInterval(2000)
        self._watchdog_timer.timeout.connect(self._watchdog)

    # ------------------------------------------------------------------ API
    def apply(self, profile: Profile, monitor_id: str) -> None:
        """Regenera la imagen de la mira y recoloca la ventana en el monitor elegido."""
        self._image, self._radius = render_crosshair(profile)
        self._opacity = profile.opacity
        cx, cy = find_monitor(monitor_id).center
        self._center = QPoint(cx + profile.offset_x, cy + profile.offset_y)
        self._place()
        self.update()

    @property
    def physical_center(self) -> QPoint:
        return QPoint(self._center)

    # ------------------------------------------------------------ eventos Qt
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if IS_WINDOWS:
            win32.make_click_through(int(self.winId()))
        QTimer.singleShot(0, self._place)
        self._watchdog_timer.start()

    def hideEvent(self, event) -> None:
        self._watchdog_timer.stop()
        super().hideEvent(event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self.update()  # El desplazamiento de dibujo depende del origen real

    def paintEvent(self, event) -> None:
        if self._image is None:
            return
        painter = QPainter(self)
        dpr = self.devicePixelRatioF()
        painter.scale(1.0 / dpr, 1.0 / dpr)          # A partir de aquí: 1 unidad = 1 píxel físico
        ox, oy = self._physical_origin()
        painter.setOpacity(self._opacity)
        painter.drawImage(self._center.x() - self._radius - ox,
                          self._center.y() - self._radius - oy, self._image)
        painter.end()

    # ------------------------------------------------------------ colocación
    def _place(self) -> None:
        if self._image is None:
            return
        size = 2 * (self._radius + MARGIN) + 1
        x = self._center.x() - self._radius - MARGIN
        y = self._center.y() - self._radius - MARGIN
        self._desired = (x, y, size, size)
        if IS_WINDOWS:
            # Coordenadas físicas exactas, sin pasar por el redondeo lógico de Qt.
            win32.set_window_pos(int(self.winId()), x, y, size, size)
        else:
            dpr = self._dpr_at(self._center)
            self.setGeometry(math.floor(x / dpr), math.floor(y / dpr),
                             math.ceil(size / dpr) + 1, math.ceil(size / dpr) + 1)
        self.update()

    def _physical_origin(self) -> tuple[int, int]:
        if IS_WINDOWS:
            left, top, _, _ = win32.get_window_rect(int(self.winId()))
            return left, top
        dpr = self.devicePixelRatioF()
        g = self.geometry()
        return round(g.x() * dpr), round(g.y() * dpr)

    @staticmethod
    def _dpr_at(point: QPoint) -> float:
        for screen in QGuiApplication.screens():
            g, d = screen.geometry(), screen.devicePixelRatio()
            if (g.x() * d <= point.x() < (g.x() + g.width()) * d
                    and g.y() * d <= point.y() < (g.y() + g.height()) * d):
                return d
        primary = QGuiApplication.primaryScreen()
        return primary.devicePixelRatio() if primary else 1.0

    def _watchdog(self) -> None:
        """Algunos juegos en ventana sin bordes se ponen encima: se reafirma el orden Z.
        Si un cambio de DPI/resolución desplazó la ventana, se vuelve a colocar."""
        if not IS_WINDOWS or not self.isVisible():
            return
        hwnd = int(self.winId())
        win32.bring_topmost(hwnd)
        if self._desired and win32.get_window_rect(hwnd)[:2] != self._desired[:2]:
            self._place()
