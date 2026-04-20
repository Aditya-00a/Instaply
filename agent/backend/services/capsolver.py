"""CapSolver integration for solving reCAPTCHA v2/v3 on job application forms.

Usage:
    token = await solve_recaptcha(page)
    if token:
        # Token injected into page, submit should now work
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from playwright.async_api import Page

log = logging.getLogger(__name__)

CAPSOLVER_API_KEY = os.getenv(
    "CAPSOLVER_API_KEY",
    "CAP-FE3471CF946A9D8B738BD7BEDFDC6DC96EFB6A3C9C5F05CADCECD43BF7CE0FB3",
)
CAPSOLVER_API = "https://api.capsolver.com"

_MAX_POLL = 60  # seconds to wait for solution
_LOW_BALANCE_THRESHOLD = 0.50  # warn when balance drops below this


async def check_balance() -> float | None:
    """Check CapSolver account balance. Returns balance or None on error."""
    if not CAPSOLVER_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{CAPSOLVER_API}/getBalance",
                json={"clientKey": CAPSOLVER_API_KEY},
            )
            data = resp.json()
            if data.get("errorId", 0) != 0:
                log.warning("CapSolver balance check error: %s", data.get("errorDescription"))
                return None
            balance = data.get("balance", 0.0)
            log.info("CapSolver balance: $%.4f", balance)
            if balance < _LOW_BALANCE_THRESHOLD:
                log.warning("⚠️  CapSolver balance LOW: $%.4f — credits running out!", balance)
            return balance
    except Exception as e:
        log.warning("CapSolver balance check failed: %s", e)
        return None


async def _extract_sitekey(page: Page) -> tuple[str, str, bool]:
    """Extract reCAPTCHA sitekey, version, and invisibility from the page.

    Returns (sitekey, version, is_invisible) where version is 'v2' or 'v3'.
    """
    # Try data-sitekey attribute first (most common)
    info = await page.evaluate("""() => {
        // Check .g-recaptcha div
        const el = document.querySelector('.g-recaptcha[data-sitekey]');
        if (el) {
            const sitekey = el.getAttribute('data-sitekey');
            const size = el.getAttribute('data-size');
            const isInvisible = size === 'invisible';
            // Detect v3: grecaptcha.execute exists or render param in script src
            let isV3 = false;
            try {
                isV3 = typeof grecaptcha !== 'undefined' && typeof grecaptcha.execute === 'function';
            } catch(e) {}
            if (isInvisible && !isV3) {
                // Could be invisible v2 (common on Greenhouse, Lever, etc.)
            }
            return { sitekey, isV3: isV3 || false, isInvisible };
        }
        // Check any element with data-sitekey
        const any = document.querySelector('[data-sitekey]');
        if (any) {
            const sitekey = any.getAttribute('data-sitekey');
            const size = any.getAttribute('data-size');
            return { sitekey, isV3: false, isInvisible: size === 'invisible' };
        }
        return null;
    }""")

    if info and info.get("sitekey"):
        sitekey = info["sitekey"]
        is_v3 = info.get("isV3", False)
        is_invisible = info.get("isInvisible", False)
        if is_v3:
            return sitekey, "v3", True  # v3 is always invisible
        return sitekey, "v2", is_invisible

    # Try extracting from iframe src
    iframe_info = await page.evaluate("""() => {
        const frames = document.querySelectorAll('iframe[src*="recaptcha"]');
        for (const f of frames) {
            const match = f.src.match(/[?&]k=([^&]+)/);
            if (match) {
                // Check if it's an invisible iframe (size=invisible in URL or no visible checkbox)
                const isInvisible = f.src.includes('size=invisible')
                    || f.style.display === 'none'
                    || f.offsetHeight === 0
                    || f.offsetWidth === 0;
                return { sitekey: match[1], isInvisible };
            }
        }
        return null;
    }""")

    if iframe_info and iframe_info.get("sitekey"):
        return iframe_info["sitekey"], "v2", iframe_info.get("isInvisible", True)

    # Try extracting from script tags (grecaptcha.render calls)
    sitekey = await page.evaluate("""() => {
        const scripts = document.querySelectorAll('script');
        for (const s of scripts) {
            const text = s.textContent || s.innerText || '';
            const match = text.match(/sitekey['":\\s]+['"]([A-Za-z0-9_-]{40})['"]/);
            if (match) return match[1];
            const render = text.match(/render['":\\s]+['"]([A-Za-z0-9_-]{40})['"]/);
            if (render) return render[1];
        }
        // Check for recaptcha script src with render parameter
        const recaptchaScript = document.querySelector('script[src*="recaptcha"]');
        if (recaptchaScript) {
            const match = recaptchaScript.src.match(/render=([A-Za-z0-9_-]{40})/);
            if (match) return match[1];
        }
        return '';
    }""")

    if sitekey:
        return sitekey, "v3", True  # Script-embedded sitekeys are typically v3
    return "", "v2", True  # Default to invisible for job application forms


async def _create_task(sitekey: str, page_url: str, version: str, is_invisible: bool = True) -> str | None:
    """Create a CapSolver task and return the task ID."""
    if not CAPSOLVER_API_KEY:
        log.warning("No CapSolver API key configured")
        return None

    if version == "v3":
        task_type = "ReCaptchaV3TaskProxyLess"
        task = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": sitekey,
            "pageAction": "submit",
        }
    else:
        task_type = "ReCaptchaV2TaskProxyLess"
        task = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": sitekey,
            "isInvisible": is_invisible,
        }

    payload = {
        "clientKey": CAPSOLVER_API_KEY,
        "task": task,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{CAPSOLVER_API}/createTask", json=payload)
            data = resp.json()

            if data.get("errorId", 0) != 0:
                log.warning("CapSolver createTask error: %s — %s",
                           data.get("errorCode"), data.get("errorDescription"))
                return None

            task_id = data.get("taskId")
            log.info("CapSolver task created: %s (type=%s)", task_id, task_type)
            return task_id
    except Exception as e:
        log.warning("CapSolver createTask request failed: %s", e)
        return None


async def _poll_result(task_id: str) -> str | None:
    """Poll for task result, return the reCAPTCHA token."""
    payload = {
        "clientKey": CAPSOLVER_API_KEY,
        "taskId": task_id,
    }

    for attempt in range(_MAX_POLL // 3):
        await asyncio.sleep(3)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{CAPSOLVER_API}/getTaskResult", json=payload)
                data = resp.json()

                if data.get("errorId", 0) != 0:
                    log.warning("CapSolver poll error: %s", data.get("errorDescription"))
                    return None

                status = data.get("status")
                if status == "ready":
                    solution = data.get("solution", {})
                    token = solution.get("gRecaptchaResponse", "")
                    if token:
                        log.info("CapSolver solved reCAPTCHA (attempt %d)", attempt + 1)
                        return token
                    log.warning("CapSolver returned ready but no token")
                    return None

                # Still processing
                if attempt % 5 == 4:
                    log.debug("CapSolver still solving... (attempt %d)", attempt + 1)

        except Exception as e:
            log.debug("CapSolver poll error: %s", e)

    log.warning("CapSolver timed out after %ds", _MAX_POLL)
    return None


async def _inject_token(page: Page, token: str) -> bool:
    """Inject the solved reCAPTCHA token into the page."""
    try:
        injected = await page.evaluate("""(token) => {
            // Set the g-recaptcha-response textarea (standard for both v2 and v3)
            const textareas = document.querySelectorAll('textarea[name="g-recaptcha-response"]');
            let set = 0;
            textareas.forEach(ta => {
                ta.value = token;
                ta.innerHTML = token;
                ta.dispatchEvent(new Event('input', { bubbles: true }));
                ta.dispatchEvent(new Event('change', { bubbles: true }));
                set++;
            });

            // Also try hidden input
            const hiddenInputs = document.querySelectorAll('input[name="g-recaptcha-response"]');
            hiddenInputs.forEach(inp => {
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(inp, token);
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                set++;
            });

            // Call the reCAPTCHA callback if it exists
            try {
                if (typeof ___grecaptcha_cfg !== 'undefined') {
                    const clients = ___grecaptcha_cfg.clients;
                    for (const key in clients) {
                        const client = clients[key];
                        // Walk the client object to find callback
                        const findCallback = (obj, depth) => {
                            if (depth > 5 || !obj) return null;
                            for (const k in obj) {
                                if (typeof obj[k] === 'function' && k.length < 3) {
                                    return obj[k];
                                }
                                if (typeof obj[k] === 'object') {
                                    const found = findCallback(obj[k], depth + 1);
                                    if (found) return found;
                                }
                            }
                            return null;
                        };
                        const cb = findCallback(client, 0);
                        if (cb) {
                            cb(token);
                            set++;
                        }
                    }
                }
            } catch(e) {}

            // Try grecaptcha callback
            try {
                if (window.grecaptcha && window.grecaptcha.getResponse) {
                    // Override getResponse to return our token
                    const origGetResponse = window.grecaptcha.getResponse;
                    window.grecaptcha.getResponse = function() { return token; };
                }
            } catch(e) {}

            return set;
        }""", token)

        log.info("Injected reCAPTCHA token into %d elements", injected)
        return injected > 0
    except Exception as e:
        log.warning("Failed to inject reCAPTCHA token: %s", e)
        return False


async def _extract_hcaptcha_sitekey(page: Page) -> str:
    """Extract hCaptcha sitekey from the page."""
    sitekey = await page.evaluate("""() => {
        // Check for hCaptcha div
        const el = document.querySelector('.h-captcha[data-sitekey]');
        if (el) return el.getAttribute('data-sitekey');
        // Check iframe
        const frames = document.querySelectorAll('iframe[src*="hcaptcha"]');
        for (const f of frames) {
            const match = f.src.match(/sitekey=([^&]+)/);
            if (match) return match[1];
        }
        // Check any element with hcaptcha data-sitekey
        const any = document.querySelector('[data-sitekey]');
        if (any) {
            const key = any.getAttribute('data-sitekey');
            // hCaptcha keys are UUIDs (contain dashes), reCAPTCHA keys are 40 chars alphanumeric
            if (key && key.includes('-')) return key;
        }
        return '';
    }""")
    return sitekey or ""


async def _create_hcaptcha_task(sitekey: str, page_url: str) -> str | None:
    """Create a CapSolver hCaptcha task and return the task ID."""
    if not CAPSOLVER_API_KEY:
        return None

    task = {
        "type": "HCaptchaTaskProxyLess",
        "websiteURL": page_url,
        "websiteKey": sitekey,
    }
    payload = {
        "clientKey": CAPSOLVER_API_KEY,
        "task": task,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{CAPSOLVER_API}/createTask", json=payload)
            data = resp.json()
            if data.get("errorId", 0) != 0:
                log.warning("CapSolver hCaptcha createTask error: %s — %s",
                           data.get("errorCode"), data.get("errorDescription"))
                return None
            task_id = data.get("taskId")
            log.info("CapSolver hCaptcha task created: %s", task_id)
            return task_id
    except Exception as e:
        log.warning("CapSolver hCaptcha createTask failed: %s", e)
        return None


async def _inject_hcaptcha_token(page: Page, token: str) -> bool:
    """Inject the solved hCaptcha token into the page."""
    try:
        injected = await page.evaluate("""(token) => {
            let set = 0;
            // Set h-captcha-response textareas
            document.querySelectorAll('textarea[name="h-captcha-response"], [name="g-recaptcha-response"]').forEach(ta => {
                ta.value = token;
                ta.innerHTML = token;
                ta.dispatchEvent(new Event('input', { bubbles: true }));
                set++;
            });
            // Set hidden inputs
            document.querySelectorAll('input[name="h-captcha-response"]').forEach(inp => {
                inp.value = token;
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                set++;
            });
            // Try hcaptcha callback
            try {
                if (window.hcaptcha && window.hcaptcha.getResponse) {
                    const orig = window.hcaptcha.getResponse;
                    window.hcaptcha.getResponse = function() { return token; };
                    set++;
                }
            } catch(e) {}
            return set;
        }""", token)
        log.info("Injected hCaptcha token into %d elements", injected)
        return injected > 0
    except Exception as e:
        log.warning("Failed to inject hCaptcha token: %s", e)
        return False


async def _detect_captcha_type(page: Page) -> str:
    """Detect which captcha type is on the page: 'recaptcha', 'hcaptcha', or 'none'."""
    return await page.evaluate("""() => {
        // Check for hCaptcha
        if (document.querySelector('.h-captcha[data-sitekey]')
            || document.querySelector('iframe[src*="hcaptcha"]')
            || document.querySelector('script[src*="hcaptcha"]')) {
            return 'hcaptcha';
        }
        // Check for reCAPTCHA
        if (document.querySelector('.g-recaptcha[data-sitekey]')
            || document.querySelector('[data-sitekey]')
            || document.querySelector('iframe[src*="recaptcha"]')
            || document.querySelector('script[src*="recaptcha"]')) {
            return 'recaptcha';
        }
        return 'none';
    }""") or "none"


async def solve_recaptcha(page: Page) -> str | None:
    """Detect, solve, and inject any CAPTCHA (reCAPTCHA or hCaptcha) on the page.

    Returns the token string if successful, None otherwise.
    """
    if not CAPSOLVER_API_KEY:
        return None

    # Detect captcha type first
    captcha_type = await _detect_captcha_type(page)

    if captcha_type == "hcaptcha":
        return await _solve_hcaptcha(page)
    elif captcha_type == "recaptcha":
        return await _solve_recaptcha_inner(page)
    else:
        log.debug("No CAPTCHA detected on page")
        return None


async def _solve_hcaptcha(page: Page) -> str | None:
    """Solve hCaptcha on the page."""
    sitekey = await _extract_hcaptcha_sitekey(page)
    if not sitekey:
        log.debug("No hCaptcha sitekey found on page")
        return None

    page_url = page.url
    log.info("Solving hCaptcha (sitekey=%s...) on %s", sitekey[:12], page_url[:60])

    task_id = await _create_hcaptcha_task(sitekey, page_url)
    if not task_id:
        return None

    token = await _poll_result(task_id)
    if not token:
        return None

    try:
        await check_balance()
    except Exception:
        pass

    await _inject_hcaptcha_token(page, token)
    return token


async def _solve_recaptcha_inner(page: Page) -> str | None:
    """Solve reCAPTCHA on the page."""
    sitekey, version, is_invisible = await _extract_sitekey(page)
    if not sitekey:
        log.debug("No reCAPTCHA sitekey found on page")
        return None

    page_url = page.url
    log.info("Solving reCAPTCHA %s (sitekey=%s... invisible=%s) on %s",
             version, sitekey[:12], is_invisible, page_url[:60])

    task_id = await _create_task(sitekey, page_url, version, is_invisible)
    if not task_id:
        return None

    token = await _poll_result(task_id)
    if not token:
        return None

    try:
        await check_balance()
    except Exception:
        pass

    await _inject_token(page, token)
    return token
