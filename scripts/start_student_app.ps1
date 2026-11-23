param(
    [string]$Python = 'python',
    [int]$Port = 8001,
    [string]$StudentUrl = 'http://127.0.0.1:28081'
)
$ErrorActionPreference = 'Stop'
$ChillerProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ChillerProjectRoot
$ChillerTokenPath = Join-Path $ChillerProjectRoot '.student_credentials/student-service.token'
if (-not (Test-Path -LiteralPath $ChillerTokenPath -PathType Leaf)) {
    throw 'Student credential missing. First configure the existing model backup; never paste the token into chat.'
}
$ChillerListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try { $ChillerListener.Start() }
catch { throw "Port $Port cannot be used. Choose another -Port; keep the GPU service and SSH tunnel open." }
finally { $ChillerListener.Stop() }
$env:ENERGY_AGENT_STUDENT_FOCUSED_ENABLED = '1'
$env:ENERGY_AGENT_STUDENT_FOCUSED_URL = $StudentUrl
$env:ENERGY_AGENT_STUDENT_FOCUSED_TOKEN_FILE = $ChillerTokenPath
$env:ENERGY_AGENT_STUDENT_FOCUSED_TIMEOUT_S = '60'
$env:ENERGY_AGENT_STUDENT_SHADOW_ENABLED = '0'
Write-Host "Open http://127.0.0.1:$Port/chat. The default analysis model is focused1186."
& $Python -m uvicorn chiller_app.api.fastapi_app:app --host 127.0.0.1 --port $Port
