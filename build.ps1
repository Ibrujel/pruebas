# Empaqueta Crosshair Overlay como un único .exe de Windows (sin consola).
# Uso (PowerShell, en la carpeta del proyecto):  .\build.ps1
$ErrorActionPreference = "Stop"
if (-not (Test-Path .venv)) { py -3 -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-build.txt
.\.venv\Scripts\pyinstaller --noconfirm --clean --onefile --windowed `
    --name CrosshairOverlay `
    --exclude-module tkinter `
    main.py
Write-Host "Listo: dist\CrosshairOverlay.exe"
