<#
.SYNOPSIS
    Health check for the Instaply Job Agent system.

.DESCRIPTION
    Checks:
      - API server reachability and /health endpoint
      - Ollama LLM server reachability
      - Ollama model availability
      - SQLite database stats (job counts, recent jobs, pending follow-ups)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\health-check.ps1
#>

param(
    [switch]$Json
)

$ErrorActionPreference = "Continue"

$RevizeRoot = "C:\Ravendise\Instaply"
$ConfigPath = Join-Path $RevizeRoot "config\openclaw.yaml"
$DbPath = Join-Path $RevizeRoot "data\jobs.db"

# ── Parse config ─────────────────────────────────────────────
$ApiBase = "http://127.0.0.1:8002"
$OllamaHost = "http://localhost:11434"
$OllamaModel = "qwen3-coder:30b"

if (Test-Path $ConfigPath) {
    $configText = Get-Content $ConfigPath -Raw
    # Simple YAML extraction (no external dependency)
    if ($configText -match 'base_url:\s*(\S+)') { $ApiBase = $Matches[1] }
    if ($configText -match 'host:\s*(\S+)') { $OllamaHost = $Matches[1] }
    if ($configText -match 'model:\s*(\S+)') { $OllamaModel = $Matches[1] }
}

$results = [ordered]@{
    timestamp  = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    api_server = @{ status = "unknown" }
    ollama     = @{ status = "unknown" }
    model      = @{ status = "unknown"; name = $OllamaModel }
    database   = @{ status = "unknown" }
}

function Write-Check {
    param([string]$Label, [bool]$Ok, [string]$Detail = "")
    $icon = if ($Ok) { "[OK]" } else { "[FAIL]" }
    $color = if ($Ok) { "Green" } else { "Red" }
    $msg = "  $icon $Label"
    if ($Detail) { $msg += " - $Detail" }
    Write-Host $msg -ForegroundColor $color
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Instaply Job Agent - Health Check" -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkGray
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. API Server ────────────────────────────────────────────
Write-Host "API Server ($ApiBase)" -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri "$ApiBase/health" -TimeoutSec 5 -UseBasicParsing
    if ($resp.StatusCode -eq 200) {
        $body = $resp.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
        $detail = if ($body.status) { $body.status } else { "HTTP 200" }
        $results.api_server = @{ status = "healthy"; detail = $detail; url = $ApiBase }
        Write-Check "Health endpoint" $true $detail
    } else {
        $results.api_server = @{ status = "degraded"; http_code = $resp.StatusCode }
        Write-Check "Health endpoint" $false "HTTP $($resp.StatusCode)"
    }
} catch {
    $results.api_server = @{ status = "down"; error = $_.Exception.Message }
    Write-Check "Health endpoint" $false "Not reachable"
}
Write-Host ""

# ── 2. Ollama Server ────────────────────────────────────────
Write-Host "Ollama LLM ($OllamaHost)" -ForegroundColor Yellow
try {
    $ollamaResp = Invoke-WebRequest -Uri "$OllamaHost/api/tags" -TimeoutSec 5 -UseBasicParsing
    if ($ollamaResp.StatusCode -eq 200) {
        $results.ollama = @{ status = "healthy"; url = $OllamaHost }
        Write-Check "Ollama server" $true "Reachable"

        # Check if the configured model is loaded
        $tags = $ollamaResp.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
        $modelNames = @()
        if ($tags.models) {
            $modelNames = $tags.models | ForEach-Object { $_.name }
        }

        # Match model name (with or without :latest tag)
        $modelBase = ($OllamaModel -split ":")[0]
        $found = $modelNames | Where-Object { $_ -like "$modelBase*" }
        if ($found) {
            $results.model = @{ status = "loaded"; name = $OllamaModel; available = @($found) }
            Write-Check "Model '$OllamaModel'" $true "Available"
        } else {
            $results.model = @{ status = "not_found"; name = $OllamaModel; available_models = $modelNames }
            Write-Check "Model '$OllamaModel'" $false "Not found (available: $($modelNames -join ', '))"
        }
    }
} catch {
    $results.ollama = @{ status = "down"; error = $_.Exception.Message }
    Write-Check "Ollama server" $false "Not reachable"
    $results.model = @{ status = "unknown"; name = $OllamaModel; note = "Ollama unreachable" }
    Write-Check "Model '$OllamaModel'" $false "Cannot check (Ollama down)"
}
Write-Host ""

# ── 3. Database Stats ───────────────────────────────────────
Write-Host "Database ($DbPath)" -ForegroundColor Yellow

