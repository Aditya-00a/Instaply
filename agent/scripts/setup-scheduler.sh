#!/usr/bin/env bash
# Cross-platform scheduler installer for the Instaply agent.
#
# - macOS  → installs a launchd LaunchAgent at ~/Library/LaunchAgents/
# - Linux  → adds a crontab entry that runs run.py every 30 minutes
# - Other  → bails politely
#
# Usage:
#   bash scripts/setup-scheduler.sh          # install
#   bash scripts/setup-scheduler.sh status   # show whether it's installed + running
#   bash scripts/setup-scheduler.sh remove   # uninstall
#   bash scripts/setup-scheduler.sh start    # start it now (without rescheduling)
#   bash scripts/setup-scheduler.sh stop     # stop it now
#
# Idempotent — running install twice is fine.

set -euo pipefail

# Resolve the agent dir (one above this script's location)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
AGENT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_PY="${AGENT_DIR}/run.py"
LOG_DIR="${AGENT_DIR}/data/logs"
LOG_FILE="${LOG_DIR}/agent.log"

# Pick a Python interpreter — prefer the venv if it exists
if [ -x "${AGENT_DIR}/.venv/bin/python" ]; then
  PYTHON="${AGENT_DIR}/.venv/bin/python"
else
  PYTHON="$(command -v python3 || command -v python)"
fi

if [ -z "${PYTHON}" ]; then
  echo "✗ No python interpreter found on PATH. Install Python 3.10+ first." >&2
  exit 1
fi

mkdir -p "${LOG_DIR}"

# ─────────────────────────────────────────────────────────────────────
#  Platform detection
# ─────────────────────────────────────────────────────────────────────
case "$(uname -s)" in
  Darwin*)  PLATFORM="macos" ;;
  Linux*)   PLATFORM="linux" ;;
  *)        echo "✗ Unsupported platform: $(uname -s). Use scripts/setup-scheduler.ps1 on Windows." >&2; exit 1 ;;
esac

CMD="${1:-install}"

# ─────────────────────────────────────────────────────────────────────
#  macOS implementation (launchd)
# ─────────────────────────────────────────────────────────────────────
LAUNCH_AGENT_LABEL="ai.instaply.agent"
LAUNCH_AGENT_PLIST="${HOME}/Library/LaunchAgents/${LAUNCH_AGENT_LABEL}.plist"

write_launchd_plist() {
  cat > "${LAUNCH_AGENT_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>           <string>${LAUNCH_AGENT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${RUN_PY}</string>
  </array>
  <key>WorkingDirectory</key><string>${AGENT_DIR}</string>
  <key>RunAtLoad</key>       <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
    <key>Crashed</key>       <true/>
  </dict>
  <key>StartInterval</key>   <integer>1800</integer>  <!-- restart every 30 min if the loop self-exits -->
  <key>StandardOutPath</key> <string>${LOG_FILE}</string>
  <key>StandardErrorPath</key><string>${LOG_FILE}</string>
  <key>ProcessType</key>     <string>Background</string>
</dict>
</plist>
EOF
}

macos_install() {
  mkdir -p "${HOME}/Library/LaunchAgents"
  write_launchd_plist
  launchctl unload "${LAUNCH_AGENT_PLIST}" 2>/dev/null || true
  launchctl load -w "${LAUNCH_AGENT_PLIST}"
  echo "✓ Installed launchd agent: ${LAUNCH_AGENT_LABEL}"
  echo "  Plist: ${LAUNCH_AGENT_PLIST}"
  echo "  Log:   ${LOG_FILE}"
  echo "  Status:        bash ${SCRIPT_DIR}/setup-scheduler.sh status"
  echo "  Stop / remove: bash ${SCRIPT_DIR}/setup-scheduler.sh remove"
}

macos_remove() {
  if [ -f "${LAUNCH_AGENT_PLIST}" ]; then
    launchctl unload "${LAUNCH_AGENT_PLIST}" 2>/dev/null || true
    rm -f "${LAUNCH_AGENT_PLIST}"
    echo "✓ Removed launchd agent: ${LAUNCH_AGENT_LABEL}"
  else
    echo "  No launchd agent installed."
  fi
}

