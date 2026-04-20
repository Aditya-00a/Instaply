"""Browser stealth and anti-bot detection utilities.

Provides human-like browser behavior, fingerprint evasion, and
CAPTCHA handling to avoid bot detection on job application sites.
"""
from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

log = logging.getLogger(__name__)

# ── Realistic User Agents (Chrome 124-130 on Win/Mac) ─────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

# ── Realistic Viewport Sizes ──────────────────────────────────────
_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]


def get_random_ua() -> str:
    """Return a random realistic user agent string."""
    return random.choice(_USER_AGENTS)


def get_random_viewport() -> dict[str, int]:
    """Return a random realistic viewport size."""
    return random.choice(_VIEWPORTS)


async def apply_stealth(context: BrowserContext) -> None:
    """Apply all stealth evasions to a browser context.

    Layers:
    1. playwright-stealth (if installed) — patches navigator, chrome, webdriver
    2. Extra JS patches for edge cases playwright-stealth misses
    """
    # Layer 1: playwright-stealth library
    try:
        from playwright_stealth import Stealth
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
        log.debug("playwright-stealth applied")
    except (ImportError, Exception) as e:
        log.debug("playwright-stealth not available: %s — applying manual patches", e)

    # Layer 2: Additional JS evasions applied to every new page
    _EXTRA_STEALTH_JS = """
    () => {
        // Prevent webdriver detection (backup if stealth didn't cover it)
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

        // Override permissions.query to not reveal automation
        if (navigator.permissions) {
            const origQuery = navigator.permissions.query;
            navigator.permissions.query = (parameters) => {
                if (parameters.name === 'notifications') {
                    return Promise.resolve({ state: Notification.permission });
                }
                return origQuery.call(navigator.permissions, parameters);
            };
        }

        // Make chrome.runtime appear normal (not headless)
        if (!window.chrome) window.chrome = {};
        if (!window.chrome.runtime) {
            window.chrome.runtime = {
                connect: function() {},
                sendMessage: function() {},
            };
        }

        // Override outerHeight/outerWidth to match real browser
        Object.defineProperty(window, 'outerHeight', {
            get: () => window.innerHeight + 85  // toolbar height
        });
        Object.defineProperty(window, 'outerWidth', {
            get: () => window.innerWidth
        });

        // Consistent screen dimensions
        Object.defineProperty(screen, 'availWidth', { get: () => screen.width });
        Object.defineProperty(screen, 'availHeight', { get: () => screen.height - 40 });

        // Patch console.debug (some sites check for automation)
        const origDebug = console.debug;
        console.debug = function(...args) {
            if (args[0] && typeof args[0] === 'string' && args[0].includes('chromium')) return;
            return origDebug.apply(console, args);
        };
    }
    """
    await context.add_init_script(_EXTRA_STEALTH_JS)
    log.debug("Extra stealth JS patches applied")


async def human_delay(page: Page, min_ms: int = 200, max_ms: int = 800) -> None:
    """Wait a random human-like duration between actions."""
    delay = random.randint(min_ms, max_ms)
    await page.wait_for_timeout(delay)


async def human_type(page: Page, selector: str, text: str) -> None:
    """Type text with human-like variable speed.

    Each character has a slightly different delay (40-120ms),
    simulating natural typing rhythm.
    """
    el = page.locator(selector).first
    if await el.count() == 0:
        return
    await el.click()
    await human_delay(page, 100, 300)

    for char in text:
        await page.keyboard.type(char, delay=random.randint(40, 120))

    await human_delay(page, 50, 200)


