# =============================================================
#  Genera dist\BombaJeringa.exe (un solo archivo, sin consola)
#  Uso:  powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
# =============================================================
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creando entorno virtual..."
    python -m venv .venv
}

& $py -m pip install -q -r requirements.txt pyinstaller

New-Item -ItemType Directory -Force assets | Out-Null
& $py syringe_pump_gui.py --export-icon assets\icon.ico

& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "BombaJeringa" `
    --icon "assets\icon.ico" `
    --exclude-module tkinter `
    syringe_pump_gui.py

Write-Host ""
Write-Host "Listo: dist\BombaJeringa.exe" -ForegroundColor Green
