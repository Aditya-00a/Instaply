"""Vendored copy of the Instaply autofill worker (rules engine,
ATS adapters, Playwright executor).

Source of truth: `worker/` at the repo root. This is a snapshot
imported by the MCP package so `uvx instaply-mcp` is self-contained.

Drift policy: re-vendor by copying the source files when the upstream
worker changes. The vendored copy uses relative imports only — no
rewrites needed.
"""
