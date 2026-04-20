param(
    [switch]$NoBrowser,
    [int]$Port = 8002,
    [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

function Test-PortListening {
    param(
        [string]$HostName,
        [int]$Port
    )

    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $async = $tcp.BeginConnect($HostName, $Port, $null, $null)
        $waited = $async.AsyncWaitHandle.WaitOne(500)
        if (-not $waited) {
            $tcp.Close()
            return $false
        }
        $tcp.EndConnect($async)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Test-PythonUvicorn {
    param([string]$PythonExe)
    try {
        $null = & $PythonExe -c "import uvicorn; import dotenv; import backend.api.main" 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

$PythonExe = "python"
if ((Test-Path $VenvPython) -and (Test-PythonUvicorn -PythonExe $VenvPython)) {
    $PythonExe = $VenvPython
}

$BaseUrl = "http://$HostName`:$Port"
$DocsUrl = "$BaseUrl/docs"
$DashboardUrl = "$BaseUrl/dashboard"

if (Test-PortListening -HostName $HostName -Port $Port) {
    Write-Host "Agent API is already running at $BaseUrl" -ForegroundColor Yellow
    if (-not $NoBrowser) {
        Start-Process $DocsUrl | Out-Null
    }
    return
}

$Arguments = @(
    "-m",
    "uvicorn",
    "backend.api.main:app",
    "--host",
    $HostName,
    "--port",
    "$Port"
)

Write-Host "Starting JobAgent API from $RepoRoot" -ForegroundColor Cyan
Start-Process -FilePath $PythonExe -ArgumentList $Arguments -WorkingDirectory $RepoRoot | Out-Null

$Started = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-PortListening -HostName $HostName -Port $Port) {
        $Started = $true
        break
    }
}

if (-not $Started) {
    throw "Agent API did not start on $BaseUrl within the expected time."
}

Write-Host "Agent API is running." -ForegroundColor Green
Write-Host "Docs: $DocsUrl"
Write-Host "Dashboard: $DashboardUrl"

if (-not $NoBrowser) {
    Start-Process $DocsUrl | Out-Null
}
