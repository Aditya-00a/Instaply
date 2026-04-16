# Instaply MCP Server

Use Instaply directly inside Claude Desktop.

## Install

```bash
uvx instaply-mcp   # verifies the package runs
```

Or from source during development:

```bash
cd mcp
pip install -e .
```

## Configure Claude Desktop

1. Open your dashboard at **https://instaply.asion.ai/settings/mcp** and copy your MCP token.
2. Open Claude Desktop's config file:
   - **macOS / Linux**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
3. Add the `instaply` server block (merge with any existing `mcpServers`):

```json
{
  "mcpServers": {
    "instaply": {
      "command": "uvx",
      "args": ["instaply-mcp"],
      "env": {
        "INSTAPLY_TOKEN": "PASTE_YOUR_TOKEN_HERE"
      }
    }
  }
}
```

4. Quit and relaunch Claude Desktop.

## What you can do

Once connected, Claude has five tools:

| Tool | What it does |
|---|---|
| `search_jobs` | Search Instaply's catalog by title + location |
| `queue_application` | Queue an application (consumes one credit on confirmed submit) |
| `list_applications` | View your application history and status |
| `get_credits` | Check credit balance and plan |
| `update_profile` | Edit your profile (work authorization, links, preferences) |

## Example conversations

> Find me senior Python roles in NYC that don't require sponsorship, then queue applications to the top five.

> What's my application status from today? Any failures?

> I have 3 credits left and 10 Greenhouse postings queued — which five are the strongest fit?

## Billing

- **3 free applications** on signup. No credit card required.
- Beyond that, **USD 1 per application** (charged only when submission is confirmed via email).
- Minimum top-up **$10**. Bonus tiers: 30 credits for $25, 70 credits for $50.
- Manage billing at **https://instaply.asion.ai/billing**.

## Privacy

Your MCP token is stored only in your local Claude Desktop config. The server runs locally on your machine and calls our API over HTTPS. It never touches third-party LLMs directly — all reasoning happens inside Claude itself.

See **https://instaply.asion.ai/legal/privacy** for the full Privacy Policy.

## Support

Email **support@asion.ai** or open an issue at **https://github.com/ravendise/instaply-mcp/issues**.
