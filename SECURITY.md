# Security policy

## Threat model

Instaply runs **entirely on your laptop**. There are no Instaply servers. There is no Instaply account. The privacy story is mostly:

- Your data lives in `~/.instaply/` on your own machine.
- The code that touches your data is in this repo — you can audit every line.
- The only outbound network calls Instaply makes are:
  1. To the **ATS website** (the place you're applying — Greenhouse, Lever, etc.) via Playwright. They see what they would see if you filled the form by hand.
  2. To **your chosen LLM provider** (NIM / Ollama / OpenAI / etc.), with the screening question and relevant profile fields. Pick Ollama if you want this to also be local.
  3. To **Google's Gmail API**, only if you opted in to confirmation-email verification, only with your OAuth token, scoped to read-only.

There is no fourth call. If you find one, that's a bug — please report it.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Email **hello@asion.ai** with:

- A clear description of the issue
- Steps to reproduce
- Your assessment of impact
- Optionally, a suggested fix

I'll respond within 72 hours. For confirmed issues, I'll work on a fix and credit you (with your permission) in the release notes.

## Scope

In scope:
- Anything in this repo that compromises a user's local data, credentials, or applications
- Supply-chain risks (compromised dependencies, malicious tag releases)
- Bugs in the adapters that could leak user data to the wrong destination
- Anything that makes outbound network calls beyond the three described above

Out of scope:
- Issues with third-party services (Gmail, NVIDIA NIM, OpenAI) — report those upstream
- Vulnerabilities in Playwright or other dependencies — please report upstream and let me know via dependabot
- Social-engineering attacks against you the user (we cover practical mitigations in [QUICKSTART.md](QUICKSTART.md))

## Supported versions

Only the latest minor version is supported with security updates. Pre-1.0 we move fast.

## Hardening checklist for users

- Always install from PyPI (`pipx install instaply`), not from a fork or mirror you don't trust
- Verify the GitHub release SHA against your installed version
- Keep dependencies updated (`pipx upgrade instaply`)
- Use OS-level disk encryption — your `~/.instaply/db.sqlite` contains your application history
- Don't share your `~/.instaply/` folder
- For Gmail verification: review the OAuth scope (read-only) before granting

Thanks for helping keep Instaply safe for the students using it.
