# Quickstart

Get Instaply applying to jobs while you sleep, in about 60 seconds.

> **TL;DR:** clone the repo, run `python setup.py`, drop your profile,
> hit `python run.py` (or install the scheduled task). Done.

---

## 1. Clone the repo

```bash
git clone https://github.com/Aditya-00a/Instaply
cd Instaply/agent
```

You need **Python 3.10 or newer**. Check with `python --version`.

If you don't have it: [python.org](https://python.org) (Windows / macOS) or `sudo apt install python3.12` (Ubuntu / Debian).

---

## 2. Run the setup wizard

```bash
python setup.py
```

The wizard handles everything that's painful about local LLMs:

| Step | What it does |
|---|---|
| 🔍 **Detect** | OS, RAM, CPU cores, NVIDIA / Apple Silicon / AMD GPU, VRAM |
| 🦙 **Install Ollama** | If you don't have it: `brew install --cask ollama` (Mac), `winget install Ollama.Ollama` (Windows), or `curl -fsSL https://ollama.com/install.sh \| sh` (Linux) |
| 🎯 **Pick a model** | The biggest model that fits in ~85% of your usable memory budget. Walks `qwen2.5:3b → llama3.2:3b → llama3.1:8b → qwen2.5:7b → qwen2.5:14b → qwen3-coder:30b → llama3.1:70b` |
| ⬇️ **Pull the model** | `ollama pull <chosen>` (this is the biggest download — typically 2–20 GB) |
| ✏️ **Write `.env`** | Drops the right `LLM_PROVIDER` + `MODEL_NAME` + `OLLAMA_BASE_URL` into `config/.env` |

Flags:
- `--yes` / `-y` — skip every confirmation (CI / scripted use)
- `--detect-only` — print the hardware + recommendation as JSON and exit (useful for "what would it pick on my machine?")

Example:

```bash
python setup.py --detect-only
# {
#   "hardware": {"os_name": "Darwin", "ram_gb": 16, "vram_gb": null, "apple_silicon": true},
#   "recommendation": {"name": "llama3.1:8b", "label": "Llama 3.1 8B", ...}
# }
```

---

## 3. Install Python dependencies

```bash
pip install -r requirements.txt    # if you have one
# or, minimally:
pip install playwright httpx pydantic python-dotenv beautifulsoup4 lxml \
    requests psutil openai sqlite-utils

python -m playwright install chromium
```

The Chromium download is ~150 MB, downloaded once, reused forever.

---

## 4. Drop in your profile + master resume

The agent reads two files at boot:

```
agent/data/profile.json          # contact, work auth, EEO, target roles, salary
agent/data/master-resume.json    # the full resume the tailor module re-ranks per JD
```

Schemas live at `backend/models/schemas.py`. A profile-bootstrapping
wizard is on the roadmap; for now you author these manually.

---

## 5. Run it

### Foreground (recommended for the first run)

```bash
python run.py
```

You'll see the loop tick: discover → score → tailor → queue. The first
cycle takes a few minutes (cold ATS pool scans). Subsequent cycles are
incremental.

### Background — Windows (scheduled task)

```powershell
.\scripts\setup-scheduler.ps1
```

That registers a Task Scheduler entry that runs the daily cycle and a
watchdog that restarts the loop if it dies.

Manage it with:

```powershell
.\scripts\manage.ps1 status        # see if it's running
.\scripts\manage.ps1 stop          # stop it
.\scripts\manage.ps1 start         # start it back up
```

### Background — macOS / Linux

The cron / launchd setup scripts are on the roadmap. For now the
hand-rolled equivalent on Linux:

```bash
crontab -e
# Add this line to run every 30 minutes:
*/30 * * * * cd /path/to/Instaply/agent && /usr/bin/python run.py >> data/logs/cron.log 2>&1
```

---

## 6. Review the queue

The agent **never silently submits**. It drafts applications into a
queue at `~/.instaply/data.db` (status: `packet_generated`). When you're
ready, run:

```bash
python apply_now.py             # walks the queue interactively
```

For each draft:
1. Opens your real Chrome
2. Autofills the form (~80% from rules, ~20% from your local LLM)
3. **Pauses** at the captcha (you solve it)
4. **Pauses** at the final Submit button (you click it)
5. Logs the result + a screenshot to `data/artifacts/<job-id>/`

---

## Where things live

```
agent/
├── data/
│   ├── profile.json           # YOU EDIT THIS — your identity, work auth, EEO, targets
│   ├── master-resume.json     # YOU EDIT THIS — the full resume to tailor from
│   ├── jobs.db                # auto-managed — discovered jobs + applications
│   └── company_pools/         # ATS slug pools (greenhouse, lever, ashby, workday)
├── config/
│   ├── .env                   # YOU EDIT THIS — LLM provider, SMTP if you want, etc.
│   ├── resume_rules.json      # per-role tailoring rules (override per profile)
│   └── …
└── backend/                   # services — usually no reason to touch
```

You own all of this. Delete `data/` to factory-reset.

---

## Troubleshooting

### "Ollama not running"
`ollama serve` in another terminal, or run any `ollama run <model>` once
to launch the daemon.

### "Form filled, but the wrong values"
Check what was filled vs your profile:

```bash
python -c "import json; print(json.load(open('data/profile.json')))"
```

Then look at the screenshot in `data/artifacts/<job-id>/` and the
field-decision log next to it.

### "ATS X isn't supported"
Today: **Greenhouse**, **Lever**, **SmartRecruiters**. Workday is in
beta. Ashby and iCIMS are roadmap. File an issue with a sample URL,
or contribute an adapter ([CONTRIBUTING.md](./CONTRIBUTING.md)).

### "Setup wizard recommended a model that's too small / big"
Pass `--detect-only` to see the math. The wizard's budget formula is
`VRAM + (system RAM / 2)` for NVIDIA, full system RAM for Apple
Silicon, system RAM for CPU-only. If you want a different model, just
edit `config/.env` and `ollama pull <model>` manually.

---

## What still needs you

Three things Instaply will never do silently:

1. **Solve captcha** — hCaptcha / reCAPTCHA Enterprise pause for you
2. **Click final Submit** — always your call
3. **Confirm landing** — look for the confirmation page yourself, then mark it done

Everything else runs unattended.
