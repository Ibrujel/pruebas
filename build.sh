#!/usr/bin/env bash
# Empaqueta para Linux o macOS (genera dist/CrosshairOverlay o dist/CrosshairOverlay.app).
set -euo pipefail
python3 -m venv .venv
.venv/bin/pip install -r requirements-build.txt
.venv/bin/pyinstaller --noconfirm --clean --windowed --name CrosshairOverlay main.py
echo "Listo: dist/"
