# Changelog

All notable changes to Instaply will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] — Autonomous-only pivot

The big simplification.

### Added
- **`agent/setup.py`** — cross-platform setup wizard. Detects OS, RAM,
  CPU, GPU + VRAM (NVIDIA / Apple Silicon / AMD). Offers to install
  Ollama via the right channel for the OS (`brew --cask ollama`,
  `winget install Ollama.Ollama`, or `curl ... | sh`). Recommends and
  pulls the right local model based on a memory budget heuristic
  (VRAM + RAM/2 for NVIDIA, full RAM for Apple Silicon). Writes
  `config/.env` with the chosen settings.
- **`agent/`** — the autonomous loop, lifted from the Revize prototype
  and de-personalised. The persistent discovery + score + tailor +
  queue + apply pipeline.
- **`agent/scripts/`** — Windows scheduled-task installer, watchdog
  with auto-restart, daily-cycle wrapper, health-check, manage helper,
  Gmail confirmation tracker.
- **`LAUNCH.md`** — end-to-end launch playbook (GitHub repo polish,
  pre-launch sanity checks, announcement order across HN / Reddit /
  Twitter / LinkedIn / Indie Hackers).
- **Refreshed README, banner, demo, and architecture diagram** for the
  autonomous-first product.

### Changed
- **The product shape.** Instaply is now a single thing: a background
  agent that applies to jobs while you sleep. One install path
  (`git clone` → `python setup.py`), one mental model.

### Removed
- **`mcp/`** — the entire MCP server package. The Anthropic-specific
  integration was a clever distribution hack but it complicated the
  story (two install paths, two narratives) and the autonomous mode is
  what people actually need. Quietly retired.
- **`.github/workflows/publish-mcp.yml`** — the auto-publish pipeline.
- **The hosted `instaply.mcpb` bundle** at `instaply.asion.ai/instaply.mcpb`.
- All references to MCP / Claude Desktop / Cursor / Codex / Windsurf /
  Zed in the README, QUICKSTART, banner, demo, and architecture diagram.

### Fixed
- A bunch of personal-info defaults that the original Revize source had
  baked into `agent/backend/services/autofill.py` (race, gender,
  pronouns, school, GPA, visa status, salary expectations, employer
  names, project names, portfolio URL, LinkedIn handle, full-resume
  paragraphs in LLM prompts) — all replaced with empty strings + TODO
  markers so nothing auto-submits one user's data onto another's
  applications.

---

## [0.4.x] — MCP era (deprecated)

This range of versions shipped the `instaply-mcp` package on PyPI and
the `instaply.mcpb` bundle for Claude Desktop. The package is no longer
published or maintained as of v0.5.0 — see "Removed" above.

---

## [0.1.0] — Initial public release

### Added
- Repo went public as MIT-licensed open source.
- Story landing at [instaply.asion.ai](https://instaply.asion.ai).
- Pivoted from hosted SaaS to local-first OSS — runs entirely on the user's machine.
- ATS adapters: Greenhouse, Lever, SmartRecruiters.
- Autofill rule engine with 30+ deterministic field rules.
- LLM provider choice at setup: NVIDIA NIM, Ollama, OpenAI, or any OpenAI-compatible endpoint.
- Local SQLite store.
- Optional Gmail OAuth integration for confirmation-email verification.

### Removed
- Hosted FastAPI service.
- Supabase multi-tenant schema.
- Paddle billing + credit ledger.
- All payment / subscription infrastructure.
- Anti-abuse system (signup fingerprints, email allowlists, etc.).

---

## Notes

Prior to v0.1.0, Instaply was a private SaaS prototype. The changelog
starts from the public OSS release.