async def human_click(page: Page, selector: str) -> bool:
    """Click an element with human-like mouse movement.

    Moves to a random point within the element (not dead center)
    with slight delay before and after clicking.
    """
    el = page.locator(selector).first
    if await el.count() == 0 or not await el.is_visible():
        return False

    try:
        box = await el.bounding_box()
        if not box:
            await el.click()
            return True

        # Click at a random point within the element (not exact center)
        x_offset = random.uniform(box["width"] * 0.2, box["width"] * 0.8)
        y_offset = random.uniform(box["height"] * 0.2, box["height"] * 0.8)

        await page.mouse.move(
            box["x"] + x_offset,
            box["y"] + y_offset,
            steps=random.randint(5, 15),  # Smooth movement
        )
        await human_delay(page, 50, 150)
        await page.mouse.click(box["x"] + x_offset, box["y"] + y_offset)
        return True
    except Exception:
        # Fallback to standard click
        await el.click()
        return True


async def human_scroll(page: Page, direction: str = "down", amount: int | None = None) -> None:
    """Scroll the page in a human-like manner with variable speed."""
    if amount is None:
        amount = random.randint(200, 600)

    if direction == "down":
        delta = amount
    else:
        delta = -amount

    # Scroll in small increments to look natural
    steps = random.randint(3, 8)
    per_step = delta // steps

    for _ in range(steps):
        await page.mouse.wheel(0, per_step + random.randint(-20, 20))
        await page.wait_for_timeout(random.randint(30, 80))

    await human_delay(page, 100, 300)


async def detect_and_handle_cloudflare(page: Page) -> bool:
    """Detect and attempt to handle Cloudflare challenges.

    Returns True if a challenge was detected (even if not solved).
    """
    try:
        # Cloudflare "Checking your browser" / "Just a moment..."
        body_text = (await page.text_content("body") or "").lower()
        cf_indicators = [
            "checking your browser",
            "just a moment",
            "attention required",
            "enable javascript and cookies",
            "cf-browser-verification",
            "cloudflare",
        ]

        is_cf = any(ind in body_text for ind in cf_indicators)
        if not is_cf:
            # Also check for Cloudflare turnstile iframe
            turnstile = page.locator("iframe[src*='challenges.cloudflare.com'], [class*='cf-turnstile']")
            is_cf = await turnstile.count() > 0

        if is_cf:
            log.warning("Cloudflare challenge detected — waiting for auto-solve...")
            # Cloudflare JS challenges often auto-solve after a few seconds
            # The stealth patches help pass the JS checks
            for wait in [5000, 5000, 10000]:
                await page.wait_for_timeout(wait)
                new_text = (await page.text_content("body") or "").lower()
                if not any(ind in new_text for ind in cf_indicators[:3]):
                    log.info("Cloudflare challenge appears to have resolved")
                    return True

            # Check for Turnstile checkbox
            turnstile_cb = page.locator("iframe[src*='challenges.cloudflare.com']")
            if await turnstile_cb.count() > 0:
                try:
                    frame = await turnstile_cb.first.content_frame()
                    if frame:
                        checkbox = frame.locator("input[type='checkbox'], [role='checkbox']")
                        if await checkbox.count() > 0:
                            await checkbox.first.click()
                            await page.wait_for_timeout(5000)
                            log.info("Clicked Cloudflare Turnstile checkbox")
                except Exception as e:
                    log.debug("Could not interact with Turnstile: %s", e)

            log.warning("Cloudflare challenge may not have been solved")
            return True

        return False
    except Exception:
        return False