macos_status() {
  if [ -f "${LAUNCH_AGENT_PLIST}" ]; then
    echo "  Plist: ${LAUNCH_AGENT_PLIST} (present)"
    if launchctl list | grep -q "${LAUNCH_AGENT_LABEL}"; then
      echo "✓ launchd agent is loaded:"
      launchctl list | grep "${LAUNCH_AGENT_LABEL}" | sed 's/^/    /'
    else
      echo "  Plist exists but agent is not loaded."
    fi
  else
    echo "  No launchd agent installed."
  fi
}

# ─────────────────────────────────────────────────────────────────────
#  Linux implementation (cron)
# ─────────────────────────────────────────────────────────────────────
CRON_TAG="# instaply-agent"
CRON_LINE="*/30 * * * * cd ${AGENT_DIR} && ${PYTHON} ${RUN_PY} >> ${LOG_FILE} 2>&1 ${CRON_TAG}"

linux_install() {
  # Pull current crontab (may not exist), strip any existing instaply line,
  # append the fresh one.
  ( crontab -l 2>/dev/null | grep -v "${CRON_TAG}" || true; echo "${CRON_LINE}" ) | crontab -
  echo "✓ Installed cron entry (every 30 min):"
  echo "    ${CRON_LINE}"
  echo "  Log: ${LOG_FILE}"
  echo "  Status:        bash ${SCRIPT_DIR}/setup-scheduler.sh status"
  echo "  Stop / remove: bash ${SCRIPT_DIR}/setup-scheduler.sh remove"
}

linux_remove() {
  if crontab -l 2>/dev/null | grep -q "${CRON_TAG}"; then
    crontab -l 2>/dev/null | grep -v "${CRON_TAG}" | crontab -
    echo "✓ Removed cron entry."
  else
    echo "  No cron entry installed."
  fi
}

linux_status() {
  if crontab -l 2>/dev/null | grep -q "${CRON_TAG}"; then
    echo "✓ Cron entry installed:"
    crontab -l 2>/dev/null | grep "${CRON_TAG}" | sed 's/^/    /'
    if pgrep -f "${RUN_PY}" >/dev/null; then
      echo "✓ run.py is currently running (pid: $(pgrep -f "${RUN_PY}" | tr '\n' ' '))"
    else
      echo "  run.py is not currently running (will fire at next cron tick)."
    fi
  else
    echo "  No cron entry installed."
  fi
}

# ─────────────────────────────────────────────────────────────────────
#  Foreground start / stop (works on both)
# ─────────────────────────────────────────────────────────────────────
generic_start() {
  echo "  Starting run.py in the background. Logs → ${LOG_FILE}"
  ( cd "${AGENT_DIR}" && nohup "${PYTHON}" "${RUN_PY}" >> "${LOG_FILE}" 2>&1 & )
  sleep 1
  if pgrep -f "${RUN_PY}" >/dev/null; then
    echo "✓ Started (pid: $(pgrep -f "${RUN_PY}" | tr '\n' ' '))"
  else
    echo "✗ Failed to start. Check ${LOG_FILE}."
    exit 1
  fi
}

generic_stop() {
  if pgrep -f "${RUN_PY}" >/dev/null; then
    pkill -f "${RUN_PY}"
    sleep 1
    echo "✓ Stopped any running run.py instances."
  else
    echo "  No running run.py instances."
  fi
}

# ─────────────────────────────────────────────────────────────────────
#  Dispatch
# ─────────────────────────────────────────────────────────────────────
case "${PLATFORM}_${CMD}" in
  macos_install) macos_install ;;
  macos_remove)  macos_remove ;;
  macos_status)  macos_status ;;
  linux_install) linux_install ;;
  linux_remove)  linux_remove ;;
  linux_status)  linux_status ;;
  *_start)       generic_start ;;
  *_stop)        generic_stop ;;
  *)
    echo "Unknown command: ${CMD}" >&2
    echo "Usage: bash $0 [install|remove|status|start|stop]" >&2
    exit 2
    ;;
esac
