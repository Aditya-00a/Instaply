"""Instaply worker — autofill + submit + verify pipeline.

Single package, two runtimes:
  - cloud:   imported by Fly background worker
  - desktop: bundled into Tauri sidecar via PyInstaller

Nothing in this package should depend on where it runs.
Runtime-specific concerns (filesystem paths, auth token source) live in runtime.py.
"""
__version__ = "0.1.0"
