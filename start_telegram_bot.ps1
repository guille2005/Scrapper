$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "telegram_access_bot.py"

Start-Process `
    -FilePath "python" `
    -ArgumentList "`"$scriptPath`"" `
    -WorkingDirectory $PSScriptRoot `
    -WindowStyle Hidden

Write-Host "Bot de Telegram iniciado en segundo plano."
