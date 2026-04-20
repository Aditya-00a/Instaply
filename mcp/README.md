# Instaply MCP

[![PyPI](https://img.shields.io/pypi/v/instaply-mcp?color=a78bfa)](https://pypi.org/project/instaply-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)

Local-first, captcha-safe job applications inside Claude Desktop, Claude Code,
Cursor, Codex CLI, Windsurf, Zed, and any other local MCP client.

Everything that matters lives on the user's machine:

- profile
- saved screening answers
- job cache
- application history
- the browser session itself

Stored at `~/.instaply/data.db`. **No Instaply backend is in the loop.**

---

## Why this shape

- **No captcha walls.** The browser runs from the user's residential IP, with their cookies. Datacenter IPs trip hCaptcha / reCAPTCHA Enterprise within seconds — local doesn't.
- **No hosted maintenance.** No accounts, no auth, no servers, no PII flowing through me.
- **No vendor lock-in.** Every MCP-compatible client gets the same tools.
- **Resume drives the rest.** One `import_resume` call seeds profile, skills, and search queries.

---

## Install

### Claude Desktop (one click)

[Download `instaply.mcpb`](https://instaply.asion.ai/instaply.mcpb) → double-click → done.

### Claude Code

```bash
claude mcp add instaply -- uvx instaply-mcp
```

### Cursor / Windsurf / Zed / Codex CLI / generic

```json
{
  "mcpServers": {
    "instaply": {
      "command": "uvx",
      "args": ["instaply-mcp"]
    }
  }
}
```

### Plain Python fallback

```bash
pip install instaply-mcp
python -m instaply_mcp
```

---

## Quick start

Once Instaply shows up in your client's tool list, just talk:

1. `Import my resume from /absolute/path/to/resume.pdf`
2. `Find jobs for me based on my resume`
3. `Apply to the best Greenhouse or Lever match`
4. (Solve captcha + click Submit on the page that opens.)
5. `That one is submitted`

The intended flow:

- `import_resume` reads PDF, DOCX, TXT, or raw pasted resume text
- `apply_chat_update` lets the user say "update …" in chat and have Instaply persist the change
- `search_jobs` derives likely role targets from the imported resume/profile if no query is given
- `apply_to_job` opens the local browser, fills what it can, and pauses for captcha + Submit
- `mark_complete` closes the loop

---

## Tools (v0.4.2)

| Tool | What it does |
|---|---|
| `import_resume(resume_path? or resume_text?)` | Extract grounded profile, skills, titles, and role targets from a resume and save locally. |
| `apply_chat_update(message)` | Parse a chat-style update and persist it. Good for profile edits, saved answers, or marking an application done. |
| `update_profile(patch)` | Sparse update of profile fields. |
| `get_profile()` | Read the local Instaply profile. |
| `search_jobs(query?, location?, remote?, limit?)` | Search public job sources. If `query` is omitted, derive it from the imported resume/profile. |
| `save_answer(question, answer)` | Save a screening answer for reuse. |
| `list_answers(limit?)` | Review saved answers. |
| `delete_answer(answer_id)` | Forget a saved answer. |
| `list_applications(status?, limit?)` | Read the local application audit trail. |
| `get_status()` | Counts by status, plus cached jobs and saved answers. |
| `apply_to_job(apply_url, ...)` | Open the application page locally and fill the form. Pauses for captcha + Submit. |
| `mark_complete(application_id)` | Mark an application submitted after confirmation is visible. |

---

## Optional extras

Base install works for profile, resume parsing, and search via public sources.

For local browser automation (the `apply_to_job` tool):

```bash
pip install "instaply-mcp[worker]"
python -m playwright install chromium
```

For broader search coverage via JobSpy:

```bash
pip install "instaply-mcp[search]"
```

For both:

```bash
pip install "instaply-mcp[worker,search]"
python -m playwright install chromium
```

`search_jobs` still works without JobSpy — the extra just widens the source set.

The `.mcpb` bundle ships with `[worker]` already included.

---

## Storage

Default:

```text
~/.instaply/data.db
```

Override with:

```bash
export INSTAPLY_DATA_DIR=/path/you/prefer
```

Delete the folder to factory-reset.

---

## What still isn't automatic

- Captcha solving (hCaptcha / reCAPTCHA Enterprise)
- The final Submit click
- Perfect resume parsing for every weird layout
- Confirmation-email matching (planned: Gmail OAuth)

This package is designed to **reduce** the work sharply, not pretend those pieces don't exist.

---

## Releasing (maintainers)

```powershell
cd mcp
.\scripts\release.ps1 0.4.3      # bumps version + commits + tags
git push && git push --tags      # GitHub Actions takes over
```

Within ~3 minutes, GitHub Actions:
1. Builds the wheel + sdist + `.mcpb` bundle
2. Publishes to PyPI via Trusted Publishing (no token)
3. Creates a GitHub Release with the `.mcpb` attached

Full doc: [`RELEASING.md`](./RELEASING.md).

---

## License

MIT. See [LICENSE](../LICENSE).
