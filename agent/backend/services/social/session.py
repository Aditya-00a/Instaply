"""Shared session management for LinkedIn / Indeed / Glassdoor etc.

Key guarantees:
- Uses the SAME persistent Chrome profile as Scout's main autofill (reuses
  cookies from manual one-time login; no password handling in code).
- Enforces per-platform rate limits (sliding 24h window) persisted to disk.
- Enforces human-like delays between actions.
- Exits early with `SessionBlockedError` if the platform appears to have
  challenged us (CAPTCHA, 2FA, "verify it's you" interstitial).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent.parent
ARTIFACTS = ROOT / "artifacts"
RATE_LIMIT_STATE = ARTIFACTS / "social_rate_limits.json"


class SessionBlockedError(Exception):
    """Raised when a platform appears to have challenged/blocked us."""


@dataclass
class PlatformLimits:
    """Per-platform rate limits — conservative defaults. Tune in config."""
    max_actions_per_day: int = 20
    max_actions_per_hour: int = 5
    min_action_delay_sec: int = 120
    max_action_delay_sec: int = 480

    # What counts as an "action" for rate-limiting
    # (connection request, apply, message, etc.)


DEFAULT_LIMITS = {
    "linkedin_outreach": PlatformLimits(
        max_actions_per_day=20,      # LinkedIn's soft limit is ~100/week
        max_actions_per_hour=3,
        min_action_delay_sec=180,    # 3 min min
        max_action_delay_sec=600,    # 10 min max
    ),
    "linkedin_easy_apply": PlatformLimits(
        max_actions_per_day=15,      # Very conservative
        max_actions_per_hour=3,
        min_action_delay_sec=240,    # 4 min min
        max_action_delay_sec=900,    # 15 min max
    ),
    "indeed_quick_apply": PlatformLimits(
        max_actions_per_day=50,      # Indeed more permissive
        max_actions_per_hour=10,
        min_action_delay_sec=60,
        max_action_delay_sec=180,
    ),
}


# ──────────────────────────────────────────────────────────────────────
# Rate limit tracking (persisted to disk so restarts don't lose state)
# ──────────────────────────────────────────────────────────────────────


def _load_state() -> dict[str, list[str]]:
    if RATE_LIMIT_STATE.exists():
        try:
            return json.loads(RATE_LIMIT_STATE.read_text())
        except Exception:
            return {}
    return {}


def _save_state(state: dict[str, list[str]]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    RATE_LIMIT_STATE.write_text(json.dumps(state, indent=2))


def _prune_window(actions: list[str], window: timedelta) -> list[str]:
    cutoff = datetime.now(timezone.utc) - window
    out = []
    for ts_str in actions:
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts >= cutoff:
                out.append(ts_str)
        except Exception:
            continue
    return out


def can_take_action(platform: str, limits: PlatformLimits | None = None) -> tuple[bool, str]:
    """Returns (allowed, reason). reason is human-readable when blocked."""
    limits = limits or DEFAULT_LIMITS.get(platform, PlatformLimits())
    state = _load_state()
    actions = state.get(platform, [])

    # Prune actions outside 24h window
    day = _prune_window(actions, timedelta(days=1))
    hour = _prune_window(actions, timedelta(hours=1))

    if len(day) >= limits.max_actions_per_day:
        return False, f"daily cap hit ({limits.max_actions_per_day})"
    if len(hour) >= limits.max_actions_per_hour:
        return False, f"hourly cap hit ({limits.max_actions_per_hour})"

    # Enforce min gap since last action
    if day:
        try:
            last_ts = datetime.fromisoformat(day[-1])
            gap = (datetime.now(timezone.utc) - last_ts).total_seconds()
            if gap < limits.min_action_delay_sec:
                return False, f"cooldown {limits.min_action_delay_sec - int(gap)}s remaining"
        except Exception:
            pass

    return True, "ok"


def record_action(platform: str) -> None:
    state = _load_state()
    actions = state.get(platform, [])
    actions.append(datetime.now(timezone.utc).isoformat())
    # Prune very old entries (>7 days) to keep file small
    actions = _prune_window(actions, timedelta(days=7))
    state[platform] = actions
    _save_state(state)


async def human_delay(limits: PlatformLimits) -> None:
    """Sleep for a human-like random duration."""
    sec = random.uniform(limits.min_action_delay_sec, limits.max_action_delay_sec)
    log.info("human_delay sleeping %.1fs", sec)
    await asyncio.sleep(sec)


# ──────────────────────────────────────────────────────────────────────
# Session helpers
# ──────────────────────────────────────────────────────────────────────


async def ensure_logged_in_linkedin(page) -> bool:
    """Return True if the persistent profile has a valid LinkedIn session."""
    try:
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded",
                        timeout=30_000)
        await page.wait_for_timeout(2000)
        url = page.url.lower()
        if "login" in url or "authwall" in url or "checkpoint" in url:
            log.warning("LinkedIn session not active — URL: %s", url)
            return False
        # Feed should have an element we recognize
        has_feed = await page.locator("main, div[role='main'], [data-test-id='feed']").count() > 0
        if not has_feed:
            log.warning("LinkedIn feed not detected — may be logged out or challenged")
            return False
        return True
    except Exception as e:
        log.warning("LinkedIn session check failed: %s", e)
        return False


async def ensure_logged_in_indeed(page) -> bool:
    """Return True if the persistent profile has a valid Indeed session."""
    try:
        await page.goto("https://my.indeed.com/profile", wait_until="domcontentloaded",
                        timeout=30_000)
        await page.wait_for_timeout(2000)
        url = page.url.lower()
        if "account/login" in url or "signin" in url:
            log.warning("Indeed session not active — URL: %s", url)
            return False
        return True
    except Exception as e:
        log.warning("Indeed session check failed: %s", e)
        return False


async def detect_challenge(page, platform: str) -> bool:
    """Returns True if the page appears to be an anti-bot challenge.

    Raises SessionBlockedError-level concern — caller should cool off.
    """
    try:
        body = (await page.text_content("body") or "").lower()
        challenges = [
            "verify it's you", "security verification",
            "unusual activity", "suspicious activity",
            "we've detected", "please verify", "captcha",
            "prove you're human", "i'm not a robot",
            "your account has been restricted",
            "your account is restricted",
        ]
        if any(ch in body for ch in challenges):
            log.warning("%s challenge page detected", platform)
            return True
        url = page.url.lower()
        if "checkpoint" in url or "challenge" in url:
            return True
    except Exception:
        pass
    return False