async def detect_and_handle_recaptcha(page: Page) -> bool:
    """Detect reCAPTCHA v2/v3 presence. Cannot solve, but can detect and log.

    Returns True if reCAPTCHA was detected.
    """
    try:
        recaptcha_indicators = [
            "iframe[src*='recaptcha']",
            "iframe[src*='google.com/recaptcha']",
            ".g-recaptcha",
            "[data-sitekey]",
            "#recaptcha",
        ]

        for sel in recaptcha_indicators:
            if await page.locator(sel).count() > 0:
                log.warning("reCAPTCHA detected on page — may need manual intervention")
                # reCAPTCHA v2 invisible/checkbox: try waiting for auto-solve via stealth
                await page.wait_for_timeout(3000)

                # Check if reCAPTCHA has a checkbox iframe we can click
                rc_frame = page.locator("iframe[src*='recaptcha'][title*='reCAPTCHA']")
                if await rc_frame.count() > 0:
                    try:
                        frame = await rc_frame.first.content_frame()
                        if frame:
                            checkbox = frame.locator(".recaptcha-checkbox-border, #recaptcha-anchor")
                            if await checkbox.count() > 0:
                                await checkbox.first.click()
                                log.info("Clicked reCAPTCHA checkbox — waiting for verification...")
                                await page.wait_for_timeout(5000)
                    except Exception as e:
                        log.debug("Could not interact with reCAPTCHA: %s", e)

                return True

        return False
    except Exception:
        return False


async def detect_bot_block(page: Page) -> str | None:
    """Detect common bot-blocking pages. Returns block type or None.

    Block types: 'cloudflare', 'recaptcha', 'rate_limit', 'bot_detected', None
    """
    try:
        body = (await page.text_content("body") or "").lower()

        # Rate limiting
        rate_limit_phrases = [
            "rate limit", "too many requests", "429",
            "slow down", "please try again later",
            "browsing and clicking at a speed much faster",  # SeatGeek
        ]
        if any(phrase in body for phrase in rate_limit_phrases):
            return "rate_limit"

        # Generic bot detection
        bot_phrases = [
            "bot detected", "automated access",
            "suspicious activity", "access denied",
            "please verify you are a human",
            "we detected unusual activity",
            "your request has been blocked",
        ]
        if any(phrase in body for phrase in bot_phrases):
            return "bot_detected"

        # Cloudflare
        cf = await detect_and_handle_cloudflare(page)
        if cf:
            return "cloudflare"

        # reCAPTCHA
        rc = await detect_and_handle_recaptcha(page)
        if rc:
            return "recaptcha"

        return None
    except Exception:
        return None


async def pre_fill_warmup(page: Page) -> None:
    """Simulate brief human browsing behavior before filling a form.

    This helps establish a "normal" behavioral fingerprint on the page
    before rapid form-filling begins.
    """
    try:
        # Small random scroll to show the page was "read"
        await human_scroll(page, "down", random.randint(100, 400))
        await human_delay(page, 500, 1500)

        # Slight upward scroll (natural browsing pattern)
        await human_scroll(page, "up", random.randint(50, 150))
        await human_delay(page, 300, 800)

        # Move mouse to a random visible element (mimics reading)
        try:
            body_box = await page.locator("body").bounding_box()
            if body_box:
                await page.mouse.move(
                    random.uniform(200, min(body_box["width"] - 100, 1200)),
                    random.uniform(200, min(body_box["height"] - 100, 700)),
                    steps=random.randint(8, 20),
                )
        except Exception:
            pass

        await human_delay(page, 200, 600)
    except Exception:
        pass  # Non-critical — just best-effort


async def create_stealth_context(
    pw_browser,
    *,
    headless: bool = True,
) -> BrowserContext:
    """Create a browser context with all stealth measures applied.

    Returns a ready-to-use BrowserContext with:
    - Random realistic user agent
    - Random viewport size
    - Stealth JS patches
    - Proper locale/timezone
    """
    ua = get_random_ua()
    viewport = get_random_viewport()

    context = await pw_browser.new_context(
        viewport=viewport,
        user_agent=ua,
        locale="en-US",
        timezone_id="America/New_York",
        # Realistic screen size (larger than viewport)
        screen={"width": viewport["width"], "height": viewport["height"] + 140},
        color_scheme="light",
        # Don't reveal automation
        java_script_enabled=True,
        has_touch=False,
        is_mobile=False,
    )

    await apply_stealth(context)

    log.debug("Stealth context created: UA=%s..., viewport=%s", ua[:50], viewport)
    return context
