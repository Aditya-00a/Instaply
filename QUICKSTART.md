# Quickstart

Get Instaply applying to jobs while you sleep, in about 5 commands.

> **TL;DR:** clone the repo, run the four wizards (`setup.py`, `setup.py profile`, `setup.py doctor`, `run.py`), then install the scheduler. Done.

---

## 1. Clone the repo

```bash
git clone https://github.com/Aditya-00a/Instaply
cd Instaply/agent
```

You need **Python 3.10 or newer**. Check with `python --version`.

If you don't have it: [python.org](https://python.org) (Windows / macOS) or `sudo apt install python3.12` (Ubuntu / Debian).

---

## 2. Hardware + LLM wizard

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

---

## 3. Profile wizard

```bash
python setup.py profile --resume ~/Desktop/your-cv.pdf
```

Walks ~15 questions and writes both `data/profile.json` (identity / work auth / target roles / EEO) and `data/master-resume.json` (the source of truth for resume tailoring).

Pass `--resume <path>` (PDF / DOCX / TXT) to autopopulate fields from your resume — name, email, phone, school, degree, skills, role targets all show up as green defaults you just press Enter to accept.

| Flag | Effect |
|---|---|
| `--resume <path>` | Parse a resume and pre-fill what we can detect |
| `--yes` / `-y` | Accept all defaults where possible |
| `--force` | Overwrite an existing `profile.json` without asking |

Skip `--resume` for fully manual entry if you don't have a current resume PDF.

---

## 4. Sanity check

```bash
python setup.py doctor
```

Runs 10 pass/fail checks and tells you exactly what to fix:

```
✓ Python ≥ 3.10                           running 3.12.4
✓ Python dependencies installed           playwright, httpx, pydantic, bs4, lxml
✓ config/.env exists                      config/.env
✓ Ollama reachable (http://localhost:11434)  HTTP 200
✓ Model `llama3.1:8b` pulled              available as: llama3.1:8b
✓ Playwright Chromium installed           ready
✓ data/ directory writable                data
✓ SQLite writable (data/jobs.db)
✓ data/profile.json valid                 Jane Smith · 3 target roles
✓ data/master-resume.json valid           14 skills · 1 education entries

  All 10 checks passed. The agent should run.
```

If any check fails, you get the one-line fix command. `--json` mode for CI / scripted use.

---

## 5. Install dependencies (once)

If `doctor` reports missing deps:

```bash
pip install playwright httpx pydantic python-dotenv beautifulsoup4 lxml requests psutil openai sqlite-utils tenacity
python -m playwright install chromium
```

The Chromium download is ~150 MB, downloaded once, reused forever.

---

## 6. Run it

### Foreground (recommended for the first run)

```bash
python run.py
```

You'll see the loop tick: discover → score → tailor → queue. The first cycle takes a few minutes (cold ATS pool scans). Subsequent cycles are incremental.

### Background — macOS / Linux

```bash
bash scripts/setup-scheduler.sh
```

That auto-detects your OS:
- **macOS** → writes a launchd LaunchAgent at `~/Library/LaunchAgents/ai.instaply.agent.plist` and loads it. KeepAlive on crash, restart every 30 min.
- **Linux** → adds a `*/30 * * * *` crontab entry (tagged so it can be cleanly removed).

Manage it with:
```bash
bash scripts/setup-scheduler.sh status        # is it installed + running?
bash scripts/setup-scheduler.sh stop          # stop the running process
bash scripts/setup-scheduler.sh start         # start it (foreground daemon)
bash scripts/setup-scheduler.sh remove        # uninstall the schedule
```

### Background — Windows

```powershell
.\scripts\setup-scheduler.ps1
```

Manage with `.\scripts\manage.ps1 status` / `stop` / `start`.

---

## 7. Review the queue

The agent **never silently submits**. It drafts applications into a queue at `~/.instaply/data.db` (status: `packet_generated`). When you're ready, run:

```bash
python apply_now.py             # walks the queue interactively
```

For each draft:
1. Opens your real Chrome (visible, not headless)
2. Autofills the form (~80% from rules, ~20% from your local LLM)
3. **Browser stays open** when human action is needed (captcha, final Submit, etc.)
4. The terminal prints `>>> Browser staying open. Press Enter when done.`
5. You solve the captcha, click Submit, then hit Enter in the terminal
6. The browser closes and the result + screenshot land in `data/artifacts/<job-id>/`

For unattended scheduled runs that should never block, set `INSTAPLY_AUTO_CLOSE=1` in `config/.env` — the browser then closes immediately after autofill and the draft stays in `ready_for_review` status for later manual completion.

---

## Where things live

```
agent/
├── setup.py                   # ← runs the LLM wizard, profile wizard, doctor
├── profile_wizard.py          # the profile Q&A
├── doctor.py                  # the health check
├── resume_parser.py           # PDF/DOCX → structured profile
├── run.py                     # the persistent loop
├── apply_now.py               # interactive queue walker
├── data/
│   ├── profile.json           # written by `setup.py profile`
│   ├── master-resume.json     # written by `setup.py profile`
│   ├── jobs.db                # auto-managed — discovered jobs + queue
│   └── company_pools/         # ATS slug pools (greenhouse / lever / ashby / workday)
├── config/
│   ├── .env                   # written by `setup.py`
│   ├── resume_rules.json      # per-role tailoring rules
│   └── …
├── backend/                   # services — usually no reason to touch
└── scripts/
    ├── setup-scheduler.sh     # macOS / Linux installer
    ├── setup-scheduler.ps1    # Windows installer
    ├── manage.ps1             # Windows start/stop helpers
    ├── watchdog.py            # auto-restart on crash
    └── …
```

You own all of this. Delete `data/` to factory-reset.

---

## Troubleshooting

### "Ollama not running"
`ollama serve` in another terminal, or run any `ollama run <model>` once to launch the daemon. `python setup.py doctor` will tell you specifically.

### "Form filled, but the wrong values"
Look at the screenshot in `data/artifacts/<job-id>/` and the field-decision log next to it. Then check what's in your profile:

```bash
python -c "import json; print(json.dumps(json.load(open('data/profile.json')), indent=2))"
```

If a value is wrong, re-run `python setup.py profile --force` to redo the wizard.

### "ATS X isn't supported"
Today: **Greenhouse**, **Lever**, **SmartRecruiters**. Workday is in beta. Ashby and iCIMS are roadmap. File an issue with a sample URL, or contribute an adapter ([CONTRIBUTING.md](./CONTRIBUTING.md)).

### "Setup wizard recommended a model that's too small / big"
Pass `--detect-only` to see the math. The wizard's budget formula is `VRAM + (system RAM / 2)` for NVIDIA, full system RAM for Apple Silicon, system RAM for CPU-only. If you want a different model, just edit `config/.env` and `ollama pull <model>` manually.

### "Discovery cycle is slow / silent"
By default `CAREER_DISCOVERY_ENABLED=false` (skips the slow web-scraping step that probes corporate sites). Set it to `true` in `config/.env` only if you want to grow your slug pool beyond the 16k+ already shipped.

---

## What still needs you

Three things Instaply will never do silently:

1. **Solve captcha** — hCaptcha / reCAPTCHA Enterprise pause for you
2. **Click final Submit** — always your call
3. **Confirm landing** — look for the confirmation page yourself, then mark it done

Everything else runs unattended.
