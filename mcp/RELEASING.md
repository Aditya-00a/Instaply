# Releasing Instaply MCP

Automated end-to-end. After the one-time setup below, every release is
**three commands**.

## One-time setup

### Step 1: Configure PyPI Trusted Publishing

This avoids storing a PyPI token in GitHub secrets (more secure, less
to rotate).

1. Go to https://pypi.org/manage/project/instaply-mcp/settings/publishing/
2. Click **Add a new publisher**
3. Fill in:
   - **Publisher:** GitHub
   - **Owner:** `Aditya-00a`
   - **Repository name:** `Instaply`
   - **Workflow name:** `publish-mcp.yml`
   - **Environment name:** `pypi`
4. Click Add

After this, the GitHub Actions workflow can publish without any token.

### Step 2: Create the GitHub Environment

1. Go to https://github.com/Aditya-00a/Instaply/settings/environments
2. Click **New environment** → name it `pypi`
3. Optional: add a required reviewer if you want a manual approval gate
   before each PyPI publish.

That's it for setup. Done once, never again.

## Every release: three commands

```powershell
cd C:\Ravendise\Instaply\mcp
.\scripts\release.ps1 0.4.3      # bumps version files + commits + tags
git push && git push --tags      # triggers the workflow
```

Within ~2-3 minutes, GitHub Actions:

1. Builds the wheel + sdist + `.mcpb` bundle
2. Publishes the wheel/sdist to PyPI
3. Creates a GitHub Release with the `.mcpb` attached at a stable URL:
   `https://github.com/Aditya-00a/Instaply/releases/download/v0.4.3/instaply.mcpb`

Anyone using `uvx instaply-mcp` or `pip install instaply-mcp --upgrade`
gets the new version automatically on their next call.

## What still needs a manual step

**Refreshing `instaply.asion.ai/instaply.mcpb`** is not yet automated.
After a release lands, run:

```powershell
cd C:\Ravendise\Instaply
copy mcp\dist\instaply.mcpb apps\web\public\instaply.mcpb
copy mcp\dist\instaply_mcp-*.whl apps\web\public\
npx vercel --prod --yes --token=$env:VERCEL_TOKEN
```

Or skip Vercel entirely and link to the GitHub Release URL — that one
is always-current and zero-maintenance.

## Auto-update on the user side

Users get new versions automatically depending on how they installed:

| Install method | Update behavior |
|---|---|
| `uvx instaply-mcp` | Pulls latest on each invocation (uvx caches but refreshes) |
| `pip install instaply-mcp` | Manual: `pip install --upgrade instaply-mcp` |
| `.mcpb` from website | Manual re-download. Future Claude Desktop versions may add MCP-bundle auto-update — TBD by Anthropic. |
| `.mcpb` from GitHub Release URL | Same — manual re-download. |

The `uvx` path is the most "set it and forget it" for end users.
