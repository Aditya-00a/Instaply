# Instaply Agent (autonomous mode)

This directory holds the **autonomous job-application agent** lifted from
the Revize prototype on 2026-04-19. It runs in the background, discovers
new jobs every cycle, and queues them ready for review — the user never
has to type a command per job.

> **Status:** raw lift, personal info scrubbed (148+ replacements). Not
> yet integrated with the rest of Instaply. Imports `backend.*` modules
> from inside this directory tree, so it runs from `agent/` standalone
> for now. The plan is to thin it into the core package over the next
> few releases.

## Shape

```
agent/
├── run.py              # the persistent loop (discovery + apply)
├── apply_now.py        # single-job worker (called by run.py + manually)
├── find_wd_job.py      # Workday-specific discovery
├── jobspy_search.py    # JobSpy wrapper for LinkedIn / Indeed / etc.
├── backend/            # services the loop depends on
│   ├── services/       # auto_apply, application_pipeline, tailor, etc.
│   ├── db/             # job repository
│   ├── models/         # pydantic schemas
│   ├── prompts/        # LLM prompts
│   └── api/            # (FastAPI surface — optional)
├── config/
│   ├── .env.example    # copy to .env and fill in
│   ├── *.json          # resume / cover-letter design tokens
│   └── openclaw.yaml   # OpenClaw skill manifest
├── data/
│   └── company_pools/  # ATS slug pools (greenhouse / lever / ashby / workday)
└── scripts/
    ├── watchdog.py             # restart loop if it dies
    ├── gmail_tracker.py        # confirmation-email matcher
    ├── setup-scheduler.ps1     # install Windows scheduled task
    ├── manage.ps1              # start/stop/status helpers
    ├── start-agent.ps1         # foreground start
    ├── run-daily-cycle.cmd     # one-shot daily wrapper
    ├── run_watchdog.cmd        # watchdog launcher
    └── health-check.ps1        # poke the runtime
```

## What was scrubbed

The Revize source had personal info baked in. The lift removed:

- The original author's name (full, first, last, snake_case, kebab-case variants)
- University and previous-employer references in comments
- Personal LinkedIn and portfolio URLs
- Personal email addresses and phone numbers
- The original `config/.env` (real SMTP, Apollo, Hunter API keys)
- All `*.bak`, `*.db`, `*.sqlite`, `*.log`, `__pycache__` artefacts
- The entire outreach + people-finder + WhatsApp-review subsystem
  (cold-outreach to hiring managers — outside the autonomous-apply scope)
- Hardcoded EEO defaults (race, gender, veteran/disability status), school
  name, state, and visa status from `autofill.py` — replaced with empty
  values + TODOs so nothing personal auto-fills onto the next user's job
  applications

A few function-internal regex patterns (e.g. `tailor.py`'s name-stripper)
now match `[user]` literally — they need to be re-parametrised against
the active profile before this pipeline can do real tailoring. Marked
TODO inline.

## Running it (local, manual)

```bash
cd agent
cp config/.env.example .env
# fill in API keys + email creds in .env
pip install -r ../mcp/requirements.txt   # or whatever the merged deps file is
python run.py
```

## Running it (Windows scheduler)

```powershell
cd agent\scripts
.\setup-scheduler.ps1     # one-time, installs the scheduled task
.\manage.ps1 status       # see if it's running
.\manage.ps1 stop         # stop it
.\manage.ps1 start        # start it back up
```

## What still needs work (post-lift)

1. **Profile bootstrap.** `run.py` and `apply_now.py` import
   `load_profile()` and `load_master_resume()` from `backend.services.files`
   — those expect `data/profile.json` and `data/master-resume.json` to
   exist. Need a setup wizard that creates them from the user's resume.
2. **Hardcoded company pools.** `run.py` (~5,000 lines) has giant
   hardcoded slug lists. Move to `data/company_pools/*.json` with
   sensible defaults; let users append.
3. **Hardcoded query templates.** The `LINKEDIN_KEYWORDS` /
   `INDEED_KEYWORDS` lists assume a specific job target. Move to a
   config file driven by the profile's role targets.
4. **Tailoring patterns.** `tailor.py` regexes expect `[user]` literally
   after the scrub — make them read the active first/last name from the
   profile.
5. **Storage merge.** Right now `agent/` writes to its own SQLite under
   `data/`. The MCP package writes to `~/.instaply/data.db`. Pick one
   and migrate.

None of these are blockers for landing the lift. They're follow-ups.
