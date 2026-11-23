param(
    [Parameter(Mandatory=$true)][string]$Server,
    [int]$SshPort = 22,
    [string]$User = 'root',
    [int]$LocalPort = 28081,
    [int]$RemotePort = 18081
)
$ErrorActionPreference = 'Stop'
Write-Host "Forwarding local $LocalPort to GPU loopback $RemotePort. Keep this terminal open."
& ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 `
    -L "127.0.0.1:${LocalPort}:127.0.0.1:${RemotePort}" -p $SshPort "${User}@${Server}"
