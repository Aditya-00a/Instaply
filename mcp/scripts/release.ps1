# Release helper — bump version + tag + push, which triggers
# .github/workflows/publish-mcp.yml to do the actual PyPI + GitHub
# Release publish.
#
# Usage:
#   .\scripts\release.ps1 0.4.3
#
# What this does:
#   1. Updates version in mcp/pyproject.toml AND mcp/instaply_mcp/__init__.py
#   2. Updates manifest.json version (so the .mcpb bundle metadata matches)
#   3. Commits the bump
#   4. Tags v<new-version>
#   5. Pushes both commit + tag — GitHub Actions takes over from there
#
# After this runs, in ~2-3 minutes:
#   - PyPI has the new version (uvx + pip pull it on next call)
#   - GitHub Release exists with the .mcpb attached
#   - The hosted .mcpb at instaply.asion.ai is a separate Vercel deploy
#     (run `npx vercel --prod` after copying mcp/dist/instaply.mcpb to
#     apps/web/public/) — that step is NOT yet automated; if you want it
#     to be, add a vercel deploy hook or extend the GitHub workflow.

param(
    [Parameter(Mandatory=$true)]
    [string]$Version
)

$ErrorActionPreference = 'Stop'

# Validate version looks like semver
if ($Version -notmatch '^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$') {
    Write-Error "Version must look like 0.4.3 or 1.0.0-rc1 (got: $Version)"
    exit 1
}

$root = Split-Path -Parent $PSScriptRoot   # …\mcp
Push-Location $root

try {
    # 1. pyproject.toml
    $pp = Get-Content 'pyproject.toml' -Raw
    $pp = $pp -replace '(?m)^(version\s*=\s*)"[^"]+"', "`$1`"$Version`""
    Set-Content 'pyproject.toml' $pp -NoNewline -Encoding utf8
    Write-Host "  pyproject.toml -> $Version" -ForegroundColor Green

    # 2. instaply_mcp/__init__.py
    $init = Get-Content 'instaply_mcp/__init__.py' -Raw
    $init = $init -replace '(?m)^(__version__\s*=\s*)"[^"]+"', "`$1`"$Version`""
    Set-Content 'instaply_mcp/__init__.py' $init -NoNewline -Encoding utf8
    Write-Host "  __init__.py    -> $Version" -ForegroundColor Green

    # 3. manifest.json
    $mfPath = 'manifest.json'
    $mf = Get-Content $mfPath -Raw | ConvertFrom-Json
    $mf.version = $Version
    ($mf | ConvertTo-Json -Depth 100) | Set-Content $mfPath -Encoding utf8
    Write-Host "  manifest.json  -> $Version" -ForegroundColor Green

    # 4. Commit + tag
    git add pyproject.toml instaply_mcp/__init__.py manifest.json
    git commit -m "Release v$Version"
    git tag "v$Version"

    # 5. Push (triggers GitHub Actions)
    Write-Host "`nReady to push. Run:" -ForegroundColor Yellow
    Write-Host "  git push && git push --tags" -ForegroundColor Cyan
    Write-Host "`nGitHub Actions will then:" -ForegroundColor Yellow
    Write-Host "  - publish v$Version to PyPI" -ForegroundColor White
    Write-Host "  - create a GitHub Release with the .mcpb attached" -ForegroundColor White
    Write-Host "  - users on uvx/pip get the new version on their next call" -ForegroundColor White
}
finally {
    Pop-Location
}
