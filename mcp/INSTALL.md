# Install Instaply

Instaply supports:

1. Claude Desktop via `.mcpb`
2. Claude Code via stdio command
3. Any local MCP client that can run `uvx instaply-mcp` or `python -m instaply_mcp`

## Requirements

- Python 3.10+
- A local MCP client

No Instaply account is required for the MCP flow.

## Claude Code

```bash
claude mcp add instaply -- uvx instaply-mcp
```

Then restart the Claude Code session and verify:

```bash
claude mcp list
```

## Claude Desktop

Either:

1. double-click `instaply.mcpb`, or
2. configure it manually:

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

Restart Claude Desktop fully after install.

## First-time workflow

A good first conversation is:

1. `Import my resume into Instaply from /absolute/path/to/resume.pdf`
2. `Update my Instaply profile: I'm based in New York and my preferred titles are Data Analyst, Risk Analyst`
3. `Find jobs for me based on my resume`
4. `Apply me to the best Greenhouse or Lever option`

If the user wants browser automation on the same machine, install the worker
extra once:

```bash
pip install "instaply-mcp[worker]"
python -m playwright install chromium
```

If the user wants broader search coverage through JobSpy:

```bash
pip install "instaply-mcp[search]"
```

## Troubleshooting

**The tools do not appear**
- Restart the client fully.
- Re-run `claude mcp list` in Claude Code.

**Resume import says it cannot read the file**
- Use an absolute file path.
- PDF, DOCX, TXT, and raw text are supported.

**Search works but browser fill does not**
- Install the worker extra and Playwright Chromium.

**The browser filled the form but did not submit**
- That is expected. Instaply leaves captcha and final submit to the user.
