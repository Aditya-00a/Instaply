# Quickstart

Get Instaply running inside Claude (or any MCP client) in about 2 minutes.

> **TL;DR for Claude Desktop users:** [download `instaply.mcpb`](https://instaply.asion.ai/instaply.mcpb), double-click, you're done. The rest of this doc is for everyone else.

---

## 1. Pick your client

Instaply is an **MCP server**. It plugs into any local MCP-aware app:

| Client | Install method |
|---|---|
| **Claude Desktop** | Download [`instaply.mcpb`](https://instaply.asion.ai/instaply.mcpb), double-click |
| **Claude Code** | `claude mcp add instaply -- uvx instaply-mcp` |
| **Cursor / Windsurf / Zed / Codex CLI** | Add the JSON snippet below to that app's MCP config |
| **Anything else MCP-compatible** | Same JSON snippet |

It does **not** work in Claude.ai web, ChatGPT.com, or Codex Cloud — those run in sandboxes that can't open a real browser. Instaply needs your local Chrome.

---

## 2. Manual MCP config (for clients without a one-click install)

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

`uvx` comes with [uv](https://github.com/astral-sh/uv) — install it once with:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then `uvx instaply-mcp` will auto-fetch the latest version on every launch.

### Plain pip (alternative)

```bash
pip install instaply-mcp
```

Then point your client at `python -m instaply_mcp` instead of `uvx instaply-mcp`.

---

## 3. Add the browser (one-time, ~150 MB)

For the `apply_to_job` tool to actually open a browser, you need Playwright's Chromium:

```bash
pip install "instaply-mcp[worker]"
python -m playwright install chromium
```

The `.mcpb` bundle ships these already — skip this step if you installed via Claude Desktop.

---

## 4. First chat

Open Claude (Desktop / Code / wherever), make sure Instaply shows up in the tools list, and just talk:

```
You: Import my resume from ~/Desktop/cv.pdf
Claude: ✓ Imported. Saved 12 skills, inferred role targets:
        Data Analyst, Risk Analyst, Quantitative Analyst.

You: Find me 5 entry-level data analyst roles, US, no sponsorship needed
Claude: Found 5. Here they are…

You: Apply to #2
Claude: Opening Chrome on your machine. Filled 14 fields from your
        profile, paused at the captcha. Solve it + click Submit, then
        say "done".

You: done
Claude: ✓ Logged. Application #7. status=submitted.
```

That's the whole product loop.

---

## 5. (Optional) Save a screening answer once, reuse it forever

```
You: When asked "Why do you want to work here?", save this answer:
     "I'm drawn to roles where rigorous data work directly shapes risk decisions…"
Claude: Saved.
```

Next time any ATS asks that exact question (or a close paraphrase — we hash-normalize), Instaply auto-fills the saved answer.

```
You: Show me what answers you've saved
Claude: 4 answers cached. (lists them)
```

---

## 6. Where your data lives

```
~/.instaply/
└── data.db    # profile, applications, saved answers, job cache
```

That's it. One SQLite file. Delete the folder to factory-reset.

Override the location with:

```bash
export INSTAPLY_DATA_DIR=/path/you/prefer
```

---

## Troubleshooting

### "instaply" doesn't appear in Claude's tool list

- **Claude Desktop:** Quit fully (Cmd-Q on Mac, right-click tray icon → Quit on Windows) and relaunch.
- **Claude Code:** Run `claude mcp list` — does Instaply show "✓ Connected"? If not, `claude mcp remove instaply` and re-add.
- **Other clients:** Check the client's MCP log — usually it says exactly what failed.

### "Browser not found" when calling `apply_to_job`

```bash
pip install "instaply-mcp[worker]"
python -m playwright install chromium
```

The `.mcpb` bundle ships these already. If you installed via `pip` or `uvx` you have to do this once.

### Form filled, but the wrong values

Ask Claude to show you the field decisions:

```
You: That last apply — show me what you filled where
```

It can read from `~/.instaply/data.db` and walk you through it. Update your profile or saved answers and re-run.

### A specific ATS isn't supported

Currently supported: **Greenhouse**, **Lever**, **SmartRecruiters**. Workday/Ashby/iCIMS are on the roadmap. File an issue with a sample URL — or contribute an adapter, see [CONTRIBUTING.md](./CONTRIBUTING.md).

---

## Updating

| How you installed | How to update |
|---|---|
| `uvx instaply-mcp` | Automatic — pulls the latest on each launch |
| `pip install instaply-mcp` | `pip install --upgrade instaply-mcp` |
| `.mcpb` bundle | Re-download from [instaply.asion.ai/instaply.mcpb](https://instaply.asion.ai/instaply.mcpb) |
| GitHub Release `.mcpb` | Re-download from [latest release](https://github.com/Aditya-00a/Instaply/releases/latest) |

---

## What still needs you

Three things Instaply will never do silently:

1. **Solve captcha** — hCaptcha / reCAPTCHA pause for you
2. **Click Submit** — always your final call
3. **Confirm landing** — look for the confirmation page yourself, then tell Claude "done"

Everything else is automated.