if (-not (Test-Path $DbPath)) {
    $results.database = @{ status = "missing"; path = $DbPath }
    Write-Check "Database file" $false "Not found"
} else {
    $dbSizeMB = [math]::Round((Get-Item $DbPath).Length / 1MB, 2)
    Write-Check "Database file" $true "${dbSizeMB} MB"

    $VenvPython = Join-Path $RevizeRoot ".venv\Scripts\python.exe"
    $PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

    $dbQuery = @"
import sqlite3, json, sys
from pathlib import Path

db = Path(r'$DbPath')
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

stats = {}

# Total jobs
try:
    stats['total_jobs'] = conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
except: stats['total_jobs'] = 'error'

# Jobs by status
try:
    rows = conn.execute('SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status ORDER BY cnt DESC').fetchall()
    stats['by_status'] = {r['status']: r['cnt'] for r in rows}
except: stats['by_status'] = 'error'

# Jobs discovered in last 24h
try:
    stats['last_24h'] = conn.execute("SELECT COUNT(*) FROM jobs WHERE discovered_at > datetime('now', '-1 day')").fetchone()[0]
except: stats['last_24h'] = 'error'

# Jobs discovered in last 7 days
try:
    stats['last_7d'] = conn.execute("SELECT COUNT(*) FROM jobs WHERE discovered_at > datetime('now', '-7 days')").fetchone()[0]
except: stats['last_7d'] = 'error'

# Pending follow-ups (packet_generated but not applied)
try:
    stats['pending_followups'] = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'packet_generated'").fetchone()[0]
except: stats['pending_followups'] = 'error'

# High-scoring jobs (fit_score >= 70, still active)
try:
    stats['high_score_active'] = conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score >= 70 AND status NOT IN ('rejected','expired','applied')").fetchone()[0]
except: stats['high_score_active'] = 'error'

# Most recent job
try:
    row = conn.execute("SELECT title, company, fit_score, discovered_at FROM jobs ORDER BY discovered_at DESC LIMIT 1").fetchone()
    if row:
        stats['newest_job'] = {'title': row['title'], 'company': row['company'], 'score': row['fit_score'], 'discovered': row['discovered_at']}
except: stats['newest_job'] = 'error'

conn.close()
print(json.dumps(stats))
"@

    try {
        $statsJson = & $PythonExe -c $dbQuery 2>$null
        $stats = $statsJson | ConvertFrom-Json

        $results.database = @{
            status         = "healthy"
            size_mb        = $dbSizeMB
            total_jobs     = $stats.total_jobs
            last_24h       = $stats.last_24h
            last_7d        = $stats.last_7d
            pending        = $stats.pending_followups
            high_score     = $stats.high_score_active
        }

        Write-Host ""
        Write-Host "  Job Statistics:" -ForegroundColor DarkCyan
        Write-Host "    Total jobs:             $($stats.total_jobs)"
        Write-Host "    Discovered (24h):       $($stats.last_24h)"
        Write-Host "    Discovered (7d):        $($stats.last_7d)"
        Write-Host "    Pending follow-ups:     $($stats.pending_followups)"
        Write-Host "    High-score active:      $($stats.high_score_active)"

        if ($stats.by_status -and $stats.by_status -ne "error") {
            Write-Host ""
            Write-Host "  Status Breakdown:" -ForegroundColor DarkCyan
            $stats.by_status.PSObject.Properties | ForEach-Object {
                Write-Host "    $($_.Name): $($_.Value)"
            }
        }

        if ($stats.newest_job -and $stats.newest_job -ne "error") {
            Write-Host ""
            Write-Host "  Most Recent Job:" -ForegroundColor DarkCyan
            Write-Host "    $($stats.newest_job.title) @ $($stats.newest_job.company)"
            Write-Host "    Score: $($stats.newest_job.score) | Discovered: $($stats.newest_job.discovered)"
        }
    } catch {
        $results.database = @{ status = "error"; error = $_.Exception.Message; size_mb = $dbSizeMB }
        Write-Check "Database query" $false $_.Exception.Message
    }
}
Write-Host ""

# ── 4. Scheduler Status ─────────────────────────────────────
Write-Host "Scheduled Tasks" -ForegroundColor Yellow
$taskNames = @("RevizeJobAgent-DailyCycle", "RevizeJobAgent-EveningAlerts")
foreach ($tn in $taskNames) {
    $task = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
    if ($task) {
        $info = $task | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
        $nextRun = if ($info.NextRunTime) { $info.NextRunTime.ToString("yyyy-MM-dd HH:mm") } else { "N/A" }
        $lastRun = if ($info.LastRunTime -and $info.LastRunTime.Year -gt 1999) { $info.LastRunTime.ToString("yyyy-MM-dd HH:mm") } else { "Never" }
        $lastResult = if ($info.LastTaskResult -eq 0) { "Success" } elseif ($info.LastTaskResult -eq 267011) { "Never run" } else { "Exit $($info.LastTaskResult)" }
        Write-Check $tn $true "State: $($task.State) | Next: $nextRun | Last: $lastRun ($lastResult)"
    } else {
        Write-Check $tn $false "Not registered (run setup-scheduler.ps1)"
    }
}
Write-Host ""

# ── Overall Summary ──────────────────────────────────────────
$allOk = ($results.api_server.status -eq "healthy") -and
         ($results.ollama.status -eq "healthy") -and
         ($results.model.status -eq "loaded") -and
         ($results.database.status -eq "healthy")

if ($allOk) {
    Write-Host "Overall: ALL SYSTEMS HEALTHY" -ForegroundColor Green
} else {
    $issues = @()
    if ($results.api_server.status -ne "healthy") { $issues += "API server ($($results.api_server.status))" }
    if ($results.ollama.status -ne "healthy") { $issues += "Ollama ($($results.ollama.status))" }
    if ($results.model.status -ne "loaded") { $issues += "Model ($($results.model.status))" }
    if ($results.database.status -ne "healthy") { $issues += "Database ($($results.database.status))" }
    Write-Host "Overall: ISSUES DETECTED" -ForegroundColor Red
    Write-Host "  $($issues -join ', ')" -ForegroundColor DarkYellow
}
Write-Host ""

# ── JSON output mode ─────────────────────────────────────────
if ($Json) {
    $results | ConvertTo-Json -Depth 5
}
