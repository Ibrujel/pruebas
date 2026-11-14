"""Dibujo de la mira en una imagen, compartido por la superposición y la vista previa.

La imagen se genera en píxeles físicos (1 unidad = 1 píxel real de pantalla) con
rectángulos de coordenadas enteras y sin antialiasing, para que las líneas queden nítidas.
Solo el círculo usa antialiasing. Se regenera únicamente cuando cambia el perfil.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from .config import Profile


def extent(p: Profile) -> int:
    """Radio (en px) que necesita la mira desde el píxel central, contorno incluido."""
    r = 1
    if p.arms and p.length > 0:
        r = max(r, p.gap + p.length, p.thickness // 2 + 1)
    if p.dot:
        r = max(r, p.dot_size // 2 + 1)
    if p.circle:
        r = max(r, p.circle_radius + (p.circle_thickness + 1) // 2 + 1)
    if p.outline:
        r += p.outline_thickness
    return r + 1


def _shape_rects(p: Profile, c: int) -> list[QRect]:
    """Rectángulos de brazos y punto alrededor del píxel central (c, c)."""
    rects: list[QRect] = []
    t, length, g = p.thickness, p.length, p.gap
    if p.arms and length > 0:
        a = c - t // 2  # primera fila/columna del grosor del brazo
        rects.append(QRect(c + g, a, length, t))               # derecha
        rects.append(QRect(c - g - length + 1, a, length, t))  # izquierda
        rects.append(QRect(a, c + g, t, length))               # abajo
        if not p.t_style:                                      # estilo T: sin brazo superior
            rects.append(QRect(a, c - g - length + 1, t, length))
    if p.dot:
        s = p.dot_size
        d = c - s // 2
        rects.append(QRect(d, d, s, s))
    return rects


def render_crosshair(p: Profile) -> tuple[QImage, int]:
    """Devuelve (imagen opaca de la mira, radio). El píxel central es (radio, radio).

    La opacidad NO se aplica aquí: se aplica al componer la imagen, para que el contorno
    no se transparente a través del relleno cuando la opacidad es < 100 %.
    """
    r = extent(p)
    n = 2 * r + 1
    img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    color = QColor(p.color)
    outline_color = QColor(p.outline_color)
    o = p.outline_thickness if p.outline else 0
    rects = _shape_rects(p, r)
    center = QPointF(r + 0.5, r + 0.5)

    def draw_circle(col: QColor, width: int) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(col, width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, p.circle_radius, p.circle_radius)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    # 1) Contornos (debajo)
    if o:
        if p.circle:
            draw_circle(outline_color, p.circle_thickness + 2 * o)
        for rect in rects:
            painter.fillRect(rect.adjusted(-o, -o, o, o), outline_color)
    # 2) Relleno (encima)
    if p.circle:
        draw_circle(color, p.circle_thickness)
    for rect in rects:
        painter.fillRect(rect, color)
    painter.end()
    return img, r
