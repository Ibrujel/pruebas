"""Controlador: une configuración, superposición, atajos, bandeja del sistema y ajustes."""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .config import ConfigStore, Profile
from .hotkeys import create_hotkey_manager
from .overlay import OverlayWindow
from .settings_ui import SettingsWindow


def make_app_icon() -> QIcon:
    """Icono generado por código (sin archivos de recursos)."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for color, width in ((QColor("#101010"), 9), (QColor("#3CFF3C"), 5)):
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.drawEllipse(QPointF(32, 32), 19, 19)
        p.drawLine(32, 2, 32, 22)
        p.drawLine(32, 42, 32, 62)
        p.drawLine(2, 32, 22, 32)
        p.drawLine(42, 32, 62, 32)
    p.end()
    return QIcon(pix)


class CrosshairApp(QObject):
    # Tipo de cambio: "profile", "profiles", "monitor", "hotkeys", "visible", "general"
    changed = Signal(str)

    def __init__(self, store: ConfigStore, start_hidden: bool = False):
        super().__init__()
        self.store = store
        self.cfg = store.load()

        # Guardado diferido: agrupa ráfagas de cambios en una sola escritura a disco.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_now)

        self.overlay = OverlayWindow()
        self.hotkeys = create_hotkey_manager(self)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.hotkey_failures = self.hotkeys.register_all(self.cfg.hotkeys)

        self.icon = make_app_icon()
        QApplication.instance().setWindowIcon(self.icon)
        self.tray: QSystemTrayIcon | None = None
        self.settings = SettingsWindow(self)
        self._setup_tray()
        self._watch_screens()

        self.refresh_overlay()
        if self.cfg.visible:
            self.overlay.show()
        if not self.has_tray or (self.cfg.show_settings_on_start and not start_hidden):
            self.settings.show_and_focus()
        elif self.hotkey_failures and self.tray:
            self.tray.showMessage("Crosshair Overlay", "Algunos atajos no se pudieron registrar. "
                                  "Revisa la pestaña Atajos.", QSystemTrayIcon.MessageIcon.Warning)

    # ------------------------------------------------------------------ estado
    @property
    def profile(self) -> Profile:
        return self.cfg.profiles[self.cfg.active_profile]

    @property
    def config_path(self):
        return self.store.path

    @property
    def has_tray(self) -> bool:
        return self.tray is not None

    def refresh_overlay(self) -> None:
        self.overlay.apply(self.profile, self.cfg.monitor)

    def _commit(self, kind: str, redraw: bool = True) -> None:
        if redraw:
            self.refresh_overlay()
        self._save_timer.start()
        self.changed.emit(kind)
        self._update_tray()

    def save_now(self) -> None:
        try:
            self.store.save(self.cfg)
        except OSError as exc:
            print(f"[config] Error al guardar: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------ perfiles
    def update_profile(self, **changes) -> None:
        p = self.profile
        for key, value in changes.items():
            if hasattr(p, key) and key != "name":
                setattr(p, key, value)
        p.clamp()
        self._commit("profile")

    def set_active_profile(self, index: int) -> None:
        if 0 <= index < len(self.cfg.profiles) and index != self.cfg.active_profile:
            self.cfg.active_profile = index
            self._commit("profiles")

    def cycle_profile(self, step: int) -> None:
        n = len(self.cfg.profiles)
        self.set_active_profile((self.cfg.active_profile + step) % n)

    def add_profile(self, name: str, copy_current: bool) -> None:
        new = self.profile.copy(name=name) if copy_current else Profile(name=name).clamp()
        self.cfg.profiles.append(new)
        self.cfg.active_profile = len(self.cfg.profiles) - 1
        self._commit("profiles")

    def rename_profile(self, name: str) -> None:
        self.profile.name = name
        self.profile.clamp()
        self._commit("profiles", redraw=False)

    def delete_profile(self) -> None:
        if len(self.cfg.profiles) > 1:
            self.cfg.profiles.pop(self.cfg.active_profile)
            self.cfg.active_profile = min(self.cfg.active_profile, len(self.cfg.profiles) - 1)
            self._commit("profiles")

    def nudge(self, dx: int, dy: int) -> None:
        p = self.profile
        self.update_profile(offset_x=p.offset_x + dx, offset_y=p.offset_y + dy)

    def reset_offset(self) -> None:
        self.update_profile(offset_x=0, offset_y=0)

    # ------------------------------------------------------------------ otros ajustes
    def set_monitor(self, monitor_id: str) -> None:
        self.cfg.monitor = monitor_id
        self._commit("monitor")

    def set_visible(self, visible: bool) -> None:
        self.cfg.visible = bool(visible)
        self.overlay.setVisible(self.cfg.visible)
        self._commit("visible", redraw=False)

    def toggle_visible(self) -> None:
        self.set_visible(not self.cfg.visible)

    def set_option(self, name: str, value) -> None:
        setattr(self.cfg, name, value)
        self._commit("general", redraw=False)

    def set_hotkey(self, action: str, text: str) -> None:
        self.cfg.hotkeys[action] = text
        self.hotkey_failures = self.hotkeys.register_all(self.cfg.hotkeys)
        self._commit("hotkeys", redraw=False)

    def _on_hotkey(self, action: str) -> None:
        handlers = {
            "toggle": self.toggle_visible,
            "next_profile": lambda: self.cycle_profile(1),
            "prev_profile": lambda: self.cycle_profile(-1),
            "nudge_up": lambda: self.nudge(0, -1),
            "nudge_down": lambda: self.nudge(0, 1),
            "nudge_left": lambda: self.nudge(-1, 0),
            "nudge_right": lambda: self.nudge(1, 0),
            "reset_offset": self.reset_offset,
            "open_settings": self.settings.show_and_focus,
        }
        handler = handlers.get(action)
        if handler:
            handler()

    # ------------------------------------------------------------------ pantallas
    def _watch_screens(self) -> None:
        """Recoloca la mira si cambian monitores, resolución o escalado."""
        self._screen_timer = QTimer(self)
        self._screen_timer.setSingleShot(True)
        self._screen_timer.setInterval(300)
        self._screen_timer.timeout.connect(lambda: self._commit("monitor"))
        app = QGuiApplication.instance()

        def hook(screen):
            screen.geometryChanged.connect(self._screen_timer.start)
            screen.logicalDotsPerInchChanged.connect(self._screen_timer.start)

        for screen in app.screens():
            hook(screen)
        app.screenAdded.connect(lambda s: (hook(s), self._screen_timer.start()))
        app.screenRemoved.connect(lambda _s: self._screen_timer.start())
        app.primaryScreenChanged.connect(lambda _s: self._screen_timer.start())

    # ------------------------------------------------------------------ bandeja
    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.icon, self)
        menu = QMenu()
        self._tray_visible = QAction("Mostrar mira", menu, checkable=True)
        self._tray_visible.toggled.connect(lambda v: v != self.cfg.visible and self.set_visible(v))
        menu.addAction(self._tray_visible)
        self._tray_profiles = menu.addMenu("Perfil")
        menu.addAction("Ajustes…", self.settings.show_and_focus)
        menu.addSeparator()
        menu.addAction("Salir", self.quit)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self._update_tray()
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.settings.show_and_focus()

    def _update_tray(self) -> None:
        if not self.tray:
            return
        self._tray_visible.blockSignals(True)
        self._tray_visible.setChecked(self.cfg.visible)
        self._tray_visible.blockSignals(False)
        self._tray_profiles.clear()
        group = QActionGroup(self._tray_profiles)
        for i, p in enumerate(self.cfg.profiles):
            action = self._tray_profiles.addAction(p.name)
            action.setCheckable(True)
            action.setChecked(i == self.cfg.active_profile)
            action.triggered.connect(lambda _=False, idx=i: self.set_active_profile(idx))
            group.addAction(action)
        state = "visible" if self.cfg.visible else "oculta"
        self.tray.setToolTip(f"Crosshair Overlay — {self.profile.name} ({state})")

    # ------------------------------------------------------------------ salida
    def quit(self) -> None:
        QApplication.instance().quit()

    def shutdown(self) -> None:
        self.hotkeys.unregister_all()
        self._save_timer.stop()
        self.save_now()
        if self.tray:
            self.tray.hide()
