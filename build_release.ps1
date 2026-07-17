$ErrorActionPreference = "Stop"

python -m py_compile scraper_correos_flet.py
flet pack "scraper_correos_flet.py" --name ScraperCorreos --distpath "$env:USERPROFILE\Desktop" --yes

Write-Host "Ejecutable generado en: $env:USERPROFILE\Desktop\ScraperCorreos.exe"
