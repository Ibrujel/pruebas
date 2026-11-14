"""Punto de entrada de Crosshair Overlay.

Uso:
    python main.py                 # arranca normalmente
    python main.py --minimized     # arranca solo en la bandeja
    python main.py --config ruta   # usa otro archivo de configuración (modo portable)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from crosshair import __version__
from crosshair.app import CrosshairApp
from crosshair.config import ConfigStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Mira superpuesta para juegos")
    parser.add_argument("--config", help="Ruta del archivo config.json")
    parser.add_argument("--minimized", action="store_true", help="Iniciar oculto en la bandeja")
    args, qt_args = parser.parse_known_args()

    # Qt 6 activa DPI "Per-Monitor v2" en Windows. PassThrough conserva escalas fraccionarias
    # (125 %, 150 %) para que la interfaz se vea bien; la mira se dibuja en px físicos.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("Crosshair Overlay")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)  # La app vive en la bandeja

    store = ConfigStore(Path(args.config) if args.config else None)
    store.path.parent.mkdir(parents=True, exist_ok=True)

    # Una sola instancia (evita dos miras y atajos duplicados).
    lock = QLockFile(str(store.path.parent / "instance.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "Crosshair Overlay",
                                "La aplicación ya está en ejecución. Búscala en la bandeja del sistema.")
        return 0

    controller = CrosshairApp(store, start_hidden=args.minimized)
    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
