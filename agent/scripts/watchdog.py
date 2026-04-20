"""
Instaply Auto-Apply Agent Watchdog.

Checks the health of the offline auto-apply daemon and reports status.
Run on a schedule (Windows Task Scheduler, every 30 min) or on-demand.

Exit codes:
  0 = healthy
  1 = warning (agent running but degraded)
  2 = critical (agent dead, stuck, or no recent activity)

Outputs:
  - Pretty status to stdout
  - JSON status to artifacts/watchdog_status.json
  - Windows toast notification on warning/critical (if --toast)

Usage:
  python scripts/agent_watchdog.py            # human-readable
  python scripts/agent_watchdog.py --json     # JSON only
  python scripts/agent_watchdog.py --toast    # also pop a Windows toast on issues
  python scripts/agent_watchdog.py --quiet    # only print on warning/critical
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"
LOG_FILE = ARTIFACTS / "auto_apply.log"
LOCK_FILE = ARTIFACTS / ".auto_apply.lock"
STATUS_FILE = ARTIFACTS / "watchdog_status.json"
DB_PATH = ROOT / "data" / "jobs.db"

# Thresholds
LOG_STALE_WARN_MIN = 15       # warn if no log entry in 15 min
LOG_STALE_CRIT_MIN = 60       # critical if no log entry in 60 min
ERROR_RATE_WARN = 0.50        # warn if >50% of last-hour outcomes are errors/skips
SUBMIT_DROUGHT_HOURS = 4      # warn if no successful submit in 4 hours during waking hours


def now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def read_lock() -> tuple[int | None, datetime | None]:
    """Return (pid, lock_mtime) or (None, None) if no lock.

    NOTE: Scout holds an exclusive Windows lock (msvcrt.locking) on this file,
    so reading it from another process raises PermissionError. We can still
    stat it (get mtime) to know it exists and is held. In that case we resolve
    the PID via process-scan instead of file-read.
    """
    if not LOCK_FILE.exists():
        return None, None
    mtime = datetime.fromtimestamp(LOCK_FILE.stat().st_mtime).astimezone()
    pid: int | None = None
    try:
        pid_text = LOCK_FILE.read_text().strip()
        if pid_text.isdigit():
            pid = int(pid_text)
    except PermissionError:
        # Lock is held exclusively → Scout is alive. Find its PID by process scan.
        pid = find_scout_pid_via_ps()
    except Exception:
        pass
    return pid, mtime


def find_scout_pid_via_ps() -> int | None:
    """Fallback: find the running `python run_auto_apply.py` PID via WMI."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-WmiObject Win32_Process | "
             "Where-Object { $_.CommandLine -like '*run_auto_apply.py*' -and $_.Name -eq 'python.exe' } | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=10,
        )
        for ln in (r.stdout or "").splitlines():
            ln = ln.strip()
            if ln.isdigit():
                return int(ln)
    except Exception:
        pass
    return None


