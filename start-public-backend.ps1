param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https://')]
    [string]$FrontendOrigin
)

$ErrorActionPreference = 'Stop'
$backendRoot = $PSScriptRoot
$pythonPath = Join-Path $backendRoot 'env\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found at $pythonPath"
}

$env:PUBLIC_FRONTEND_ORIGINS = $FrontendOrigin.TrimEnd('/')
Set-Location -LiteralPath $backendRoot

Write-Host "Starting FastAPI for frontend: $env:PUBLIC_FRONTEND_ORIGINS"
Write-Host 'Keep this terminal open while the public frontend is in use.'
& $pythonPath main.py
