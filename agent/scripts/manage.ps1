param(
    [ValidateSet("status", "cycle", "queue", "alerts", "job")]
    [string]$Action = "status",
    [string]$JobId = "",
    [int]$Limit = 20
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = "python"
$ScriptPath = Join-Path $RepoRoot "scripts\openclaw_revize.py"

function Run-Instaply {
    param(
        [string[]]$ArgsList
    )

    & $PythonExe $ScriptPath @ArgsList
}

switch ($Action) {
    "status" {
        Write-Host "Instaply local status" -ForegroundColor Cyan
        Run-Instaply @("queue", "--limit", "$Limit")
    }
    "cycle" {
        Write-Host "Running full Instaply cycle..." -ForegroundColor Cyan
        Run-Instaply @("cycle")
    }
    "queue" {
        Run-Instaply @("queue", "--limit", "$Limit")
    }
    "alerts" {
        Run-Instaply @("alerts", "--limit", "$Limit")
    }
    "job" {
        if (-not $JobId) {
            throw "Provide -JobId for the job action."
        }
        Run-Instaply @("job", $JobId)
    }
}