def pid_alive(pid: int) -> bool:
    """Check if a PID is alive on Windows."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in out.stdout
    except Exception:
        return False


def tail_log(n: int = 200) -> list[str]:
    if not LOG_FILE.exists():
        return []
    try:
        with LOG_FILE.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 256 * 1024)  # 256KB tail
            f.seek(size - chunk)
            data = f.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        return lines[-n:]
    except Exception:
        return []


_LOG_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+(\w+)")


def parse_log_lines(lines: list[str]) -> list[tuple[datetime, str, str]]:
    """Return [(ts, level, message), ...]."""
    out = []
    for line in lines:
        m = _LOG_TS.match(line)
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").astimezone()
        except Exception:
            continue
        out.append((ts, m.group(2), line))
    return out


def db_today_stats() -> dict:
    if not DB_PATH.exists():
        return {"error": f"DB missing at {DB_PATH}"}
    today = now().strftime("%Y-%m-%d")
    one_hour_ago = (now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        c = sqlite3.connect(str(DB_PATH))
        cur = c.cursor()

        # Today's outcomes from job_status_events
        cur.execute(
            "SELECT reason, COUNT(*) FROM job_status_events "
            "WHERE created_at >= ? GROUP BY reason ORDER BY 2 DESC",
            (today,),
        )
        today_events = {r[0]: r[1] for r in cur.fetchall()}

        # Last hour's outcomes
        cur.execute(
            "SELECT reason, COUNT(*) FROM job_status_events "
            "WHERE created_at >= ? GROUP BY reason ORDER BY 2 DESC",
            (one_hour_ago,),
        )
        last_hour_events = {r[0]: r[1] for r in cur.fetchall()}

        # Most recent successful submit
        cur.execute(
            "SELECT created_at FROM job_status_events "
            "WHERE reason = 'application_submitted' ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        last_submit = row[0] if row else None

        # Queue depth
        cur.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('new','packet_generated')")
        queue_depth = cur.fetchone()[0]

        c.close()

        submitted = today_events.get("application_submitted", 0)
        not_found = today_events.get("auto_apply:submit_not_found", 0)
        needs_review = today_events.get("auto_apply:needs_review", 0)
        attempted = submitted + not_found + needs_review
        success_rate = (submitted / attempted) if attempted else None

        return {
            "today_events": today_events,
            "last_hour_events": last_hour_events,
            "submitted_today": submitted,
            "rejected_expired_today": not_found,
            "needs_review_today": needs_review,
            "success_rate_today": success_rate,
            "last_successful_submit": last_submit,
            "queue_depth": queue_depth,
        }
    except Exception as exc:
        return {"error": str(exc)}


def build_status() -> dict:
    pid, lock_mtime = read_lock()
    log_lines = tail_log(300)
    parsed = parse_log_lines(log_lines)
    last_log_ts = parsed[-1][0] if parsed else None
    log_age_min = ((now() - last_log_ts).total_seconds() / 60.0) if last_log_ts else None

    # Recent error count
    recent_errors = sum(1 for ts, lvl, _ in parsed[-100:] if lvl == "ERROR")
    recent_warns = sum(1 for ts, lvl, _ in parsed[-100:] if lvl == "WARNING")

    db = db_today_stats()
    alive = pid_alive(pid) if pid else False

    issues: list[str] = []
    severity = "ok"  # ok | warning | critical

    if pid is None:
        issues.append("No lock file — agent not running.")
        severity = "critical"
    elif not alive:
        issues.append(f"Lock file points to PID {pid} but process is dead (stale lock).")
        severity = "critical"
    else:
        if log_age_min is None:
            issues.append("Log file empty or unparseable.")
            severity = max(severity, "warning", key=_sev_rank)
        elif log_age_min > LOG_STALE_CRIT_MIN:
            issues.append(f"No log activity for {log_age_min:.0f} min (>{LOG_STALE_CRIT_MIN}).")
            severity = "critical"
        elif log_age_min > LOG_STALE_WARN_MIN:
            issues.append(f"No log activity for {log_age_min:.0f} min (>{LOG_STALE_WARN_MIN}).")
            severity = max(severity, "warning", key=_sev_rank)

    if recent_errors >= 10:
        issues.append(f"{recent_errors} ERROR lines in last ~100 log entries.")
        severity = max(severity, "warning", key=_sev_rank)

    if isinstance(db, dict) and "success_rate_today" in db:
        sr = db["success_rate_today"]
        if sr is not None and sr < 0.20 and (db["submitted_today"] + db["rejected_expired_today"]) >= 20:
            issues.append(f"Submit success rate today is only {sr:.0%}.")
            severity = max(severity, "warning", key=_sev_rank)

    return {
        "checked_at": now().isoformat(),
        "severity": severity,
        "alive": alive,
        "pid": pid,
        "lock_mtime": lock_mtime.isoformat() if lock_mtime else None,
        "last_log_ts": last_log_ts.isoformat() if last_log_ts else None,
        "log_age_min": round(log_age_min, 1) if log_age_min is not None else None,
        "recent_errors": recent_errors,
        "recent_warnings": recent_warns,
        "db": db,
        "issues": issues,
    }


_SEV_ORDER = {"ok": 0, "warning": 1, "critical": 2}


def _sev_rank(s: str) -> int:
    return _SEV_ORDER.get(s, 0)


def render_human(s: dict) -> str:
    sev = s["severity"]
    icon = {"ok": "✓", "warning": "⚠", "critical": "✗"}[sev]
    color = {"ok": "OK", "warning": "WARNING", "critical": "CRITICAL"}[sev]

    lines = [
        f"=== Instaply Auto-Apply Watchdog — {color} {icon} ===",
        f"Checked at:        {s['checked_at']}",
        f"Process alive:     {s['alive']}  (pid={s['pid']})",
        f"Last log entry:    {s['last_log_ts']}  ({s['log_age_min']} min ago)",
        f"Recent errors:     {s['recent_errors']}  warnings: {s['recent_warnings']}",
    ]
    db = s.get("db") or {}
    if "error" in db:
        lines.append(f"DB:                ERROR — {db['error']}")
    else:
        lines += [
            f"Submitted today:   {db.get('submitted_today', 0)}",
            f"Rejected (dead):   {db.get('rejected_expired_today', 0)}",
            f"Needs review:      {db.get('needs_review_today', 0)}",
            f"Success rate:      {('%.0f%%' % (db['success_rate_today']*100)) if db.get('success_rate_today') is not None else 'n/a'}",
            f"Queue depth:       {db.get('queue_depth', 0)}",
            f"Last submit:       {db.get('last_successful_submit', 'n/a')}",
        ]
    if s["issues"]:
        lines.append("Issues:")
        for i in s["issues"]:
            lines.append(f"  - {i}")
    return "\n".join(lines)


def toast(title: str, message: str) -> None:
    """Pop a Windows toast notification using PowerShell."""
    try:
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null;"
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            f"$xml = [xml]$template.GetXml(); $xml.toast.visual.binding.text[0].InnerText = '{title}';"
            f"$xml.toast.visual.binding.text[1].InnerText = '{message}';"
            "$updated = New-Object Windows.Data.Xml.Dom.XmlDocument; $updated.LoadXml($xml.OuterXml);"
            "$toast = New-Object Windows.UI.Notifications.ToastNotification $updated;"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Instaply Watchdog').Show($toast);"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=8,
        )
    except Exception:
        pass


def auto_restart_scout() -> dict:
    """Kill stale Scout + Chrome + locks, then respawn run_auto_apply.py detached.

    Returns a dict with what was done (safe to JSON-dump).
    """
    actions: list[str] = []

    # 1. Kill any python.exe running run_auto_apply.py
    try:
        ps_cmd = (
            "Get-WmiObject Win32_Process | "
            "Where-Object { $_.CommandLine -like '*run_auto_apply.py*' -and $_.Name -eq 'python.exe' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                       capture_output=True, timeout=15)
        actions.append("killed run_auto_apply python processes")
    except Exception as e:
        actions.append(f"kill scout failed: {e}")

    # 2. Kill orphan Chrome spawned from the bot profile (but not user's personal Chrome)
    try:
        ps_cmd = (
            "Get-WmiObject Win32_Process | "
            "Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*chrome_bot_profile*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                       capture_output=True, timeout=15)
        actions.append("killed bot-profile chrome processes")
    except Exception as e:
        actions.append(f"kill chrome failed: {e}")

    # 3. Clear locks
    for lock_name in ("auto_apply.lock", ".auto_apply.lock"):
        try:
            lf = ARTIFACTS / lock_name
            if lf.exists():
                lf.unlink()
                actions.append(f"removed {lock_name}")
        except Exception as e:
            actions.append(f"unlink {lock_name} failed: {e}")
    for sub in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            p = ARTIFACTS / "chrome_bot_profile" / sub
            if p.exists():
                p.unlink()
                actions.append(f"removed chrome {sub}")
        except Exception:
            pass

    # 4. Clear __pycache__ so a reloaded worker picks up any fresh code changes
    try:
        import shutil
        for root, dirs, _ in os.walk(ROOT):
            for d in dirs:
                if d == "__pycache__":
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
        actions.append("cleared __pycache__")
    except Exception:
        pass

    # 5. Spawn Scout detached
    try:
        DETACHED = 0x00000008  # subprocess.DETACHED_PROCESS on Windows
        log_path = ARTIFACTS / "auto_apply.log"
        env = {**os.environ, "MODEL_NAME": os.environ.get("MODEL_NAME", "gemma4:e4b")}
        with log_path.open("ab") as logf:
            p = subprocess.Popen(
                ["python", "run_auto_apply.py"],
                cwd=str(ROOT),
                stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
                env=env,
                creationflags=DETACHED if os.name == "nt" else 0,
            )
        actions.append(f"spawned Scout (PID {p.pid})")
        return {"ok": True, "pid": p.pid, "actions": actions}
    except Exception as e:
        actions.append(f"spawn failed: {e}")
        return {"ok": False, "actions": actions, "error": str(e)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true", help="output JSON only")
    p.add_argument("--toast", action="store_true", help="show Windows toast on warning/critical")
    p.add_argument("--quiet", action="store_true", help="only print when not OK")
    p.add_argument("--autorestart", action="store_true",
                   help="on critical severity, kill & respawn Scout automatically")
    args = p.parse_args()

    s = build_status()

    restart_info = None
    if args.autorestart and s["severity"] == "critical":
        restart_info = auto_restart_scout()
        s["auto_restart"] = restart_info
        # Re-evaluate status after restart so downstream toast/log reflects recovery
        try:
            import time as _time
            _time.sleep(3)
            s_after = build_status()
            s["post_restart_severity"] = s_after.get("severity")
        except Exception:
            pass

    # Persist status
    try:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(s, indent=2, default=str))
    except Exception:
        pass

    if args.json:
        print(json.dumps(s, indent=2, default=str))
    elif args.quiet and s["severity"] == "ok":
        pass
    else:
        try:
            print(render_human(s))
        except UnicodeEncodeError:
            print(render_human(s).encode("ascii", "replace").decode("ascii"))
        if restart_info:
            print(f"\n[AUTO-RESTART] {restart_info}")

    if args.toast and s["severity"] in ("warning", "critical"):
        first_issue = s["issues"][0] if s["issues"] else "see watchdog_status.json"
        prefix = "Instaply Agent (auto-restarted): " if restart_info and restart_info.get("ok") else "Instaply Agent: "
        toast(f"{prefix}{s['severity'].upper()}", first_issue[:120])

    return {"ok": 0, "warning": 1, "critical": 2}[s["severity"]]


if __name__ == "__main__":
    sys.exit(main())
