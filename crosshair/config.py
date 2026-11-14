"""Modelo de configuración (perfiles, atajos) y persistencia en un JSON local.

Este módulo no depende de Qt para que sea fácil de probar y reutilizar.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_DIR_NAME = "CrosshairOverlay"
CONFIG_VERSION = 1
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Límites de cada campo numérico (todas las medidas en píxeles físicos de pantalla).
INT_LIMITS: dict[str, tuple[int, int]] = {
    "length": (0, 200),
    "thickness": (1, 30),
    "gap": (0, 100),
    "outline_thickness": (1, 6),
    "dot_size": (1, 30),
    "circle_radius": (1, 150),
    "circle_thickness": (1, 20),
    "offset_x": (-2000, 2000),
    "offset_y": (-2000, 2000),
}
OPACITY_LIMITS = (0.05, 1.0)

# Acciones con atajo global -> texto que se muestra en la interfaz.
ACTIONS: dict[str, str] = {
    "toggle": "Mostrar / ocultar la mira",
    "next_profile": "Perfil siguiente",
    "prev_profile": "Perfil anterior",
    "nudge_up": "Mover la mira 1 px hacia arriba",
    "nudge_down": "Mover la mira 1 px hacia abajo",
    "nudge_left": "Mover la mira 1 px a la izquierda",
    "nudge_right": "Mover la mira 1 px a la derecha",
    "reset_offset": "Restablecer el desplazamiento (0, 0)",
    "open_settings": "Abrir los ajustes",
}

# Se usan los nombres "portables" de Qt (los mismos que produce QKeySequence).
DEFAULT_HOTKEYS: dict[str, str] = {
    "toggle": "Ctrl+Alt+X",
    "next_profile": "Ctrl+Alt+PgDown",
    "prev_profile": "Ctrl+Alt+PgUp",
    "nudge_up": "Ctrl+Alt+Up",
    "nudge_down": "Ctrl+Alt+Down",
    "nudge_left": "Ctrl+Alt+Left",
    "nudge_right": "Ctrl+Alt+Right",
    "reset_offset": "Ctrl+Alt+Home",
    "open_settings": "Ctrl+Alt+S",
}


@dataclass
class Profile:
    """Un perfil de mira. Las formas son combinables mediante los flags booleanos."""

    name: str = "Perfil"
    # Color y opacidad
    color: str = "#00FF00"
    opacity: float = 1.0
    # Formas (combinables): brazos en cruz, estilo T, círculo y punto central
    arms: bool = True
    t_style: bool = False          # Sin brazo superior (solo tiene efecto con arms=True)
    circle: bool = False
    dot: bool = False
    # Dimensiones
    length: int = 6                # Longitud de cada brazo
    thickness: int = 2             # Grosor de los brazos
    gap: int = 3                   # Distancia del centro al inicio de cada brazo (0 = cruz sólida)
    dot_size: int = 2              # Lado del punto central
    circle_radius: int = 10
    circle_thickness: int = 1
    # Contorno
    outline: bool = True
    outline_thickness: int = 1
    outline_color: str = "#000000"
    # Ajuste fino de posición respecto al centro del monitor
    offset_x: int = 0
    offset_y: int = 0

    def clamp(self) -> "Profile":
        """Normaliza tipos y recorta valores fuera de rango (protege ante JSON editado a mano)."""
        for name, (lo, hi) in INT_LIMITS.items():
            setattr(self, name, max(lo, min(hi, int(getattr(self, name)))))
        lo, hi = OPACITY_LIMITS
        self.opacity = round(max(lo, min(hi, float(self.opacity))), 3)
        for name in ("arms", "t_style", "circle", "dot", "outline"):
            setattr(self, name, bool(getattr(self, name)))
        defaults = Profile.__dataclass_fields__
        for name in ("color", "outline_color"):
            value = str(getattr(self, name))
            setattr(self, name, value.upper() if _HEX_COLOR.match(value) else defaults[name].default)
        self.name = str(self.name).strip()[:40] or "Perfil"
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> "Profile":
        profile = cls()
        if not isinstance(data, dict):
            return profile
        for f in fields(cls):
            if f.name not in data:
                continue
            default = getattr(profile, f.name)
            try:
                # Ojo: bool es subclase de int, así que se comprueba primero.
                if isinstance(default, bool):
                    value = bool(data[f.name])
                elif isinstance(default, int):
                    value = int(data[f.name])
                elif isinstance(default, float):
                    value = float(data[f.name])
                else:
                    value = str(data[f.name])
            except (TypeError, ValueError):
                continue
            setattr(profile, f.name, value)
        return profile.clamp()

    def copy(self, **changes) -> "Profile":
        data = self.to_dict()
        data.update(changes)
        return Profile.from_dict(data)


def default_profiles() -> list[Profile]:
    return [
        Profile(name="Clásica", color="#00FF00", length=6, thickness=2, gap=3),
        Profile(name="Punto", color="#FF3030", arms=False, dot=True, dot_size=4),
        Profile(name="Círculo + punto", color="#00E5FF", arms=False, circle=True, dot=True,
                circle_radius=12, circle_thickness=2, dot_size=2),
        Profile(name="T táctica", color="#FFE000", t_style=True, length=8, thickness=2, gap=4, dot=True),
    ]


@dataclass
class AppConfig:
    version: int = CONFIG_VERSION
    visible: bool = True
    show_settings_on_start: bool = True
    monitor: str = ""              # Identificador del monitor; "" = monitor principal
    active_profile: int = 0
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    profiles: list[Profile] = field(default_factory=default_profiles)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "visible": self.visible,
            "show_settings_on_start": self.show_settings_on_start,
            "monitor": self.monitor,
            "active_profile": self.active_profile,
            "hotkeys": dict(self.hotkeys),
            "profiles": [p.to_dict() for p in self.profiles],
        }

    @classmethod
    def from_dict(cls, data: object) -> "AppConfig":
        cfg = cls()
        if not isinstance(data, dict):
            return cfg
        cfg.visible = bool(data.get("visible", cfg.visible))
        cfg.show_settings_on_start = bool(data.get("show_settings_on_start", cfg.show_settings_on_start))
        cfg.monitor = str(data.get("monitor", "") or "")
        hotkeys = data.get("hotkeys")
        if isinstance(hotkeys, dict):
            for action in ACTIONS:
                if isinstance(hotkeys.get(action), str):
                    cfg.hotkeys[action] = hotkeys[action].strip()  # "" = atajo desactivado
        profiles = data.get("profiles")
        if isinstance(profiles, list):
            parsed = [Profile.from_dict(p) for p in profiles if isinstance(p, dict)]
            if parsed:
                cfg.profiles = parsed
        try:
            active = int(data.get("active_profile", 0))
        except (TypeError, ValueError):
            active = 0
        cfg.active_profile = max(0, min(len(cfg.profiles) - 1, active))
        return cfg


def default_config_dir() -> Path:
    """Carpeta de configuración por usuario según el sistema operativo."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "crosshair-overlay"


class ConfigStore:
    """Carga y guarda AppConfig en JSON con escritura atómica."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_config_dir() / "config.json"

    def load(self) -> AppConfig:
        if not self.path.exists():
            cfg = AppConfig()
            self.save(cfg)
            return cfg
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                return AppConfig.from_dict(json.load(fh))
        except (OSError, ValueError) as exc:
            # Archivo corrupto: se conserva una copia y se arranca con valores por defecto.
            backup = self.path.with_suffix(".json.bak")
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            print(f"[config] No se pudo leer {self.path} ({exc}); copia en {backup}", file=sys.stderr)
            return AppConfig()

    def save(self, cfg: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(cfg.to_dict(), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, self.path)  # Atómico: nunca queda un config.json a medio escribir.
