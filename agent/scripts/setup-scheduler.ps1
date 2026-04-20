<#
.SYNOPSIS
    Sets up Windows Task Scheduler tasks for the Instaply Job Agent.

.DESCRIPTION
    Creates two scheduled tasks:
      1. RevizeJobAgent-DailyCycle  - Runs the full pipeline daily at 7:00 AM
      2. RevizeJobAgent-EveningAlerts - Sends email alerts for high-scoring jobs at 6:00 PM

    Run this script as Administrator for "run whether logged in or not" support.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup-scheduler.ps1
    powershell -ExecutionPolicy Bypass -File setup-scheduler.ps1 -Remove
#>

param(
    [switch]$Remove,
    [string]$MorningTime = "07:00",
    [string]$EveningTime = "18:00"
)

$ErrorActionPreference = "Stop"

$RevizeRoot = "C:\Ravendise\Instaply"
$TaskNameCycle = "RevizeJobAgent-DailyCycle"
$TaskNameAlerts = "RevizeJobAgent-EveningAlerts"

# ── Remove mode ──────────────────────────────────────────────
if ($Remove) {
    Write-Host "Removing scheduled tasks..." -ForegroundColor Yellow
    foreach ($name in @($TaskNameCycle, $TaskNameAlerts)) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "  Removed: $name" -ForegroundColor Green
        } else {
            Write-Host "  Not found: $name" -ForegroundColor DarkGray
        }
    }
    return
}

# ── Validate prerequisites ───────────────────────────────────
if (-not (Test-Path (Join-Path $RevizeRoot "run-daily-cycle.cmd"))) {
    throw "run-daily-cycle.cmd not found in $RevizeRoot"
}
if (-not (Test-Path (Join-Path $RevizeRoot ".venv\Scripts\python.exe"))) {
    Write-Warning "Virtual environment not found at $RevizeRoot\.venv - tasks will use system Python."
}

$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Instaply Job Agent - Scheduler Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  User:          $CurrentUser"
Write-Host "  Admin:         $IsAdmin"
Write-Host "  Morning cycle: $MorningTime"
Write-Host "  Evening alerts: $EveningTime"
Write-Host "  Working dir:   $RevizeRoot"
Write-Host ""

# ── Helper: create or update a task ──────────────────────────
function Register-RevizeTask {
    param(
        [string]$TaskName,
        [string]$Description,
        [string]$Executable,
        [string]$Arguments,
        [string]$TriggerTime,
        [string]$WorkingDir
    )

    $trigger = New-ScheduledTaskTrigger -Daily -At $TriggerTime

    $action = New-ScheduledTaskAction `
        -Execute $Executable `
        -Argument $Arguments `
        -WorkingDirectory $WorkingDir

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
        -RestartCount 1 `
        -RestartInterval (New-TimeSpan -Minutes 5)

    # Remove existing task if present
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Write-Host "  Updating existing task: $TaskName" -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    if ($IsAdmin) {
        # Run whether user is logged in or not (requires admin + password)
        $principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType S4U -RunLevel Highest
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Description $Description `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            | Out-Null
        Write-Host "  Created (run whether logged in or not): $TaskName" -ForegroundColor Green
    } else {
        # Interactive-only logon (no admin needed)
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Description $Description `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -User $CurrentUser `
            | Out-Null
        Write-Host "  Created (interactive logon only): $TaskName" -ForegroundColor Green
        Write-Host "  NOTE: Run this script as Administrator to enable 'run whether logged in or not'." -ForegroundColor DarkYellow
    }
}

# ── Task 1: Full Daily Cycle (7:00 AM) ──────────────────────
Write-Host "Setting up $TaskNameCycle..." -ForegroundColor Cyan

Register-RevizeTask `
    -TaskName $TaskNameCycle `
    -Description "Instaply Job Agent: full daily cycle - scout jobs, generate application packets, send alerts" `
    -Executable "cmd.exe" `
    -Arguments "/c `"$RevizeRoot\run-daily-cycle.cmd`"" `
    -TriggerTime $MorningTime `
    -WorkingDir $RevizeRoot

# ── Task 2: Evening Alerts (6:00 PM) ────────────────────────
Write-Host "Setting up $TaskNameAlerts..." -ForegroundColor Cyan

# Build the command for evening alerts only
$VenvPython = Join-Path $RevizeRoot ".venv\Scripts\python.exe"
$AlertScript = Join-Path $RevizeRoot "scripts\openclaw_revize.py"

if (Test-Path $VenvPython) {
    $AlertExe = $VenvPython
} else {
    $AlertExe = "python"
}

Register-RevizeTask `
    -TaskName $TaskNameAlerts `
    -Description "Instaply Job Agent: evening email alerts for high-scoring jobs" `
    -Executable $AlertExe `
    -Arguments "`"$AlertScript`" alerts --limit 15" `
    -TriggerTime $EveningTime `
    -WorkingDir $RevizeRoot

# ── Summary ──────────────────────────────────────────────────
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Scheduled tasks:"

$tasks = Get-ScheduledTask -TaskName "RevizeJobAgent-*" -ErrorAction SilentlyContinue
foreach ($task in $tasks) {
    $info = $task | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
    $nextRun = if ($info.NextRunTime) { $info.NextRunTime.ToString("yyyy-MM-dd HH:mm") } else { "Not scheduled" }
    Write-Host "  $($task.TaskName): next run at $nextRun  (state: $($task.State))"
}

Write-Host ""
Write-Host "To test immediately:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskNameCycle'"
Write-Host "  Start-ScheduledTask -TaskName '$TaskNameAlerts'"
Write-Host ""
Write-Host "To remove:"
Write-Host "  powershell -ExecutionPolicy Bypass -File setup-scheduler.ps1 -Remove"
