$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'Open http://127.0.0.1:8765 after the server starts. Ctrl+C stops it.'
Write-Host 'Starting the app does not make API calls.'
python .\app.py
