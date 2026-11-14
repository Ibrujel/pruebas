"""Ventana de ajustes con vista previa en tiempo real.

Cada control escribe directamente en el perfil activo a través del controlador; la
superposición y la vista previa se actualizan al instante y el guardado se hace con
un pequeño retardo (para no escribir el disco en cada pulsación de una flecha).
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QKeySequenceEdit, QLabel, QMessageBox, QPushButton, QSlider, QSpinBox,
    QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from .config import ACTIONS, INT_LIMITS, Profile
from .hotkeys import parse_hotkey
from .monitors import find_monitor, list_monitors
from .renderer import render_crosshair

# (etiqueta, flags de forma). Las formas también se pueden combinar a mano con las casillas.
PRESETS: list[tuple[str, dict[str, bool]]] = [
    ("Cruz", dict(arms=True, t_style=False, circle=False, dot=False)),
    ("Cruz + punto", dict(arms=True, t_style=False, circle=False, dot=True)),
    ("Punto", dict(arms=False, t_style=False, circle=False, dot=True)),
    ("Círculo", dict(arms=False, t_style=False, circle=True, dot=False)),
    ("Círculo + punto", dict(arms=False, t_style=False, circle=True, dot=True)),
    ("Cruz + círculo", dict(arms=True, t_style=False, circle=True, dot=False)),
    ("T", dict(arms=True, t_style=True, circle=False, dot=False)),
    ("T + punto", dict(arms=True, t_style=True, circle=False, dot=True)),
]
CUSTOM_PRESET = "Personalizado"


class ColorButton(QPushButton):
    """Botón que muestra un color y abre el selector al pulsarlo."""

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self._color = "#FFFFFF"
        self._on_change = on_change
        self.setMinimumWidth(110)
        self.clicked.connect(self._pick)

    def set_color(self, hex_color: str) -> None:
        self._color = hex_color
        text_color = "#000000" if QColor(hex_color).lightness() > 128 else "#FFFFFF"
        self.setText(hex_color)
        self.setStyleSheet(f"background:{hex_color}; color:{text_color}; border:1px solid #666; padding:4px;")

    def _pick(self) -> None:
        color = QColorDialog.getColor(QColor(self._color), self, "Elegir color")
        if color.isValid():
            self.set_color(color.name().upper())
            self._on_change(self._color)


class PreviewWidget(QWidget):
    """Vista previa 1:1 (o ampliada sin suavizado) sobre distintos fondos."""

    BACKGROUNDS = ["Escena", "Oscuro", "Claro", "Ajedrez"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(280, 280)
        self._image = None
        self._radius = 0
        self._opacity = 1.0
        self._zoom = 3
        self._background = 0

    def set_profile(self, profile: Profile) -> None:
        self._image, self._radius = render_crosshair(profile)
        self._opacity = profile.opacity
        self.update()

    def set_zoom(self, zoom: int) -> None:
        self._zoom = zoom
        self.update()

    def set_background(self, index: int) -> None:
        self._background = index
        self.update()

    def _paint_background(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        if self._background == 0:      # Cielo y suelo, simulando una escena de juego
            sky = QLinearGradient(0, 0, 0, h / 2)
            sky.setColorAt(0, QColor("#6E9CC4"))
            sky.setColorAt(1, QColor("#C9D8E3"))
            p.fillRect(0, 0, w, h // 2, sky)
            ground = QLinearGradient(0, h / 2, 0, h)
            ground.setColorAt(0, QColor("#6B6A5C"))
            ground.setColorAt(1, QColor("#34332D"))
            p.fillRect(0, h // 2, w, h - h // 2, ground)
        elif self._background == 1:
            p.fillRect(self.rect(), QColor("#1E2124"))
        elif self._background == 2:
            p.fillRect(self.rect(), QColor("#E8E8E8"))
        else:
            tile = 16
            for y in range(0, h, tile):
                for x in range(0, w, tile):
                    dark = (x // tile + y // tile) % 2
                    p.fillRect(x, y, tile, tile, QColor("#555555" if dark else "#8A8A8A"))

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        self._paint_background(p)
        if self._image is not None:
            # Se pinta en píxeles físicos para ver exactamente lo que verá el juego.
            dpr = self.devicePixelRatioF()
            p.scale(1.0 / dpr, 1.0 / dpr)
            z = self._zoom
            left = int(self.width() * dpr / 2 - (self._radius + 0.5) * z)
            top = int(self.height() * dpr / 2 - (self._radius + 0.5) * z)
            n = self._image.width() * z
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)  # Escalado "pixelado"
            p.setOpacity(self._opacity)
            p.drawImage(QRect(left, top, n, n), self._image)
        p.end()


class SettingsWindow(QWidget):
    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self._loading = False
        self._fields: dict[str, QWidget] = {}
        self._hotkey_edits: dict[str, QKeySequenceEdit] = {}
        self.setWindowTitle("Crosshair Overlay — Ajustes")
        self._build()
        ctrl.changed.connect(self._on_changed)
        self._reload_profiles()
        self._reload_monitors()
        self._reload_hotkeys()
        self._reload_general()
        self._load_profile()

    # ============================================================ construcción
    def _build(self) -> None:
        root = QVBoxLayout(self)

        # --- Perfiles
        row = QHBoxLayout()
        row.addWidget(QLabel("Perfil:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        row.addWidget(self.profile_combo, 1)
        for text, slot in (("Nuevo", self._new_profile), ("Duplicar", self._duplicate_profile),
                           ("Renombrar", self._rename_profile), ("Eliminar", self._delete_profile)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        root.addLayout(row)

        body = QHBoxLayout()
        tabs = QTabWidget()
        tabs.addTab(self._build_shape_tab(), "Forma")
        tabs.addTab(self._build_color_tab(), "Color")
        tabs.addTab(self._build_position_tab(), "Posición")
        tabs.addTab(self._build_hotkeys_tab(), "Atajos")
        tabs.addTab(self._build_general_tab(), "General")
        body.addWidget(tabs, 3)
        body.addWidget(self._build_preview(), 2)
        root.addLayout(body, 1)

        # --- Barra inferior
        bottom = QHBoxLayout()
        self.visible_check = QCheckBox("Mira visible")
        self.visible_check.toggled.connect(lambda v: None if self._loading else self.ctrl.set_visible(v))
        bottom.addWidget(self.visible_check)
        bottom.addStretch(1)
        hide_button = QPushButton("Ocultar ventana")
        hide_button.clicked.connect(self.close)
        quit_button = QPushButton("Salir")
        quit_button.clicked.connect(self.ctrl.quit)
        bottom.addWidget(hide_button)
        bottom.addWidget(quit_button)
        root.addLayout(bottom)

    def _int_field(self, name: str, suffix: str = " px") -> QSpinBox:
        lo, hi = INT_LIMITS[name]
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setSuffix(suffix)
        spin.setAccelerated(True)
        spin.valueChanged.connect(lambda v, n=name: self._set(n, v))
        self._fields[name] = spin
        return spin

    def _bool_field(self, name: str, text: str) -> QCheckBox:
        check = QCheckBox(text)
        check.toggled.connect(lambda v, n=name: self._set(n, v))
        self._fields[name] = check
        return check

    def _color_field(self, name: str) -> ColorButton:
        button = ColorButton(lambda c, n=name: self._set(n, c))
        self._fields[name] = button
        return button

    def _build_shape_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        shapes = QGroupBox("Forma (combinable)")
        form = QFormLayout(shapes)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([label for label, _ in PRESETS] + [CUSTOM_PRESET])
        self.preset_combo.activated.connect(self._on_preset)
        form.addRow("Plantilla:", self.preset_combo)
        grid = QGridLayout()
        grid.addWidget(self._bool_field("arms", "Brazos (cruz)"), 0, 0)
        grid.addWidget(self._bool_field("t_style", "Estilo T (sin brazo superior)"), 0, 1)
        grid.addWidget(self._bool_field("circle", "Círculo"), 1, 0)
        grid.addWidget(self._bool_field("dot", "Punto central"), 1, 1)
        form.addRow(grid)
        layout.addWidget(shapes)

        dims = QGroupBox("Dimensiones (píxeles reales de pantalla)")
        form = QFormLayout(dims)
        form.addRow("Longitud de brazo:", self._int_field("length"))
        form.addRow("Grosor de brazo:", self._int_field("thickness"))
        form.addRow("Separación central:", self._int_field("gap"))
        form.addRow("Tamaño del punto:", self._int_field("dot_size"))
        form.addRow("Radio del círculo:", self._int_field("circle_radius"))
        form.addRow("Grosor del círculo:", self._int_field("circle_thickness"))
        layout.addWidget(dims)
        layout.addStretch(1)
        return page

    def _build_color_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Color")
        form = QFormLayout(box)
        form.addRow("Color de la mira:", self._color_field("color"))
        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_label = QLabel()
        self.opacity_label.setMinimumWidth(40)
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_label)
        form.addRow("Opacidad:", opacity_row)
        layout.addWidget(box)

        box = QGroupBox("Contorno")
        form = QFormLayout(box)
        form.addRow(self._bool_field("outline", "Dibujar contorno"))
        form.addRow("Grosor del contorno:", self._int_field("outline_thickness"))
        form.addRow("Color del contorno:", self._color_field("outline_color"))
        layout.addWidget(box)
        layout.addStretch(1)
        return page

    def _build_position_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        box = QGroupBox("Monitor")
        form = QFormLayout(box)
        mon_row = QHBoxLayout()
        self.monitor_combo = QComboBox()
        self.monitor_combo.activated.connect(self._on_monitor_selected)
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(self._reload_monitors)
        mon_row.addWidget(self.monitor_combo, 1)
        mon_row.addWidget(refresh)
        form.addRow("Mostrar en:", mon_row)
        layout.addWidget(box)

        box = QGroupBox("Ajuste fino (si el centro del juego no coincide con el de la pantalla)")
        form = QFormLayout(box)
        form.addRow("Desplazamiento X:", self._int_field("offset_x"))
        form.addRow("Desplazamiento Y:", self._int_field("offset_y"))
        pad = QGridLayout()
        for text, dx, dy, r, c in (("▲", 0, -1, 0, 1), ("◀", -1, 0, 1, 0), ("▶", 1, 0, 1, 2), ("▼", 0, 1, 2, 1)):
            button = QToolButton()
            button.setText(text)
            button.setAutoRepeat(True)
            button.clicked.connect(lambda _=False, x=dx, y=dy: self.ctrl.nudge(x, y))
            pad.addWidget(button, r, c)
        center = QToolButton()
        center.setText("0")
        center.setToolTip("Volver al centro exacto")
        center.clicked.connect(self.ctrl.reset_offset)
        pad.addWidget(center, 1, 1)
        pad_wrap = QHBoxLayout()
        pad_wrap.addLayout(pad)
        pad_wrap.addStretch(1)
        form.addRow("Mover 1 px:", pad_wrap)
        self.position_info = QLabel()
        self.position_info.setWordWrap(True)
        form.addRow(self.position_info)
        layout.addWidget(box)
        layout.addStretch(1)
        return page

    def _build_hotkeys_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        grid = QGridLayout()
        for row, (action, label) in enumerate(ACTIONS.items()):
            grid.addWidget(QLabel(label), row, 0)
            edit = QKeySequenceEdit()
            if hasattr(edit, "setMaximumSequenceLength"):  # Qt >= 6.5
                edit.setMaximumSequenceLength(1)
            edit.editingFinished.connect(lambda a=action: self._on_hotkey_edited(a))
            self._hotkey_edits[action] = edit
            grid.addWidget(edit, row, 1)
            clear = QToolButton()
            clear.setText("✕")
            clear.setToolTip("Desactivar este atajo")
            clear.clicked.connect(lambda _=False, a=action: self.ctrl.set_hotkey(a, ""))
            grid.addWidget(clear, row, 2)
        layout.addLayout(grid)
        self.hotkey_status = QLabel()
        self.hotkey_status.setWordWrap(True)
        layout.addWidget(self.hotkey_status)
        note = QLabel("Haz clic en un campo y pulsa la combinación. Evita Ctrl+Alt+número en "
                      "teclados con AltGr (Ctrl+Alt equivale a AltGr y escribe símbolos).")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.startup_check = QCheckBox("Abrir esta ventana al iniciar")
        self.startup_check.toggled.connect(
            lambda v: None if self._loading else self.ctrl.set_option("show_settings_on_start", v))
        layout.addWidget(self.startup_check)
        path_label = QLabel(f"Archivo de configuración:<br><code>{self.ctrl.config_path}</code>")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        open_dir = QPushButton("Abrir carpeta de configuración")
        open_dir.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctrl.config_path.parent))))
        layout.addWidget(open_dir, 0, Qt.AlignmentFlag.AlignLeft)
        notice = QLabel(
            "<b>Avisos:</b><br>• La mira solo es visible en modo <i>ventana sin bordes</i> "
            "(borderless); en pantalla completa exclusiva el juego tapa cualquier superposición.<br>"
            "• Esta aplicación no lee ni modifica la memoria del juego ni captura la pantalla.<br>"
            "• Algunos juegos competitivos o sistemas antitrampas prohíben las miras externas: "
            "revisa las normas de cada juego antes de usarla.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addStretch(1)
        return page

    def _build_preview(self) -> QWidget:
        box = QGroupBox("Vista previa en tiempo real")
        layout = QVBoxLayout(box)
        self.preview = PreviewWidget()
        layout.addWidget(self.preview, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Zoom:"))
        zoom = QSpinBox()
        zoom.setRange(1, 8)
        zoom.setSuffix("×")
        zoom.setValue(3)
        zoom.valueChanged.connect(self.preview.set_zoom)
        row.addWidget(zoom)
        row.addWidget(QLabel("Fondo:"))
        bg = QComboBox()
        bg.addItems(PreviewWidget.BACKGROUNDS)
        bg.currentIndexChanged.connect(self.preview.set_background)
        row.addWidget(bg, 1)
        layout.addLayout(row)
        return box

    # ============================================================ sincronización
    def _set(self, name: str, value) -> None:
        if not self._loading:
            self.ctrl.update_profile(**{name: value})

    def _on_opacity(self, value: int) -> None:
        self.opacity_label.setText(f"{value} %")
        self._set("opacity", value / 100.0)

    def _on_changed(self, kind: str) -> None:
        if kind == "profiles":
            self._reload_profiles()
        elif kind == "hotkeys":
            self._reload_hotkeys()
        elif kind in ("visible", "general"):
            self._reload_general()
            return
        elif kind == "monitor":
            self._reload_monitors()
        self._load_profile()

    def _load_profile(self) -> None:
        """Vuelca el perfil activo en los controles sin disparar cambios de vuelta."""
        p = self.ctrl.profile
        self._loading = True
        try:
            for name, widget in self._fields.items():
                value = getattr(p, name)
                if isinstance(widget, QSpinBox):
                    widget.setValue(value)
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(value)
                elif isinstance(widget, ColorButton):
                    widget.set_color(value)
            self.opacity_slider.setValue(round(p.opacity * 100))
            self.opacity_label.setText(f"{round(p.opacity * 100)} %")
            current = {k: getattr(p, k) for k in ("arms", "t_style", "circle", "dot")}
            if not current["arms"]:
                current["t_style"] = False
            index = next((i for i, (_, flags) in enumerate(PRESETS) if flags == current), len(PRESETS))
            self.preset_combo.setCurrentIndex(index)
        finally:
            self._loading = False
        # Habilita solo los controles que afectan a las formas activas.
        for name in ("length", "thickness", "gap", "t_style"):
            self._fields[name].setEnabled(p.arms)
        self._fields["dot_size"].setEnabled(p.dot)
        self._fields["circle_radius"].setEnabled(p.circle)
        self._fields["circle_thickness"].setEnabled(p.circle)
        self._fields["outline_thickness"].setEnabled(p.outline)
        self._fields["outline_color"].setEnabled(p.outline)
        self.preview.set_profile(p)
        self._update_position_info()

    def _reload_profiles(self) -> None:
        self._loading = True
        try:
            self.profile_combo.clear()
            self.profile_combo.addItems([p.name for p in self.ctrl.cfg.profiles])
            self.profile_combo.setCurrentIndex(self.ctrl.cfg.active_profile)
        finally:
            self._loading = False

    def _reload_monitors(self) -> None:
        self._loading = True
        try:
            self.monitor_combo.clear()
            self.monitor_combo.addItem("Automático (monitor principal)", "")
            for i, m in enumerate(list_monitors()):
                self.monitor_combo.addItem(m.describe(i), m.id)
            index = self.monitor_combo.findData(self.ctrl.cfg.monitor)
            self.monitor_combo.setCurrentIndex(max(0, index))
        finally:
            self._loading = False
        self._update_position_info()

    def _reload_hotkeys(self) -> None:
        for action, edit in self._hotkey_edits.items():
            edit.setKeySequence(QKeySequence(self.ctrl.cfg.hotkeys.get(action, "")))
        failures = self.ctrl.hotkey_failures
        lines = [f"Sistema de atajos: {self.ctrl.hotkeys.backend}."]
        if failures:
            lines += [f"⚠ {ACTIONS[a]}: {reason}" for a, reason in failures.items()]
        else:
            lines.append("✔ Todos los atajos activos están registrados.")
        self.hotkey_status.setText("<br>".join(lines))

    def _reload_general(self) -> None:
        self._loading = True
        try:
            self.visible_check.setChecked(self.ctrl.cfg.visible)
            self.startup_check.setChecked(self.ctrl.cfg.show_settings_on_start)
        finally:
            self._loading = False

    def _update_position_info(self) -> None:
        m = find_monitor(self.ctrl.cfg.monitor)
        p = self.ctrl.profile
        cx, cy = m.center
        self.position_info.setText(
            f"Resolución física {m.width}×{m.height}, escala {round(m.scale * 100)} %.<br>"
            f"Centro de la mira: ({cx + p.offset_x}, {cy + p.offset_y}) — "
            f"desplazamiento ({p.offset_x:+d}, {p.offset_y:+d}) px.")

    # ============================================================ acciones
    def _on_profile_selected(self, index: int) -> None:
        if not self._loading and index >= 0:
            self.ctrl.set_active_profile(index)

    def _on_preset(self, index: int) -> None:
        if index < len(PRESETS):
            self.ctrl.update_profile(**PRESETS[index][1])

    def _on_monitor_selected(self, index: int) -> None:
        if not self._loading:
            self.ctrl.set_monitor(self.monitor_combo.itemData(index) or "")

    def _ask_name(self, title: str, default: str) -> str | None:
        name, ok = QInputDialog.getText(self, title, "Nombre del perfil:", text=default)
        return name.strip() if ok and name.strip() else None

    def _new_profile(self) -> None:
        name = self._ask_name("Nuevo perfil", f"Perfil {len(self.ctrl.cfg.profiles) + 1}")
        if name:
            self.ctrl.add_profile(name, copy_current=False)

    def _duplicate_profile(self) -> None:
        name = self._ask_name("Duplicar perfil", f"{self.ctrl.profile.name} (copia)")
        if name:
            self.ctrl.add_profile(name, copy_current=True)

    def _rename_profile(self) -> None:
        name = self._ask_name("Renombrar perfil", self.ctrl.profile.name)
        if name:
            self.ctrl.rename_profile(name)

    def _delete_profile(self) -> None:
        if len(self.ctrl.cfg.profiles) <= 1:
            QMessageBox.information(self, "Eliminar perfil", "Debe quedar al menos un perfil.")
            return
        answer = QMessageBox.question(self, "Eliminar perfil", f"¿Eliminar «{self.ctrl.profile.name}»?")
        if answer == QMessageBox.StandardButton.Yes:
            self.ctrl.delete_profile()

    def _on_hotkey_edited(self, action: str) -> None:
        seq = self._hotkey_edits[action].keySequence()
        text = "" if seq.isEmpty() else QKeySequence(seq[0]).toString(QKeySequence.SequenceFormat.PortableText)
        if text and parse_hotkey(text) is None:
            QMessageBox.warning(self, "Atajo no válido", f"La tecla «{text}» no se puede usar como atajo global.")
            self._reload_hotkeys()
            return
        if text != self.ctrl.cfg.hotkeys.get(action, ""):
            self.ctrl.set_hotkey(action, text)

    def closeEvent(self, event) -> None:
        # Con icono en la bandeja, cerrar solo oculta la ventana; la mira sigue activa.
        if self.ctrl.has_tray:
            event.ignore()
            self.hide()
        else:
            event.accept()
            self.ctrl.quit()

    def show_and_focus(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

