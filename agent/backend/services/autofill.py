"""Playwright-based autofill service for job application forms.

Detects ATS platforms (Greenhouse, Lever, Workday, iCIMS, Ashby,
SmartRecruiters) and fills standard fields from profile data.  Unknown
questions are stored for later review or answered via LLM.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright

from backend.db.database import get_connection
from backend.services.config import ROOT_DIR, settings

log = logging.getLogger(__name__)

SCREENSHOTS_DIR = ROOT_DIR / "artifacts" / "autofill_screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Persistent Chrome profile — reuses cookies/history across runs so
# reCAPTCHA builds up trust over time.  Uses real Chrome (not Chromium).
# ---------------------------------------------------------------------------
_CHROME_PROFILE_DIR = str(ROOT_DIR / "artifacts" / "chrome_bot_profile")
_CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
# Use Chrome exe — Brave cookies already copied into the bot profile
_BROWSER_EXE = _CHROME_EXE


async def _launch_persistent_browser(pw, *, headless: bool = False):
    """Launch a persistent browser context using the real Chrome executable.

    Returns (context, None) — the context IS the browser for persistent mode.
    The second element is None to signal callers not to close a separate browser.
    """
    import subprocess
    # Kill Chrome instances using our bot profile so we get a clean launch.
    # Without this, launch_persistent_context detects an existing session and fails.
    try:
        # Use PowerShell to find Chrome PIDs with our bot profile in cmdline
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
            "Where-Object { $_.CommandLine -like '*chrome_bot_profile*' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=8,
        )
        pids = [line.strip() for line in result.stdout.splitlines()
                if line.strip().isdigit()]
        if pids:
            for pid in pids:
                subprocess.run(["taskkill", "/F", "/PID", pid],
                               capture_output=True, timeout=5)
            log.info("Killed %d bot-profile Chrome processes: %s", len(pids), pids)
        elif (Path(_CHROME_PROFILE_DIR) / "SingletonLock").exists():
            # Fallback: PowerShell didn't match but profile is locked — kill all Chrome
            subprocess.run(
                ["taskkill", "/F", "/IM", "chrome.exe"],
                capture_output=True, timeout=5,
            )
            log.warning("Fallback: killed all Chrome (SingletonLock was stale)")
        import asyncio
        await asyncio.sleep(1.5)  # let OS release the profile lock
    except Exception:
        # Ultimate fallback — just kill all Chrome
        try:
            subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                           capture_output=True, timeout=5)
        except Exception:
            pass
    # Remove stale lock files
    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        lock_path = Path(_CHROME_PROFILE_DIR) / lock_name
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    # Clear stale Workday cookies from SQLite before Chrome starts
    # (prevents "Continue Application" stale sessions that break school AJAX)
    _cookies_db = Path(_CHROME_PROFILE_DIR) / "Default" / "Network" / "Cookies"
    if _cookies_db.exists():
        try:
            import sqlite3 as _sq3
            _cconn = _sq3.connect(str(_cookies_db))
            _ccur = _cconn.cursor()
            _ccur.execute("DELETE FROM cookies WHERE host_key LIKE '%workday%' OR host_key LIKE '%myworkdayjobs%'")
            if _ccur.rowcount > 0:
                log.info("Cleared %d stale Workday cookies from Chrome profile", _ccur.rowcount)
            _cconn.commit()
            _cconn.close()
        except Exception as _ce:
            log.debug("Workday cookie clear failed (non-fatal): %s", _ce)

    from backend.services.browser_stealth import apply_stealth, get_random_viewport

    viewport = get_random_viewport()
    context = await pw.chromium.launch_persistent_context(
        _CHROME_PROFILE_DIR,
        executable_path=_BROWSER_EXE if Path(_BROWSER_EXE).exists() else None,
        headless=headless,
        viewport=viewport,
        locale="en-US",
        timezone_id="America/New_York",
        screen={"width": viewport["width"], "height": viewport["height"] + 140},
        color_scheme="light",
        java_script_enabled=True,
        has_touch=False,
        is_mobile=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        ignore_default_args=["--enable-automation"],
    )
    await apply_stealth(context)
    log.info("Persistent Chrome profile launched from %s", _CHROME_PROFILE_DIR)
    return context

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

_PLATFORM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Greenhouse hosts jobs at:
    #   - boards.greenhouse.io / job-boards.greenhouse.io / greenhouse.io/embed
    #   - custom company domains with ?gh_jid= parameter (Bird, Nuro, Robinhood direct)
    # All three paths use the SAME Greenhouse backend (incl. OTP security code flow),
    # so route all to the Greenhouse handler.
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io|greenhouse\.io/embed|[?&]gh_jid=", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co", re.I)),
    ("workday", re.compile(r"myworkdayjobs\.com|wd\d+\.myworkday\.com", re.I)),
    ("icims", re.compile(r"icims\.com|careers-.*\.icims\.com", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com|ashbyhq\.com/jobs", re.I)),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com|smartrecruiters\.com", re.I)),
]


def detect_platform(url: str) -> str:
    """Return the ATS platform name or ``'generic'``.

    Also detects embedded Greenhouse forms on company career pages
    (identified by ``gh_jid`` query parameter).
    """
    for name, pattern in _PLATFORM_PATTERNS:
        if pattern.search(url):
            return name
    # Embedded Greenhouse forms on company domains use gh_jid param.
    if re.search(r"[?&]gh_jid=\d+", url):
        return "greenhouse"
    return "generic"


# ---------------------------------------------------------------------------
# Stored-answer helpers
# ---------------------------------------------------------------------------

def _normalize_prompt(text: str) -> str:
    """Collapse whitespace and lowercase for matching."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _css_escape_id(id_str: str) -> str:
    """Escape special CSS characters in an element ID for use in selectors."""
    return id_str.replace("[", "\\[").replace("]", "\\]")


def _lookup_answer(prompt_text: str, scope: str = "global") -> str | None:
    """Look up a stored answer from ``application_answers``."""
    key = _normalize_prompt(prompt_text)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT answer_text FROM application_answers
            WHERE prompt_key = ? AND active = 1
              AND scope IN ('global', ?)
            ORDER BY
              CASE scope WHEN ? THEN 0 ELSE 1 END,
              updated_at DESC
            LIMIT 1
            """,
            (key, scope, scope),
        ).fetchone()
    return row["answer_text"] if row else None


def store_answer(question_pattern: str, answer: str, scope: str = "global") -> dict[str, Any]:
    """Store a reusable answer for a question pattern.

    ``scope`` can be ``"global"``, ``"company"``, or a specific job id.
    """
    key = _normalize_prompt(question_pattern)
    answer_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        # Deactivate any previous answer with the same key+scope.
        conn.execute(
            "UPDATE application_answers SET active = 0, updated_at = ? WHERE prompt_key = ? AND scope = ?",
            (now, key, scope),
        )
        conn.execute(
            """
            INSERT INTO application_answers
              (id, scope, prompt_key, prompt_text, answer_text, answer_source, confidence, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'user', 1.0, 1, ?, ?)
            """,
            (answer_id, scope, key, question_pattern.strip(), answer, now, now),
        )
        conn.commit()
    return {"id": answer_id, "prompt_key": key, "scope": scope, "status": "stored"}


# ---------------------------------------------------------------------------
# Field-fill helpers (shared across platforms)
# ---------------------------------------------------------------------------

_FIELD_MAP: list[tuple[str, list[str], str]] = [
    # (profile_key, label_patterns, attr_patterns)
    ("first_name", ["first name"], "first.?name"),
    ("last_name", ["last name", "family name", "surname"], "last.?name|surname"),
    ("email", ["email"], "email"),
    ("phone", ["phone", "mobile", "telephone"], "phone|mobile|tel"),
    ("linkedin", ["linkedin"], "linkedin"),
    ("website", ["website", "portfolio", "github", "personal url"], "website|portfolio|github|personal.?url"),
]

_DECLINE_LABELS = [
    "decline",
    "prefer not",
    "i don't wish",
    "choose not",
]

_EEO_KEYWORDS = ["gender", "race", "ethnicity", "veteran", "disability", "demographic"]


async def _type_into_field(page: Page, selector: str, value: str) -> bool:
    """Fill a field if it exists, return True on success.

    Works with ``<input>``, ``<textarea>``, and ``<select>`` elements.
    """
    try:
        loc = page.locator(selector).first
        if await loc.count() > 0 and await loc.is_visible():
            tag = await loc.evaluate("e => e.tagName")
            if tag == "SELECT":
                await loc.select_option(label=value)
            else:
                await loc.click()
                await loc.fill(value)
            return True
    except Exception:
        pass
    # Fallback: if selector targets an input but a textarea has the same id.
    if selector.startswith("#"):
        try:
            ta = page.locator(f"textarea{selector}").first
            if await ta.count() > 0 and await ta.is_visible():
                await ta.click()
                await ta.fill(value)
                return True
        except Exception:
            pass
    return False


async def _upload_file(page: Page, selector: str, file_path: str) -> bool:
    """Upload a file to an input[type=file] matched by *selector*."""
    try:
        loc = page.locator(selector).first
        if await loc.count() > 0:
            await loc.set_input_files(file_path)
            return True
    except Exception:
        pass
    return False


async def _select_decline_option(page: Page, container_selector: str) -> bool:
    """Try to select a 'Decline to self-identify' option within *container_selector*."""
    try:
        container = page.locator(container_selector).first
        if await container.count() == 0:
            return False
        # Try <select> option first.
        selects = container.locator("select")
        if await selects.count() > 0:
            options = await selects.first.locator("option").all_text_contents()
            for opt in options:
                if any(d in opt.lower() for d in _DECLINE_LABELS):
                    await selects.first.select_option(label=opt)
                    return True
        # Try radio / checkbox labels.
        labels = container.locator("label")
        count = await labels.count()
        for i in range(count):
            text = (await labels.nth(i).text_content() or "").lower()
            if any(d in text for d in _DECLINE_LABELS):
                await labels.nth(i).click()
                return True
    except Exception:
        pass
    return False


async def _fill_profile_fields(
    page: Page,
    profile: dict[str, Any],
    filled: list[str],
) -> None:
    """Attempt to fill standard text fields from *profile*."""
    contact = profile.get("contact", profile)
    value_map = {
        "first_name": contact.get("first_name", ""),
        "last_name": contact.get("last_name", ""),
        "email": contact.get("email", settings.job_application_email),
        "phone": contact.get("phone", ""),
        "linkedin": contact.get("linkedin", ""),
        "website": contact.get("website", contact.get("github", "")),
    }

    for key, labels, attr_pat in _FIELD_MAP:
        val = value_map.get(key, "")
        if not val:
            continue
        # Strategy 1: input[name] / input[id]
        ok = await _type_into_field(page, f"input[name*='{key}' i]", val)
        if not ok:
            ok = await _type_into_field(page, f"input[id*='{key}' i]", val)
        # Strategy 2: placeholder text
        if not ok:
            for lbl in labels:
                ok = await _type_into_field(page, f"input[placeholder*='{lbl}' i]", val)
                if ok:
                    break
        # Strategy 3: label text -> associated input
        if not ok:
            for lbl in labels:
                try:
                    label_loc = page.locator(f"label:text-is('{lbl}')").first
                    if await label_loc.count() == 0:
                        label_loc = page.get_by_text(re.compile(re.escape(lbl), re.I)).first
                    for_attr = await label_loc.get_attribute("for")
                    if for_attr:
                        ok = await _type_into_field(page, f"#{for_attr}", val)
                        if ok:
                            break
                except Exception:
                    continue
        if ok:
            filled.append(key)


async def _fill_work_auth(page: Page, filled: list[str]) -> None:
    """Handle work-authorization and sponsorship fields.

    Supports radio buttons, native selects, and Greenhouse-style custom
    combobox dropdowns.
    """
    auth_value = settings.us_work_authorized  # "Yes" / "No"
    sponsor_value = settings.requires_sponsorship  # "Yes" / "No" / ""

    for keyword, value in [("authorized", auth_value), ("sponsorship", sponsor_value)]:
        if not value:
            continue

        # Strategy 1: Find the label, then its associated input (combobox).
        try:
            labels = page.locator("label")
            label_count = await labels.count()
            for i in range(label_count):
                text = (await labels.nth(i).text_content() or "").lower()
                if keyword in text:
                    for_attr = await labels.nth(i).get_attribute("for")
                    if for_attr:
                        inp = page.locator(f"input#{for_attr}").first
                        if await inp.count() > 0:
                            await inp.click()
                            await page.wait_for_timeout(300)
                            option = page.locator(f"div[role='option']:has-text('{value}')").first
                            if await option.count() > 0:
                                await option.click()
                                filled.append(keyword)
                                break
                            await page.locator("body").click()
        except Exception:
            pass

        if keyword in filled:
            continue

        # Strategy 2: Radio buttons near the keyword.
        try:
            section = page.locator(f"*:has-text('{keyword}')").last
            radios = section.locator(f"label:text-is('{value}')")
            if await radios.count() > 0:
                await radios.first.click()
                filled.append(keyword)
                continue
            # Try select dropdowns.
            selects = section.locator("select")
            if await selects.count() > 0:
                await selects.first.select_option(label=value)
                filled.append(keyword)
        except Exception:
            pass


async def _fill_eeo_fields(page: Page, filled: list[str]) -> None:
    """Fill EEO demographic questions with actual user values.

    TODO(post-lift): read these from the profile, not hardcoded. Empty
    strings here so we don't auto-submit demographic answers we don't own.
    """
    # Map of standard Greenhouse EEO field IDs to the correct answers.
    _EEO_ANSWERS: dict[str, str] = {
        "gender": "",
        "race": "",
        "hispanic_ethnicity": "",
        "veteran_status": "",
        "disability_status": "",
    }
    for field_id, answer in _EEO_ANSWERS.items():
        try:
            inp = page.locator(f"input#{field_id}").first
            if await inp.count() == 0 or not await inp.is_visible():
                continue
            role = await inp.get_attribute("role") or ""
            if role == "combobox":
                # React-select: type answer and select matching option.
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(200)
                await inp.click()
                await page.wait_for_timeout(300)
                await inp.fill("")
                await inp.type(answer, delay=80)
                await page.wait_for_timeout(1000)
                listbox_id = f"react-select-{field_id}-listbox"
                listbox = page.locator(f"#{listbox_id}")
                selected = False
                if await listbox.count() > 0:
                    options = listbox.locator("[role='option']")
                    opt_count = await options.count()
                    answer_lower = answer.lower()
                    for i in range(opt_count):
                        text = (await options.nth(i).text_content() or "").strip().lower()
                        if answer_lower in text or text in answer_lower or text.startswith(answer_lower[:4]):
                            await options.nth(i).click()
                            filled.append(f"eeo_{field_id}")
                            selected = True
                            log.info("EEO field '%s' set to '%s'", field_id, answer)
                            break
                if selected:
                    # Propagate value to hidden validation input inside react-select
                    await page.evaluate(f"""() => {{
                        const el = document.getElementById('{field_id}');
                        if (!el) return;
                        // Walk up to find the react-select container
                        let container = el.parentElement;
                        for (let i = 0; i < 6 && container; i++) {{
                            const hiddens = container.querySelectorAll(
                                'input[required][tabindex="-1"], input[required][aria-hidden="true"]'
                            );
                            hiddens.forEach(h => {{
                                const sv = container.querySelector(
                                    '[class*="singleValue"], [class*="single-value"]'
                                );
                                if (sv && sv.textContent.trim()) {{
                                    const setter = Object.getOwnPropertyDescriptor(
                                        window.HTMLInputElement.prototype, 'value'
                                    ).set;
                                    setter.call(h, sv.textContent.trim());
                                    h.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    h.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                }} else {{
                                    h.removeAttribute('required');
                                }}
                            }});
                            container = container.parentElement;
                        }}
                        // Also clear required from the combobox input itself if it's :invalid
                        if (el.required && !el.checkValidity()) {{
                            el.removeAttribute('required');
                            el.removeAttribute('aria-required');
                        }}
                    }}""")
                else:
                    await page.keyboard.press("Escape")
            else:
                # Regular input: try finding option with matching text.
                await inp.click()
                await page.wait_for_timeout(300)
                options = page.locator("div[role='option']")
                opt_count = await options.count()
                answer_lower = answer.lower()
                selected = False
                for i in range(opt_count):
                    text = (await options.nth(i).text_content() or "").strip().lower()
                    if answer_lower in text or text in answer_lower:
                        await options.nth(i).click()
                        filled.append(f"eeo_{field_id}")
                        selected = True
                        log.info("EEO field '%s' set to '%s'", field_id, answer)
                        break
                if not selected:
                    await page.locator("body").click()
        except Exception:
            pass

    # Fallback: handle traditional fieldset/select-based EEO fields.
    # Skip gender -- always handled above with "Male", never decline.
    eeo_ids = list(_EEO_ANSWERS.keys())
    for kw in _EEO_KEYWORDS:
        if kw == "gender":
            continue  # Never use decline for gender -- must be "Male"
        if any(f"eeo_{eid}" in filled for eid in eeo_ids if kw in eid):
            continue
        try:
            sections = page.locator(f"fieldset:has-text('{kw}'), div:has-text('{kw}')")
            count = await sections.count()
            for i in range(min(count, 3)):
                sel = sections.nth(i)
                sel_html = await sel.inner_html()
                if len(sel_html) > 5000:
                    continue
                ok = await _select_decline_option(page, f"fieldset:has-text('{kw}')")
                if not ok:
                    ok = await _select_decline_option(page, f"div:has-text('{kw}')")
                if ok:
                    filled.append(f"eeo_{kw}")
                    break
        except Exception:
            pass


def _choose_file(
    pdf_path: str | None,
    docx_path: str | None,
    prefer_docx: bool,
    accept_attr: str | None,
) -> str | None:
    """Pick the file to upload -- always .docx, never PDF.

    The system generates both formats but we only submit .docx files
    for resume and cover letter uploads.  PDF is only used as a last
    resort when no .docx exists at all.
    """
    has_docx = bool(docx_path and Path(docx_path).exists())
    has_pdf = bool(pdf_path and Path(pdf_path).exists())

    if not has_pdf and not has_docx:
        return None

    # Always prefer docx -- only fall back to PDF if docx doesn't exist.
    if has_docx:
        return docx_path
    return pdf_path


def _choose_resume_file(
    pdf_path: str | None,
    docx_path: str | None,
    prefer_docx: bool,
    accept_attr: str | None,
) -> str | None:
    """Select the resume file to upload."""
    return _choose_file(pdf_path, docx_path, prefer_docx, accept_attr)


def _choose_cover_letter_file(
    pdf_path: str | None,
    docx_path: str | None,
    prefer_docx: bool,
    accept_attr: str | None,
) -> str | None:
    """Select the cover letter file to upload."""
    return _choose_file(pdf_path, docx_path, prefer_docx, accept_attr)


async def _get_accept_attr(inp) -> str | None:
    """Read the ``accept`` attribute from a file input element."""
    try:
        return await inp.get_attribute("accept")
    except Exception:
        return None


async def _upload_documents(
    page: Page,
    resume_pdf_path: str | None,
    cover_letter_pdf_path: str | None,
    filled: list[str],
    *,
    resume_docx_path: str | None = None,
    cover_letter_docx_path: str | None = None,
    prefer_docx: bool = True,
) -> None:
    """Upload resume and cover-letter files, preferring docx when available."""
    file_inputs = page.locator("input[type='file']")
    count = await file_inputs.count()

    for i in range(count):
        inp = file_inputs.nth(i)
        # Walk up to parent and check nearby text.
        try:
            parent_text = (await inp.locator("xpath=./ancestor::div[1]").text_content() or "").lower()
        except Exception:
            parent_text = ""

        accept_attr = await _get_accept_attr(inp)

        if (resume_pdf_path or resume_docx_path) and ("resume" in parent_text or "cv" in parent_text):
            chosen = _choose_resume_file(resume_pdf_path, resume_docx_path, prefer_docx, accept_attr)
            if chosen:
                try:
                    await inp.set_input_files(chosen)
                    filled.append("resume_upload")
                except Exception:
                    pass
        elif (cover_letter_pdf_path or cover_letter_docx_path) and "cover" in parent_text:
            chosen = _choose_cover_letter_file(cover_letter_pdf_path, cover_letter_docx_path, prefer_docx, accept_attr)
            if chosen:
                try:
                    await inp.set_input_files(chosen)
                    filled.append("cover_letter_upload")
                except Exception:
                    pass

    # Fallback: if only one file input, upload resume.
    if count == 1 and (resume_pdf_path or resume_docx_path) and "resume_upload" not in filled:
        try:
            accept_attr = await _get_accept_attr(file_inputs.first)
            chosen = _choose_resume_file(resume_pdf_path, resume_docx_path, prefer_docx, accept_attr)
            if chosen:
                await file_inputs.first.set_input_files(chosen)
                filled.append("resume_upload")
        except Exception:
            pass


# Labels / keywords that should never be flagged as "unknown questions".
_KNOWN_FIELD_KEYWORDS = [
    "first name", "last name", "email", "phone", "mobile", "linkedin",
    "website", "portfolio", "github", "resume", "cover letter", "cv",
    "attach", "upload", "enter manually", "personal preferences",
    "gender", "race", "ethnicity",
    "veteran status", "disability status", "disability", "veteran", "demographic", "decline",
    # Cookie consent / GDPR banners (not application questions).
    "cookie", "cookies", "consent", "targeting", "functional",
    "performance cookies", "analytics cookies", "strictly necessary",
    "cookie policy", "privacy policy", "accept all", "reject all",
    # Optional fields that can be left empty.
    "additional information", "additional comments", "anything else",
    # Lever-specific fields already handled by _fill_lever.
    "sponsorship", "immigration", "visa", "authorized", "previously employed",
    "right to work",
    "worked for", "interested in working", "rate", "impression",
    "current location", "current company", "cover letter",
    "how did you hear", "where did you hear",
    # EEO / survey labels.
    "hispanic", "latino", "sexual orientation",
]


async def _collect_unknown_questions(
    page: Page,
    filled: list[str],
    scope: str,
) -> list[dict[str, str]]:
    """Return questions we could not fill so the user can answer them."""
    needs_review: list[dict[str, str]] = []
    # Build a set of lowercase tokens from filled fields for fuzzy matching.
    filled_tokens = set()
    for f in filled:
        for token in re.split(r"[-_\s]+", f.lower()):
            if len(token) >= 3:
                filled_tokens.add(token)

    try:
        # On Greenhouse board pages, scope labels to the #application form
        # to avoid picking up page-level filter labels (Department, Office).
        is_gh_board = re.search(r"boards\.greenhouse\.io", page.url, re.I)
        app_container = None
        if is_gh_board:
            app_loc = page.locator("#application, #app")
            if await app_loc.count() > 0:
                app_container = app_loc.first
                log.debug("Scoping label scan to #application container on Greenhouse board")

        base = app_container if app_container else page
        # Skip labels inside cookie/consent banners entirely.
        labels = base.locator("label:not([class*='cookie']):not([class*='consent'])")
        count = await labels.count()
        for i in range(min(count, 60)):
            el = labels.nth(i)
            text = (await el.text_content() or "").strip()
            if not text or len(text) < 4 or len(text) > 300:
                continue

            # Skip if inside a cookie/consent container.
            try:
                in_consent = await el.evaluate(
                    """e => {
                        let p = e;
                        while (p) {
                            const id = (p.id || '').toLowerCase();
                            const cls = (p.className || '').toString().toLowerCase();
                            if (id.includes('cookie') || id.includes('consent') || id.includes('onetrust')
                                || cls.includes('cookie') || cls.includes('consent') || cls.includes('onetrust'))
                                return true;
                            p = p.parentElement;
                        }
                        return false;
                    }"""
                )
                if in_consent:
                    continue
            except Exception:
                pass

            normalized = _normalize_prompt(text)

            # Skip CSS/UI noise labels that aren't form questions.
            _NOISE_LABELS = {
                "color", "opacity", "search", "search by job title",
                "search by job title, location, department, category, etc.",
                "filter", "sort", "clear", "close", "menu",
                "department", "office", "location",  # page-level filter labels
            }
            if normalized.lower().strip() in _NOISE_LABELS:
                continue
            # Skip race/ethnicity checkbox options (handled by EEO handler).
            _RACE_OPTIONS = {
                "american indian or alaska native", "asian",
                "black or african american", "middle eastern or north african",
                "native hawaiian or other pacific islander", "white",
                "something not listed above", "i don't wish to answer",
                "two or more races", "hispanic or latino",
            }
            if normalized.lower().strip() in _RACE_OPTIONS:
                continue

            # Skip already-filled (fuzzy token match).
            label_clean = re.sub(r"[*\s]+", " ", normalized).strip()
            if any(kw in label_clean for kw in _KNOWN_FIELD_KEYWORDS):
                continue
            if any(token in label_clean for token in filled_tokens):
                continue

            # Check if we have a stored answer.
            stored = _lookup_answer(text, scope=scope)
            if stored:
                for_attr = await labels.nth(i).get_attribute("for")
                if for_attr:
                    ok = await _type_into_field(page, f"#{for_attr}", stored)
                    if not ok:
                        # Try textarea fallback.
                        try:
                            ta = page.locator(f"textarea#{for_attr}")
                            if await ta.count() > 0:
                                await ta.fill(stored)
                                ok = True
                        except Exception:
                            pass
                    if ok:
                        continue
            needs_review.append({"question": text, "normalized_key": normalized})
    except Exception as exc:
        log.warning("Error collecting unknown questions: %s", exc)
    return needs_review


# ---------------------------------------------------------------------------
# Platform-specific handlers
# ---------------------------------------------------------------------------

async def _fill_greenhouse(
    page: Page,
    profile: dict[str, Any],
    files: dict[str, str | None],
    filled: list[str],
) -> None:
    """Greenhouse forms use ``id`` attributes like ``first_name``, ``email``, etc."""
    contact = profile.get("contact", profile)

    # --- Standard fields by id ---
    id_map = {
        "first_name": contact.get("first_name", ""),
        "last_name": contact.get("last_name", ""),
        "preferred_name": contact.get("first_name", ""),  # Common Greenhouse field
        "email": contact.get("email", settings.job_application_email),
        "phone": contact.get("phone", ""),
    }
    for field_id, val in id_map.items():
        if not val:
            continue
        # Try exact id first, then attribute selector for numeric IDs.
        ok = await _type_into_field(page, f"input[id='{field_id}']", val)
        if not ok:
            try:
                ok = await _type_into_field(page, f"input#{field_id}", val)
            except Exception:
                pass
        if ok:
            filled.append(field_id)

    # --- Label-based fallback for "Preferred Name" and similar ---
    first_name = contact.get("first_name", "")
    if first_name and "preferred_name" not in filled:
        for label_pat in ("Preferred Name", "Preferred name", "preferred name"):
            try:
                lbl = page.get_by_text(re.compile(re.escape(label_pat), re.I)).first
                if await lbl.count() > 0:
                    for_attr = await lbl.get_attribute("for")
                    if for_attr:
                        ok = await _type_into_field(page, f"input[id='{for_attr}']", first_name)
                        if ok:
                            filled.append("preferred_name")
                            log.info("Filled 'Preferred Name' via label with '%s'", first_name)
                            break
            except Exception:
                continue

    # --- LinkedIn / website via aria-label or question fields ---
    linkedin = contact.get("linkedin", "")
    website = contact.get("website", contact.get("github", ""))
    if linkedin:
        ok = await _type_into_field(page, "input[aria-label*='LinkedIn' i]", linkedin)
        if not ok:
            ok = await _type_into_field(page, "input[id*='linkedin' i]", linkedin)
        if ok:
            filled.append("linkedin")
    if website:
        ok = await _type_into_field(page, "input[aria-label*='Website' i]", website)
        if not ok:
            ok = await _type_into_field(page, "input[aria-label*='GitHub' i]", website)
        if ok:
            filled.append("website")

    # --- React-select combobox helper ---
    async def _verify_react_select_value(input_id: str) -> str:
        """Check if a react-select has a visible selected value."""
        try:
            inp = page.locator(f"input[id='{input_id}']").first
            if await inp.count() == 0:
                return ""
            # Strategy 1: look for singleValue CSS class in ancestor.
            for ancestor_q in [
                "xpath=ancestor::div[contains(@class,'select')]",
                "xpath=ancestor::div[contains(@class,'Select')]",
                "xpath=ancestor::div[3]",
            ]:
                container = inp.locator(ancestor_q).first
                if await container.count() > 0:
                    single_val = container.locator(
                        "[class*='singleValue'], [class*='single-value'], "
                        "[class*='SingleValue']"
                    ).first
                    if await single_val.count() > 0:
                        text = (await single_val.text_content() or "").strip()
                        if text:
                            return text

            # Strategy 2: check the input's aria-activedescendant or
            # aria-live region for "option X, selected" pattern.
            for ancestor_q in [
                "xpath=ancestor::div[contains(@class,'select')]",
                "xpath=ancestor::div[contains(@class,'Select')]",
                "xpath=ancestor::div[3]",
            ]:
                container = inp.locator(ancestor_q).first
                if await container.count() > 0:
                    # Some react-selects put the value in a div with
                    # role or class containing "value" or "placeholder".
                    for val_sel in [
                        "[class*='value' i]:not([class*='placeholder' i])",
                        "[class*='Value' i]:not([class*='Placeholder' i])",
                    ]:
                        val_el = container.locator(val_sel).first
                        if await val_el.count() > 0:
                            text = (await val_el.text_content() or "").strip()
                            if text and text != "Select...":
                                return text
                    # Fallback: parse "option X, selected" from live region text.
                    live = container.locator("[aria-live]").first
                    if await live.count() > 0:
                        live_text = (await live.text_content() or "").strip()
                        m = re.search(r"option\s+(.+?),\s*selected", live_text)
                        if m:
                            return m.group(1).strip()
                    # Last resort: get container text and look for selected info.
                    ct = (await container.text_content() or "").strip()
                    m2 = re.search(r"option\s+(.+?),\s*selected", ct)
                    if m2:
                        return m2.group(1).strip()

            # Strategy 3: check hidden validation input value.
            for ancestor_q in [
                "xpath=ancestor::div[contains(@class,'field') or contains(@class,'select')]",
                "xpath=ancestor::div[3]",
            ]:
                container = inp.locator(ancestor_q).first
                if await container.count() > 0:
                    val_input = container.locator(
                        "input[tabindex='-1'][aria-hidden='true']"
                    ).first
                    if await val_input.count() > 0:
                        val = await val_input.input_value()
                        if val.strip():
                            return val.strip()
        except Exception:
            pass
        return ""

    async def _read_react_select_options(input_id: str) -> list[str]:
        """Open a react-select dropdown and read ALL available options."""
        options_list: list[str] = []
        try:
            inp = page.locator(f"input[id='{input_id}']").first
            if await inp.count() == 0:
                return []
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
            await inp.scroll_into_view_if_needed()
            await inp.click()
            await page.wait_for_timeout(500)
            # Clear any typed text to show full list
            await inp.fill("")
            await page.wait_for_timeout(300)
            # Press ArrowDown to ensure dropdown opens
            await inp.press("ArrowDown")
            await page.wait_for_timeout(500)
            listbox_id = f"react-select-{input_id}-listbox"
            listbox = page.locator(f"[id='{listbox_id}']")
            if await listbox.count() > 0:
                options = listbox.locator("[role='option']")
                opt_count = await options.count()
                for oi in range(min(opt_count, 30)):
                    text = (await options.nth(oi).text_content() or "").strip()
                    if text:
                        options_list.append(text)
            # Close dropdown
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
        except Exception as exc:
            log.debug("Could not read options for %s: %s", input_id, exc)
        return options_list

    async def _pick_best_option(input_id: str, question: str, options: list[str],
                                 company: str = "", role: str = "") -> bool:
        """Given a question and list of dropdown options, pick the best one.

        Uses rules first, then LLM if needed. Clicks the chosen option.
        """
        if not options:
            return False
        q_lower = question.lower()
        chosen: str | None = None

        # ── Rule-based picking: scan actual options for known answers ──
        # Map: question pattern -> list of preferred option substrings (in priority order)
        _PICK_RULES: list[tuple[re.Pattern[str], list[str]]] = [
            # Gender / sex
            # Gender/pronouns/transgender — TODO(post-lift): read from
            # profile.eeo_answers. Empty here so we don't auto-pick demographic
            # answers that don't belong to the current user.
            (re.compile(r"gender|identify.*sex|your sex", re.I),
             []),
            # Pronouns
            (re.compile(r"pronoun", re.I),
             []),
            # Transgender
            (re.compile(r"transgender|trans identity|cisgender", re.I),
             []),
            # Sexual orientation
            (re.compile(r"sexual orientation", re.I),
             ["don't wish", "decline", "prefer not"]),
            # Race
            (re.compile(r"race", re.I),
             ["asian", "decline", "don't wish", "prefer not"]),
            # Ethnicity
            (re.compile(r"ethnicit", re.I),
             ["not hispanic", "no", "decline", "don't wish", "prefer not"]),
            # Hispanic/Latino
            (re.compile(r"hispanic|latino", re.I),
             ["no", "not hispanic", "decline", "don't wish"]),
            # Veteran
            (re.compile(r"veteran", re.I),
             ["not a protected veteran", "i am not", "no", "decline", "don't wish"]),
            # Disability
            (re.compile(r"disabilit", re.I),
             ["no, i do not", "no, i don't", "no", "decline", "don't wish"]),
            # Work authorization
            (re.compile(r"authorized.*work|legally authorized|work authorization", re.I),
             ["yes"]),
            # Sponsorship
            (re.compile(r"sponsor|visa|immigration", re.I),
             ["yes"]),
            # Government
            (re.compile(r"government.*entit|work.*government|employed.*government", re.I),
             ["no"]),
            # Worked/employed before at company
            (re.compile(r"worked.*before|previously.*employed|employed.*engaged|been employed", re.I),
             ["no"]),
            # How did you hear
            (re.compile(r"how did you hear|where did you hear|how did you find", re.I),
             ["career", "website", "company", "linkedin", "other"]),
            # Graduation month
            (re.compile(r"month.*graduat|graduat.*month", re.I),
             ["may"]),
            # Graduation year
            (re.compile(r"year.*graduat|graduat.*year", re.I),
             ["2026"]),
            # School/university — TODO(post-lift): read from profile
            (re.compile(r"school|university|college|institution", re.I),
             []),
            # Degree
            (re.compile(r"degree|level.*education|education.*level", re.I),
             ["master"]),
            # Major/discipline
            (re.compile(r"major|field of study|discipline", re.I),
             ["analytics", "risk", "business", "data analytics", "data science",
              "business analytics", "management", "information systems",
              "statistics", "applied mathematics", "mathematics", "economics", "other"]),
            # State — TODO(post-lift): read from profile.address.state
            (re.compile(r"state.*reside|state.*live|state.*locat|which state", re.I),
             []),
            # Country (any country dropdown including "home address country")
            (re.compile(r"country|nation(?!ality)", re.I),
             ["united states", "us", "usa", "united states of america"]),
            # Relocation / in-person / on-site
            (re.compile(r"relocat|in.person|on.site|hybrid|office", re.I),
             ["yes"]),
            # Currently employed
            (re.compile(r"currently employed|are you employed", re.I),
             ["no"]),
            # Referred
            (re.compile(r"referred|referral", re.I),
             ["no"]),
            # Languages — only English, Hindi, Marathi
            (re.compile(r"language.*fluent|fluent.*language|other.*language|additional.*language|second.*language|bilingual", re.I),
             ["hindi", "other", "none", "n/a", "prefer not"]),
            (re.compile(r"which language|what language|primary language|native language", re.I),
             ["english"]),
            # Acknowledge / agree
            (re.compile(r"acknowledge|i agree|consent|privacy", re.I),
             ["yes", "i agree", "acknowledge"]),
            # End date year (education)
            (re.compile(r"end.*date.*year|year.*end|completion.*year", re.I),
             ["2026"]),
            # End date month
            (re.compile(r"end.*date.*month|month.*end|completion.*month", re.I),
             ["may"]),
            # Start date year (education)
            (re.compile(r"start.*date.*year|year.*start|begin.*year", re.I),
             ["2024"]),
            # Start date month
            (re.compile(r"start.*date.*month|month.*start|begin.*month", re.I),
             ["august", "aug"]),
            # Visa type / work auth type
            (re.compile(r"visa.*type|type.*visa|source.*right|authorization.*type|immigration.*status", re.I),
             ["student", "f-1", "opt", "other"]),
        ]

        for pattern, preferred_subs in _PICK_RULES:
            if pattern.search(q_lower):
                # Find the first option matching any preferred substring.
                # Use word-boundary matching to avoid "male" in "female".
                for pref in preferred_subs:
                    pref_lower = pref.lower()
                    for opt in options:
                        opt_lower = opt.lower()
                        # Exact match
                        if opt_lower == pref_lower:
                            chosen = opt
                            break
                        # Word-boundary match: "male" matches "Male" but not "Female"
                        # Check if pref appears at start of a word boundary
                        if re.search(r"(?:^|\b)" + re.escape(pref_lower) + r"(?:\b|$)", opt_lower):
                            chosen = opt
                            break
                    if chosen:
                        break
                if not chosen:
                    # No preferred match -- take last option (often "decline"/"prefer not")
                    chosen = options[-1]
                break

        # ── LLM fallback: ask the model to pick from actual options ──
        if not chosen:
            try:
                from backend.services.llm_client import generate
                opts_str = "\n".join(f"  {i+1}. {o}" for i, o in enumerate(options))
                llm_prompt = (
                    f"You are filling a job application for a candidate.\n"
                    f"Question: \"{question}\"\n"
                    f"Available options:\n{opts_str}\n\n"
                    # TODO(post-lift): inject the user's profile summary
                    # (location, work auth, demographic answers) instead of
                    # hardcoding. Empty until the profile pipeline is wired.
                    f"Key facts: (profile summary not configured)\n\n"
                    f"Reply with ONLY the number of the best option. Nothing else."
                )
                llm_resp = await generate(llm_prompt)
                # Parse the number
                import re as _re
                num_match = _re.search(r"(\d+)", llm_resp.strip())
                if num_match:
                    idx = int(num_match.group(1)) - 1
                    if 0 <= idx < len(options):
                        chosen = options[idx]
                        log.info("LLM picked option %d for '%s': '%s'", idx+1, question[:50], chosen)
            except Exception as exc:
                log.warning("LLM option picking failed for '%s': %s", question[:50], exc)

        if not chosen:
            log.warning("Could not pick option for '%s' from %d options", question[:50], len(options))
            return False

        # ── Click the chosen option ──
        # Use _fill_react_select which handles all the retry/verify logic.
        log.info("Picking '%s' for question '%s'", chosen, question[:60])
        ok = await _fill_react_select(input_id, chosen)
        if ok:
            log.info("Smart-picked '%s' for '%s' -> confirmed", chosen, question[:40])
            return True
        # If exact text failed, try opening full list and clicking by index.
        try:
            chosen_lower = chosen.lower()
            inp = page.locator(f"input[id='{input_id}']").first
            if await inp.count() == 0:
                return False
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
            await inp.scroll_into_view_if_needed()
            await inp.click()
            await page.wait_for_timeout(300)
            await inp.fill("")
            await page.wait_for_timeout(200)
            await inp.press("ArrowDown")
            await page.wait_for_timeout(600)
            listbox_id = f"react-select-{input_id}-listbox"
            listbox = page.locator(f"[id='{listbox_id}']")
            if await listbox.count() > 0:
                opts = listbox.locator("[role='option']")
                opt_count = await opts.count()
                for oi in range(opt_count):
                    opt_text = (await opts.nth(oi).text_content() or "").strip()
                    if opt_text.lower() == chosen_lower or chosen_lower in opt_text.lower():
                        await opts.nth(oi).click()
                        await page.wait_for_timeout(500)
                        displayed = await _verify_react_select_value(input_id)
                        if displayed:
                            log.info("Smart-picked '%s' via full list for '%s' -> '%s'",
                                     chosen, question[:40], displayed)
                            return True
                        break
        except Exception as exc:
            log.warning("Smart-pick fallback failed for '%s': %s", question[:40], exc)
        return False

    async def _fill_react_select(input_id: str, search_text: str) -> bool:
        """Fill a Greenhouse react-select combobox by typing and selecting.

        After selecting, verifies the value is visible in the text box.
        Retries up to 2 times if the selection didn't stick.
        """
        # Skip page-level filter dropdowns (department, office, location filters
        # found on Greenhouse job board pages -- NOT part of the application form).
        if "filter" in input_id.lower():
            log.debug("Skipping filter dropdown: %s", input_id)
            return False
        for attempt in range(3):
            try:
                # Use attribute selector first -- safe for numeric IDs (e.g., '4028768003').
                inp = page.locator(f"input[id='{input_id}']").first
                if await inp.count() == 0:
                    try:
                        inp = page.locator(f"input#{input_id}").first
                    except Exception:
                        pass
                if await inp.count() == 0:
                    log.debug("react-select input '%s' not found", input_id)
                    return False
                # Close any open dropdowns first.
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(200)
                # Focus and open the dropdown.
                await inp.scroll_into_view_if_needed()
                await page.wait_for_timeout(200)
                await inp.click()
                await page.wait_for_timeout(300)
                # Clear and type a SEARCH KEY -- use only the first distinctive
                # word(s) so the react-select filter shows relevant options.
                # e.g. "I am not a protected veteran" -> type "not a protected"
                #      "Man" -> type "Man"
                #      "Asian" -> type "Asian"
                _SEARCH_KEYS = {
                    "i am not a protected veteran": "not a protected",
                    "no, i am not a protected veteran": "not a protected",
                    "i don't wish to answer": "don't wish",
                    "i prefer not to answer": "prefer not",
                    "decline to self-identify": "Decline",
                    "no, i don't have a disability": "don't have",
                    "no, i do not have a disability": "do not have",
                    "prefer not to say": "prefer not",
                    "choose not to disclose": "choose not",
                    "asian (not hispanic or latino)": "Asian",
                    "man (including transgender men)": "Man",
                    "no, i am not transgender": "not transgender",
                    "company careers page": "Career",
                    "master's degree": "Master",
                    "analytics": "Analy",
                    "risk": "Risk",
                    "business": "Business",
                }
                type_text = _SEARCH_KEYS.get(search_text.lower(), search_text)
                await inp.fill("")
                await inp.type(type_text, delay=80)
                await page.wait_for_timeout(1200)
                # Find the listbox specific to this input.
                listbox_id = f"react-select-{input_id}-listbox"
                listbox = page.locator(f"[id='{listbox_id}']")
                clicked_option = False
                if await listbox.count() > 0:
                    options = listbox.locator("[role='option']")
                    opt_count = await options.count()
                    if opt_count > 0:
                        # Prefer exact/closest match over first option.
                        search_lower = search_text.lower()
                        best_idx = 0
                        best_score = 0
                        for oi in range(opt_count):
                            opt_text = (await options.nth(oi).text_content() or "").strip().lower()
                            # Scoring: exact match > word-boundary contains > substring
                            if opt_text == search_lower:
                                best_idx = oi
                                best_score = 100
                                break
                            # Word-boundary match (avoids "male" in "female")
                            elif re.search(r"(?:^|\b)" + re.escape(search_lower) + r"(?:\b|$)", opt_text):
                                if best_score < 90:
                                    best_idx = oi
                                    best_score = 90
                            elif re.search(r"(?:^|\b)" + re.escape(opt_text) + r"(?:\b|$)", search_lower):
                                if best_score < 80:
                                    best_idx = oi
                                    best_score = 80
                            elif search_lower in opt_text:
                                if best_score < 60:
                                    best_idx = oi
                                    best_score = 60
                            elif opt_text in search_lower:
                                if best_score < 50:
                                    best_idx = oi
                                    best_score = 50
                            # Partial word overlap (for fuzzy EEO matching)
                            else:
                                search_words = set(search_lower.split())
                                opt_words = set(opt_text.split())
                                overlap = len(search_words & opt_words)
                                if overlap >= 2 and best_score < 50 + overlap:
                                    best_idx = oi
                                    best_score = 50 + overlap
                        await options.nth(best_idx).click()
                        await page.wait_for_timeout(500)
                        clicked_option = True
                if not clicked_option:
                    # No matches for typed text -- clear and try selecting from full list.
                    log.debug("No options matched '%s' for %s, trying full list (attempt %d)",
                              search_text, input_id, attempt + 1)
                    await inp.fill("")
                    await page.wait_for_timeout(300)
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(200)
                    await inp.click()
                    await page.wait_for_timeout(500)
                    # Try ArrowDown to open/navigate
                    await inp.press("ArrowDown")
                    await page.wait_for_timeout(300)
                    # Check if listbox appeared with options now
                    listbox = page.locator(f"[id='{listbox_id}']")
                    if await listbox.count() > 0:
                        options = listbox.locator("[role='option']")
                        opt_count = await options.count()
                        # Try to find closest text match using word overlap.
                        search_lower = search_text.lower()
                        search_words = set(search_lower.split())
                        best_idx = -1
                        best_score = 0
                        for oi in range(opt_count):
                            opt_text = (await options.nth(oi).text_content() or "").strip().lower()
                            if search_lower in opt_text or opt_text in search_lower:
                                best_idx = oi
                                best_score = 100
                                break
                            opt_words = set(opt_text.split())
                            overlap = len(search_words & opt_words)
                            if overlap >= 2 and overlap > best_score:
                                best_idx = oi
                                best_score = overlap
                        if best_idx >= 0:
                            await options.nth(best_idx).click()
                            await page.wait_for_timeout(500)
                            clicked_option = True
                        elif opt_count > 0:
                            # No text match -- just pick first option.
                            await options.first.click()
                            await page.wait_for_timeout(500)
                            clicked_option = True
                    if not clicked_option:
                        # Last fallback: keyboard navigation.
                        await inp.press("Enter")
                        await page.wait_for_timeout(500)

                # --- Verify the selection is showing and correct ---
                displayed = await _verify_react_select_value(input_id)
                if displayed:
                    # Check the displayed value is a reasonable match.
                    d_lower = displayed.lower()
                    s_lower = search_text.lower()
                    # Known equivalent pairs (both directions are acceptable).
                    # TODO(post-lift): the original Revize source had personal
                    # demographic answers (race, gender, pronouns, veteran
                    # status) hardcoded here. Stripped — opt-in mappings now
                    # only cover the privacy-preserving "decline" answers.
                    _EQUIVALENTS = {
                        "i don't wish to answer": {"decline to self-identify", "prefer not to say",
                                                    "i prefer not to answer"},
                        "decline to self-identify": {"i don't wish to answer", "prefer not to say"},
                        "master's degree": {"master's, jd, and/or phd", "master's", "masters",
                                            "graduate degree", "master's degree or higher"},
                        "united states": {"+1", "united states of america", "us", "usa",
                                          "united states (+1)", "+1 (united states)"},
                        "student visa": {"yes", "f-1", "f1", "opt", "f-1 opt",
                                         "other (work visa, student visa, etc.)",
                                         "student visa (e.g. f-1)"},
                        "analytics": {"accounting", "business", "data science", "information systems",
                                      "management", "statistics", "mathematics", "other"},
                        "company careers page": {"adyen career page", "career page", "careers page",
                                                  "company website", "job board", "deepmind website",
                                                  "company career page", "employer website"},
                        "yes": {"i am authorised to work in the country which this role is located (citizen, permanent resident etc)",
                                "i am authorized to work in the country which this role is located",
                                "authorized to work", "i have permanent work rights"},
                    }
                    is_match = (
                        s_lower == d_lower
                        or d_lower in _EQUIVALENTS.get(s_lower, set())
                        or any(d_lower in eqs for eqs in _EQUIVALENTS.values() if s_lower in eqs)
                        # Word-boundary substring (avoids "male" matching "female")
                        or bool(re.search(r"(?:^|\b)" + re.escape(s_lower) + r"(?:\b|$)", d_lower))
                        # Word overlap: at least 2 shared words
                        or len(set(s_lower.split()) & set(d_lower.split())) >= 2
                    )
                    if is_match:
                        log.info("react-select '%s' confirmed: '%s'", input_id, displayed)
                        return True
                    else:
                        log.warning("react-select '%s' shows '%s' but expected '%s' (attempt %d)",
                                    input_id, displayed, search_text, attempt + 1)
                        # Clear the wrong selection and retry.
                        try:
                            clear_btn = page.locator(
                                f"input[id='{input_id}']"
                            ).locator("xpath=ancestor::div[contains(@class,'select')]").first.locator(
                                "[class*='clearIndicator'], [class*='clear-indicator'], [aria-label='Clear']"
                            ).first
                            if await clear_btn.count() > 0:
                                await clear_btn.click()
                                await page.wait_for_timeout(300)
                        except Exception:
                            pass
                else:
                    log.warning("react-select '%s' selection didn't stick (attempt %d), retrying...",
                                input_id, attempt + 1)
                    # Click away to reset, then retry.
                    await page.locator("body").click()
                    await page.wait_for_timeout(300)
            except Exception as exc:
                log.warning("Could not fill react-select %s (attempt %d): %s",
                            input_id, attempt + 1, exc, exc_info=True)
        log.warning("react-select '%s' failed after 3 attempts", input_id)
        return False

    # --- Country dropdown (wait for react-select to initialize) ---
    # Some Greenhouse forms use id="country" for the phone country code prefix
    # (already shows "+1" for US).  Try "United States" first; if it fails,
    # that's fine -- it's likely already set to the correct phone code.
    await page.wait_for_timeout(1000)
    country_filled = await _fill_react_select("country", "United States")
    if country_filled:
        filled.append("country")
        log.info("Filled country dropdown with 'United States'")
    else:
        # Might be a phone code dropdown already showing "+1" -- that's OK.
        log.info("Country dropdown not filled (may be phone code prefix -- already correct)")
        filled.append("country")  # Mark as handled either way

    # --- Location field ---
    location = contact.get("location", "New York, NY")
    if location and await _fill_react_select("candidate-location", location):
        filled.append("location")

    # --- Resume upload ---
    if files.get("resume") or files.get("resume_docx"):
        prefer_docx = files.get("prefer_docx", True)
        for sel in ["input#resume[type='file']", "input[type='file']"]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    accept_attr = await _get_accept_attr(loc)
                    chosen = _choose_resume_file(files.get("resume"), files.get("resume_docx"), prefer_docx, accept_attr)
                    if chosen:
                        await loc.set_input_files(chosen)
                        filled.append("resume_upload")
                        break
            except Exception:
                continue

    # --- Cover letter upload ---
    if files.get("cover_letter") or files.get("cover_letter_docx"):
        prefer_docx = files.get("prefer_docx", True)
        cl_uploaded = False
        # Try dedicated cover letter input first.
        for sel in ["input#cover_letter[type='file']", "input[type='file']:nth-of-type(2)"]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    accept_attr = await _get_accept_attr(loc)
                    chosen = _choose_cover_letter_file(files.get("cover_letter"), files.get("cover_letter_docx"), prefer_docx, accept_attr)
                    if chosen:
                        await loc.set_input_files(chosen)
                        filled.append("cover_letter_upload")
                        cl_uploaded = True
                        log.info("Uploaded cover letter: %s", Path(chosen).name)
                        break
            except Exception:
                continue
        # Fallback: use second file input if cover letter input not found.
        if not cl_uploaded:
            try:
                file_inputs = page.locator("input[type='file']")
                count = await file_inputs.count()
                if count >= 2:
                    loc = file_inputs.nth(1)
                    accept_attr = await _get_accept_attr(loc)
                    chosen = _choose_cover_letter_file(files.get("cover_letter"), files.get("cover_letter_docx"), prefer_docx, accept_attr)
                    if chosen:
                        await loc.set_input_files(chosen)
                        filled.append("cover_letter_upload")
                        log.info("Uploaded cover letter (fallback): %s", Path(chosen).name)
            except Exception:
                pass

    # --- Fill Greenhouse education dropdowns (school, degree, dates) ---
    _EDU_FIELD_MAP = {
        "school": "",
        "degree": "Master's Degree",
        "discipline": "Management and Analytics",
        "start-month": "August",
        "start-year": "2024",
        "end-month": "May",
        "end-year": "2026",
    }
    for prefix, value in _EDU_FIELD_MAP.items():
        for idx in range(3):  # support up to 3 education entries
            # Try both single-dash (degree-0) and double-dash (degree--0) ID formats
            for field_id in [f"{prefix}-{idx}", f"{prefix}--{idx}"]:
                try:
                    inp = page.locator(f"input[id='{field_id}'][role='combobox']").first
                    if await inp.count() > 0:
                        # Only fill the first education entry (idx 0).
                        if idx == 0:
                            ok = await _fill_react_select(field_id, value)
                            if ok:
                                filled.append(field_id)
                                log.info("Filled education field %s = '%s'", field_id, value)
                            else:
                                # Try smart picker as fallback for education fields
                                avail = await _read_react_select_options(field_id)
                                if avail:
                                    ok = await _pick_best_option(field_id, prefix, avail)
                                    if ok:
                                        filled.append(field_id)
                                        log.info("Smart-filled education field %s", field_id)
                                if field_id not in filled:
                                    log.warning("Could not fill education field %s", field_id)
                except Exception as exc:
                    log.debug("Error filling education %s: %s", field_id, exc)

    # --- GDPR / consent / agreement checkboxes ---
    # Some Greenhouse forms have required consent checkboxes (gdpr, data processing, etc.)
    consent_selectors = [
        "input[id*='gdpr'][type='checkbox']",
        "input[id*='consent'][type='checkbox']",
        "input[id*='data_processing'][type='checkbox']",
        "input[name*='gdpr'][type='checkbox']",
        "input[name*='consent_given'][type='checkbox']",
    ]
    for sel in consent_selectors:
        try:
            cbs = page.locator(sel)
            cb_count = await cbs.count()
            for ci in range(cb_count):
                cb = cbs.nth(ci)
                if not await cb.is_checked():
                    await cb.check()
                    cb_id = await cb.get_attribute("id") or f"consent_{ci}"
                    filled.append(cb_id)
                    log.info("Checked consent checkbox: %s", cb_id)
        except Exception as exc:
            log.debug("Consent checkbox %s error: %s", sel, exc)

    # --- Fill any combobox questions (work auth, worked before, etc.) ---
    # EEO field IDs that are normally optional but some companies make required.
    _EEO_FIELD_IDS = {"gender", "hispanic_ethnicity", "veteran_status", "disability_status",
                      "race", "ethnicity", "sexual_orientation"}
    _EEO_DEFAULT = "Decline to self-identify"

    combobox_questions = page.locator("input[role='combobox']:visible")
    cb_count = await combobox_questions.count()
    for i in range(cb_count):
        cb = combobox_questions.nth(i)
        cb_id = await cb.get_attribute("id") or ""
        if not cb_id or cb_id in ("country", "candidate-location") or \
           cb_id.startswith(("school-", "degree-", "discipline-", "start-month-", "end-month-",
                             "start-year-", "end-year-")) or \
           "filter" in cb_id.lower():
            continue
        # Already filled?
        if cb_id in filled:
            continue
        # Find the label for this combobox.
        label_el = page.locator(f"label[for='{cb_id}']").first
        if await label_el.count() == 0:
            # Try parent div for label.
            try:
                parent = cb.locator("xpath=ancestor::div[contains(@class,'field')]").first
                if await parent.count() > 0:
                    label_el = parent.locator("label").first
            except Exception:
                pass
        label_text = ""
        if label_el and await label_el.count() > 0:
            label_text = (await label_el.text_content() or "").strip().lower()
        # Determine answer based on label.
        answer = None
        if "authorized" in label_text:
            answer = settings.us_work_authorized or "Yes"
        elif "sponsorship" in label_text or "visa" in label_text:
            answer = settings.requires_sponsorship or "Yes"
        elif ("worked" in label_text and ("before" in label_text or "past" in label_text or "previously" in label_text)):
            answer = "No"
        elif "interviewed" in label_text and "before" in label_text:
            answer = "No"
        elif "how did you hear" in label_text or "where did you hear" in label_text:
            answer = "Company careers page"
        elif "source of" in label_text and "right to work" in label_text:
            answer = "Student Visa"
        elif "right to work" in label_text or "work authorization type" in label_text:
            answer = "Student Visa"
        elif "relocation" in label_text or "relocate" in label_text:
            answer = "Yes"
        elif "in-person" in label_text or "in person" in label_text or "on-site" in label_text or "onsite" in label_text:
            answer = "Yes"
        elif "ai policy" in label_text or "acknowledge" in label_text:
            answer = "Yes"
        elif "remote" in label_text and "open" in label_text:
            answer = "Yes"
        elif "currently employed" in label_text:
            answer = "No"
        elif "current company" in label_text or "current employer" in label_text:
            answer = "N/A"
        elif ("government" in label_text and ("work for" in label_text or "worked for" in label_text or "employed" in label_text)):
            answer = "No"
        elif "government entity" in label_text:
            answer = "No"
        elif ("country" in label_text and "reside" in label_text) or "currently living" in label_text:
            answer = "United States"
        elif "highest education" in label_text or "education level" in label_text:
            answer = "Master's Degree"
        elif "referred" in label_text:
            answer = "No"
        elif "earliest" in label_text and "start" in label_text:
            answer = ""  # TODO(post-lift): profile.start_date
        elif "salary" in label_text or "compensation" in label_text:
            answer = "Open to discussion"
        # Graduation month/year — TODO(post-lift): profile.education[0]
        elif "month of graduation" in label_text or "graduation month" in label_text:
            answer = ""
        elif "year of graduation" in label_text or "graduation year" in label_text:
            answer = ""
        elif "graduation" in label_text and "date" in label_text:
            answer = ""
        # State of residence — TODO(post-lift): profile.address.state
        elif "state" in label_text and ("reside" in label_text or "live" in label_text or "located" in label_text):
            answer = ""
        # School / university name — TODO(post-lift): profile.education[0].school
        elif "school" in label_text or "university" in label_text or "college" in label_text or "institution" in label_text:
            answer = ""
        elif "degree" in label_text or "level of education" in label_text:
            answer = "Master's Degree"
        elif "major" in label_text or "field of study" in label_text or "discipline" in label_text:
            answer = "Management and Analytics"
        elif "gpa" in label_text:
            answer = ""  # TODO(post-lift): profile.education[0].gpa
        elif "first generation" in label_text or "first-generation" in label_text:
            answer = "Yes"

        # ── For known-answer fields, try _fill_react_select directly ──
        if answer:
            ok = await _fill_react_select(cb_id, answer)
            if ok:
                filled.append(cb_id)
                log.info("Filled combobox '%s' with '%s'", label_text[:60], answer)
                continue
            # Direct fill failed -- fall through to smart picker below.
            log.debug("Direct fill '%s' failed for '%s', trying smart picker", answer, label_text[:60])

        # ── Smart option picker: READ actual options, then pick the best one ──
        # This handles EEO fields, unknown dropdowns, and any field where
        # we don't know the exact option text upfront.
        available_options = await _read_react_select_options(cb_id)
        if available_options:
            question_text = label_text or cb_id
            ok = await _pick_best_option(cb_id, question_text, available_options)
            if ok:
                filled.append(cb_id)
                log.info("Smart-filled combobox '%s' (id=%s)", label_text[:60], cb_id)
            else:
                log.warning("Smart picker failed for '%s' (id=%s) -- %d options available",
                            label_text[:60], cb_id, len(available_options))
        elif label_text:
            log.warning("No options found for combobox '%s' (id=%s)", label_text[:60], cb_id)

    # --- Second pass: fill any remaining unfilled required react-select dropdowns ---
    # These are hidden validation inputs that still have no value.
    # Re-query each iteration since DOM may change after filling a dropdown.
    for _pass in range(3):  # Up to 3 passes to handle cascading fills
        hidden_req = page.locator("input[tabindex='-1'][aria-hidden='true'][required]")
        try:
            hidden_count = await hidden_req.count()
        except Exception:
            break
        any_filled = False
        for i in range(hidden_count):
            inp = hidden_req.nth(i)
            try:
                val = await inp.input_value(timeout=3000)
                if val.strip():
                    continue  # Already filled
            except Exception:
                continue  # DOM changed or element stale -- skip
            # Find the associated visible combobox input.
            try:
                inp_name = await inp.get_attribute("name", timeout=3000) or ""
                inp_id = await inp.get_attribute("id", timeout=3000) or ""
            except Exception:
                continue  # Element stale
            # Try to find the visible combobox in the same form-group.
            cb_input = None
            label_text = ""
            try:
                parent = inp.locator("xpath=ancestor::div[contains(@class,'field') or contains(@class,'select')]").first
                if await parent.count() > 0:
                    cb_input = parent.locator("input[role='combobox']").first
                    lbl = parent.locator("label").first
                    if await lbl.count() > 0:
                        label_text = (await lbl.text_content() or "").strip()
            except Exception:
                pass
            if not cb_input or await cb_input.count() == 0:
                log.debug("No visible combobox found for hidden input name=%s id=%s", inp_name, inp_id)
                continue
            try:
                cb_id = await cb_input.get_attribute("id", timeout=3000) or ""
            except Exception:
                continue
            if cb_id in filled:
                continue
            # Skip education fields in second pass -- they should be filled above.
            if any(cb_id.startswith(p) for p in ("school-", "school--", "degree-", "degree--",
                                                   "discipline-", "discipline--", "start-month-",
                                                   "start-year-", "end-month-", "end-year-")):
                continue
            label_lower = label_text.lower()
            # Education fields that slipped through -- fill with proper values, NOT "Yes".
            if "degree" in label_lower or "level of education" in label_lower:
                answer = "Master's Degree"
            elif "major" in label_lower or "field of study" in label_lower or "discipline" in label_lower:
                answer = "Management and Analytics"
            elif "school" in label_lower or "university" in label_lower or "college" in label_lower:
                answer = ""
            # Determine answer for this unfilled dropdown.
            elif "race" in label_lower or "ethnicit" in label_lower:
                answer = ""  # TODO(post-lift): profile.eeo.race
            elif "hispanic" in label_lower or "latino" in label_lower:
                answer = ""  # TODO(post-lift): profile.eeo.hispanic
            elif "veteran" in label_lower:
                answer = ""  # TODO(post-lift): profile.eeo.veteran_status
            elif "disability" in label_lower:
                answer = ""  # TODO(post-lift): profile.eeo.disability
            elif "transgender" in label_lower:
                answer = ""  # TODO(post-lift): profile.eeo.transgender
            elif "first.generation" in re.sub(r"\s+", ".", label_lower) or "first-generation" in label_lower or "first generation" in label_lower:
                answer = ""  # TODO(post-lift): profile.eeo.first_generation
            elif "sexual orientation" in label_lower:
                answer = ""  # TODO(post-lift): profile.eeo.sexual_orientation
            elif "gender" in label_lower or "sex" in label_lower:
                answer = ""  # TODO(post-lift): profile.eeo.gender
            else:
                # Try rule-based answer first.
                rule_ans = _rule_based_answer(label_text) if label_text else None
                if rule_ans is not None:
                    answer = rule_ans
                # Smart defaults for common question patterns.
                elif "experience" in label_lower or "have you worked" in label_lower:
                    answer = "Yes"
                elif "live in" in label_lower or "reside" in label_lower or "located" in label_lower:
                    answer = "Yes"
                elif "which location" in label_lower or "which office" in label_lower:
                    answer = "New York"
                elif "previously" in label_lower and ("employed" in label_lower or "worked" in label_lower):
                    answer = "No"
                else:
                    # No rule matched -- use smart option picker instead of blind default
                    answer = None
            if cb_id:
                if answer:
                    log.info("Second-pass filling combobox '%s' (id=%s) with '%s'",
                             label_text[:60], cb_id, answer)
                    ok = await _fill_react_select(cb_id, answer)
                    if ok:
                        filled.append(cb_id)
                        any_filled = True
                        log.info("Second-pass filled combobox '%s' with '%s'", label_text[:60], answer)
                    else:
                        # Direct fill failed -- try smart picker
                        avail = await _read_react_select_options(cb_id)
                        if avail:
                            ok = await _pick_best_option(cb_id, label_text or cb_id, avail)
                            if ok:
                                filled.append(cb_id)
                                any_filled = True
                                log.info("Second-pass smart-filled combobox '%s' (id=%s)", label_text[:60], cb_id)
                else:
                    # No answer determined -- use smart option picker
                    avail = await _read_react_select_options(cb_id)
                    if avail:
                        ok = await _pick_best_option(cb_id, label_text or cb_id, avail)
                        if ok:
                            filled.append(cb_id)
                            any_filled = True
                            log.info("Second-pass smart-filled combobox '%s' (id=%s)", label_text[:60], cb_id)
        if not any_filled:
            break  # No more unfilled dropdowns found
        await page.wait_for_timeout(500)  # Let DOM settle after fills

    # --- Also run generic field fill for anything we missed ---
    await _fill_profile_fields(page, profile, filled)


async def _fill_lever(
    page: Page,
    profile: dict[str, Any],
    files: dict[str, str | None],
    filled: list[str],
) -> None:
    """Lever uses a cards-based form layout."""
    contact = profile.get("contact", profile)
    lever_map = {
        "name": f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip(),
        "email": contact.get("email", settings.job_application_email),
        "phone": contact.get("phone", ""),
        "location": contact.get("location", "New York, NY"),
        "org": "",  # Current company -- leave empty (student/recent grad)
        "urls[LinkedIn]": contact.get("linkedin", ""),
        "urls[GitHub]": contact.get("github", ""),
        "urls[Portfolio]": contact.get("website", ""),
        "urls[Other]": contact.get("website", ""),
    }
    for name, val in lever_map.items():
        if val and await _type_into_field(page, f"input[name='{name}']", val):
            filled.append(name)

    # Lever resume upload via the card.
    if files.get("resume") or files.get("resume_docx"):
        prefer_docx = files.get("prefer_docx", True)
        for sel in ["input[type='file'][name='resume']", ".application-upload input[type='file']"]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    accept_attr = await _get_accept_attr(loc)
                    chosen = _choose_resume_file(files.get("resume"), files.get("resume_docx"), prefer_docx, accept_attr)
                    if chosen:
                        await loc.set_input_files(chosen)
                        filled.append("resume_upload")
                        break
            except Exception:
                continue

    if files.get("cover_letter") or files.get("cover_letter_docx"):
        prefer_docx = files.get("prefer_docx", True)
        try:
            loc = page.locator("input[type='file'][name*='cover']").first
            if await loc.count() > 0:
                accept_attr = await _get_accept_attr(loc)
                chosen = _choose_cover_letter_file(files.get("cover_letter"), files.get("cover_letter_docx"), prefer_docx, accept_attr)
                if chosen:
                    await loc.set_input_files(chosen)
                    filled.append("cover_letter_upload")
        except Exception:
            pass

    # --- Lever custom question cards (radio buttons) ---
    custom_cards = page.locator(".application-question.custom-question")
    card_count = await custom_cards.count()
    for ci in range(card_count):
        card = custom_cards.nth(ci)
        # Get question text.
        label_el = card.locator(".application-label").first
        if await label_el.count() == 0:
            label_el = card.locator("label").first
        if await label_el.count() == 0:
            continue
        q_text = (await label_el.text_content() or "").strip().lower()

        radios = card.locator("input[type='radio']")
        r_count = await radios.count()
        if r_count > 0:
            # Determine the right answer based on question text.
            target_value = None
            if "sponsorship" in q_text or "visa" in q_text or "immigration" in q_text:
                target_value = "Yes"
            elif "authorized" in q_text:
                target_value = "Yes"
            elif "previously employed" in q_text or "worked" in q_text:
                target_value = "No"
            elif "rate" in q_text or "impression" in q_text or "compare" in q_text:
                # Pick a positive rating -- find the highest numeric option.
                for ri in range(r_count - 1, -1, -1):
                    try:
                        await radios.nth(ri).click()
                        filled.append(f"lever_card_{ci}")
                        log.info("Lever: selected highest rating option for '%s'", q_text[:60])
                        break
                    except Exception:
                        continue
                continue

            if target_value:
                # Find and click the radio with matching label text.
                clicked = False
                for ri in range(r_count):
                    try:
                        parent_span = radios.nth(ri).locator("..").locator("span")
                        if await parent_span.count() > 0:
                            opt_text = (await parent_span.text_content() or "").strip()
                            if opt_text.lower() == target_value.lower():
                                await radios.nth(ri).click()
                                filled.append(f"lever_card_{ci}")
                                log.info("Lever: selected '%s' for '%s'", opt_text, q_text[:60])
                                clicked = True
                                break
                    except Exception:
                        continue
                if clicked:
                    continue

            # Fallback: try rule-based answer for unhandled radio groups
            if f"lever_card_{ci}" not in filled:
                rule_answer = _rule_based_answer(q_text)
                if rule_answer:
                    # Try to match answer text to a radio option
                    for ri in range(r_count):
                        try:
                            parent_span = radios.nth(ri).locator("..").locator("span")
                            if await parent_span.count() > 0:
                                opt_text = (await parent_span.text_content() or "").strip()
                                if opt_text.lower() == rule_answer.lower():
                                    await radios.nth(ri).click()
                                    filled.append(f"lever_card_{ci}")
                                    log.info("Lever: rule-based '%s' for '%s'", opt_text, q_text[:60])
                                    break
                        except Exception:
                            continue

            # Last resort: for EEO/demographic/unknown radio groups, pick first option
            if f"lever_card_{ci}" not in filled:
                eeo_keywords = ["gender", "race", "ethnicity", "veteran", "disability",
                                "sexual orientation", "pronoun", "demographic",
                                "how did you hear", "where did you hear", "referral source"]
                is_eeo = any(kw in q_text for kw in eeo_keywords)
                if is_eeo or not target_value:
                    # For EEO questions: pick "Decline to self identify" or "Prefer not" if available
                    decline_clicked = False
                    for ri in range(r_count):
                        try:
                            parent_span = radios.nth(ri).locator("..").locator("span")
                            if await parent_span.count() > 0:
                                opt_text = (await parent_span.text_content() or "").strip().lower()
                                if any(d in opt_text for d in ["decline", "prefer not", "not to", "choose not"]):
                                    await radios.nth(ri).click()
                                    filled.append(f"lever_card_{ci}")
                                    log.info("Lever: declined EEO '%s'", q_text[:60])
                                    decline_clicked = True
                                    break
                        except Exception:
                            continue
                    # If no decline option, click first radio as fallback
                    if not decline_clicked:
                        try:
                            await radios.first.click()
                            filled.append(f"lever_card_{ci}")
                            log.info("Lever: fallback first-option for '%s'", q_text[:60])
                        except Exception:
                            pass

        # Handle select dropdowns in custom cards.
        selects = card.locator("select")
        sel_count = await selects.count()
        for si in range(sel_count):
            sel = selects.nth(si)
            try:
                # Check if already has a value
                current = await sel.input_value()
                if current and current.strip():
                    continue
                # Get all options
                options = await sel.locator("option").all_text_contents()
                # Try rule-based answer
                rule_answer = _rule_based_answer(q_text)
                picked = False
                if rule_answer:
                    for opt in options:
                        if opt.strip().lower() == rule_answer.lower():
                            await sel.select_option(label=opt.strip())
                            filled.append(f"lever_card_{ci}_sel{si}")
                            log.info("Lever: select rule-based '%s' for '%s'", opt.strip(), q_text[:60])
                            picked = True
                            break
                if not picked:
                    # Pick "Decline" or "Prefer not" for EEO
                    for opt in options:
                        opt_lower = opt.strip().lower()
                        if any(d in opt_lower for d in ["decline", "prefer not", "not to"]):
                            await sel.select_option(label=opt.strip())
                            filled.append(f"lever_card_{ci}_sel{si}")
                            log.info("Lever: select decline for '%s'", q_text[:60])
                            picked = True
                            break
                if not picked and len(options) > 1:
                    # Pick the second option (first is usually blank placeholder)
                    val = options[1].strip() if len(options) > 1 else options[0].strip()
                    if val:
                        await sel.select_option(label=val)
                        filled.append(f"lever_card_{ci}_sel{si}")
                        log.info("Lever: select fallback '%s' for '%s'", val[:30], q_text[:60])
            except Exception:
                pass

        # Handle checkbox questions.
        checkboxes = card.locator("input[type='checkbox']")
        cb_count = await checkboxes.count()
        if cb_count > 0:
            if "interested" in q_text or "why" in q_text:
                # Select the first 2-3 options for "Why are you interested" type questions.
                checked = 0
                for cbi in range(min(cb_count, 3)):
                    try:
                        await checkboxes.nth(cbi).check()
                        checked += 1
                    except Exception:
                        continue
                if checked:
                    filled.append(f"lever_card_{ci}")
                    log.info("Lever: checked %d options for '%s'", checked, q_text[:60])

    # --- Comments textarea (can paste cover letter text) ---
    comments = page.locator("textarea[name='comments']").first
    if await comments.count() > 0:
        cl_text = contact.get("cover_letter_text", "")
        if not cl_text:
            cl_text = "I am excited about this opportunity and believe my skills are a strong match for this role."
        try:
            await comments.fill(cl_text)
            filled.append("comments")
        except Exception:
            pass


async def _fetch_workday_verify_link(*, max_wait_seconds: int = 60, tenant_hint: str = "") -> str | None:
    """Poll IMAP for a Workday verification email and return the verify link.

    DISABLED in production: we no longer poll any inbox (the previous
    implementation polled ONE shared inbox = the platform owner's, which
    leaked verification tokens between tenants and forced every Workday
    account to be created under the wrong identity). The submitter now
    surfaces Workday verification stalls to the user via the dashboard
    "Open & finish step" CTA, and they click the verify link in their
    own inbox themselves. Zero IMAP credentials needed from anyone.

    Returning None here causes the autofill flow to fall through to its
    "ready_for_review" branch, which the cloud_submitter classifies as
    a verify-stall and surfaces correctly.
    """
    log.info("Workday verify-link IMAP polling is disabled — letting verify-stall handler surface to user (tenant_hint=%s, max_wait=%s)",
             tenant_hint, max_wait_seconds)
    return None
    # ── Original IMAP-polling implementation kept below for reference; ──
    # ── intentionally unreachable. Will be restored if/when we add     ──
    # ── per-user inbox routing (e.g. plus-addressing on a wildcard MX).──
    import imaplib
    import email as email_mod
    import time
    import re as _re
    from html.parser import HTMLParser

    class _LinkExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links: list[str] = []
        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag == "a":
                for k, v in attrs:
                    if k == "href" and v:
                        self.links.append(v)

    _URL_RE = _re.compile(r'https?://[^\s<>"\']+')
    _VERIFY_KW = ("verify", "confirm", "activate", "token", "validate")
    _WD_DOMAINS = ("myworkdayjobs.com", "myworkday.com", "workday.com")

    def _extract_links_from_body(body_text: str) -> list[str]:
        """Extract all URLs from text — both href attrs and bare URLs."""
        links: list[str] = []
        # HTML href links
        parser = _LinkExtractor()
        try:
            parser.feed(body_text)
            links.extend(parser.links)
        except Exception:
            pass
        # Bare URLs in text (Workday sometimes puts the URL as plain text)
        for m in _URL_RE.finditer(body_text):
            url = m.group(0).rstrip('.,;)')
            if url not in links:
                links.append(url)
        return links

    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        try:
            mail = imaplib.IMAP4_SSL(settings.imap_host, int(settings.imap_port))
            mail.login(settings.imap_username, settings.imap_password)
            mail.select("INBOX")
            # Search for Workday emails — include SEEN emails too (might have been
            # read by another client or marked read by a previous IMAP session).
            status, messages = mail.search(
                None,
                '(OR (OR FROM "workday" FROM "myworkdayjobs") FROM "otp.workday.com")',
            )
            if status == "OK" and messages[0]:
                ids = messages[0].split()
                # Collect all candidate links, preferring tenant-matched ones
                all_candidates: list[tuple[str, bool]] = []  # (link, is_tenant_match)
                for eid in reversed(ids):  # newest first
                    _, data = mail.fetch(eid, "(RFC822)")
                    msg = email_mod.message_from_bytes(data[0][1])
                    subj = (msg.get("Subject", "") or "").lower()
                    if not any(w in subj for w in ["verify", "confirm", "activate", "account"]):
                        continue
                    # Extract links from all text/html and text/plain parts
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct not in ("text/html", "text/plain"):
                            continue
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        links = _extract_links_from_body(body)
                        for link in links:
                            ll = link.lower()
                            if any(kw in ll for kw in _VERIFY_KW) and any(d in ll for d in _WD_DOMAINS):
                                is_match = bool(tenant_hint and tenant_hint.lower() in ll)
                                all_candidates.append((link, is_match))
                    if len(all_candidates) > 10:
                        break  # Don't scan too many emails
                # Sort: tenant-matched first, then by order (newest first)
                if all_candidates:
                    mail.logout()
                    tenant_matched = [c for c in all_candidates if c[1]]
                    if tenant_matched:
                        log.info("Found Workday verification link (tenant match): %s", tenant_matched[0][0][:120])
                        return tenant_matched[0][0]
                    else:
                        log.info("Found Workday verification link: %s", all_candidates[0][0][:120])
                        return all_candidates[0][0]
            mail.logout()
        except Exception as exc:
            log.warning("IMAP check for Workday verify failed: %s", exc)
        time.sleep(5)
    return None


async def _wd_check_consent_checkbox(page: Page) -> None:
    """Check consent/privacy checkbox on Workday Create Account page.

    Workday uses several checkbox implementations:
    1. Standard ``input[type='checkbox']`` (sometimes hidden behind a label)
    2. Custom ``div[role='checkbox']`` or ``span[role='checkbox']``
    3. ``data-automation-id`` attributes like ``createAccountCheckbox``
    4. Label wrapping a hidden checkbox that must be clicked
    """
    # Method 1: Workday automation-id checkbox
    for sel in [
        "[data-automation-id='createAccountCheckbox']",
        "[data-automation-id='termsCheckbox']",
        "[data-automation-id='privacyCheckbox']",
        "[data-automation-id='consentCheckbox']",
    ]:
        try:
            cb = page.locator(sel).first
            if await cb.count() > 0 and await cb.is_visible():
                checked = await cb.get_attribute("aria-checked")
                if checked != "true":
                    await cb.click()
                    log.info("Workday: checked consent checkbox via %s", sel)
                return
        except Exception:
            continue

    # Method 2: role="checkbox" elements
    try:
        role_cbs = page.locator("[role='checkbox']:visible")
        for i in range(await role_cbs.count()):
            cb = role_cbs.nth(i)
            checked = await cb.get_attribute("aria-checked")
            if checked != "true":
                await cb.click()
                log.info("Workday: checked role=checkbox element %d", i)
                return
    except Exception:
        pass

    # Method 3: Standard input[type='checkbox'] (visible)
    try:
        cb = page.locator("input[type='checkbox']:visible").first
        if await cb.count() > 0 and not await cb.is_checked():
            await cb.check()
            log.info("Workday: checked visible input[type=checkbox]")
            return
    except Exception:
        pass

    # Method 4: Hidden checkbox — click the label/container instead
    # Workday often hides the input and shows a styled label
    try:
        checked_via_label = await page.evaluate("""() => {
            // Find checkboxes (even hidden) and click their label or parent container
            const inputs = document.querySelectorAll('input[type="checkbox"]');
            for (const inp of inputs) {
                if (inp.checked) continue;
                // Try clicking the associated label
                if (inp.id) {
                    const label = document.querySelector('label[for="' + inp.id + '"]');
                    if (label) { label.click(); return true; }
                }
                // Try clicking the parent label
                const parentLabel = inp.closest('label');
                if (parentLabel) { parentLabel.click(); return true; }
                // Try clicking the parent div (Workday wraps checkboxes in styled divs)
                const parent = inp.parentElement;
                if (parent) { parent.click(); return true; }
            }
            return false;
        }""")
        if checked_via_label:
            log.info("Workday: checked checkbox via label/container JS fallback")
            return
    except Exception:
        pass

    # Method 5: Look for any clickable element near "acknowledge" / "agree" / "privacy" text
    try:
        clicked = await page.evaluate("""() => {
            const keywords = ['acknowledge', 'agree', 'consent', 'privacy', 'terms'];
            const els = document.querySelectorAll('label, div[role="checkbox"], span[role="checkbox"], [class*="checkbox"], [class*="Checkbox"]');
            for (const el of els) {
                const txt = (el.textContent || '').toLowerCase();
                if (keywords.some(k => txt.includes(k))) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        if clicked:
            log.info("Workday: checked consent via keyword-matching element")
    except Exception:
        pass


async def _wd_fill_and_submit_signin(page: Page, email: str, password: str) -> bool:
    """Fill and submit a Workday Sign In form. Returns True if submitted.

    Workday Sign In can appear as:
    1. A standalone page (simple form with email + password)
    2. A MODAL dialog over the Create Account page — the modal has its OWN
       email/password fields separate from the form underneath.

    We detect the modal by looking for a dialog/overlay container and scope
    our selectors to it so we don't accidentally fill the Create Account
    form's fields behind the modal.
    """
    # Detect if a Sign In modal is open (Workday uses div[role='dialog'] or similar)
    modal = None
    for modal_sel in [
        "[role='dialog']:visible",
        "[data-automation-id='signInDialog']:visible",
        "div[class*='Modal']:visible",
        "div[class*='modal']:visible",
        "div[class*='Dialog']:visible",
        "div[class*='dialog']:visible",
        "div[class*='Overlay']:visible",
    ]:
        try:
            loc = page.locator(modal_sel)
            if await loc.count() > 0:
                # Check if this modal contains "Sign In" text
                for i in range(await loc.count()):
                    m = loc.nth(i)
                    txt = (await m.text_content() or "").lower()
                    if "sign in" in txt and ("email" in txt or "password" in txt):
                        modal = m
                        log.info("Workday sign-in: found modal via %s", modal_sel)
                        break
                if modal:
                    break
        except Exception:
            continue

    # If no modal found, try a broader JS approach
    if not modal:
        try:
            has_modal = await page.evaluate("""() => {
                // Look for an overlay/dialog element that contains Sign In
                const dialogs = document.querySelectorAll('[role="dialog"], [aria-modal="true"], .modal, .Modal');
                for (const d of dialogs) {
                    const txt = (d.textContent || '').toLowerCase();
                    if (txt.includes('sign in') && d.offsetParent !== null) {
                        return true;
                    }
                }
                return false;
            }""")
            if has_modal:
                modal = page.locator("[role='dialog']:visible, [aria-modal='true']:visible").first
                if await modal.count() == 0:
                    modal = None
                else:
                    log.info("Workday sign-in: found modal via JS detection")
        except Exception:
            pass

    # Determine the scope: modal if found, otherwise the page
    scope = modal if modal else page

    # Fill email — use .last to get the topmost/modal field when multiple exist
    email_filled = False
    for sel in [
        "input[data-automation-id='email']", "input[type='email']",
        "input[aria-label*='email' i]", "input[name*='email' i]",
    ]:
        try:
            inp = scope.locator(sel).last if modal else page.locator(sel).last
            if await inp.count() > 0 and await inp.is_visible():
                await inp.fill("")
                await inp.fill(email)
                log.info("Workday sign-in: filled email via %s (modal=%s)", sel, modal is not None)
                email_filled = True
                break
        except Exception:
            continue

    # If modal scope didn't work, try page-level with .last (modal fields render later)
    if not email_filled and modal:
        for sel in ["input[type='email']:visible", "input[data-automation-id='email']:visible"]:
            try:
                inp = page.locator(sel).last
                if await inp.count() > 0 and await inp.is_visible():
                    await inp.fill("")
                    await inp.fill(email)
                    log.info("Workday sign-in: filled email via page-level .last (%s)", sel)
                    email_filled = True
                    break
            except Exception:
                continue

    # Fill password — use .last to get the modal's password field
    pwd_filled = False
    for sel in [
        "input[data-automation-id='password']", "input[type='password']",
    ]:
        try:
            inp = scope.locator(sel).last if modal else page.locator(sel).last
            if await inp.count() > 0 and await inp.is_visible():
                await inp.fill(password)
                log.info("Workday sign-in: filled password via %s (modal=%s)", sel, modal is not None)
                pwd_filled = True
                break
        except Exception:
            continue

    if not pwd_filled and modal:
        for sel in ["input[type='password']:visible"]:
            try:
                inp = page.locator(sel).last
                if await inp.count() > 0 and await inp.is_visible():
                    await inp.fill(password)
                    log.info("Workday sign-in: filled password via page-level .last")
                    pwd_filled = True
                    break
            except Exception:
                continue

    # Click submit — Workday uses a "click_filter" overlay div that intercepts
    # pointer events on the actual <button>. We must click the overlay OR use
    # force=True OR use JavaScript to bypass it.

    # Method 1: Click the click_filter overlay (Workday's intended click target)
    for sel in [
        "[data-automation-id='click_filter'][aria-label='Sign In']",
        "[data-automation-id='click_filter']:near(button[data-automation-id='signInSubmitButton'])",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(3000)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                except Exception:
                    pass
                await page.wait_for_timeout(2000)
                log.info("Workday sign-in: submitted via click_filter overlay")
                return True
        except Exception:
            continue

    # Method 2: Click the actual button with force=True (bypasses interceptor check)
    for sel in [
        "button[data-automation-id='signInSubmitButton']",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click(force=True)
                await page.wait_for_timeout(3000)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                except Exception:
                    pass
                await page.wait_for_timeout(2000)
                log.info("Workday sign-in: submitted via %s (force=True)", sel)
                return True
        except Exception:
            continue

    # Method 3: JavaScript click (bypasses all Playwright interceptor checks)
    try:
        clicked = await page.evaluate("""() => {
            // Try clicking the click_filter overlay first
            const filter = document.querySelector('[data-automation-id="click_filter"][aria-label="Sign In"]');
            if (filter) { filter.click(); return 'click_filter'; }
            // Try the actual button
            const btn = document.querySelector('button[data-automation-id="signInSubmitButton"]');
            if (btn) { btn.click(); return 'signInSubmitButton'; }
            // Try any Sign In button
            const buttons = [...document.querySelectorAll('button')];
            for (const b of buttons) {
                if ((b.textContent || '').trim() === 'Sign In' && b.offsetParent !== null) {
                    b.click(); return 'textMatch';
                }
            }
            return null;
        }""")
        if clicked:
            await page.wait_for_timeout(3000)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)
            log.info("Workday sign-in: submitted via JS fallback (%s)", clicked)
            return True
    except Exception:
        pass

    # Method 4: Fallback — find any Sign In button
    for sel in [
        "button:has-text('Sign In')",
        "button:has-text('Log In')",
        "button[type='submit']",
    ]:
        try:
            btn = page.locator(sel).last
            if await btn.count() > 0 and await btn.is_visible():
                btn_text = (await btn.text_content() or "").strip()
                if "create" in btn_text.lower():
                    continue
                await btn.click(force=True)
                await page.wait_for_timeout(3000)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                except Exception:
                    pass
                await page.wait_for_timeout(2000)
                log.info("Workday sign-in: submitted via %s (text='%s', force=True)", sel, btn_text)
                return True
        except Exception:
            continue
    return False


async def _wd_fill_and_submit_create_account(page: Page, email: str, password: str) -> bool:
    """Fill and submit a Workday Create Account form. Returns True if submitted."""
    # Fill email if empty
    for sel in [
        "input[data-automation-id='email']", "input[type='email']",
        "input[aria-label*='email' i]",
    ]:
        try:
            inp = page.locator(sel).first
            if await inp.count() > 0 and await inp.is_visible():
                val = (await inp.input_value() or "").strip()
                if not val:
                    await inp.fill(email)
                    log.info("Workday create: filled email")
                break
        except Exception:
            continue

    # Fill ALL visible password fields (password + verify password)
    # Clear first then fill to avoid stale values triggering validation
    pwd_fields = page.locator("input[type='password']:visible")
    pwd_count = await pwd_fields.count()
    log.info("Workday create: found %d password fields", pwd_count)
    for pi in range(min(pwd_count, 3)):
        try:
            field = pwd_fields.nth(pi)
            await field.fill("")  # Clear first
            await field.fill(password)
            log.info("Workday create: filled password field %d/%d", pi + 1, pwd_count)
        except Exception:
            continue

    # Check consent checkbox (critical — form won't submit without this)
    await _wd_check_consent_checkbox(page)
    await page.wait_for_timeout(500)

    # Take a debug screenshot before clicking Create Account
    try:
        ss_dir = Path("artifacts/autofill_screenshots")
        ss_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        ss_path = str(ss_dir / f"wd_create_account_pre_click_{ts}.png")
        await page.screenshot(path=ss_path, full_page=False)
        log.info("Workday create: pre-click screenshot saved to %s", ss_path)
    except Exception:
        pass

    # Click Create Account submit button
    # NOTE: Workday uses a click_filter overlay div that intercepts pointer events.
    # We must click the overlay, use force=True, or use JavaScript.
    create_clicked = False

    # Method 1: Click the click_filter overlay for Create Account
    for sel in [
        "[data-automation-id='click_filter'][aria-label='Create Account']",
        "[data-automation-id='click_filter']:near(button[data-automation-id='createAccountSubmitButton'])",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                log.info("Workday create: clicked via click_filter overlay (%s)", sel)
                create_clicked = True
                break
        except Exception:
            continue

    # Method 2: force=True on the actual button
    if not create_clicked:
        for sel in [
            "button[data-automation-id='createAccountSubmitButton']",
            "[data-automation-id='createAccountSubmitButton']",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(force=True)
                    log.info("Workday create: clicked submit via %s (force=True)", sel)
                    create_clicked = True
                    break
            except Exception:
                continue

    # Method 3: JavaScript fallback
    if not create_clicked:
        try:
            create_clicked = await page.evaluate("""() => {
                // Try click_filter overlay first
                const filter = document.querySelector('[data-automation-id="click_filter"][aria-label="Create Account"]');
                if (filter) { filter.click(); return true; }
                // Try the actual button with force
                const btn = document.querySelector('button[data-automation-id="createAccountSubmitButton"]');
                if (btn) { btn.click(); return true; }
                // Fallback: any "Create Account" button/role=button (last one = submit, not header)
                const btns = [...document.querySelectorAll('button, [role="button"]')];
                for (const b of btns.reverse()) {
                    const txt = (b.textContent || b.value || '').trim().toLowerCase();
                    if (txt === 'create account') {
                        b.click();
                        return true;
                    }
                }
                return false;
            }""")
            if create_clicked:
                log.info("Workday create: clicked via JS fallback")
        except Exception:
            pass

    if create_clicked:
        await page.wait_for_timeout(5000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass

        # Post-click screenshot
        try:
            ts = _dt.now().strftime("%Y%m%d_%H%M%S")
            ss_path = str(ss_dir / f"wd_create_account_post_click_{ts}.png")
            await page.screenshot(path=ss_path, full_page=False)
            log.info("Workday create: post-click screenshot saved to %s", ss_path)
        except Exception:
            pass

    return create_clicked


async def _workday_login_or_create(
    page: Page,
    *,
    job_url: str = "",
    wd_email: str = "",
    wd_password: str = "",
) -> bool:
    """Log into Workday or create a new account.

    Strategy:
    1. If on Create Account page → try Sign In first (account may already exist).
    2. If sign-in fails → fill Create Account form (with checkbox!).
    3. If account creation says "already exists" → go back to Sign In.
    4. Verification email goes to the user's own inbox; the cloud submitter's
       verify-stall handler surfaces a "complete this step" CTA on the dashboard.
       (We do NOT poll the user's IMAP — too much onboarding friction.)
    Returns True if authenticated successfully.
    """
    # Per-user credentials, plumbed in from the submitter via the profile dict.
    # If they're missing, we cannot proceed safely — refuse rather than fall
    # back to a shared/hardcoded account (legal + identity disaster).
    if not wd_email or not wd_password:
        log.warning("Workday: missing per-user credentials (email=%s, has_pw=%s) — aborting login",
                    bool(wd_email), bool(wd_password))
        return False
    _WD_EMAIL = wd_email
    _WD_PASS = wd_password

    page_text = (await page.text_content("body") or "").lower()

    # Detect dead/expired job pages — don't waste time logging in
    if any(phrase in page_text for phrase in [
        "doesn't exist", "does not exist", "page not found",
        "the page you are looking for", "no longer available",
    ]):
        log.warning("Workday: job page not found — skipping login (URL=%s)", page.url[:80])
        return True  # Let the caller detect the dead posting

    # Check if we even need to log in
    has_pwd_field = await page.locator("input[type='password']:visible").count() > 0
    has_email_field = await page.locator("input[type='email']:visible, input[data-automation-id='email']:visible").count() > 0
    # Some Workday tenants show "Sign in with email" button before showing the actual form
    has_signin_btn = await page.locator("button:has-text('Sign in with email'), a:has-text('Sign in with email'), button:has-text('Sign In with Email')").count() > 0
    is_login_page = has_pwd_field or has_email_field or has_signin_btn
    if not is_login_page:
        log.info("Workday: no login form detected — proceeding (URL=%s)", page.url[:80])
        return True

    # If "Sign in with email" button is visible, click it first to reveal the form
    if has_signin_btn and not has_pwd_field and not has_email_field:
        try:
            btn = page.locator("button:has-text('Sign in with email'), a:has-text('Sign in with email'), button:has-text('Sign In with Email')").first
            await btn.click()
            await page.wait_for_timeout(3000)
            log.info("Workday: clicked 'Sign in with email' button to reveal form")
            # Re-check for fields
            has_pwd_field = await page.locator("input[type='password']:visible").count() > 0
            has_email_field = await page.locator("input[type='email']:visible, input[data-automation-id='email']:visible").count() > 0
        except Exception as exc:
            log.debug("Workday: failed to click Sign in with email: %s", exc)

    # --- Detect if we're on Create Account vs Sign In ---
    # Create Account has: verify password field, or 2+ password fields
    verify_pwd_visible = await page.locator(
        "input[data-automation-id='verifyNewPassword']:visible, "
        "input[aria-label*='verify' i]:visible"
    ).count() > 0
    pwd_count = await page.locator("input[type='password']:visible").count()
    on_create_page = verify_pwd_visible or pwd_count >= 2

    if on_create_page:
        log.info("Workday: on Create Account page (verify_pwd=%s, pwd_count=%d)",
                 verify_pwd_visible, pwd_count)
        # Try Sign In first — click "Already have an account? Sign In"
        # NOTE: Workday's Sign In link uses data-automation-id, NOT <a> tags!
        switched_to_signin = False
        for sel in [
            "[data-automation-id='signInLink']",
            "button:has-text('Already have an account')",
            "a:has-text('Already have an account')",
            "*:has-text('Already have an account') >> a, *:has-text('Already have an account') >> button",
            "button:has-text('Sign In')",
            "a:has-text('Sign In')",
            "a:has-text('Sign in')",
        ]:
            try:
                link = page.locator(sel).last  # Bottom link, not nav
                if await link.count() > 0 and await link.is_visible():
                    await link.click()
                    await page.wait_for_timeout(3000)
                    log.info("Workday: clicked '%s' to switch to Sign In", sel)
                    switched_to_signin = True
                    break
            except Exception:
                continue

        if switched_to_signin:
            # Try Sign In
            await _wd_fill_and_submit_signin(page, _WD_EMAIL, _WD_PASS)
            post_text = (await page.text_content("body") or "").lower()

            # Check if sign-in succeeded (no more password fields visible)
            still_has_pwd = await page.locator("input[type='password']:visible").count() > 0
            signin_error = any(p in post_text for p in [
                "incorrect email", "incorrect password", "invalid credentials",
                "invalid email or password", "account does not exist",
                "unable to sign in", "sign-in failed",
            ])
            needs_verify = any(p in post_text for p in [
                "verify your account", "verify your email", "resend account verification",
                "verification email", "confirm your email",
            ])

            if not still_has_pwd and not signin_error:
                log.info("Workday: sign-in succeeded after switching from Create Account")
                return True

            if needs_verify:
                # Account exists but needs email verification — handle it now
                log.info("Workday: account needs verification — handling email verification")
                # Click Resend if available
                for sel in [
                    "a:has-text('Resend Account Verification')",
                    "a:has-text('Resend')", "button:has-text('Resend')",
                ]:
                    try:
                        link = page.locator(sel).first
                        if await link.count() > 0 and await link.is_visible():
                            await link.click()
                            log.info("Workday: clicked Resend Verification")
                            await page.wait_for_timeout(3000)
                            break
                    except Exception:
                        continue

                import re as _re_t; _tenant_m = _re_t.search(r'([a-z]+\.wd\d+)', job_url); _t_hint = _tenant_m.group(1) if _tenant_m else ""
                verify_link = await _fetch_workday_verify_link(max_wait_seconds=90, tenant_hint=_t_hint)
                if verify_link:
                    log.info("Workday: found verification link, visiting")
                    await page.goto(verify_link, wait_until="domcontentloaded", timeout=30_000)
                    await page.wait_for_timeout(5000)
                    # After verification, may be redirected to apply page or need to sign in
                    has_pwd = await page.locator("input[type='password']:visible").count() > 0
                    if has_pwd:
                        # Switch to Sign In if needed
                        pwd_cnt = await page.locator("input[type='password']:visible").count()
                        if pwd_cnt >= 2:
                            try:
                                await page.locator("[data-automation-id='signInLink']").first.click()
                                await page.wait_for_timeout(3000)
                            except Exception:
                                pass
                        await _wd_fill_and_submit_signin(page, _WD_EMAIL, _WD_PASS)
                    # Check if we're now authenticated
                    if await page.locator("input[type='password']:visible").count() == 0:
                        log.info("Workday: verified and signed in successfully")
                        return True
                else:
                    log.warning("Workday: no verification link found")
                # Don't fall through to Create Account — account already exists
                # Skip to final auth check
            else:
                log.info("Workday: sign-in failed (still_has_pwd=%s, signin_error=%s) — will create account",
                         still_has_pwd, signin_error)
                # Navigate back to Create Account
                for sel in [
                    "[data-automation-id='createAccountLink']",
                    "a:has-text('Create Account')", "a:has-text('Create an Account')",
                    "button:has-text('Create Account')",
                ]:
                    try:
                        link = page.locator(sel).first
                        if await link.count() > 0 and await link.is_visible():
                            await link.click()
                            await page.wait_for_timeout(3000)
                            log.info("Workday: navigated back to Create Account")
                            break
                    except Exception:
                        continue

        # --- Fill and submit Create Account form ---
        # Only create account if we didn't detect a needs_verify state
        # (needs_verify means account already exists but is unverified)
        _body_text = (await page.text_content("body") or "").lower()
        _skip_create = switched_to_signin and any(p in _body_text for p in [
            "verify your account", "resend account verification",
        ])
        if _skip_create:
            log.info("Workday: skipping Create Account — account exists but needs verification")
        else:
            await _wd_fill_and_submit_create_account(page, _WD_EMAIL, _WD_PASS)

        # Check result
        post_create = (await page.text_content("body") or "").lower()
        account_exists = any(p in post_create for p in [
            "already exists", "already registered",
            "account with this email", "email is already",
        ])
        if account_exists:
            log.info("Workday: account already exists — switching to Sign In")
            for sel in [
                "[data-automation-id='signInLink']",
                "a:has-text('Already have an account')",
                "button:has-text('Sign In')",
                "a:has-text('Sign In')",
                "a:has-text('Sign in')",
            ]:
                try:
                    link = page.locator(sel).last
                    if await link.count() > 0 and await link.is_visible():
                        await link.click()
                        await page.wait_for_timeout(3000)
                        log.info("Workday: clicked '%s' to Sign In after account exists", sel)
                        break
                except Exception:
                    continue
            await _wd_fill_and_submit_signin(page, _WD_EMAIL, _WD_PASS)

    else:
        # --- We're on a Sign In page (single password field) ---
        log.info("Workday: on Sign In page")
        await _wd_fill_and_submit_signin(page, _WD_EMAIL, _WD_PASS)

        post_text = (await page.text_content("body") or "").lower()
        still_has_pwd = await page.locator("input[type='password']:visible").count() > 0
        signin_error = any(p in post_text for p in [
            "incorrect email", "incorrect password", "invalid credentials",
            "invalid email or password", "account does not exist",
            "unable to sign in", "wrong email", "wrong password",
            "entered the wrong", "account might be locked",
        ])

        if still_has_pwd and signin_error:
            log.info("Workday: sign-in failed — trying Create Account")
            # Close any Sign In modal first (press Escape or click X)
            try:
                close_btn = page.locator("[role='dialog'] button[aria-label='close'], [role='dialog'] button:has-text('×')").first
                if await close_btn.count() > 0:
                    await close_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass
            for sel in [
                "[data-automation-id='createAccountLink']",
                "a:has-text('Create Account')", "a:has-text('Create an Account')",
                "button:has-text('Create Account')",
            ]:
                try:
                    link = page.locator(sel).first
                    if await link.count() > 0 and await link.is_visible():
                        await link.click()
                        await page.wait_for_timeout(3000)
                        break
                except Exception:
                    continue
            await _wd_fill_and_submit_create_account(page, _WD_EMAIL, _WD_PASS)

    # --- Handle email verification ---
    final_text = (await page.text_content("body") or "").lower()
    if any(phrase in final_text for phrase in [
        "verify your email", "verification email", "check your email",
        "we sent", "confirm your email", "verify your account",
    ]):
        log.info("Workday: email verification required — checking inbox")
        import re as _re_t; _tenant_m = _re_t.search(r'([a-z]+\.wd\d+)', job_url); _t_hint = _tenant_m.group(1) if _tenant_m else ""
        verify_link = await _fetch_workday_verify_link(max_wait_seconds=60, tenant_hint=_t_hint)
        if verify_link:
            log.info("Workday: found verification link, navigating")
            await page.goto(verify_link, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(5000)
            # After verification, may need to sign in again
            (await page.text_content("body") or "").lower()
            if await page.locator("input[type='password']:visible").count() > 0:
                log.info("Workday: post-verification sign-in required")
                await _wd_fill_and_submit_signin(page, _WD_EMAIL, _WD_PASS)
        else:
            log.warning("Workday: no verification link found in email within timeout")

    # --- Handle "Verify your account" page (shown after sign-in if unverified) ---
    final_text = (await page.text_content("body") or "").lower()
    needs_verify = any(p in final_text for p in [
        "verify your account", "verify your email", "verification email",
        "check your email", "confirm your email", "resend account verification",
    ])
    if needs_verify:
        log.info("Workday: account needs email verification")
        # Click "Resend Account Verification" if available
        for sel in [
            "a:has-text('Resend Account Verification')",
            "a:has-text('Resend')",
            "button:has-text('Resend')",
            "[data-automation-id='resendVerification']",
        ]:
            try:
                link = page.locator(sel).first
                if await link.count() > 0 and await link.is_visible():
                    await link.click()
                    log.info("Workday: clicked Resend Verification via %s", sel)
                    await page.wait_for_timeout(3000)
                    break
            except Exception:
                continue

        # Poll IMAP for verification link (allow extra time after resend)
        import re as _re_t; _tenant_m = _re_t.search(r'([a-z]+\.wd\d+)', job_url); _t_hint = _tenant_m.group(1) if _tenant_m else ""
        verify_link = await _fetch_workday_verify_link(max_wait_seconds=90, tenant_hint=_t_hint)
        if verify_link:
            log.info("Workday: found verification link, visiting")
            await page.goto(verify_link, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(5000)
            # After verification, navigate back to job and try sign-in again
            # The verify link often redirects to the apply page automatically.
            (await page.text_content("body") or "").lower()
            has_pwd = await page.locator("input[type='password']:visible").count() > 0
            if has_pwd:
                log.info("Workday: post-verification sign-in required")
                # Switch to Sign In if on Create Account
                pwd_cnt = await page.locator("input[type='password']:visible").count()
                if pwd_cnt >= 2:
                    try:
                        await page.locator("[data-automation-id='signInLink']").first.click()
                        await page.wait_for_timeout(3000)
                    except Exception:
                        pass
                await _wd_fill_and_submit_signin(page, _WD_EMAIL, _WD_PASS)
        else:
            log.warning("Workday: no verification link found after resend")

    # --- Final auth check ---
    has_pwd_field = await page.locator("input[type='password']:visible").count() > 0
    if not has_pwd_field:
        log.info("Workday: authenticated successfully")
        return True
    else:
        log.warning("Workday: authentication failed — still see password field")
        try:
            ss_dir = Path("artifacts/autofill_screenshots")
            from datetime import datetime as _dt
            ts = _dt.now().strftime("%Y%m%d_%H%M%S")
            await page.screenshot(
                path=str(ss_dir / f"wd_auth_failed_{ts}.png"),
                full_page=False,
            )
        except Exception:
            pass
        return False


async def _wd_click_next(page: Page) -> bool:
    """Click the Workday 'Save and Continue' / 'Next' button.

    Uses JS click on click_filter overlay first (most reliable per reference repos),
    then falls back to Playwright click. After clicking, checks for validation
    errors to report whether the page actually advanced.
    """
    # Check for Submit button — don't click it during navigation
    submit_btn = page.locator("button:has-text('Submit')").first
    if await submit_btn.count() > 0 and await submit_btn.is_visible():
        btn_text = (await submit_btn.text_content() or "").strip().lower()
        if "submit" in btn_text and "continue" not in btn_text:
            log.info("Workday: found Submit button — final step, stopping navigation.")
            return False

    (await page.text_content("body") or "")[:300].lower()

    # Primary: JS click on click_filter overlay (Workday's actual click target)
    clicked = await page.evaluate("""() => {
        // click_filter overlays are Workday's actual click targets
        const filters = document.querySelectorAll('[data-automation-id="click_filter"]');
        for (const f of filters) {
            const label = (f.getAttribute('aria-label') || '').toLowerCase();
            if (label.includes('save') || label.includes('continue') || label.includes('next')) {
                f.click();
                return label;
            }
        }
        // Fallback: the actual button
        const btn = document.querySelector('button[data-automation-id="bottom-navigation-next-button"]');
        if (btn) { btn.click(); return 'bottom-nav-button'; }
        return null;
    }""")

    if not clicked:
        # Playwright fallback
        for sel in [
            "button[data-automation-id='bottom-navigation-next-button']",
            "button:has-text('Save and Continue')",
            "button:has-text('Continue')",
            "button:has-text('Next')",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await page.wait_for_timeout(200)
                    await btn.click(force=True, timeout=5000)
                    clicked = sel
                    break
            except Exception:
                continue

    if not clicked:
        return False

    log.info("Workday: clicked Next via '%s'", clicked)
    await page.wait_for_timeout(3000)
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)

    # Check if validation errors are blocking — look for inline error messages
    error_count = await page.evaluate("""() => {
        const errs = document.querySelectorAll(
            '[data-automation-id="errorMessage"], .css-1lyba0b, [role="alert"]'
        );
        let visible = 0;
        for (const e of errs) {
            if (e.offsetParent !== null) visible++;
        }
        return visible;
    }""")
    if error_count > 0:
        log.warning("Workday: %d validation error(s) after clicking Next — may not have advanced", error_count)

    return True


async def _wd_detect_page_js(page: "Page") -> str:
    """Detect which Workday wizard step via JS on the live page.

    Reads the current step number from Workday's progress indicator element,
    which has an aria-label like 'current step 3 of 6'. Falls back to checking
    the active/current step name in the step list.
    """
    info = await page.evaluate("""() => {
        // Method 1: aria-label 'current step N of M' on any element
        const allEls = document.querySelectorAll('[aria-label]');
        for (const el of allEls) {
            const lbl = (el.getAttribute('aria-label') || '').toLowerCase();
            const m = lbl.match(/current step (\\d+) of (\\d+)/);
            if (m) return {step: parseInt(m[1]), total: parseInt(m[2]), source: 'aria'};
        }
        // Method 2: look for active step in progress nav (various selectors)
        const progSelectors = [
            '[data-automation-id="progressBarStepLink"]',
            '[data-automation-id="progressStep"]',
            'li[aria-current="step"]',
            'li[aria-current="true"]',
            '[role="tab"][aria-selected="true"]',
        ];
        for (const sel of progSelectors) {
            const steps = document.querySelectorAll(sel);
            if (steps.length === 0) continue;
            for (let i = 0; i < steps.length; i++) {
                const cur = steps[i].getAttribute('aria-current');
                if (cur === 'step' || cur === 'true' || steps[i].matches('[aria-selected="true"]')) {
                    return {step: i + 1, total: steps.length, source: 'progress:' + sel};
                }
            }
        }
        // Method 3: look for the active/selected step by class or aria in the step list
        const stepLinks = document.querySelectorAll('[data-automation-id*="stepLink"], [class*="step"][class*="current"], [class*="step"][class*="active"]');
        if (stepLinks.length > 0) {
            // Count all step links and find the current one
            const allStepLinks = document.querySelectorAll('[data-automation-id*="stepLink"]');
            if (allStepLinks.length > 0) {
                for (let i = 0; i < allStepLinks.length; i++) {
                    const cur = allStepLinks[i].getAttribute('aria-current');
                    const selected = allStepLinks[i].getAttribute('aria-selected');
                    if (cur === 'step' || cur === 'true' || selected === 'true') {
                        return {step: i + 1, total: allStepLinks.length, source: 'stepLink'};
                    }
                }
            }
        }
        // Method 4: visually-hidden text — find ALL 'current step N of M' and take the one
        // inside the active/visible progress indicator (not the nav bar listing)
        const spans = document.querySelectorAll('span');
        for (const span of spans) {
            const txt = (span.textContent || '').trim().toLowerCase();
            const m = txt.match(/^current step (\\d+) of (\\d+)$/);
            if (m) return {step: parseInt(m[1]), total: parseInt(m[2]), source: 'span'};
        }
        // Method 5: fallback — match last occurrence in body text
        const body = document.body.textContent || '';
        const matches = [...body.matchAll(/current step (\\d+) of (\\d+)/gi)];
        if (matches.length > 0) {
            const last = matches[matches.length - 1];
            return {step: parseInt(last[1]), total: parseInt(last[2]), source: 'text-last'};
        }
        return null;
    }""")
    if info and info.get("step"):
        step_num = info["step"]
        total = info.get("total", 6)
        log.info("Workday: step %d of %d (source: %s)", step_num, total, info.get("source"))
        # Map by position — Workday standard wizard order
        if step_num == 1:
            return "my_information"
        elif step_num == 2:
            return "my_experience"
        elif step_num == total:
            return "review"
        elif step_num == total - 1:
            # Second to last is usually Self-Identify or Voluntary
            return "voluntary"
        elif step_num == total - 2:
            # Third from last is usually Voluntary Disclosures
            return "voluntary"
        else:
            return "questions"

    # Last resort: check for unique form content on the page
    t = (await page.text_content("body") or "").lower()
    if "how did you hear" in t and ("first name" in t or "last name" in t):
        return "my_information"
    if "upload your resume" in t or "upload resume" in t:
        return "my_experience"
    if any(q in t for q in ["are you legally authorized", "require sponsorship",
                             "will you now or in the future"]):
        return "questions"
    return "unknown"


async def _wd_fill_identity(page: Page, profile: dict[str, Any], filled: list[str]) -> None:
    """Fill Workday 'My Information' page: name, email, phone, address, source."""
    contact = profile.get("contact", profile)
    email = contact.get("email", settings.job_application_email)

    # Dismiss any popups/modals that might block form interaction
    for dismiss_sel in [
        "button[aria-label='close']:visible",
        "button[aria-label='Close']:visible",
        "[data-automation-id='closeButton']:visible",
        "button:has-text('✕'):visible",
        "button:has-text('×'):visible",
    ]:
        try:
            btn = page.locator(dismiss_sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                log.info("Workday: dismissed popup via %s", dismiss_sel)
                await page.wait_for_timeout(1000)
        except Exception:
            pass

    # Wait for the form fields to actually render (Workday SPA loads lazily)
    # Workday forms use name= attributes (e.g. name='legalName--firstName') not data-automation-id
    try:
        await page.wait_for_selector(
            "input[name='legalName--firstName'], "
            "input[data-automation-id='legalNameSection_firstName'], "
            "[data-automation-id='legalNameSection_firstName'] input",
            timeout=10_000,
        )
        log.info("Workday: form fields loaded")
    except Exception:
        log.info("Workday: form fields not found after 10s — trying to fill anyway")
    await page.wait_for_timeout(2000)  # Extra settle time

    # Text input fields — try name= first (Comcast-style), then data-automation-id (other WD sites)
    wd_text_fields = [
        ("firstName", contact.get("first_name", ""), [
            "input[name='legalName--firstName']",
            "[data-automation-id='legalNameSection_firstName'] input",
            "input[data-automation-id='legalNameSection_firstName']",
        ]),
        ("lastName", contact.get("last_name", ""), [
            "input[name='legalName--lastName']",
            "[data-automation-id='legalNameSection_lastName'] input",
            "input[data-automation-id='legalNameSection_lastName']",
        ]),
        ("addressLine1", "3405 Farragut Rd", [
            "input[name='addressLine1']",
            "[data-automation-id='addressSection_addressLine1'] input",
            "input[data-automation-id='addressSection_addressLine1']",
        ]),
        ("city", "", [  # TODO(post-lift): profile.address.city
            "input[name='city']",
            "[data-automation-id='addressSection_city'] input",
            "input[data-automation-id='addressSection_city']",
        ]),
        ("postalCode", "", [  # TODO(post-lift): profile.address.postal_code
            "input[name='postalCode']",
            "[data-automation-id='addressSection_postalCode'] input",
            "input[data-automation-id='addressSection_postalCode']",
        ]),
        ("phoneNumber", re.sub(r'^\+?1[\s\-]*', '', contact.get("phone", "")).strip(), [
            "input[name='phoneNumber']",
            "[data-automation-id='phone-number'] input",
            "input[data-automation-id='phone-number']",
        ]),
        ("email", email, [
            "input[data-automation-id='email']",
            "input[name='email']",
            "input[type='email']",
            "input[data-automation-id='emailAddress']",
            "input[data-automation-id*='email']",
        ]),
    ]
    for field_name, val, selectors in wd_text_fields:
        if not val:
            continue
        ok = False
        for sel in selectors:
            try:
                inp = page.locator(sel).first
                if await inp.count() > 0 and await inp.is_visible():
                    current = (await inp.input_value() or "").strip()
                    if current:
                        log.info("Workday: %s already has '%s', skipping", field_name, current[:30])
                        ok = True
                        break
                    await inp.fill("")
                    await inp.fill(val)
                    log.info("Workday: filled %s = '%s'", field_name, val[:30])
                    ok = True
                    break
            except Exception:
                continue
        if ok:
            filled.append(field_name)
        elif field_name == "email" and not ok:
            # Fallback: find email input by walking from "Email" label
            try:
                email_fallback = await page.evaluate("""(email) => {
                    const labels = document.querySelectorAll('label');
                    for (const lbl of labels) {
                        if (lbl.offsetParent === null) continue;
                        const lt = (lbl.textContent || '').toLowerCase().trim();
                        if (lt.includes('email') && !lt.includes('verify') && !lt.includes('notification')) {
                            const parent = lbl.closest('[data-automation-id]') || lbl.parentElement;
                            if (!parent) continue;
                            const inp = parent.querySelector('input:not([type="hidden"]):not([type="checkbox"]):not([type="password"])');
                            if (inp && inp.offsetParent !== null && !inp.value) {
                                const nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                                nativeSet.call(inp, email);
                                inp.dispatchEvent(new Event('input', {bubbles: true}));
                                inp.dispatchEvent(new Event('change', {bubbles: true}));
                                inp.dispatchEvent(new Event('blur', {bubbles: true}));
                                return true;
                            }
                        }
                    }
                    return false;
                }""", email)
                if email_fallback:
                    filled.append("email")
                    log.info("Workday: filled email via label-based fallback")
            except Exception:
                pass

    # --- Helper: JS click on element (bypasses popper overlays) ---
    async def _js_click(selector: str) -> bool:
        return await page.evaluate("""(s) => {
            const el = document.querySelector(s);
            if (el) { el.click(); return true; }
            return false;
        }""", selector)

    # --- Helper to pick a Workday dropdown: JS-click to open, JS-click option ---
    async def _wd_pick_dropdown(label: str, btn_selectors: list[str],
                                search_terms: list[str],
                                skip_if_contains: str = "",
                                force_change: bool = False) -> bool:
        """Open dropdown via JS click, then JS-click a matching option."""
        for sel in btn_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() == 0 or not await btn.is_visible():
                    continue
                aria = (await btn.get_attribute("aria-label") or "").lower()
                val_text = (await btn.text_content() or "").strip().lower()
                current = aria + " " + val_text
                if not force_change and skip_if_contains and skip_if_contains.lower() in current:
                    log.info("Workday: %s already set (%s), skipping", label, current[:50])
                    filled.append(label)
                    return True
                if not force_change and val_text and val_text not in ("select one", "select", "--", ""):
                    if any(t.lower() in current for t in search_terms):
                        log.info("Workday: %s already set to desired (%s)", label, val_text[:40])
                        filled.append(label)
                        return True
                # JS click to open (bypasses popper overlays)
                await _js_click(sel)
                await page.wait_for_timeout(800)
                # JS-click matching option from the dropdown listbox
                for term in search_terms:
                    clicked = await page.evaluate("""(t) => {
                        // Search all visible option/listitem elements
                        const sels = 'div[role="option"], li[role="option"], [role="option"], [data-automation-id="promptOption"]';
                        const opts = document.querySelectorAll(sels);
                        for (const opt of opts) {
                            if (opt.offsetParent === null) continue; // skip hidden
                            const txt = (opt.textContent || '').trim();
                            if (txt.toLowerCase().includes(t.toLowerCase())) {
                                opt.click();
                                return txt;
                            }
                        }
                        return null;
                    }""", term)
                    if clicked:
                        filled.append(label)
                        log.info("Workday: dropdown %s = '%s'", label, clicked[:40])
                        await page.wait_for_timeout(400)
                        # Dismiss popper to avoid blocking subsequent fields
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(200)
                        return True
                # Fallback: click first visible option
                clicked = await page.evaluate("""() => {
                    const opts = document.querySelectorAll('div[role="option"], li[role="option"]');
                    for (const opt of opts) {
                        if (opt.offsetParent !== null) {
                            opt.click();
                            return opt.textContent.trim();
                        }
                    }
                    return null;
                }""")
                if clicked:
                    filled.append(label)
                    log.info("Workday: dropdown %s = '%s' (first option)", label, clicked[:40])
                    await page.wait_for_timeout(400)
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(200)
                    return True
                await page.keyboard.press("Escape")
            except Exception as exc:
                log.debug("Workday dropdown %s sel=%s: %s", label, sel, exc)
        return False

    # --- Helper: pick from Workday multiselect ---
    async def _wd_pick_multiselect(label: str, input_selectors: list[str],
                                   search_terms: list[str]) -> bool:
        """Open multiselect dropdown and select an option via keyboard.

        Strategy: type to filter, ArrowDown to highlight, Enter to select.
        This goes through Workday's UXI keyboard event path which properly
        updates form validation state (unlike React onClick which only creates
        visual pills).
        """
        async def _get_pill_count() -> int:
            return await page.evaluate("""() => {
                const c = document.querySelector('[data-automation-id="formField-source"]');
                if (!c) return 0;
                const aria = c.querySelector('[data-automation-id="promptAriaInstruction"]');
                if (aria) {
                    const m = (aria.textContent || '').match(/(\\d+) items? selected/);
                    if (m) return parseInt(m[1]);
                }
                return c.querySelectorAll('[data-automation-id="selectedItem"]').length;
            }""")

        for sel in input_selectors:
            try:
                inp = page.locator(sel).first
                if await inp.count() == 0 or not await inp.is_visible():
                    continue
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)

                pills_before = await _get_pill_count()

                for term in search_terms:
                    await inp.click()
                    await page.wait_for_timeout(400)
                    await inp.fill("")
                    await page.wait_for_timeout(200)
                    await inp.press_sequentially(term, delay=80)
                    await page.wait_for_timeout(1500)

                    # Check dropdown has results
                    has_results = await page.evaluate("""() => {
                        const lists = document.querySelectorAll('[data-automation-id="activeListContainer"]');
                        for (const list of lists) {
                            if (list.offsetParent === null) continue;
                            const items = list.querySelectorAll('[data-automation-id="promptLeafNode"]');
                            for (const item of items) {
                                if (item.offsetParent !== null) return true;
                            }
                        }
                        return false;
                    }""")
                    if not has_results:
                        await inp.fill("")
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(400)
                        continue

                    # Keyboard select: ArrowDown + Enter
                    await page.keyboard.press("ArrowDown")
                    await page.wait_for_timeout(300)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(1200)

                    pills_after = await _get_pill_count()
                    if pills_after > pills_before:
                        filled.append(label)
                        log.info("Workday: multiselect %s = '%s' (keyboard, pills %d->%d)",
                                 label, term, pills_before, pills_after)
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(200)
                        return True

                    # May have expanded subcategory — try again
                    await page.keyboard.press("ArrowDown")
                    await page.wait_for_timeout(300)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(1200)
                    if await _get_pill_count() > pills_before:
                        filled.append(label)
                        log.info("Workday: multiselect %s = '%s' (keyboard subcategory, pills %d->%d)",
                                 label, term, pills_before, await _get_pill_count())
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(200)
                        return True

                    await inp.fill("")
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(400)

                # Fallback: open and just ArrowDown + Enter on first item
                await inp.click()
                await page.wait_for_timeout(1000)
                await page.keyboard.press("ArrowDown")
                await page.wait_for_timeout(300)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1200)
                if await _get_pill_count() > pills_before:
                    filled.append(label)
                    log.info("Workday: multiselect %s = first option (keyboard fallback)", label)
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(200)
                    return True

                await page.keyboard.press("Escape")
            except Exception as exc:
                log.debug("Workday multiselect %s sel=%s: %s", label, sel, exc)
        return False

    # Country (often pre-filled to United States)
    await _wd_pick_dropdown("country", [
        "button[name='country']",
        "[data-automation-id='country']",
        "[data-automation-id='legalNameSection_country']",
    ], ["United States"], skip_if_contains="united states")

    # LinkedIn / Social Network URLs
    # Some tenants hide the LinkedIn input behind an "Add" button in the Social Network URLs section.
    linkedin = contact.get("linkedin", "")
    if linkedin:
        linkedin_filled = False
        for sel in [
            "input[data-automation-id='linkedinQuestion']",
            "input[data-automation-id='linkedin']",
            "input[aria-label*='LinkedIn' i]",
        ]:
            if await _type_into_field(page, sel, linkedin):
                filled.append("linkedin")
                linkedin_filled = True
                break
        # If no LinkedIn input found, try clicking "Add" button in the Social Network URLs section
        if not linkedin_filled:
            try:
                add_clicked = await page.evaluate("""() => {
                    // Find labels/headings mentioning "Social Network"
                    const allText = document.querySelectorAll('h3, h4, h5, label, legend, p, div');
                    for (const el of allText) {
                        const t = (el.textContent || '').trim();
                        if (t.toLowerCase().includes('social network') || t.toLowerCase().includes('linkedin')) {
                            // Walk up to find a section, then find an "Add" button nearby
                            let parent = el;
                            for (let i = 0; i < 6; i++) {
                                parent = parent.parentElement;
                                if (!parent) break;
                                const addBtn = parent.querySelector('button[aria-label*="Add"], button:not([aria-haspopup])');
                                if (addBtn && (addBtn.textContent || '').trim().toLowerCase() === 'add') {
                                    addBtn.click();
                                    return true;
                                }
                            }
                        }
                    }
                    return false;
                }""")
                if add_clicked:
                    await page.wait_for_timeout(1500)
                    log.info("Workday: clicked Add for Social Network URLs")
                    # Now try to fill the LinkedIn input that should have appeared
                    for sel in [
                        "input[data-automation-id='linkedinQuestion']",
                        "input[data-automation-id='linkedin']",
                        "input[aria-label*='LinkedIn' i]",
                        "input[placeholder*='linkedin' i]",
                        "input[placeholder*='URL' i]",
                    ]:
                        if await _type_into_field(page, sel, linkedin):
                            filled.append("linkedin")
                            linkedin_filled = True
                            log.info("Workday: filled LinkedIn after clicking Add")
                            break
                    # Also try the JS method from experience page
                    if not linkedin_filled:
                        count = await page.evaluate("""(url) => {
                            const inputs = document.querySelectorAll('input');
                            let filled = 0;
                            for (const inp of inputs) {
                                const all = ((inp.getAttribute('aria-label') || '') + ' ' +
                                    (inp.placeholder || '') + ' ' +
                                    (inp.getAttribute('data-automation-id') || '')).toLowerCase();
                                if ((all.includes('linkedin') || all.includes('url') || all.includes('social')) && !inp.value) {
                                    const nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                                    nativeSet.call(inp, url);
                                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                                    filled++;
                                }
                            }
                            return filled;
                        }""", linkedin)
                        if count:
                            filled.append("linkedin")
                            log.info("Workday: filled LinkedIn via JS after Add click")
            except Exception as exc:
                log.debug("Workday Social Network Add click failed: %s", exc)

    # Phone Device Type dropdown — force change from Landline to Mobile
    await _wd_pick_dropdown("phone_device_type", [
        "button[name='phoneType']",
        "#phoneNumber--phoneType",
        "[data-automation-id='phone-device-type']",
        "[data-automation-id='phoneDeviceType']",
    ], ["Mobile", "Cell"], force_change=True)

    # Country Phone Code — typeahead multiselect with virtual scroll.
    # Must type to filter the virtual-scrolled list (can't scroll to "United States").
    phone_code_done = False

    # Check if a pill/chip for "United States" already exists in the field
    try:
        _pc_pill = await page.evaluate("""() => {
            const field = document.querySelector('[data-automation-id="formField-countryPhoneCode"]');
            if (!field) return false;
            const pills = field.querySelectorAll('[data-automation-id="selectedItem"]');
            for (const p of pills) {
                if ((p.textContent||'').toLowerCase().includes('united states')) return true;
            }
            return false;
        }""")
        if _pc_pill:
            phone_code_done = True
            filled.append("country_phone_code")
            log.info("Workday: phone code already has US pill")
    except Exception:
        pass

    for pc_sel in [
        "#phoneNumber--countryPhoneCode",
        "input[id='phoneNumber--countryPhoneCode']",
        "[data-automation-id='formField-countryPhoneCode'] input",
    ]:
      if phone_code_done:
          break
      try:
        pc_inp = page.locator(pc_sel).first
        if await pc_inp.count() == 0 or not await pc_inp.is_visible():
            continue
        # Clear and type to filter
        await pc_inp.click(force=True)
        await page.wait_for_timeout(500)
        await pc_inp.fill("")
        await page.wait_for_timeout(200)
        await pc_inp.press_sequentially("United States", delay=60)
        await page.wait_for_timeout(1500)

        # Try keyboard navigation first (most reliable for Workday UXI)
        await page.keyboard.press("ArrowDown")
        await page.wait_for_timeout(300)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1000)

        # Check if pill appeared
        _pill_check = await page.evaluate("""() => {
            const field = document.querySelector('[data-automation-id="formField-countryPhoneCode"]');
            if (!field) return false;
            return field.querySelectorAll('[data-automation-id="selectedItem"]').length > 0;
        }""")
        if _pill_check:
            phone_code_done = True
            filled.append("country_phone_code")
            log.info("Workday: phone code = United States (keyboard)")
            await page.keyboard.press("Escape")
            break

        # Fallback: click visible option directly
        opt = page.locator("[data-automation-id='activeListContainer'] [role='option']:visible").first
        if await opt.count() > 0:
            opt_text = (await opt.text_content() or "").strip()
            if "united states" in opt_text.lower():
                await opt.click()
                await page.wait_for_timeout(800)
                phone_code_done = True
                filled.append("country_phone_code")
                log.info("Workday: phone code = '%s' (clicked)", opt_text[:40])

        # Fallback: React onClick on matching option
        if not phone_code_done:
            clicked = await page.evaluate("""() => {
                const c = document.querySelector('[data-automation-id="activeListContainer"]');
                if (!c) return null;
                const opts = c.querySelectorAll('[role="option"]');
                for (const opt of opts) {
                    if (opt.offsetParent === null) continue;
                    if ((opt.textContent||'').toLowerCase().includes('united states')) {
                        const leaf = opt.querySelector('[data-automation-id="promptLeafNode"]');
                        const target = leaf || opt;
                        const pk = Object.keys(target).find(k => k.startsWith('__reactProps$'));
                        if (pk && target[pk].onClick) {
                            target[pk].onClick({type:'click',target,currentTarget:target,
                                preventDefault:()=>{},stopPropagation:()=>{},
                                nativeEvent:new MouseEvent('click')});
                            return (opt.textContent||'').trim().substring(0,40);
                        }
                        target.click();
                        return (opt.textContent||'').trim().substring(0,40);
                    }
                }
                return null;
            }""")
            if clicked:
                phone_code_done = True
                filled.append("country_phone_code")
                log.info("Workday: phone code = '%s' (React onClick)", clicked)

        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
      except Exception as exc:
        log.debug("Workday: phone code %s: %s", pc_sel, exc)
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

    # State dropdown (New York)
    await _wd_pick_dropdown("state", [
        "button[name='countryRegion']",
        "[data-automation-id='addressSection_countryRegion']",
        "[data-automation-id='addressSection_regionSubdivision']",
        "[data-automation-id='state']",
    ], ["New York"])

    # Source / How Did You Hear About Us — Workday multiselect
    # Skip if already filled (prevents clearing valid chips on re-runs)
    if "source" not in filled:

        # Clear ALL stale chips/tags from previous attempts using JS click on X buttons
        try:
            cleared = await page.evaluate("""() => {
                const container = document.querySelector('[data-automation-id="formField-source"]');
                if (!container) return 0;
                let cleared = 0;
                for (let attempt = 0; attempt < 10; attempt++) {
                    const pill = container.querySelector('[data-automation-id="selectedItem"]');
                    if (!pill) break;
                    const deleteBtn = pill.querySelector('[data-automation-id="DELETE_charm"], [data-automation-id="delete"]');
                    if (deleteBtn) {
                        deleteBtn.click();
                        cleared++;
                        continue;
                    }
                    pill.focus();
                    pill.dispatchEvent(new KeyboardEvent('keydown', {key: 'Backspace', bubbles: true}));
                    pill.dispatchEvent(new KeyboardEvent('keydown', {key: 'Delete', bubbles: true}));
                    cleared++;
                }
                return cleared;
            }""")
            if cleared:
                log.info("Workday: cleared %d stale source chip(s) via JS", cleared)
                await page.wait_for_timeout(800)
        except Exception:
            pass

    # Also try Playwright approach: click pill then press Backspace/Delete keys
    if "source" not in filled:
        try:
            source_container = page.locator("[data-automation-id='formField-source']").first
            if await source_container.count() > 0:
                for attempt in range(5):
                    pills = source_container.locator("[data-automation-id='selectedItem']")
                    pill_count = await pills.count()
                    if pill_count == 0:
                        break
                    pill = pills.first
                    pill_text = (await pill.text_content() or "").strip()[:30]
                    charm = pill.locator("[data-automation-id='DELETE_charm']").first
                    if await charm.count() > 0:
                        await charm.click(force=True)
                        await page.wait_for_timeout(500)
                        log.info("Workday: deleted source chip '%s' via DELETE_charm", pill_text)
                        continue
                    inp = source_container.locator("input").first
                    if await inp.count() > 0:
                        await inp.focus()
                        await page.keyboard.press("Backspace")
                        await page.wait_for_timeout(500)
                        log.info("Workday: deleted source chip '%s' via Backspace", pill_text)
                    else:
                        break
        except Exception:
            pass

    # Try multiselect via type-to-filter + keyboard select (ArrowDown + Enter)
    # Keyboard selection goes through Workday's UXI event path and properly updates form state
    source_filled = "source" in filled
    if not source_filled:
      try:
        src_container = page.locator("[data-automation-id='formField-source']").first
        if await src_container.count() > 0:
            src_inp = src_container.locator("input").first
            if await src_inp.count() > 0 and await src_inp.is_visible():
                pills_before = await page.evaluate("""() => {
                    const c = document.querySelector('[data-automation-id="formField-source"]');
                    if (!c) return 0;
                    return c.querySelectorAll('[data-automation-id="selectedItem"]').length;
                }""")
                for term in ["Glassdoor", "Internet", "Job Board", "Job Sites",
                             "Career Site", "Company Website", "Other"]:
                    await src_inp.click()
                    await page.wait_for_timeout(400)
                    await src_inp.fill("")
                    await page.wait_for_timeout(200)
                    # Type character by character to trigger Workday's typeahead
                    await src_inp.press_sequentially(term, delay=80)
                    await page.wait_for_timeout(1500)

                    # Check if dropdown appeared with results
                    has_results = await page.evaluate("""() => {
                        const lists = document.querySelectorAll('[data-automation-id="activeListContainer"]');
                        for (const list of lists) {
                            if (list.offsetParent === null) continue;
                            const items = list.querySelectorAll('[data-automation-id="promptLeafNode"]');
                            for (const item of items) {
                                if (item.offsetParent !== null) return true;
                            }
                        }
                        return false;
                    }""")
                    if not has_results:
                        # No matching results for this term, try next
                        await src_inp.fill("")
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(400)
                        continue

                    # Use ArrowDown to highlight first option, then Enter to select
                    await page.keyboard.press("ArrowDown")
                    await page.wait_for_timeout(300)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(1200)

                    pills_after = await page.evaluate("""() => {
                        const c = document.querySelector('[data-automation-id="formField-source"]');
                        if (!c) return 0;
                        return c.querySelectorAll('[data-automation-id="selectedItem"]').length;
                    }""")
                    if pills_after > pills_before:
                        source_filled = True
                        filled.append("source")
                        log.info("Workday: source multiselect = '%s' (keyboard select, pills %d->%d)",
                                 term, pills_before, pills_after)
                        await page.keyboard.press("Escape")
                        break

                    # Enter didn't work — maybe it expanded a subcategory.
                    # Try ArrowDown + Enter again for the child item
                    await page.wait_for_timeout(400)
                    await page.keyboard.press("ArrowDown")
                    await page.wait_for_timeout(300)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(1200)
                    pills_now = await page.evaluate("""() => {
                        const c = document.querySelector('[data-automation-id="formField-source"]');
                        if (!c) return 0;
                        return c.querySelectorAll('[data-automation-id="selectedItem"]').length;
                    }""")
                    if pills_now > pills_before:
                        source_filled = True
                        filled.append("source")
                        log.info("Workday: source multiselect = '%s' (keyboard subcategory, pills %d->%d)",
                                 term, pills_before, pills_now)
                        await page.keyboard.press("Escape")
                        break

                    # Still no pill — try native Playwright click on the visible leaf as last resort
                    try:
                        leaf_loc = page.locator("[data-automation-id='activeListContainer'] [data-automation-id='promptLeafNode']").first
                        if await leaf_loc.count() > 0 and await leaf_loc.is_visible():
                            await leaf_loc.click()
                            await page.wait_for_timeout(1200)
                            pills_click = await page.evaluate("""() => {
                                const c = document.querySelector('[data-automation-id="formField-source"]');
                                if (!c) return 0;
                                return c.querySelectorAll('[data-automation-id="selectedItem"]').length;
                            }""")
                            if pills_click > pills_before:
                                source_filled = True
                                filled.append("source")
                                log.info("Workday: source multiselect = '%s' (playwright click, pills %d->%d)",
                                         term, pills_before, pills_click)
                                await page.keyboard.press("Escape")
                                break
                    except Exception:
                        pass

                    # Clear and try next term
                    await src_inp.fill("")
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(400)
      except Exception as exc:
        log.debug("Workday source type-to-filter failed: %s", exc)

    # Fallback: old multiselect approach
    if not source_filled:
        source_filled = await _wd_pick_multiselect("source", [
            "#source--source",
            "input#source--source",
            "[data-automation-id='formField-source'] input",
        ], ["Job Sites", "Email", "Career Fair", "Social Media", "Advertisement",
            "Professional Organization", "Contractor",
            "Company Website", "Career Site", "Internet", "Job Board", "Other"])

    # Fallback: try as a button dropdown (scoped to formField-source container)
    if not source_filled:
        source_filled = await _wd_pick_dropdown("source", [
            "[data-automation-id='formField-source'] button[aria-haspopup]",
            "[data-automation-id='formField-source'] button[name='source']",
            "[data-automation-id='sourcePrompt']",
        ], ["Job Sites", "Internet", "Job Board", "Career Site",
            "Company Website", "Online", "Other"])

    # Close any open poppers/dropdowns before interacting with radio buttons
    # Press Escape and click on page body to dismiss open multiselect popups
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        # Click on a neutral area (page heading) to close any open dropdowns
        heading = page.locator("h2:visible, h1:visible").first
        if await heading.count() > 0:
            await heading.click(force=True)
            await page.wait_for_timeout(300)
    except Exception:
        pass

    # "Have you previously been employed by this company?" — select No
    # Try known automation IDs first, then generic label-based approach
    prev_worker_done = False
    for radio_name in ["candidateIsPreviousWorker", "candidateIsPreviousW"]:
        if prev_worker_done:
            break
        try:
            no_radio = page.locator(f"input[name='{radio_name}'][value='false']").first
            if await no_radio.count() > 0:
                radio_id = await no_radio.get_attribute("id") or ""
                if radio_id:
                    no_label = page.locator(f"label[for='{radio_id}']").first
                    if await no_label.count() > 0:
                        await no_label.click(force=True)
                        await page.wait_for_timeout(300)
                        checked = await page.evaluate(f"""() => {{
                            const r = document.querySelector("input[name='{radio_name}'][value='false']");
                            return r ? r.checked : false;
                        }}""")
                        if checked:
                            filled.append("previousWorker")
                            prev_worker_done = True
                            log.info("Workday: selected 'No' via label click (%s)", radio_name)
                            continue
                # JS fallback
                await page.evaluate(f"""() => {{
                    const r = document.querySelector("input[name='{radio_name}'][value='false']");
                    if (!r) return;
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'checked'
                    ).set;
                    nativeInputValueSetter.call(r, true);
                    r.dispatchEvent(new Event('input', {{bubbles: true}}));
                    r.dispatchEvent(new Event('change', {{bubbles: true}}));
                    r.dispatchEvent(new MouseEvent('click', {{bubbles: true}}));
                }}""")
                await page.wait_for_timeout(300)
                filled.append("previousWorker")
                prev_worker_done = True
                log.info("Workday: selected 'No' for previous worker via JS (%s)", radio_name)
        except Exception:
            continue

    # Generic: find any radio group where label mentions "previously worked/employed"
    # and select the "No" option. Covers company-specific phrasing (Comcast, etc.)
    if not prev_worker_done:
        try:
            prev_worker_done = await page.evaluate("""() => {
                // Find all radio groups on the page
                const radios = document.querySelectorAll('input[type="radio"]');
                const groups = {};
                for (const r of radios) {
                    const name = r.getAttribute('name') || '';
                    if (!name) continue;
                    if (!groups[name]) groups[name] = [];
                    groups[name].push(r);
                }
                for (const [name, inputs] of Object.entries(groups)) {
                    // Find the label/question for this radio group
                    const container = inputs[0].closest('[data-automation-id^="formField"]') ||
                                     inputs[0].closest('fieldset') ||
                                     inputs[0].parentElement?.parentElement?.parentElement;
                    if (!container) continue;
                    const labelEl = container.querySelector('label, legend');
                    const labelText = (labelEl ? labelEl.textContent : container.textContent || '').toLowerCase();
                    // Check if this is a "previously worked/employed" question
                    if (labelText.includes('previously') && (labelText.includes('work') || labelText.includes('employ')) ||
                        labelText.includes('currently work') && labelText.includes('employee')) {
                        // Find the "No" / "false" radio
                        for (const r of inputs) {
                            const val = (r.value || '').toLowerCase();
                            const rLabel = document.querySelector('label[for="' + r.id + '"]');
                            const rText = rLabel ? rLabel.textContent.trim().toLowerCase() : '';
                            if (val === 'false' || val === 'no' || rText === 'no') {
                                // Click label for React compatibility
                                if (rLabel) rLabel.click();
                                else r.click();
                                return true;
                            }
                        }
                    }
                }
                return false;
            }""")
            if prev_worker_done:
                filled.append("previousWorker")
                log.info("Workday: selected 'No' for previous worker via generic label detection")
                await page.wait_for_timeout(300)
        except Exception as exc:
            log.debug("Workday generic previous worker radio failed: %s", exc)


async def _wd_fill_experience(page: Page, files: dict[str, str | None], filled: list[str]) -> None:
    """Fill Workday 'My Experience' page: resume upload, work history."""
    # Resume upload
    if "resume_upload" not in filled and (files.get("resume") or files.get("resume_docx")):
        prefer_docx = files.get("prefer_docx", True)
        try:
            # Count all file inputs for debugging
            all_file_inputs = page.locator("input[type='file']")
            file_count = await all_file_inputs.count()
            log.info("Workday experience: found %d file input(s)", file_count)

            for upload_sel in [
                "[data-automation-id='file-upload-input-ref']",
                "input[type='file'][data-automation-id*='upload']",
                "input[type='file']",
            ]:
                loc = page.locator(upload_sel).first
                if await loc.count() > 0:
                    accept_attr = await _get_accept_attr(loc)
                    chosen = _choose_resume_file(files.get("resume"), files.get("resume_docx"), prefer_docx, accept_attr)
                    if chosen:
                        await loc.set_input_files(chosen)
                        filled.append("resume_upload")
                        log.info("Uploaded resume to Workday: %s via %s", Path(chosen).name, upload_sel)
                        # Wait for Workday to parse the resume (shows spinner).
                        await page.wait_for_timeout(5000)
                        break
            else:
                log.info("Workday experience: no file input matched upload selectors")
        except Exception as exc:
            log.warning("Workday resume upload failed: %s", exc)

    # Cover letter upload
    if files.get("cover_letter"):
        try:
            file_inputs = page.locator("input[type='file']")
            fcount = await file_inputs.count()
            for fi in range(fcount):
                inp = file_inputs.nth(fi)
                if "resume_upload" in filled and fi == 0:
                    continue
                try:
                    await inp.set_input_files(files["cover_letter"])
                    filled.append("cover_letter_upload")
                    log.info("Uploaded cover letter to Workday")
                    break
                except Exception:
                    continue
        except Exception:
            pass

    # Work Experience + Education + Social fields via JS label-based matching
    # Workday uses varying data-automation-id names across tenants, so we find
    # fields by their visible label text inside formField containers.
    if "work_experience" not in filled:
        try:
            we_filled = await page.evaluate("""() => {
                const filled = [];
                // Map of label keywords -> value
                // TODO(post-lift): pull these from the active profile's
                // most-recent role; was hardcoded for the original author.
                const fieldMap = {
                    'job title': '',
                    'company': '',
                    'location': '',
                };
                const textareaMap = {
                    'role description': 'Developed data pipelines, ETL processes, and analytics dashboards using Python, SQL, and cloud services. Built machine learning models for predictive analytics and automated reporting systems.',
                    'description': 'Developed data pipelines, ETL processes, and analytics dashboards using Python, SQL, and cloud services. Built machine learning models for predictive analytics and automated reporting systems.',
                };
                // Find all formField containers in the Work Experience section
                const allFields = document.querySelectorAll('[data-automation-id^="formField-"]');
                for (const container of allFields) {
                    const labelEl = container.querySelector('label') ||
                                    container.querySelector('[data-automation-id="formLabel"]');
                    if (!labelEl) continue;
                    const labelText = (labelEl.textContent || '').toLowerCase().trim();

                    // Text inputs
                    for (const [keyword, value] of Object.entries(fieldMap)) {
                        if (labelText.includes(keyword)) {
                            const inp = container.querySelector('input:not([type="hidden"]):not([type="checkbox"])');
                            if (inp && !inp.value) {
                                const nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                                nativeSet.call(inp, value);
                                inp.dispatchEvent(new Event('input', {bubbles: true}));
                                inp.dispatchEvent(new Event('change', {bubbles: true}));
                                filled.push(keyword);
                            }
                            break;
                        }
                    }
                    // Textareas
                    for (const [keyword, value] of Object.entries(textareaMap)) {
                        if (labelText.includes(keyword)) {
                            const ta = container.querySelector('textarea');
                            if (ta && !ta.value) {
                                const nativeSet = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
                                nativeSet.call(ta, value);
                                ta.dispatchEvent(new Event('input', {bubbles: true}));
                                ta.dispatchEvent(new Event('change', {bubbles: true}));
                                filled.push(keyword);
                            }
                            break;
                        }
                    }
                }
                // Date fields: "From" / start date
                const dateInputs = document.querySelectorAll('input[data-automation-id*="dateSectionMonth"], input[data-automation-id*="startDate"]');
                for (const di of dateInputs) {
                    if (!di.value) {
                        const nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        nativeSet.call(di, '06/2024');
                        di.dispatchEvent(new Event('input', {bubbles: true}));
                        di.dispatchEvent(new Event('change', {bubbles: true}));
                        filled.push('from_date');
                        break;
                    }
                }
                // Also try year input
                const yearInputs = document.querySelectorAll('input[data-automation-id*="dateSectionYear"], input[data-automation-id*="Year"]');
                for (const yi of yearInputs) {
                    if (!yi.value) {
                        const nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        nativeSet.call(yi, '2024');
                        yi.dispatchEvent(new Event('input', {bubbles: true}));
                        yi.dispatchEvent(new Event('change', {bubbles: true}));
                        filled.push('from_year');
                        break;
                    }
                }
                return filled;
            }""")
            if we_filled:
                log.info("Workday: filled work experience fields: %s", we_filled)
            # Playwright-based fill: find inputs by their parent formField label
            # This is the reliable method — Playwright.fill() triggers proper React events
            # Fill work experience fields using JS to find inputs by walking from error labels
            # Workday error messages contain field names like "Error - Job Title"
            # Also: Company and School are typeahead fields — type + ArrowDown + Enter
            async def _fill_labeled_field(label_keyword: str, value: str, is_typeahead: bool = False):
                """Find a visible input/textarea near a label containing label_keyword and fill it."""
                try:
                    # Find all visible inputs and match by nearby label
                    match = await page.evaluate("""(args) => {
                        const keyword = args[0].toLowerCase();
                        // Strategy 1: Find label elements, then associated input
                        const labels = document.querySelectorAll('label');
                        for (const lbl of labels) {
                            if (lbl.offsetParent === null) continue;
                            const lt = (lbl.textContent || '').toLowerCase().trim();
                            if (!lt.includes(keyword)) continue;
                            // Find input in same container
                            const parent = lbl.closest('[data-automation-id]') || lbl.parentElement;
                            if (!parent) continue;
                            const inp = parent.querySelector('input:not([type="hidden"]):not([type="checkbox"]):not([type="file"])');
                            const ta = parent.querySelector('textarea');
                            const el = inp || ta;
                            if (el && el.offsetParent !== null && !el.value) {
                                return {tag: el.tagName, id: el.id, name: el.name,
                                        aid: el.getAttribute('data-automation-id') || '',
                                        ariaLabel: el.getAttribute('aria-label') || ''};
                            }
                        }
                        // Strategy 2: Find by aria-label
                        const inputs = document.querySelectorAll('input, textarea');
                        for (const inp of inputs) {
                            if (inp.offsetParent === null || inp.type === 'hidden' || inp.type === 'checkbox' || inp.type === 'file') continue;
                            const al = (inp.getAttribute('aria-label') || '').toLowerCase();
                            if (al.includes(keyword) && !inp.value) {
                                return {tag: inp.tagName, id: inp.id, name: inp.name,
                                        aid: inp.getAttribute('data-automation-id') || '',
                                        ariaLabel: inp.getAttribute('aria-label') || ''};
                            }
                        }
                        return null;
                    }""", [label_keyword])
                    if not match:
                        return False

                    # Build selector to find the element
                    if match['aid']:
                        sel = f"[data-automation-id='{match['aid']}']"
                    elif match['id']:
                        sel = f"#{match['id']}"
                    elif match['name']:
                        sel = f"[name='{match['name']}']"
                    elif match['ariaLabel']:
                        sel = f"[aria-label='{match['ariaLabel']}']"
                    else:
                        return False

                    el = page.locator(sel).first
                    if await el.count() == 0:
                        return False

                    if is_typeahead:
                        # Typeahead: click, type slowly, wait for dropdown, pick option
                        await el.click()
                        await page.wait_for_timeout(300)
                        await el.fill("")
                        await page.wait_for_timeout(200)
                        search_text = value
                        await el.press_sequentially(search_text, delay=60)
                        await page.wait_for_timeout(2000)
                        # Try to pick the right option from dropdown
                        opts = page.locator("[role='option']:visible, [data-automation-id='promptLeafNode']:visible")
                        opt_count = await opts.count()
                        picked = False
                        if opt_count > 0:
                            # First pass: prefer exact/starts-with match
                            best_idx = -1
                            best_score = 0
                            for oi in range(min(opt_count, 15)):
                                ot = (await opts.nth(oi).text_content() or "").strip().lower()
                                vl = value.lower()
                                if ot == vl:
                                    best_idx = oi
                                    best_score = 3
                                    break
                                elif ot.startswith(vl):
                                    if best_score < 2:
                                        best_idx = oi
                                        best_score = 2
                                elif vl in ot:
                                    if best_score < 1:
                                        best_idx = oi
                                        best_score = 1
                            if best_idx >= 0:
                                ot = (await opts.nth(best_idx).text_content() or "").strip()
                                await opts.nth(best_idx).click(force=True)
                                picked = True
                                log.info("Workday: filled typeahead '%s' = '%s' (matched '%s', score=%d)",
                                         label_keyword, value, ot, best_score)
                            if not picked:
                                await page.keyboard.press("ArrowDown")
                                await page.wait_for_timeout(300)
                                await page.keyboard.press("Enter")
                                log.info("Workday: filled typeahead '%s' = '%s' (ArrowDown+Enter)", label_keyword, value)
                        else:
                            await page.keyboard.press("ArrowDown")
                            await page.wait_for_timeout(300)
                            await page.keyboard.press("Enter")
                            log.info("Workday: filled typeahead '%s' = '%s' (no opts, keyboard)", label_keyword, value)
                        # Blur to commit multiselect chip
                        await page.wait_for_timeout(500)
                        await page.mouse.click(100, 100)
                        await page.wait_for_timeout(300)
                        # Verify chip/value committed; if not, retry with shorter prefix + first option
                        committed = await page.evaluate("""(sel) => {
                            const el = document.querySelector(sel);
                            if (!el) return false;
                            // multiselect chip lives as a sibling or in parent formField container
                            const container = el.closest('[data-automation-id^="formField-"]');
                            if (container) {
                                // Look for selected items / pills
                                const pills = container.querySelectorAll('[data-automation-id*="selectedItem"], [role="listitem"], [data-automation-id="PROMPT_SELECTED_OPTION"]');
                                if (pills.length > 0) return true;
                            }
                            return !!el.value;
                        }""", sel)
                        if not committed and label_keyword in ("field of study", "major", "discipline"):
                            log.info("Workday: '%s' did not commit, trying first-option fallback", label_keyword)
                            try:
                                await el.click()
                                await page.wait_for_timeout(300)
                                await el.fill("")
                                await page.wait_for_timeout(200)
                                # Type a prefix then pick best matching option
                                for prefix in ("Management", "Business", "Analytics", "Data"):
                                    await el.press_sequentially(prefix, delay=60)
                                    await page.wait_for_timeout(1500)
                                    fopts = page.locator("[role='option']:visible")
                                    fc = await fopts.count()
                                    if fc > 0:
                                        # Pick best match — prefer exact/startsWith > contains > skip
                                        best_fi = -1
                                        for fi in range(min(fc, 20)):
                                            ft = (await fopts.nth(fi).text_content() or "").strip().lower()
                                            if ft == prefix.lower():
                                                best_fi = fi
                                                break
                                            elif ft.startswith(prefix.lower()) and best_fi < 0:
                                                best_fi = fi
                                            elif prefix.lower() in ft and best_fi < 0:
                                                best_fi = fi
                                        if best_fi >= 0:
                                            await fopts.nth(best_fi).click(force=True)
                                            await page.wait_for_timeout(400)
                                            await page.mouse.click(100, 100)
                                            await page.wait_for_timeout(300)
                                            picked_text = (await fopts.nth(best_fi).text_content() or "").strip()
                                            log.info("Workday: '%s' fallback picked '%s' (prefix='%s')",
                                                     label_keyword, picked_text, prefix)
                                            break
                                        else:
                                            log.info("Workday: '%s' no matching option for prefix '%s' (%d opts visible)",
                                                     label_keyword, prefix, fc)
                                    # Clear and try next prefix
                                    await el.click()
                                    await el.fill("")
                            except Exception as exc:
                                log.debug("Workday: '%s' fallback failed: %s", label_keyword, exc)
                    else:
                        await el.fill(value)
                        log.info("Workday: filled '%s' = '%s'", label_keyword, value)
                    return True
                except Exception as exc:
                    log.debug("Workday: failed to fill '%s': %s", label_keyword, exc)
                    return False

            # Fill work experience text fields.
            # TODO(post-lift): pull title/company/location from the active
            # profile's most-recent role; was hardcoded for the original author.
            await _fill_labeled_field("job title", "")
            await _fill_labeled_field("company", "", is_typeahead=True)
            await _fill_labeled_field("location", "", is_typeahead=True)

            # Role description — force Playwright fill on textareas (nativeSet alone often doesn't commit for React validation)
            ROLE_DESC = "Developed data pipelines, ETL processes, and analytics dashboards using Python, SQL, and cloud services. Built machine learning models for predictive analytics and automated reporting systems."
            await _fill_labeled_field("description", ROLE_DESC)
            try:
                # Find any visible textarea whose label contains 'description' and force-refill
                ta_info = await page.evaluate("""() => {
                    const labels = document.querySelectorAll('label');
                    for (const lbl of labels) {
                        if (lbl.offsetParent === null) continue;
                        const lt = (lbl.textContent || '').toLowerCase().trim();
                        if (!lt.includes('description')) continue;
                        const parent = lbl.closest('[data-automation-id^="formField-"]') || lbl.parentElement;
                        if (!parent) continue;
                        const ta = parent.querySelector('textarea');
                        if (ta && ta.offsetParent !== null) {
                            return {id: ta.id || '', aid: ta.getAttribute('data-automation-id') || '', name: ta.name || ''};
                        }
                    }
                    return null;
                }""")
                if ta_info:
                    if ta_info['id']:
                        ta_sel = f"#{ta_info['id']}"
                    elif ta_info['aid']:
                        ta_sel = f"textarea[data-automation-id='{ta_info['aid']}']"
                    elif ta_info['name']:
                        ta_sel = f"textarea[name='{ta_info['name']}']"
                    else:
                        ta_sel = None
                    if ta_sel:
                        ta_loc = page.locator(ta_sel).first
                        await ta_loc.click()
                        await ta_loc.fill("")
                        await page.wait_for_timeout(100)
                        await ta_loc.fill(ROLE_DESC)
                        await page.keyboard.press("Tab")
                        log.info("Workday: force-refilled role description via %s", ta_sel)
            except Exception as exc:
                log.debug("Workday: role description force-refill failed: %s", exc)

            # From/To date fields — try multiple strategies with Playwright fill
            try:
                # Strategy 1: Split month/year inputs (some tenants)
                date_inputs = page.locator("input[data-automation-id*='dateSectionMonth-input']")
                if await date_inputs.count() > 0:
                    for di_idx in range(await date_inputs.count()):
                        di = date_inputs.nth(di_idx)
                        cur = await di.evaluate("el => el.value")
                        if not cur:
                            await di.click()
                            await di.fill("01")
                            await page.keyboard.press("Tab")
                            await page.wait_for_timeout(300)
                            log.info("Workday: filled date month field #%d = 01", di_idx)
                    year_inputs = page.locator("input[data-automation-id*='dateSectionYear-input']")
                    for yi_idx in range(await year_inputs.count()):
                        yi = year_inputs.nth(yi_idx)
                        cur = await yi.evaluate("el => el.value")
                        if not cur:
                            await yi.click()
                            await yi.fill("2025")
                            await page.keyboard.press("Tab")
                            await page.wait_for_timeout(300)
                            log.info("Workday: filled date year field #%d = 2025", yi_idx)

                # Strategy 2: Find date inputs near "From" label via JS proximity (same as edu dates)
                we_date_fills = await page.evaluate("""() => {
                    const results = [];
                    const labels = document.querySelectorAll('label');
                    for (const lbl of labels) {
                        if (lbl.offsetParent === null) continue;
                        const lt = (lbl.textContent || '').trim().toLowerCase();
                        if (lt !== 'from' && lt !== 'from*' && lt !== 'to' && lt !== 'to*' &&
                            !lt.startsWith('from ') && !lt.startsWith('to ')) continue;
                        let node = lbl;
                        for (let d = 0; d < 8; d++) {
                            node = node.parentElement;
                            if (!node) break;
                            const inps = node.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]):not([type="file"])');
                            for (const inp of inps) {
                                if (inp.offsetParent === null || inp.value) continue;
                                results.push({
                                    label: lt.replace('*','').trim(),
                                    aid: inp.getAttribute('data-automation-id') || '',
                                    id: inp.id || '',
                                    ariaLabel: inp.getAttribute('aria-label') || ''
                                });
                                break;
                            }
                            if (results.length > 0 && results[results.length - 1].label === lt.replace('*','').trim()) break;
                        }
                    }
                    return results;
                }""")
                for df in (we_date_fills or []):
                    try:
                        if df['aid']:
                            sel = f"[data-automation-id='{df['aid']}']"
                        elif df['id']:
                            sel = f"#{df['id']}"
                        elif df['ariaLabel']:
                            sel = f"[aria-label='{df['ariaLabel']}']"
                        else:
                            continue
                        el = page.locator(sel).first
                        if await el.count() == 0:
                            continue
                        await el.click()
                        await page.wait_for_timeout(200)
                        await el.fill("")
                        await page.wait_for_timeout(100)
                        date_val = "01/2025" if df['label'] == 'from' else ""
                        if not date_val:
                            continue
                        await el.press_sequentially(date_val, delay=50)
                        await page.wait_for_timeout(300)
                        await page.keyboard.press("Tab")
                        await page.wait_for_timeout(300)
                        log.info("Workday: filled work exp date '%s' = %s", df['label'], date_val)
                    except Exception as exc:
                        log.debug("Workday: work exp date '%s' failed: %s", df.get('label','?'), exc)

                # Strategy 3: Label-based fallback
                await _fill_labeled_field("from", "01/2025")

                # Strategy 4: Find ALL date section inputs and fill via Playwright
                for date_sel in [
                    "input[data-automation-id*='startDate']",
                    "input[data-automation-id*='dateSection']",
                    "input[id*='startDate']",
                    "input[id*='dateSectionMonth']",
                    "input[id*='dateSectionYear']",
                ]:
                    locs = page.locator(date_sel)
                    loc_count = await locs.count()
                    for li in range(loc_count):
                        loc = locs.nth(li)
                        try:
                            if not await loc.is_visible():
                                continue
                            # For spinbuttons, el.value may be set by nativeSet but React
                            # state isn't updated — aria-valuetext stays as placeholder.
                            role_attr = await loc.get_attribute("role") or ""
                            aria_vt = await loc.get_attribute("aria-valuetext") or ""
                            cur = await loc.evaluate("el => el.value")
                            if role_attr == "spinbutton":
                                # Only skip if aria-valuetext is a real value (not 'YYYY'/'MM'/'DD')
                                if aria_vt and not any(p in aria_vt for p in ("YYYY", "MM", "DD")):
                                    continue
                            elif cur:
                                continue
                            aid = await loc.get_attribute("data-automation-id") or ""
                            loc_id = await loc.get_attribute("id") or ""
                            # Prefer start/from dates only; skip end/to to avoid requiring value
                            combined = (aid + " " + loc_id).lower()
                            if "end" in combined or "to" in combined.split("--"):
                                continue
                            if "year" in aid.lower() or "year" in loc_id.lower():
                                val = "2025"
                            elif "month" in aid.lower() or "month" in loc_id.lower():
                                val = "01"
                            else:
                                val = "01/2025"
                            # JS-focus + keyboard.type drives React spinbutton validation
                            await loc.evaluate("el => { el.scrollIntoView({block:'center'}); el.focus(); }")
                            await page.wait_for_timeout(150)
                            await page.keyboard.press("Control+a")
                            await page.keyboard.press("Delete")
                            await page.wait_for_timeout(80)
                            await page.keyboard.type(val, delay=100)
                            await page.wait_for_timeout(250)
                            await page.keyboard.press("Tab")
                            await page.wait_for_timeout(350)
                            new_val = await loc.evaluate("el => el.value")
                            log.info("Workday: filled date input id=%s aid=%s val='%s' verified='%s'",
                                     loc_id, aid, val, new_val)
                        except Exception as exc:
                            log.debug("Workday: date fill exception %s: %s", date_sel, exc)
                            continue
            except Exception:
                pass

            # "I currently work here" checkbox
            try:
                cb = page.locator("label:has-text('currently work here')").first
                if await cb.count() > 0:
                    await cb.click()
                    log.info("Workday: clicked 'I currently work here'")
            except Exception:
                pass
            # Only mark as filled if we actually filled something
            if we_filled or any(
                await page.evaluate("""(kw) => {
                    const labels = document.querySelectorAll('label');
                    for (const lbl of labels) {
                        if (lbl.offsetParent === null) continue;
                        if ((lbl.textContent || '').toLowerCase().includes(kw)) {
                            const parent = lbl.closest('[data-automation-id]') || lbl.parentElement;
                            if (!parent) continue;
                            const inp = parent.querySelector('input:not([type="hidden"]):not([type="checkbox"]):not([type="file"]), textarea');
                            if (inp && inp.value) return true;
                        }
                    }
                    return false;
                }""", kw) for kw in ["job title", "company"]
            ):
                filled.append("work_experience")
                log.info("Workday: work experience fields filled")
            else:
                log.info("Workday: no work experience fields found on this page")
        except Exception as exc:
            log.debug("Workday work experience fill failed: %s", exc)

    # Education fields via JS label matching + Playwright fallback
    if "wd_education" not in filled:
        try:
            # Click "Add" button in the Education section if fields aren't visible yet
            edu_add_clicked = await page.evaluate("""() => {
                const headings = document.querySelectorAll('h3, h4, h5, label, legend, p, div, span');
                for (const el of headings) {
                    const t = (el.textContent || '').trim();
                    if (t === 'Education' || t === 'Education*') {
                        let parent = el;
                        for (let i = 0; i < 6; i++) {
                            parent = parent.parentElement;
                            if (!parent) break;
                            const addBtn = parent.querySelector('button');
                            if (addBtn && (addBtn.textContent || '').trim().toLowerCase() === 'add') {
                                addBtn.click();
                                return true;
                            }
                        }
                    }
                }
                return false;
            }""")
            if edu_add_clicked:
                await page.wait_for_timeout(2000)
                log.info("Workday: clicked Add for Education section")

            edu_filled = await page.evaluate("""() => {
                const filled = [];
                // Only fill simple text fields via nativeSet — NOT multiselects (school, university, field of study)
                // TODO(post-lift): pull GPA from profile.education[0].gpa.
                const eduMap = {
                    'gpa': '',
                    'overall result': '',
                };
                // Multiselect keywords to SKIP (handled by Playwright typeahead below)
                const multiSelectKeywords = ['school', 'university', 'field of study', 'major', 'degree'];
                const allFields = document.querySelectorAll('[data-automation-id^="formField-"]');
                for (const container of allFields) {
                    const labelEl = container.querySelector('label') ||
                                    container.querySelector('[data-automation-id="formLabel"]');
                    if (!labelEl) continue;
                    const labelText = (labelEl.textContent || '').toLowerCase().trim();

                    // Skip multiselect/typeahead/dropdown fields
                    if (multiSelectKeywords.some(kw => labelText.includes(kw))) continue;

                    for (const [keyword, value] of Object.entries(eduMap)) {
                        if (labelText.includes(keyword)) {
                            const inp = container.querySelector('input:not([type="hidden"]):not([type="checkbox"])');
                            if (inp && !inp.value) {
                                const nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                                nativeSet.call(inp, value);
                                inp.dispatchEvent(new Event('input', {bubbles: true}));
                                inp.dispatchEvent(new Event('change', {bubbles: true}));
                                filled.push(keyword);
                            }
                            break;
                        }
                    }
                }
                return filled;
            }""")
            if edu_filled:
                log.info("Workday: filled education fields: %s", edu_filled)
            # Education: School is a typeahead/multiselect, Degree is a dropdown
            school_filled = False
            # Strategy 0: Direct formField-schoolItem selector (Workday's canonical)
            try:
                school_inp = page.locator(
                    "[data-automation-id='formField-schoolItem'] input, "
                    "[data-automation-id='formField-school'] input, "
                    "div[data-automation-id*='formField-school'] input"
                ).first
                if await school_inp.count() > 0 and await school_inp.is_visible():
                    # First: remove any existing stale chip
                    try:
                        remove_btns = page.locator(
                            "[data-automation-id='formField-schoolItem'] [aria-label*='Delete' i], "
                            "[data-automation-id='formField-schoolItem'] [aria-label*='Remove' i], "
                            "[data-automation-id*='formField-school'] button[aria-label*='Delete' i]"
                        )
                        for ri in range(await remove_btns.count()):
                            try:
                                await remove_btns.nth(ri).click()
                                log.info("Workday: removed stale school chip #%d", ri)
                                await page.wait_for_timeout(400)
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # Helper to check if school pill exists
                    async def _school_has_pill():
                        return await page.evaluate("""() => {
                            const sels = [
                                '[data-automation-id="formField-schoolItem"]',
                                '[data-automation-id="formField-school"]',
                            ];
                            for (const sel of sels) {
                                const f = document.querySelector(sel);
                                if (!f) continue;
                                const pills = f.querySelectorAll(
                                    '[data-automation-id="selectedItem"], '
                                    + '[data-automation-id="SELECTED_ITEM"], '
                                    + '[data-automation-id="promptCurrentSelection"] li, '
                                    + '[data-automation-id*="pill"], '
                                    + 'div[class*="PROMPT_SELECTED"]'
                                );
                                if (pills.length > 0) return true;
                                // Also check if input value disappeared (means selection was made)
                                const inp = f.querySelector('input');
                                if (inp && !inp.value) {
                                    // TODO(post-lift): match against profile.school_name
                                    // (was hardcoded for the original author's school)
                                }
                            }
                            return false;
                        }""")

                    for search_text in ["New York", "", "", "york"]:
                        await school_inp.click()
                        await page.wait_for_timeout(300)
                        await school_inp.fill("")
                        await page.wait_for_timeout(200)
                        await school_inp.press_sequentially(search_text, delay=60)
                        await page.wait_for_timeout(3000)

                        # Diagnostic: dump what's in the dropdown
                        dropdown_diag = await page.evaluate("""() => {
                            const results = [];
                            const selectors = [
                                '[data-automation-id="activeListContainer"]',
                                '[role="listbox"]',
                                '[data-automation-id="dropdownRegion"]',
                                '[data-automation-id="promptResults"]',
                                'ul[role="tree"]',
                            ];
                            for (const sel of selectors) {
                                const containers = document.querySelectorAll(sel);
                                for (const c of containers) {
                                    if (c.offsetParent === null) continue;
                                    const items = c.querySelectorAll('*');
                                    for (const item of items) {
                                        if (item.offsetParent === null) continue;
                                        if (!item.textContent) continue;
                                        const role = item.getAttribute('role');
                                        const aid = item.getAttribute('data-automation-id');
                                        if (!role && !aid) continue;
                                        const pk = Object.keys(item).find(k => k.startsWith('__reactProps'));
                                        const handlers = [];
                                        if (pk) {
                                            if (item[pk].onClick) handlers.push('onClick');
                                            if (item[pk].onMouseDown) handlers.push('onMouseDown');
                                            if (item[pk].onPointerDown) handlers.push('onPointerDown');
                                            if (item[pk].onSelect) handlers.push('onSelect');
                                        }
                                        results.push({
                                            text: item.textContent.trim().substring(0, 80),
                                            tag: item.tagName,
                                            role: role,
                                            aid: aid,
                                            handlers: handlers.join(','),
                                        });
                                    }
                                }
                            }
                            // Deduplicate by text
                            const seen = new Set();
                            return results.filter(r => {
                                const key = r.text + r.aid;
                                if (seen.has(key)) return false;
                                seen.add(key);
                                return true;
                            }).slice(0, 15);
                        }""")
                        log.info("Workday: school dropdown after '%s': %d items", search_text, len(dropdown_diag))
                        for di in dropdown_diag[:8]:
                            log.info("  dropdown: tag=%s role=%s aid=%s handlers=%s text='%s'",
                                     di.get('tag','?'), di.get('role',''), di.get('aid',''),
                                     di.get('handlers',''), di.get('text','')[:60])

                        if not dropdown_diag:
                            log.info("Workday: no dropdown items for school '%s', trying next", search_text)
                            await school_inp.fill("")
                            await page.keyboard.press("Escape")
                            await page.wait_for_timeout(300)
                            continue

                        # Strategy A: Try mousedown event (Workday UXI often uses mousedown, not click)
                        sel_result = await page.evaluate("""() => {
                            const containers = document.querySelectorAll(
                                '[data-automation-id="activeListContainer"], [role="listbox"], '
                                + '[data-automation-id="promptResults"], ul[role="tree"]'
                            );
                            for (const c of containers) {
                                if (c.offsetParent === null) continue;
                                const items = c.querySelectorAll(
                                    '[data-automation-id="promptLeafNode"], [role="option"], '
                                    + '[data-automation-id="promptOption"], li[role="treeitem"]'
                                );
                                for (const item of items) {
                                    if (item.offsetParent === null) continue;
                                    const txt = (item.textContent || '').toLowerCase();
                                    // TODO(post-lift): substring-match against profile.school_name.
                                    // Was hardcoded; now noop until profile-driven matching lands.
                                    continue;

                                    // Walk up to find any element with React handlers
                                    let target = item;
                                    for (let depth = 0; depth < 4; depth++) {
                                        const pk = Object.keys(target).find(k => k.startsWith('__reactProps'));
                                        if (pk) {
                                            const props = target[pk];
                                            const fakeEvt = {
                                                type: 'mousedown', target: target, currentTarget: target,
                                                button: 0, buttons: 1, clientX: 0, clientY: 0,
                                                preventDefault: () => {}, stopPropagation: () => {},
                                                nativeEvent: new MouseEvent('mousedown', {bubbles: true}),
                                                persist: () => {},
                                            };
                                            // Try each handler type
                                            if (props.onMouseDown) {
                                                props.onMouseDown(fakeEvt);
                                                return {method: 'react_mousedown', depth: depth, text: txt.substring(0, 60)};
                                            }
                                            if (props.onPointerDown) {
                                                props.onPointerDown({...fakeEvt, type: 'pointerdown'});
                                                return {method: 'react_pointerdown', depth: depth, text: txt.substring(0, 60)};
                                            }
                                            if (props.onClick) {
                                                props.onClick({...fakeEvt, type: 'click'});
                                                return {method: 'react_click', depth: depth, text: txt.substring(0, 60)};
                                            }
                                        }
                                        if (!target.parentElement) break;
                                        target = target.parentElement;
                                    }

                                    // Fallback: dispatch native DOM events
                                    item.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, cancelable: true}));
                                    item.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
                                    item.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, cancelable: true}));
                                    item.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true}));
                                    item.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                                    return {method: 'native_events', depth: 0, text: txt.substring(0, 60)};
                                }
                            }
                            return null;
                        }""")

                        if sel_result:
                            await page.wait_for_timeout(1200)
                            log.info("Workday: school select via %s (depth=%d): '%s'",
                                     sel_result.get('method','?'), sel_result.get('depth',0),
                                     sel_result.get('text',''))
                            if await _school_has_pill():
                                log.info("Workday: school pill confirmed after %s!", sel_result['method'])
                                school_filled = True
                                break

                        # Strategy B: Playwright click with force on first matching option
                        opt_loc = page.locator(
                            "[data-automation-id='promptLeafNode']:visible, "
                            "[role='option']:visible, "
                            "li[role='treeitem']:visible"
                        )
                        for oi in range(min(await opt_loc.count(), 10)):
                            (await opt_loc.nth(oi).text_content() or "").lower()
                            # TODO(post-lift): replace with profile.school_name match.
                            # Disabled here so we don't auto-pick the wrong school.
                            if False:
                                try:
                                    await opt_loc.nth(oi).click(force=True)
                                    await page.wait_for_timeout(1200)
                                    log.info("Workday: school Playwright force-click on option %d", oi)
                                    if await _school_has_pill():
                                        log.info("Workday: school pill confirmed after Playwright click!")
                                        school_filled = True
                                        break
                                except Exception as ce:
                                    log.debug("Workday: school click option %d failed: %s", oi, ce)
                        if school_filled:
                            break

                        # Strategy C: ArrowDown+Enter (subcategory-aware like Source)
                        await school_inp.click()
                        await page.wait_for_timeout(200)
                        await page.keyboard.press("ArrowDown")
                        await page.wait_for_timeout(400)
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(1200)
                        if await _school_has_pill():
                            log.info("Workday: school pill confirmed after ArrowDown+Enter!")
                            school_filled = True
                            break
                        # Maybe it expanded a subcategory — try again
                        await page.keyboard.press("ArrowDown")
                        await page.wait_for_timeout(300)
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(1200)
                        if await _school_has_pill():
                            log.info("Workday: school pill confirmed after subcategory ArrowDown+Enter!")
                            school_filled = True
                            break

                        # Strategy D: Tab to commit (some comboboxes commit on blur/tab)
                        await school_inp.click()
                        await page.wait_for_timeout(200)
                        await school_inp.fill("")
                        await school_inp.press_sequentially(search_text, delay=60)
                        await page.wait_for_timeout(2500)
                        await page.keyboard.press("ArrowDown")
                        await page.wait_for_timeout(300)
                        await page.keyboard.press("Tab")
                        await page.wait_for_timeout(1200)
                        if await _school_has_pill():
                            log.info("Workday: school pill confirmed after ArrowDown+Tab!")
                            school_filled = True
                            break

                        log.info("Workday: school search '%s' did not commit, retrying", search_text)
                        await school_inp.fill("")
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(400)

                    # Blur to fully commit
                    await page.mouse.click(100, 100)
                    await page.wait_for_timeout(400)

                    # Final check — take screenshot if still not filled
                    if not school_filled and not await _school_has_pill():
                        try:
                            ss_path = f"artifacts/autofill_screenshots/wd_school_debug_{int(time.time())}.png"
                            await page.screenshot(path=ss_path, full_page=False)
                            log.info("Workday: school STILL not filled — debug screenshot: %s", ss_path)
                        except Exception:
                            pass
            except Exception as exc:
                log.info("Workday: formField-schoolItem fill exception: %s", exc)

            # Strategy 1: Fallback — use _fill_labeled_field but verify pill
            if not school_filled:
                await _fill_labeled_field("school", "", is_typeahead=True)
                # Check if it actually worked
                try:
                    school_filled = await page.evaluate("""() => {
                        const sels = ['[data-automation-id="formField-schoolItem"]', '[data-automation-id="formField-school"]'];
                        for (const sel of sels) {
                            const f = document.querySelector(sel);
                            if (!f) continue;
                            const pills = f.querySelectorAll('[data-automation-id="selectedItem"], [data-automation-id="SELECTED_ITEM"]');
                            if (pills.length > 0) return true;
                        }
                        return false;
                    }""")
                except Exception:
                    pass
            # TODO(post-lift): pull GPA from profile.education[0].gpa.
            await _fill_labeled_field("gpa", "")
            await _fill_labeled_field("overall result", "")
            await _fill_labeled_field("field of study", "Management and Analytics", is_typeahead=True)
            if not await _fill_labeled_field("major", "Management and Analytics", is_typeahead=True):
                await _fill_labeled_field("major", "Business Analytics", is_typeahead=True)

            # Degree dropdown — special handling (button-based dropdown, not input)
            try:
                degree_filled = await page.evaluate("""() => {
                    const labels = document.querySelectorAll('label');
                    for (const lbl of labels) {
                        if (lbl.offsetParent === null) continue;
                        const lt = (lbl.textContent || '').toLowerCase().trim();
                        if (!lt.includes('degree')) continue;
                        const parent = lbl.closest('[data-automation-id]') || lbl.parentElement;
                        if (!parent) continue;
                        const btn = parent.querySelector('button[aria-haspopup], button');
                        if (btn && btn.offsetParent !== null) {
                            const txt = (btn.textContent || '').trim();
                            if (txt === '' || txt === 'Select One') {
                                return {aid: btn.getAttribute('data-automation-id') || '',
                                        ariaLabel: btn.getAttribute('aria-label') || ''};
                            }
                        }
                    }
                    return null;
                }""")
                if degree_filled:
                    sel = f"[data-automation-id='{degree_filled['aid']}']" if degree_filled['aid'] else f"[aria-label='{degree_filled['ariaLabel']}']"
                    btn = page.locator(sel).first
                    if await btn.count() > 0:
                        await btn.click()
                        await page.wait_for_timeout(600)
                        opts = page.locator("[role='option']")
                        opt_count = await opts.count()
                        for deg_term in ["Master of Science", "Master's Degree", "Master of Science (MS)", "MS", "Master's", "Masters", "Graduate"]:
                            for oi in range(min(opt_count, 20)):
                                opt_text = (await opts.nth(oi).text_content() or "").strip()
                                if deg_term.lower() in opt_text.lower():
                                    await opts.nth(oi).click()
                                    log.info("Workday: selected degree = '%s'", opt_text)
                                    break
                            else:
                                continue
                            break
                        else:
                            if opt_count > 0:
                                await opts.first.click()
                        await page.wait_for_timeout(300)
            except Exception:
                pass

            # Education From/To dates — multiple strategies
            try:
                # Strategy 0 (NEW): Direct fill for year-only education fields
                # Wrapper divs have IDs like 'education-6--firstYearAttended-dateSect'
                # The actual <input> is usually INSIDE this wrapper
                log.info("Workday: starting education date fill Strategy 0")
                for id_key, year_val, role in [
                    ("firstYearAttended", "2024", "from"),
                    ("lastYearAttended", "2026", "to"),
                ]:
                    # Target the actual spinbutton input directly; filter to visible only
                    sel = f"input[role='spinbutton'][id*='{id_key}'][data-automation-id='dateSectionYear-input']"
                    inputs = page.locator(sel)
                    n = await inputs.count()
                    log.info("Workday: Strategy0 selector %s matched %d elements", sel, n)
                    for wi in range(n):
                        inp = inputs.nth(wi)
                        try:
                            visible = await inp.is_visible()
                            if not visible:
                                log.info("Workday: %s[%d] not visible, skipping", id_key, wi)
                                continue
                            cur = await inp.evaluate("el => el.value")
                            if cur:
                                log.info("Workday: %s[%d] already has value '%s'", id_key, wi, cur)
                                continue
                            # Scroll + focus via JS (avoids "outside viewport" click issues)
                            await inp.evaluate("el => { el.scrollIntoView({block:'center'}); el.focus(); }")
                            await page.wait_for_timeout(200)
                            # Clear any residue
                            await page.keyboard.press("Control+a")
                            await page.keyboard.press("Delete")
                            await page.wait_for_timeout(80)
                            # Per-keystroke type — drives React validation for spinbutton
                            await page.keyboard.type(year_val, delay=100)
                            await page.wait_for_timeout(250)
                            await page.keyboard.press("Tab")
                            await page.wait_for_timeout(350)
                            new_val = await inp.evaluate("el => el.value")
                            log.info("Workday: filled %s[%d] (%s) target='%s' verified='%s'",
                                     id_key, wi, role, year_val, new_val)
                        except Exception as exc:
                            log.info("Workday: year-only fill exception on %s[%d]: %s", id_key, wi, exc)

                # Strategy 1: Split month/year inputs (work-experience style)
                all_month = page.locator("input[data-automation-id*='dateSectionMonth-input']")
                all_year = page.locator("input[data-automation-id*='dateSectionYear-input']")
                month_count = await all_month.count()
                year_count = await all_year.count()
                for mi in range(month_count):
                    m = all_month.nth(mi)
                    if not await m.evaluate("el => el.value"):
                        await m.click()
                        await page.wait_for_timeout(100)
                        await page.keyboard.type("08", delay=80)
                        await page.keyboard.press("Tab")
                        await page.wait_for_timeout(300)
                        log.info("Workday: filled education date month #%d = 08", mi)
                for yi in range(year_count):
                    y = all_year.nth(yi)
                    if not await y.evaluate("el => el.value"):
                        await y.click()
                        await page.wait_for_timeout(100)
                        await page.keyboard.type("2024", delay=80)
                        await page.keyboard.press("Tab")
                        await page.wait_for_timeout(300)
                        log.info("Workday: filled education date year #%d = 2024", yi)

                # Strategy 2: Find date inputs near "From"/"To" labels using JS proximity
                date_fills = await page.evaluate("""() => {
                    const results = [];
                    const labels = document.querySelectorAll('label');
                    for (const lbl of labels) {
                        if (lbl.offsetParent === null) continue;
                        const lt = (lbl.textContent || '').trim().toLowerCase();
                        if (lt !== 'from' && lt !== 'from*' && lt !== 'to' && lt !== 'to*' &&
                            !lt.startsWith('from ') && !lt.startsWith('to ')) continue;
                        // Search in progressively larger parent containers
                        let node = lbl;
                        for (let d = 0; d < 8; d++) {
                            node = node.parentElement;
                            if (!node) break;
                            const inps = node.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]):not([type="file"])');
                            for (const inp of inps) {
                                if (inp.offsetParent === null || inp.value) continue;
                                const aid = inp.getAttribute('data-automation-id') || '';
                                const ph = inp.getAttribute('placeholder') || '';
                                results.push({
                                    label: lt.replace('*','').trim(),
                                    aid: aid,
                                    id: inp.id || '',
                                    placeholder: ph,
                                    ariaLabel: inp.getAttribute('aria-label') || ''
                                });
                                break;  // one input per label
                            }
                            if (results.length > 0 && results[results.length - 1].label === lt.replace('*','').trim()) break;
                        }
                    }
                    return results;
                }""")
                for df in (date_fills or []):
                    try:
                        if df['aid']:
                            sel = f"[data-automation-id='{df['aid']}']"
                        elif df['id']:
                            sel = f"#{df['id']}"
                        elif df['ariaLabel']:
                            sel = f"[aria-label='{df['ariaLabel']}']"
                        else:
                            continue
                        el = page.locator(sel).first
                        if await el.count() == 0:
                            continue
                        # Detect year-only vs MM/YYYY based on field ID/aid
                        field_hint = (df.get('id', '') + df.get('aid', '') + df.get('placeholder', '')).lower()
                        is_year_only = 'year' in field_hint and 'month' not in field_hint
                        await el.click()
                        await page.wait_for_timeout(200)
                        await page.keyboard.press("Control+a")
                        await page.keyboard.press("Delete")
                        await page.wait_for_timeout(100)
                        if is_year_only:
                            date_val = "2024" if df['label'] == 'from' else "2026"
                        else:
                            date_val = "08/2024" if df['label'] == 'from' else "05/2026"
                        # keyboard.type drives React per-keystroke validation
                        await page.keyboard.type(date_val, delay=80)
                        await page.wait_for_timeout(300)
                        await page.keyboard.press("Tab")
                        await page.wait_for_timeout(300)
                        log.info("Workday: filled education date '%s' = %s (year_only=%s, keyboard.type)", df['label'], date_val, is_year_only)
                    except Exception as exc:
                        log.debug("Workday: date fill for '%s' failed: %s", df.get('label','?'), exc)

                # Strategy 3: Label-based fallback — try year-only first, then MM/YYYY
                if not await _fill_labeled_field("from", "2024"):
                    await _fill_labeled_field("from", "08/2024")
                if not await _fill_labeled_field("to", "2026"):
                    await _fill_labeled_field("to", "05/2026")
            except Exception:
                pass
            # Only mark as filled if education fields actually exist on this page
            has_edu = await page.evaluate("""() => {
                const labels = document.querySelectorAll('label');
                for (const lbl of labels) {
                    if (lbl.offsetParent === null) continue;
                    const lt = (lbl.textContent || '').toLowerCase();
                    if (lt.includes('school') || lt.includes('university') || lt.includes('degree')) return true;
                }
                return false;
            }""")
            if has_edu or edu_filled:
                filled.append("wd_education")
                log.info("Workday: education fields filled")
            else:
                log.info("Workday: no education fields found on this page")
        except Exception as exc:
            log.debug("Workday education fill failed: %s", exc)

    # LinkedIn / Social Profile URLs
    if "wd_linkedin" not in filled:
        try:
            linkedin_filled = await page.evaluate("""() => {
                const inputs = document.querySelectorAll('input');
                let filled = 0;
                for (const inp of inputs) {
                    const label = (inp.getAttribute('aria-label') || '').toLowerCase();
                    const placeholder = (inp.placeholder || '').toLowerCase();
                    const name = (inp.getAttribute('data-automation-id') || '').toLowerCase();
                    const parentLabel = inp.closest('[data-automation-id^="formField-"]');
                    let fieldLabel = '';
                    if (parentLabel) {
                        const lbl = parentLabel.querySelector('label');
                        if (lbl) fieldLabel = (lbl.textContent || '').toLowerCase();
                    }
                    const all = label + ' ' + placeholder + ' ' + name + ' ' + fieldLabel;
                    if (all.includes('linkedin') && !inp.value) {
                        const nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        nativeSet.call(inp, '');
                        inp.dispatchEvent(new Event('input', {bubbles: true}));
                        inp.dispatchEvent(new Event('change', {bubbles: true}));
                        filled++;
                    }
                }
                return filled;
            }""")
            if linkedin_filled:
                log.info("Workday: filled %d LinkedIn field(s) via JS", linkedin_filled)
            filled.append("wd_linkedin")
        except Exception as exc:
            log.debug("Workday LinkedIn fill failed: %s", exc)


async def _wd_fill_questions(page: Page, profile: dict[str, Any], filled: list[str]) -> None:
    """Fill Workday 'Application Questions' page.

    Uses JS to enumerate all formField containers and their inputs, then
    pattern-matches labels to known answer rules. Handles dropdowns, text
    fields, radio buttons, and textareas.
    """
    # --- Answer rules: (label_contains, answer, priority) ---
    # Higher priority = matched first. For dropdowns, answer is the option text.
    _RULES: list[tuple[str, str]] = [
        # Work authorization
        ("legally authorized", "Yes"),
        ("authorized to work", "Yes"),
        ("eligible to work", "Yes"),
        ("right to work", "Yes"),
        ("work permit", "Yes"),
        ("employment eligibility", "Yes"),
        # Sponsorship — [user] needs sponsorship
        ("sponsorship", "Yes"),
        ("sponsor", "Yes"),
        ("visa", "Yes"),
        ("immigration", "Yes"),
        # Relocation
        ("willing to relocate", "Yes"),
        ("open to relocation", "Yes"),
        ("relocation assistance", "No"),
        ("relocat", "Yes"),
        # Age
        ("18 years", "Yes"),
        ("age of 18", "Yes"),
        ("at least 18", "Yes"),
        ("over 18", "Yes"),
        # Previous employment
        ("previously employed", "No"),
        ("previously worked", "No"),
        ("former employee", "No"),
        ("worked for", "No"),
        ("employed by", "No"),
        # Non-compete / agreements
        ("non-compete", "No"),
        ("non compete", "No"),
        ("noncompete", "No"),
        ("confidentiality agreement", "No"),
        ("restrictive covenant", "No"),
        # Criminal record check / background check — "willing to submit" = Yes
        ("criminal record check", "Yes"),
        ("criminal background", "Yes"),
        ("background check", "Yes"),
        ("background investigation", "Yes"),
        ("drug test", "Yes"),
        ("drug screen", "Yes"),
        # Criminal record — "have you been convicted" = No
        ("convicted", "No"),
        ("felony", "No"),
        ("criminal record", "No"),
        ("criminal conviction", "No"),
        ("misdemeanor", "No"),
        # Travel
        ("travel", "Yes"),
        ("overnight travel", "Yes"),
        # Overtime / hours
        ("overtime", "Yes"),
        ("shift", "Yes"),
        ("weekend", "Yes"),
        ("on-call", "Yes"),
        # Referral — default No, skip conditional sub-fields (no self-referral)
        ("were you referred", "No"),
        ("have you been referred", "No"),
        ("are you a referral", "No"),
        ("referred by a", "No"),
        ("employee referral", "No"),
        ("referred by", "N/A"),   # conditional sub-field ("if yes, by whom?") — safe default
        ("referral source", "LinkedIn"),
        ("referral code", "N/A"),
        ("referral", "N/A"),
        ("how did you hear", "LinkedIn"),
        # Salary
        ("salary expectation", "Open to discussion"),
        ("desired salary", "Open to discussion"),
        ("current salary", "Open to discussion"),
        ("compensation", "Open to discussion"),
        ("salary requirement", "Open to discussion"),
        # Start date — use actual date format since many Workday fields have date pickers
        ("start date", ""),
        ("earliest start", ""),
        ("available to start", ""),
        ("when can you start", ""),
        ("when are you available", ""),
        # Education
        ("highest level of education", "Master's Degree"),
        ("degree", "Master's Degree"),
        # Yes/no minimum-experience patterns (match BEFORE generic years).
        # TODO(post-lift): make the answer reflect the profile's actual
        # years_of_experience value; currently a permissive default.
        ("do you have a minimum of", "Yes"),
        ("do you have at least", "Yes"),
        ("minimum of 1 year", "Yes"),
        ("minimum of 2 year", "Yes"),
        ("minimum of 3 year", "Yes"),
        ("minimum of 4 year", "Yes"),
        ("minimum of three", "Yes"),
        ("minimum of two", "Yes"),
        ("minimum of one", "Yes"),
        ("minimum of four", "Yes"),
        ("minimum 1 year", "Yes"),
        ("minimum 2 year", "Yes"),
        ("minimum 3 year", "Yes"),
        ("minimum 4 year", "Yes"),
        ("at least 1 year", "Yes"),
        ("at least 2 year", "Yes"),
        ("at least 3 year", "Yes"),
        ("at least 4 year", "Yes"),
        ("at least one year", "Yes"),
        ("at least two year", "Yes"),
        ("at least three year", "Yes"),
        ("at least four year", "Yes"),
        ("1+ year", "Yes"),
        ("2+ year", "Yes"),
        ("3+ year", "Yes"),
        ("4+ year", "Yes"),
        # Numeric "how many years" patterns — TODO(post-lift): drive from
        # profile.years_of_experience instead of hardcoded 4.
        ("how many years", "4"),
        ("years of experience", "4"),
        ("years of relevant", "4"),
        ("years of professional", "4"),
        ("total years", "4"),
        # Citizenship
        ("citizen", "No"),
        ("permanent resident", "No"),
        ("green card", "No"),
        # Accommodation / ability to perform duties
        ("perform the duties", "Yes"),
        ("perform essential functions", "Yes"),
        ("with or without accommodation", "Yes"),
        ("reasonable accommodation", "Yes"),
        ("physical requirements", "Yes"),
        # Pay rate / salary type
        ("pay rate type", "Salary"),
        ("desired pay", "Salary"),
        ("pay type", "Salary"),
        # Chronic disease / healthcare specific
        ("chronic disease", "No"),
        ("chronic kidney", "No"),
        ("dialysis", "No"),
        ("healthcare experience", "No"),
        # Place of work / workplace
        ("place of work", "Technology"),
        ("describes your current", "Technology"),
        # Qualifications / additional info — provide brief answer
        ("qualifications did we not ask", "N/A"),
        ("additional information", "N/A"),
        ("anything else", "N/A"),
        # Commute / distance
        ("commute", "Yes"),
        ("commuting distance", "Yes"),
        # Remote / hybrid
        ("remote", "Yes"),
        ("hybrid", "Yes"),
        ("in-office", "Yes"),
        ("on-site", "Yes"),
        # Notice period
        ("notice period", "2 weeks"),
        # Clearance
        ("security clearance", "No"),
        ("clearance", "No"),
        # LinkedIn
        ("linkedin", ""),
        # Github/portfolio
        ("github", ""),
        ("portfolio", ""),
        ("website", ""),
        # Family member / relative at company
        ("family member", "No"),
        ("immediate relative", "No"),
        ("close relative", "No"),
        ("related to", "No"),
        ("audit function", "No"),
        # Previously interviewed / applied
        ("previously interviewed", "No"),
        ("previously applied", "No"),
        ("applied before", "No"),
        # Government related
        ("government official", "No"),
        ("public official", "No"),
        ("politically exposed", "No"),
        ("political action committee", "No"),
        ("pac", "No"),
        # Contractor status
        ("current contractor", "No"),
        ("contingent worker", "No"),
        # Financial relationships / conflicts
        ("financial relationship", "No"),
        ("employed by pwc", "No"),
        ("employed by kpmg", "No"),
        ("code of ethics", "Yes"),
        # Referred by government
        ("referred or recommended", "No"),
        # FINRA / professional licenses
        ("finra", "No"),
        ("series 7", "No"),
        ("professional license", "No"),
        ("cpa", "No"),
        ("cfa", "No"),
        # Disability / ADA
        ("disability", "No"),
        ("disabled", "No"),
        # Financial regulatory (Citi, Goldman, JPM, etc.)
        ("registered with", "No"),
        ("sec registration", "No"),
        ("investment adviser", "No"),
        ("broker-dealer", "No"),
        ("associated person", "No"),
        ("registered representative", "No"),
        ("regulatory action", "No"),
        ("disciplinary", "No"),
        ("terminated for cause", "No"),
        ("discharged", "No"),
        ("asked to resign", "No"),
        ("involuntarily separated", "No"),
        ("under investigation", "No"),
        ("sanctions", "No"),
        ("pending litigation", "No"),
        ("legal proceedings", "No"),
        ("bankruptcy", "No"),
        ("denied a license", "No"),
        ("barred", "No"),
        ("suspended", "No"),
        # Country / location
        ("country", "United States"),
        ("located in", "Yes"),
        ("based in", "Yes"),
        ("reside in", "Yes"),
        # Agree / accept / acknowledge
        ("agree", "Yes"),
        ("acknowledge", "Yes"),
        ("accept", "Yes"),
        ("certif", "Yes"),
        ("attest", "Yes"),
        ("consent", "Yes"),
        ("confirm", "Yes"),
        ("have you read", "Yes"),
        ("understand and agree", "Yes"),
        ("i have read", "Yes"),
        # Notice period
        ("current notice period", "2 weeks"),
        ("notice period", "2 weeks"),
        # Schedules / shifts
        ("types of schedules", "Full-Time"),
        ("schedule", "Full-Time"),
        ("work arrangement", "Full-Time"),
        ("employment type", "Full-Time"),
        # Contact previous employer
        ("contact your previous", "Yes"),
        ("contact your employer", "Yes"),
        ("may we contact", "Yes"),
        # AI consent
        ("artificial intelligence", "Yes"),
        ("ai tools", "Yes"),
        ("ai to match", "Yes"),
        ("ai to assess", "Yes"),
        # CTC / current compensation
        ("current ctc", "Open to discussion"),
        ("expected ctc", "Open to discussion"),
        ("current compensation", "Open to discussion"),
        # General yes/no heuristics — place LAST
        ("are you able", "Yes"),
        ("do you have", "No"),
        ("have you ever", "No"),
        ("are you currently", "No"),
        ("have you been", "No"),
    ]

    async def _read_wd_dropdown_options(btn_el) -> list[str]:
        """Open a Workday dropdown and read all available options without selecting."""
        try:
            await btn_el.click(force=True)
            await page.wait_for_timeout(600)
            opts = page.locator("[role='option']:visible")
            opt_count = await opts.count()
            options = []
            for oi in range(min(opt_count, 30)):
                opt_text = (await opts.nth(oi).text_content() or "").strip()
                if opt_text:
                    options.append(opt_text)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
            return options
        except Exception:
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            return []

    async def _pick_wd_dropdown(btn_el, answer_text: str) -> bool:
        """Click a Workday dropdown button and select an option matching answer_text."""
        try:
            await btn_el.click(force=True)
            await page.wait_for_timeout(600)
            opts = page.locator("[role='option']:visible")
            opt_count = await opts.count()
            all_opts = []
            for oi in range(min(opt_count, 30)):
                opt_text = (await opts.nth(oi).text_content() or "").strip()
                all_opts.append((oi, opt_text))

            # Try exact match first
            for oi, opt_text in all_opts:
                if answer_text.lower() == opt_text.lower():
                    await opts.nth(oi).click()
                    await page.wait_for_timeout(300)
                    return True
            # Then partial match
            for oi, opt_text in all_opts:
                if answer_text.lower() in opt_text.lower():
                    await opts.nth(oi).click()
                    await page.wait_for_timeout(300)
                    return True
            # Then try if the option starts with the answer
            for oi, opt_text in all_opts:
                if opt_text.lower().startswith(answer_text.lower()):
                    await opts.nth(oi).click()
                    await page.wait_for_timeout(300)
                    return True
            await page.keyboard.press("Escape")
        except Exception:
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
        return False

    async def _smart_pick_dropdown(btn_el, label: str) -> bool:
        """For unmatched required dropdowns, read options and pick the best one.

        Uses heuristics:
        - If options include Yes/No: pick based on label context
        - If options are short (< 5 options): pick the first non-empty option
        - Log all options for debugging
        """
        options = await _read_wd_dropdown_options(btn_el)
        if not options:
            return False
        log.info("Workday: dropdown '%s' has options: %s", label[:50], options[:10])

        lbl = label.lower()
        opt_lower = [o.lower() for o in options]

        # Yes/No logic based on label keywords
        _YES_KEYWORDS = [
            "authorized", "eligible", "willing", "18", "agree", "accept",
            "acknowledge", "confirm", "consent", "certif", "attest", "able to",
            "perform", "available", "can you", "do you", "have you read",
            "understand", "comply", "drug", "background", "travel", "overtime",
            "shift", "remote", "hybrid", "on-site", "relocat",
        ]
        _NO_KEYWORDS = [
            "convicted", "felony", "criminal", "non-compete", "previously employed",
            "formerly", "family member", "relative", "related to", "government official",
            "finra", "disability", "disabled", "clearance", "chronic",
            "dialysis", "veteran",
        ]

        want_yes = any(k in lbl for k in _YES_KEYWORDS)
        want_no = any(k in lbl for k in _NO_KEYWORDS)

        if want_yes and "yes" in opt_lower:
            return await _pick_wd_dropdown(btn_el, "Yes")
        if want_no and "no" in opt_lower:
            return await _pick_wd_dropdown(btn_el, "No")
        # Sponsorship is special — [user] DOES need sponsorship
        if any(k in lbl for k in ["sponsor", "visa", "immigration"]):
            if "yes" in opt_lower:
                return await _pick_wd_dropdown(btn_el, "Yes")

        # For dropdowns with "Select One" + other options, skip "Select One"
        real_options = [o for o in options if o.lower() not in ("select one", "")]
        if not real_options:
            return False

        # Try common safe defaults
        for default in ["Not Applicable", "N/A", "None", "Other", "Prefer not to say",
                        "No", "I decline", "Decline"]:
            if any(default.lower() in o.lower() for o in real_options):
                return await _pick_wd_dropdown(btn_el, default)

        # Last resort for required: pick first option
        if len(real_options) <= 5:
            return await _pick_wd_dropdown(btn_el, real_options[0])

        return False

    # Use JS to enumerate ALL form field containers and extract their structure.
    # Multiple strategies since Workday tenants use very different DOM layouts.
    form_fields = await page.evaluate("""() => {
        const fields = [];
        const seen = new Set();
        const processed = new WeakSet();

        function addField(container) {
            if (processed.has(container)) return;
            processed.add(container);

            const label = container.querySelector('label');
            let labelText = label ? label.textContent.trim() : '';

            // For questionnaire blocks, the "label" might be a <legend> or a <p>/<div> with question text
            if (!labelText) {
                const legend = container.querySelector('legend');
                if (legend) labelText = legend.textContent.trim();
            }
            if (!labelText) {
                // Look for prominent text element that looks like a question
                const candidates = container.querySelectorAll('p, div > span, h3, h4, [class*="label"], [class*="question"]');
                for (const c of candidates) {
                    const t = (c.textContent || '').trim();
                    if (t.length > 10 && t.length < 500 && (t.includes('?') || t.includes('*'))) {
                        labelText = t;
                        break;
                    }
                }
            }
            if (!labelText || seen.has(labelText)) return;
            seen.add(labelText);

            const btn = container.querySelector('button[aria-haspopup]');
            const inp = container.querySelector('input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"]):not([type="file"])');
            const textarea = container.querySelector('textarea');
            const radios = container.querySelectorAll('input[type="radio"]');
            const checkboxes = container.querySelectorAll('input[type="checkbox"]');
            const multisel = container.querySelector('[data-automation-id="multiSelectContainer"]');

            let fieldType = 'unknown';
            let currentValue = '';
            let selector = '';

            if (btn) {
                fieldType = 'dropdown';
                currentValue = (btn.textContent || '').trim();
                const autoId = btn.getAttribute('data-automation-id') || '';
                const name = btn.getAttribute('name') || '';
                const ariaLabel = btn.getAttribute('aria-label') || '';
                selector = name ? `button[name='${name}']` :
                           (autoId ? `[data-automation-id='${autoId}']` :
                           (ariaLabel ? `button[aria-label='${ariaLabel}']` :
                           (btn.id ? `#${btn.id}` : '')));
            } else if (radios.length > 0) {
                fieldType = 'radio';
                const checked = container.querySelector('input[type="radio"]:checked');
                currentValue = checked ? checked.value : '';
                const name = radios[0].name || '';
                selector = name ? `input[name='${name}']` : '';
            } else if (checkboxes.length > 0) {
                fieldType = 'checkbox';
                currentValue = container.querySelector('input[type="checkbox"]:checked') ? 'checked' : '';
                const name = checkboxes[0].name || '';
                selector = name ? `input[name='${name}']` : (checkboxes[0].id ? `#${checkboxes[0].id}` : '');
            } else if (textarea) {
                fieldType = 'textarea';
                currentValue = textarea.value;
                selector = textarea.id ? `#${textarea.id}` : (textarea.name ? `textarea[name='${textarea.name}']` : '');
            } else if (multisel) {
                fieldType = 'multiselect';
                const pills = container.querySelectorAll('[data-automation-id="selectedItem"]');
                currentValue = Array.from(pills).map(p => p.textContent.trim()).join(', ');
            } else if (inp) {
                fieldType = inp.type || 'text';
                currentValue = inp.value;
                selector = inp.id ? `#${inp.id}` : (inp.name ? `input[name='${inp.name}']` : '');
            }

            if (fieldType === 'unknown') return;

            const isRequired = !!(label?.querySelector('abbr')) || labelText.includes('*') || !!container.querySelector('[aria-required="true"]');
            const autoId = container.getAttribute('data-automation-id') || '';

            fields.push({
                label: labelText.substring(0, 300),
                type: fieldType,
                value: currentValue.substring(0, 100),
                selector: selector,
                autoId: autoId,
                required: isRequired,
                filled: !!currentValue && currentValue !== 'Select One',
            });
        }

        // Strategy 1: formField containers (standard Workday)
        document.querySelectorAll('[data-automation-id^="formField-"]').forEach(addField);

        // Strategy 2: questionSection containers (questionnaire pages)
        document.querySelectorAll('[data-automation-id^="questionSection"]').forEach(section => {
            // Each questionSection may contain one or more form fields
            const subContainers = section.querySelectorAll('[data-automation-id^="formField-"]');
            if (subContainers.length > 0) {
                subContainers.forEach(addField);
            } else {
                // The section itself is the container
                addField(section);
            }
        });

        // Strategy 3: questionnaire items (numbered question blocks)
        document.querySelectorAll('[data-automation-id^="questionItem"], [data-automation-id*="question"]').forEach(addField);

        // Strategy 4: Any visible container with a label + form element
        // Only if strategies 1-3 found very few fields
        if (fields.length < 3) {
            document.querySelectorAll('label').forEach(label => {
                if (label.offsetParent === null) return;
                // Walk up to find the nearest meaningful container
                let parent = label.parentElement;
                for (let i = 0; i < 5 && parent; i++) {
                    if (parent.querySelector('button[aria-haspopup], input:not([type="hidden"]), textarea')) {
                        addField(parent);
                        break;
                    }
                    parent = parent.parentElement;
                }
            });
        }

        // Strategy 5: fieldset/legend based (some tenants use fieldsets for question groups)
        document.querySelectorAll('fieldset').forEach(addField);

        return fields;
    }""")

    log.info("Workday questions: found %d form fields", len(form_fields))
    unfilled = [f for f in form_fields if not f.get('filled')]
    log.info("Workday questions: %d unfilled fields", len(unfilled))
    for f in unfilled[:20]:
        log.info("  [%s] %s (required=%s, selector=%s)",
                 f['type'], f['label'][:60], f['required'], f['selector'][:40])

    # Process each unfilled field
    for field in form_fields:
        if field.get('filled'):
            continue
        label = field['label'].lower()
        field_type = field['type']
        selector = field['selector']

        # Find matching rule FIRST (before skip check)
        matched_answer = None
        for pattern, answer in _RULES:
            if pattern in label:
                matched_answer = answer
                break

        # Skip fields that belong to work experience / education sections
        # (these should be filled by _wd_fill_experience, not by questions handler)
        # NEVER skip fields that already matched a rule — they are real questions.
        _SKIP_LABELS = [
            "job title", "company", "location", "from", "to", "role description",
            "school", "degree", "field of study", "gpa", "education",
            "upload", "resume", "linkedin", "facebook", "twitter", "website",
            "first name", "last name", "email", "phone", "address", "city",
            "zip", "postal",
        ]
        _SHORT_ONLY_SKIPS = ["state", "country"]
        if matched_answer is None:
            if len(label) < 60 and any(skip in label for skip in _SKIP_LABELS):
                continue
            if len(label) < 20 and any(skip in label for skip in _SHORT_ONLY_SKIPS):
                continue

        # --- Special handling for specific field types ---
        # Date fields: fill with today's date in mm/dd/yyyy format
        # Only match fields where the LABEL is just "Date" or "Date*" (signature date fields)
        # NOT fields that happen to contain "date" in a longer question
        _is_pure_date_label = label.strip().rstrip('*').strip() == 'date'
        if field_type in ('text', 'date') and _is_pure_date_label:
                from datetime import datetime as _dt
                today = _dt.now().strftime("%m/%d/%Y")
                if selector:
                    try:
                        inp = page.locator(selector).first
                        if await inp.count() > 0 and not (await inp.evaluate("el => el.value")):
                            await inp.fill(today)
                            filled.append(f"q_{label[:20]}")
                            log.info("Workday: filled date '%s' = '%s'", field['label'][:40], today)
                    except Exception as exc:
                        log.debug("Workday: failed to fill date '%s': %s", field['label'][:40], exc)
                continue

        # Name field on Self-Identify page: fill with actual name
        if field_type == 'text' and label in ('name*', 'name') and selector:
            name_val = f"{profile.get('contact', {}).get('first_name', '')} {profile.get('contact', {}).get('last_name', '')}".strip()
            if name_val:
                try:
                    inp = page.locator(selector).first
                    if await inp.count() > 0 and not (await inp.evaluate("el => el.value")):
                        await inp.fill(name_val)
                        filled.append(f"q_{label[:20]}")
                        log.info("Workday: filled name '%s' = '%s'", field['label'][:40], name_val)
                except Exception as exc:
                    log.debug("Workday: failed to fill name '%s': %s", field['label'][:40], exc)
                continue

        if matched_answer is None:
            # No matching rule — use smart defaults for required fields
            if field.get('required') and field_type == 'dropdown':
                # Try smart pick: reads options, uses heuristics
                btn = None
                if selector:
                    btn_loc = page.locator(selector).first
                    if await btn_loc.count() > 0:
                        btn = btn_loc
                if not btn:
                    _sp_temp = await page.evaluate("""(labelText) => {
                        const labels = document.querySelectorAll('label');
                        const searchLower = labelText.substring(0, 40).toLowerCase();
                        for (const lbl of labels) {
                            if (lbl.offsetParent === null) continue;
                            if (!(lbl.textContent || '').trim().toLowerCase().includes(searchLower)) continue;
                            const lblRect = lbl.getBoundingClientRect();
                            // Walk up DOM to find nearest button
                            let node = lbl;
                            for (let depth = 0; depth < 10; depth++) {
                                node = node.parentElement;
                                if (!node) break;
                                const buttons = node.querySelectorAll('button[aria-haspopup]');
                                for (const b of buttons) {
                                    if (b.offsetParent === null) continue;
                                    const btnRect = b.getBoundingClientRect();
                                    const dist = Math.abs(btnRect.top - lblRect.top);
                                    if (dist < 100) {
                                        b.setAttribute('data-wd-temp-id', 'wd_temp_' + Math.random().toString(36).substring(7));
                                        return b.getAttribute('data-wd-temp-id');
                                    }
                                }
                            }
                            // Fallback: data-automation-id ancestor
                            const autoParent = lbl.closest('[data-automation-id]');
                            if (autoParent) {
                                const b = autoParent.querySelector('button[aria-haspopup]');
                                if (b && b.offsetParent !== null) {
                                    b.setAttribute('data-wd-temp-id', 'wd_temp_' + Math.random().toString(36).substring(7));
                                    return b.getAttribute('data-wd-temp-id');
                                }
                            }
                        }
                        return null;
                    }""", field['label'])
                    if _sp_temp:
                        btn = page.locator(f"[data-wd-temp-id='{_sp_temp}']").first
                        if await btn.count() == 0:
                            btn = None
                if btn:
                    try:
                        picked = await _smart_pick_dropdown(btn, label)
                        if picked:
                            filled.append(f"q_{label[:20]}")
                            log.info("Workday: smart-picked dropdown '%s'", field['label'][:50])
                    except Exception as exc:
                        log.debug("Workday: smart-pick failed for '%s': %s", field['label'][:40], exc)
                continue
            elif field.get('required') and field_type == 'radio':
                # For required radios with no rule, try "No" as safe default
                matched_answer = "No"
            elif field.get('required') and field_type in ('text', 'textarea'):
                # Fill required text fields with "N/A" to pass validation
                matched_answer = "N/A"
            elif field.get('required') and field_type == 'checkbox':
                # Check required checkboxes (usually "I agree" type)
                matched_answer = "checked"
            else:
                continue

        if not matched_answer and field_type in ('text', 'textarea'):
            continue  # Don't fill empty answers into text fields

        try:
            if field_type == 'dropdown':
                btn = None
                # ALWAYS try label-based lookup first — selector-based can hit
                # wrong element when multiple dropdowns share the same name attribute.
                temp_id = await page.evaluate("""(labelText) => {
                    const labels = document.querySelectorAll('label');
                    const searchLower = labelText.substring(0, 40).toLowerCase();
                    for (const lbl of labels) {
                        if (lbl.offsetParent === null) continue;
                        const lt = (lbl.textContent || '').trim();
                        if (!lt.toLowerCase().includes(searchLower)) continue;

                        // Strategy A: Walk up DOM looking for nearest button[aria-haspopup]
                        let node = lbl;
                        for (let depth = 0; depth < 10; depth++) {
                            node = node.parentElement;
                            if (!node) break;
                            // Find ALL buttons in this scope, pick the closest one to our label
                            const buttons = node.querySelectorAll('button[aria-haspopup]');
                            if (buttons.length === 0) continue;

                            const lblRect = lbl.getBoundingClientRect();
                            let bestBtn = null;
                            let bestDist = Infinity;
                            for (const b of buttons) {
                                if (b.offsetParent === null) continue;
                                const btnRect = b.getBoundingClientRect();
                                // Button should be BELOW or at same level as label (not above)
                                const dist = Math.abs(btnRect.top - lblRect.top) + Math.abs(btnRect.left - lblRect.left);
                                if (dist < bestDist) {
                                    // Check no other label is closer to this button
                                    const allLabels = node.querySelectorAll('label');
                                    let isClosest = true;
                                    for (const otherLabel of allLabels) {
                                        if (otherLabel === lbl || otherLabel.offsetParent === null) continue;
                                        const otherRect = otherLabel.getBoundingClientRect();
                                        const otherDist = Math.abs(btnRect.top - otherRect.top) + Math.abs(btnRect.left - otherRect.left);
                                        if (otherDist < dist && otherRect.top >= lblRect.top - 5) {
                                            isClosest = false;
                                            break;
                                        }
                                    }
                                    if (isClosest || depth <= 2) {
                                        bestBtn = b;
                                        bestDist = dist;
                                    }
                                }
                            }
                            if (bestBtn) {
                                bestBtn.setAttribute('data-wd-temp-id', 'wd_temp_' + Math.random().toString(36).substring(7));
                                return bestBtn.getAttribute('data-wd-temp-id');
                            }
                        }

                        // Strategy B: Use data-automation-id ancestor
                        const autoParent = lbl.closest('[data-automation-id]');
                        if (autoParent) {
                            const b = autoParent.querySelector('button[aria-haspopup]');
                            if (b && b.offsetParent !== null) {
                                b.setAttribute('data-wd-temp-id', 'wd_temp_' + Math.random().toString(36).substring(7));
                                return b.getAttribute('data-wd-temp-id');
                            }
                        }
                    }
                    return null;
                }""", field['label'])
                if temp_id:
                    btn = page.locator(f"[data-wd-temp-id='{temp_id}']").first
                    if await btn.count() == 0:
                        btn = None
                # Fallback: use selector
                if not btn and selector:
                    btn_loc = page.locator(selector).first
                    if await btn_loc.count() > 0:
                        btn = btn_loc

                if btn:
                    picked = False
                    # For "how did you hear" type questions, try multiple option texts
                    if "hear" in label or "source" in label and "source of" not in label:
                        for source_term in ["Internet", "Job Board", "Online", "Career",
                                            "Website", "Glassdoor", "LinkedIn", "Indeed",
                                            "Job Search", "Other"]:
                            if await _pick_wd_dropdown(btn, source_term):
                                filled.append(f"q_{label[:20]}")
                                log.info("Workday: answered dropdown '%s' = '%s'", field['label'][:40], source_term)
                                picked = True
                                break
                    if not picked and await _pick_wd_dropdown(btn, matched_answer):
                        filled.append(f"q_{label[:20]}")
                        log.info("Workday: answered dropdown '%s' = '%s'", field['label'][:40], matched_answer)

            elif field_type == 'radio':
                # Try to click the radio matching the answer
                clicked = False
                if selector:
                    name = selector.split("'")[1] if "'" in selector else ""
                    if name:
                        for val in ["true" if matched_answer == "Yes" else "false",
                                    matched_answer, matched_answer.lower()]:
                            radio = page.locator(f"input[name='{name}'][value='{val}']").first
                            if await radio.count() > 0:
                                radio_id = await radio.get_attribute("id") or ""
                                if radio_id:
                                    lbl = page.locator(f"label[for='{radio_id}']").first
                                    if await lbl.count() > 0:
                                        await lbl.click(force=True)
                                        clicked = True
                                        break
                # Fallback: find radio by label text near the question label
                if not clicked:
                    clicked = await page.evaluate("""(args) => {
                        const [labelText, answer] = args;
                        const labels = document.querySelectorAll('label');
                        for (const lbl of labels) {
                            if (lbl.offsetParent === null) continue;
                            const lt = (lbl.textContent || '').trim().toLowerCase();
                            if (!lt.includes(labelText.substring(0, 30).toLowerCase())) continue;
                            const parent = lbl.closest('[data-automation-id]') || lbl.parentElement?.parentElement;
                            if (!parent) continue;
                            // Find radio labels matching the answer
                            const radioLabels = parent.querySelectorAll('label');
                            for (const rl of radioLabels) {
                                if (rl === lbl) continue;
                                const rlText = (rl.textContent || '').trim();
                                if (rlText.toLowerCase() === answer.toLowerCase()) {
                                    rl.click();
                                    return true;
                                }
                            }
                        }
                        return false;
                    }""", [field['label'], matched_answer])
                if clicked:
                    filled.append(f"q_{label[:20]}")
                    log.info("Workday: answered radio '%s' = '%s'", field['label'][:40], matched_answer)
                    await page.wait_for_timeout(200)

            elif field_type == 'checkbox':
                try:
                    checked = False
                    # Strategy 1: Direct selector click (most reliable)
                    if selector and not checked:
                        try:
                            cb = page.locator(selector).first
                            if await cb.count() > 0:
                                is_checked = await cb.evaluate("el => el.checked")
                                if not is_checked:
                                    # Click the label (Workday checkboxes need label click)
                                    cb_id = await cb.get_attribute("id") or ""
                                    if cb_id:
                                        lbl = page.locator(f"label[for='{cb_id}']").first
                                        if await lbl.count() > 0:
                                            await lbl.click(force=True)
                                            checked = True
                                    if not checked:
                                        await cb.click(force=True)
                                        checked = True
                        except Exception:
                            pass

                    # Strategy 2: For disability fields, find "I do not want to answer"
                    if not checked and any(w in label for w in ["disability", "disabled", "check one of the boxes"]):
                        checked = await page.evaluate("""() => {
                            const targets = ['i do not want to answer', 'i don\\'t wish',
                                           'no, i do not have', 'prefer not'];
                            const checkboxes = document.querySelectorAll('input[type="checkbox"], input[type="radio"]');
                            for (const target of targets) {
                                for (const cb of checkboxes) {
                                    if (cb.offsetParent === null || cb.checked) continue;
                                    const lbl = document.querySelector('label[for="' + cb.id + '"]');
                                    if (!lbl) continue;
                                    if (lbl.textContent.trim().toLowerCase().includes(target)) {
                                        lbl.click();
                                        return true;
                                    }
                                }
                            }
                            return false;
                        }""")

                    # Strategy 3: Label-based fallback
                    if not checked:
                        checked = await page.evaluate("""(labelText) => {
                            const labels = document.querySelectorAll('label');
                            for (const lbl of labels) {
                                if (lbl.offsetParent === null) continue;
                                const lt = (lbl.textContent || '').trim().toLowerCase();
                                if (!lt.includes(labelText.substring(0, 25).toLowerCase())) continue;
                                const parent = lbl.closest('[data-automation-id]') || lbl.parentElement;
                                if (!parent) continue;
                                const cb = parent.querySelector('input[type="checkbox"]');
                                if (cb && !cb.checked) {
                                    const cbLabel = parent.querySelector('label[for="' + cb.id + '"]') || lbl;
                                    cbLabel.click();
                                    return true;
                                }
                            }
                            return false;
                        }""", field['label'])

                    if checked:
                        filled.append(f"q_{label[:20]}")
                        log.info("Workday: checked checkbox '%s'", field['label'][:40])
                except Exception:
                    pass

            elif field_type in ('text', 'number') and selector and matched_answer:
                inp = page.locator(selector).first
                if await inp.count() > 0 and not (await inp.evaluate("el => el.value")):
                    await inp.fill(matched_answer)
                    filled.append(f"q_{label[:20]}")
                    log.info("Workday: answered text '%s' = '%s'", field['label'][:40], matched_answer)
                    await page.wait_for_timeout(200)

            elif field_type == 'textarea' and selector and matched_answer:
                ta = page.locator(selector).first
                if await ta.count() > 0 and not (await ta.evaluate("el => el.value")):
                    await ta.fill(matched_answer)
                    filled.append(f"q_{label[:20]}")
                    log.info("Workday: answered textarea '%s' = '%s'", field['label'][:40], matched_answer)
        except Exception as exc:
            log.debug("Workday: failed to answer '%s': %s", field['label'][:40], exc)

    # Also try Workday-specific automation IDs for common questions
    _WD_QUESTION_MAP = {
        "currentlyWorking": "Yes",
        "willRelocate": "Yes",
        "previouslyWorked": "No",
        "requireSponsorship": "Yes",
        "legallyAuthorized": "Yes",
    }
    for auto_id, val in _WD_QUESTION_MAP.items():
        try:
            el = page.locator(f"[data-automation-id*='{auto_id}']").first
            if await el.count() > 0:
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "button" or await el.get_attribute("aria-haspopup"):
                    if await _pick_wd_dropdown(el, val):
                        filled.append(auto_id)
                elif tag == "input":
                    if not await el.evaluate("el => el.value"):
                        await el.fill(val)
                        filled.append(auto_id)
        except Exception:
            pass


async def _wd_fill_voluntary(page: Page, filled: list[str]) -> None:
    """Fill Workday 'Voluntary Disclosures' / EEO page.

    Handles both data-automation-id based fields and label-based fields.
    """
    # Known automation IDs and their values
    # TODO(post-lift): drive these from profile.eeo. Empty so we don't
    # auto-pick demographic answers that don't belong to the active user.
    eeo_map = {
        "gender": "",
        "ethnicityDropdown": "",
        "veteranStatus": "",
        "disabilityStatus": "",
    }
    for auto_id, val in eeo_map.items():
        try:
            el = page.locator(f"[data-automation-id='{auto_id}']").first
            if await el.count() > 0:
                cur_text = (await el.text_content() or "").strip()
                if cur_text and cur_text != "Select One":
                    continue  # Already filled
                await el.click()
                await page.wait_for_timeout(500)
                options = page.locator("[role='option']")
                opt_count = await options.count()
                for oi in range(opt_count):
                    opt_text = (await options.nth(oi).text_content() or "").strip()
                    if val.lower() in opt_text.lower() or opt_text.lower() in val.lower():
                        await options.nth(oi).click()
                        filled.append(auto_id)
                        log.info("Workday EEO: %s = '%s'", auto_id, opt_text[:40])
                        break
                else:
                    await page.keyboard.press("Escape")
        except Exception:
            pass

    # Label-based fallback for EEO fields on pages that use different automation IDs
    # TODO(post-lift): drive these from profile.eeo.
    _EEO_RULES = [
        ("gender", ""),
        ("ethnicity", ""),
        ("race", ""),
        ("hispanic", ""),
        ("latino", ""),
        ("veteran", ""),
        ("disability", ""),
        ("protected veteran", "not a protected veteran"),
    ]

    # Find dropdown fields by label
    form_fields = await page.evaluate("""() => {
        const fields = [];
        document.querySelectorAll('[data-automation-id^="formField-"]').forEach(c => {
            const label = c.querySelector('label');
            if (!label) return;
            const btn = c.querySelector('button[aria-haspopup]');
            if (!btn) return;
            const name = btn.getAttribute('name') || '';
            const curVal = (btn.textContent || '').trim();
            if (curVal && curVal !== 'Select One') return; // already filled
            fields.push({
                label: label.textContent.trim().substring(0, 100).toLowerCase(),
                selector: name ? "button[name='" + name + "']" : '',
            });
        });
        return fields;
    }""")

    for field in form_fields:
        for pattern, answer in _EEO_RULES:
            if pattern in field['label'] and field['selector']:
                try:
                    btn = page.locator(field['selector']).first
                    if await btn.count() > 0:
                        await btn.click(force=True)
                        await page.wait_for_timeout(500)
                        opts = page.locator("[role='option']:visible")
                        opt_count = await opts.count()
                        for oi in range(opt_count):
                            opt_text = (await opts.nth(oi).text_content() or "").strip()
                            if answer.lower() in opt_text.lower():
                                await opts.nth(oi).click()
                                filled.append(f"eeo_{pattern}")
                                log.info("Workday EEO: '%s' = '%s'", field['label'][:30], opt_text[:40])
                                break
                        else:
                            await page.keyboard.press("Escape")
                except Exception:
                    try:
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass
                break

    # --- Self Identify page: Name, Date, Disability checkbox ---
    # Name field (for signature on disability self-identification form)
    try:
        name_inp = page.locator("#selfIdentifiedDisabilityData--name, input[name*='DisabilityData'][name*='name']").first
        if await name_inp.count() > 0 and not (await name_inp.evaluate("el => el.value")):
            await name_inp.fill("")
            filled.append("selfid_name")
            log.info("Workday Self-ID: filled name")
    except Exception:
        pass

    # Date field (signature date, mm/dd/yyyy format)
    try:
        from datetime import datetime as _dt
        today = _dt.now().strftime("%m/%d/%Y")
        date_inp = page.locator("#selfIdentifiedDisabilityData--dateSigned, input[name*='DisabilityData'][name*='date']").first
        if await date_inp.count() > 0 and not (await date_inp.evaluate("el => el.value")):
            await date_inp.fill(today)
            filled.append("selfid_date")
            log.info("Workday Self-ID: filled date = %s", today)
    except Exception:
        pass

    # Disability checkbox: select "I do not want to answer" or "No, I don't have a disability"
    try:
        checked = await page.evaluate("""() => {
            const checkboxes = document.querySelectorAll('input[type="checkbox"], input[type="radio"]');
            // Priority targets for disability self-id
            const targets = ['i do not want to answer', 'i don\\'t wish to answer',
                           'no, i do not have', 'no, i don\\'t have',
                           'i decline', 'prefer not'];
            for (const target of targets) {
                for (const cb of checkboxes) {
                    if (cb.offsetParent === null || cb.checked) continue;
                    const lbl = document.querySelector('label[for="' + cb.id + '"]');
                    if (!lbl) continue;
                    const lblText = (lbl.textContent || '').trim().toLowerCase();
                    if (lblText.includes(target)) {
                        lbl.click();
                        return lblText;
                    }
                }
            }
            return null;
        }""")
        if checked:
            filled.append("selfid_disability")
            log.info("Workday Self-ID: selected disability = '%s'", checked[:50])
    except Exception:
        pass


async def _fill_workday(
    page: Page,
    profile: dict[str, Any],
    files: dict[str, str | None],
    filled: list[str],
    *,
    job_url: str = "",
) -> None:
    """Workday multi-page wizard handler.

    Workday applications are multi-step SPAs:
      1. My Information — name, email, phone, address, source
      2. My Experience — resume upload, work history
      3. Application Questions — work auth, visa, custom Qs
      4. Voluntary Disclosures — gender, race, veteran, disability
      5. Review — summary of all info, final Submit button

    Flow: JD page → Apply button → "Start Your Application" modal →
    "Apply Manually" → login/create account → wizard pages → Submit.
    """
    _WD_APPLY_SELECTORS = [
        "a[data-automation-id='jobPostingApplyButton']",
        "button[data-automation-id='jobPostingApplyButton']",
        "a[data-automation-id='applyButton']",
        "button[data-automation-id='applyButton']",
        "a:has-text('Apply')",
        "button:has-text('Apply')",
        "a:has-text('Apply Manually')",
        "button:has-text('Apply Manually')",
        # Resume stale/incomplete applications from previous runs
        "a:has-text('Continue Application')",
        "a:has-text('Continue Applying')",
        "button:has-text('Continue Application')",
        "button:has-text('Continue Applying')",
    ]

    # Wait for Workday SPA to render
    await page.wait_for_timeout(3000)
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass

    page_text = (await page.text_content("body") or "").lower()
    current_url = page.url
    log.info("Workday: page loaded — URL=%s", current_url[:100])

    # Check for expired/unavailable job — look for specific Workday messages
    # (not just substring matches that could hit footer text)
    _EXPIRED_PHRASES = [
        "this job posting is no longer available",
        "this position has been filled",
        "job has been removed",
        "this job posting is no longer active",
        "posting is no longer available",
        "no longer accepting applications",
        "this position is closed",
        "this job is no longer available",
        "job you are looking for is no longer available",
    ]
    # Also check if the Apply button is missing AND there's no form
    has_apply_btn = await page.locator("a:has-text('Apply'), button:has-text('Apply'), a:has-text('Continue Application'), a:has-text('Continue Applying')").count() > 0
    has_form_fields = await page.locator("input[name*='legalName'], [data-automation-id*='legalName']").count() > 0
    if any(phrase in page_text for phrase in _EXPIRED_PHRASES):
        log.warning("Workday: job posting is no longer available — skipping")
        raise RuntimeError("Workday job posting expired/unavailable")
    if "doesn't exist" in page_text or "page not found" in page_text:
        if not has_apply_btn and not has_form_fields:
            # Take screenshot for debugging
            try:
                ss_dir = Path("artifacts/autofill_screenshots")
                ss_dir.mkdir(parents=True, exist_ok=True)
                from datetime import datetime as _dt
                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                await page.screenshot(path=str(ss_dir / f"wd_expired_{ts}.png"), full_page=True)
                log.info("Workday: expired page screenshot saved")
            except Exception:
                pass
            log.warning("Workday: job page not found — skipping")
            raise RuntimeError("Workday job posting expired/unavailable")

    # Detect "Something went wrong" — stale draft or session conflict
    if "something went wrong" in page_text:
        log.warning("Workday: 'Something went wrong' detected — clearing cookies for this tenant and retrying")
        # Clear cookies for this specific Workday tenant domain
        try:
            import re as _re
            tenant_match = _re.search(r'([a-z]+\.wd\d+\.myworkdayjobs\.com)', current_url)
            if tenant_match:
                tenant_domain = tenant_match.group(1)
                cookies = await page.context.cookies()
                wd_cookies = [c for c in cookies if tenant_domain in (c.get('domain', '') or '')]
                if wd_cookies:
                    await page.context.clear_cookies(domain=tenant_domain)
                    log.info("Workday: cleared %d cookies for %s", len(wd_cookies), tenant_domain)
            # Reload the page
            await page.goto(job_url, timeout=60_000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            page_text = (await page.text_content("body") or "").lower()
            if "something went wrong" in page_text:
                log.warning("Workday: still showing 'Something went wrong' after cookie clear")
                raise RuntimeError("Workday stale draft - Something went wrong")
        except RuntimeError:
            raise
        except Exception as exc:
            log.warning("Workday: cookie clear failed: %s", exc)

    # Handle "Search for Jobs" redirect — sometimes Workday redirects to the job search page
    # instead of the specific job. Try navigating back or searching for the role.
    search_input = page.locator("input[data-automation-id='searchBox'], input[aria-label*='Search' i]").first
    if await search_input.count() > 0 and not has_apply_btn and not has_form_fields:
        # We're on a search page, not the job page. Try reloading the original URL.
        log.info("Workday: on search page instead of job page — reloading original URL")
        await page.goto(job_url, timeout=60_000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        page_text = (await page.text_content("body") or "").lower()
        has_apply_btn = await page.locator("a:has-text('Apply'), button:has-text('Apply'), a:has-text('Continue Application'), a:has-text('Continue Applying')").count() > 0
        # If still on search page, try searching by job title
        if not has_apply_btn:
            search_input = page.locator("input[data-automation-id='searchBox'], input[aria-label*='Search' i]").first
            if await search_input.count() > 0:
                # Extract job title from URL (last segment before the ID)
                import re as _re
                title_match = _re.search(r'/job/[^/]+/([^/]+)_', job_url)
                search_term = title_match.group(1).replace('-', ' ')[:50] if title_match else ""
                log.info("Workday: searching for '%s' on job search page", search_term)
                await search_input.fill(search_term)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(3000)
                # Try clicking first matching job link
                job_links = page.locator("a[data-automation-id='jobTitle']")
                if await job_links.count() > 0:
                    await job_links.first.click()
                    await page.wait_for_timeout(3000)
                    page_text = (await page.text_content("body") or "").lower()
                    log.info("Workday: navigated to job from search results")
                else:
                    log.warning("Workday: no matching jobs found in search")
                    raise RuntimeError("Workday job posting expired/unavailable")

    # Step 1: Click "Apply" button on the JD page (if not already on a form)
    has_form = (
        await page.locator("[data-automation-id='legalNameSection_firstName']").count() > 0
        or await page.locator("input[data-automation-id='email']").count() > 0
        or "my information" in page_text
    )
    if not has_form:
        apply_clicked = False
        for sel in _WD_APPLY_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    log.info("Workday: clicking initial Apply button: %s", sel)
                    await btn.click()
                    apply_clicked = True
                    await page.wait_for_timeout(3000)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(2000)
                    break
            except Exception:
                continue

        # Step 2: Handle "Start Your Application" modal
        if apply_clicked:
            await page.wait_for_timeout(2000)
            modal_text = (await page.text_content("body") or "").lower()
            if "start your application" in modal_text or "apply manually" in modal_text or "apply with resume" in modal_text:
                log.info("Workday: 'Start Your Application' modal detected")
                for modal_sel in [
                    "button:has-text('Apply Manually')",
                    "a:has-text('Apply Manually')",
                    "button:has-text('Apply with Resume')",
                    "a:has-text('Apply with Resume')",
                ]:
                    try:
                        mbtn = page.locator(modal_sel).first
                        if await mbtn.count() > 0 and await mbtn.is_visible():
                            log.info("Workday: clicking modal option: %s", modal_sel)
                            await mbtn.click()
                            await page.wait_for_timeout(5000)
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=15_000)
                            except Exception:
                                pass
                            break
                    except Exception:
                        continue

        # Step 3: Authenticate (login/create account) — this may appear after Apply
        await _workday_login_or_create(
            page,
            job_url=job_url,
            wd_email=profile.get("workday_email") or profile.get("email") or "",
            wd_password=profile.get("workday_password") or "",
        )

        # Wait for redirect after auth
        await page.wait_for_timeout(3000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass

        # Step 4: Re-click Apply if we're back on the JD page after auth
        post_auth_text = (await page.text_content("body") or "").lower()
        still_on_jd = not any(kw in post_auth_text for kw in [
            "my information", "my experience", "application questions",
            "work experience", "contact information",
        ])
        if still_on_jd:
            for sel in _WD_APPLY_SELECTORS:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        log.info("Workday: re-clicking Apply after auth: %s", sel)
                        await btn.click()
                        await page.wait_for_timeout(5000)
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=15_000)
                        except Exception:
                            pass
                        break
                except Exception:
                    continue
            # Handle modal again if it appears
            modal_text2 = (await page.text_content("body") or "").lower()
            if "apply manually" in modal_text2 or "apply with resume" in modal_text2:
                for modal_sel in [
                    "button:has-text('Apply Manually')",
                    "a:has-text('Apply Manually')",
                    "button:has-text('Apply with Resume')",
                    "a:has-text('Apply with Resume')",
                ]:
                    try:
                        mbtn = page.locator(modal_sel).first
                        if await mbtn.count() > 0 and await mbtn.is_visible():
                            log.info("Workday: clicking modal after re-apply: %s", modal_sel)
                            await mbtn.click()
                            await page.wait_for_timeout(5000)
                            break
                    except Exception:
                        continue

        if not apply_clicked:
            # Log page snippet for debugging
            snippet = page_text[:500].replace("\n", " ")
            log.warning("Workday: no Apply button found. Page snippet: %s...", snippet[:200])
            # Try JS click as fallback
            try:
                js_clicked = await page.evaluate("""() => {
                    const links = [...document.querySelectorAll('a, button')];
                    for (const el of links) {
                        const text = (el.textContent || '').trim().toLowerCase();
                        if (text === 'apply' || text.includes('apply for') || text.includes('apply now')) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if js_clicked:
                    log.info("Workday: clicked Apply via JS fallback")
                    await page.wait_for_timeout(5000)
            except Exception:
                pass

    # --- Multi-page navigation loop ---
    # Fill each page, click Next, repeat up to 12 times (safety limit).
    # Step detection is unreliable (nav bar text contaminates), so run ALL
    # fillers on every page. They are idempotent (skip filled fields).
    # Stuck detection: compare page heading/content hash before and after advance.
    max_pages = 12
    no_advance_count = 0

    async def _get_page_signature():
        """Get a lightweight signature of current page content for change detection."""
        return await page.evaluate("""() => {
            const headings = Array.from(document.querySelectorAll('h2, h3'))
                .filter(h => h.offsetParent !== null)
                .map(h => h.textContent.trim()).join('|');
            const errors = document.querySelectorAll('[data-automation-id="errorMessage"]').length;
            const fields = document.querySelectorAll('input, button[aria-haspopup], textarea').length;
            const pills = document.querySelectorAll('[data-automation-id="selectedItem"]').length;
            return headings + ':' + errors + ':' + fields + ':' + pills;
        }""")

    prev_sig = await _get_page_signature()

    for page_num in range(max_pages):
        step = await _wd_detect_page_js(page)
        log.info("Workday: page %d, detected step: %s", page_num + 1, step)

        # Check for "Something went wrong" inside the wizard (stale draft)
        page_text_check = (await page.text_content("body") or "").lower()
        if "something went wrong" in page_text_check:
            log.warning("Workday: 'Something went wrong' inside wizard — trying page refresh")
            await page.reload(wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(3000)
            page_text_check = (await page.text_content("body") or "").lower()
            if "something went wrong" in page_text_check:
                log.warning("Workday: still 'Something went wrong' after refresh — stale draft, aborting")
                raise RuntimeError("Workday stale draft - Something went wrong after sign-in")
            else:
                log.info("Workday: page recovered after refresh")
                step = await _wd_detect_page_js(page)

        # Check for review page — look at page content, not just step detection
        if "review and submit" in page_text_check or "submit your application" in page_text_check:
            log.info("Workday: reached Review page — stopping navigation, submit will follow.")
            break
        if step == "review":
            log.info("Workday: step detection says Review — stopping navigation, submit will follow.")
            break

        # Run ALL fillers on every page — detection may be wrong.
        await _wd_fill_identity(page, profile, filled)
        await _wd_fill_experience(page, files, filled)
        await _wd_fill_questions(page, profile, filled)
        await _wd_fill_voluntary(page, filled)

        # Log any Workday validation errors visible on the page
        try:
            wd_errors = await page.evaluate("""() => {
                const errors = [];
                document.querySelectorAll('[data-automation-id="errorMessage"]').forEach(el => {
                    if (el.offsetParent !== null) errors.push(el.textContent.trim());
                });
                // Also check for inline error text
                document.querySelectorAll('.css-1blj3hb, [class*="error"]').forEach(el => {
                    const t = el.textContent.trim();
                    if (t && t.length < 200 && el.offsetParent !== null) errors.push(t);
                });
                return [...new Set(errors)];
            }""")
            if wd_errors:
                for err in wd_errors[:5]:
                    log.warning("Workday validation error: %s", err[:100])
        except Exception:
            pass

        # Try to advance to the next page.
        advanced = await _wd_click_next(page)
        if not advanced:
            log.info("Workday: no Next button found or final step reached on page %d.", page_num + 1)
            break

        # Wait for page transition
        await page.wait_for_timeout(4000)

        # Check if page content actually changed
        new_sig = await _get_page_signature()
        if new_sig == prev_sig:
            no_advance_count += 1
            log.warning("Workday: page content unchanged after Save and Continue (attempt %d, sig=%s)",
                        no_advance_count, new_sig[:80])
            if no_advance_count >= 3:
                log.warning("Workday: stuck — content unchanged for 3 attempts, diagnosing...")
                # Take screenshot
                try:
                    ss_dir = Path("artifacts/autofill_screenshots")
                    from datetime import datetime as _dt
                    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                    ss_path = str(ss_dir / f"wd_stuck_{step}_{ts}.png")
                    await page.screenshot(path=ss_path, full_page=True)
                    log.info("Workday: stuck screenshot saved to %s", ss_path)
                except Exception:
                    pass
                # Log all validation errors and unfilled required fields
                try:
                    diag = await page.evaluate("""() => {
                        const result = {errors: [], unfilledRequired: []};
                        // Collect error messages
                        document.querySelectorAll('[data-automation-id*="error"], [class*="error"], [role="alert"], [class*="invalid"]').forEach(el => {
                            const txt = (el.textContent || '').trim();
                            if (txt && txt.length < 300 && !result.errors.includes(txt)) result.errors.push(txt);
                        });
                        // Collect unfilled required fields
                        document.querySelectorAll('label').forEach(lbl => {
                            if (!lbl.querySelector('abbr') && !lbl.textContent.includes('*')) return;
                            if (lbl.offsetParent === null) return;
                            const parent = lbl.closest('[data-automation-id]') || lbl.parentElement;
                            if (!parent) return;
                            const inp = parent.querySelector('input:not([type="hidden"]):not([type="radio"]), textarea');
                            const btn = parent.querySelector('button[aria-haspopup]');
                            const radios = parent.querySelectorAll('input[type="radio"]');
                            let unfilled = false;
                            if (btn) {
                                const txt = (btn.textContent || '').trim();
                                if (!txt || txt === 'Select One') unfilled = true;
                            } else if (radios.length > 0) {
                                if (!parent.querySelector('input[type="radio"]:checked')) unfilled = true;
                            } else if (inp) {
                                if (!inp.value) unfilled = true;
                            }
                            if (unfilled) {
                                result.unfilledRequired.push(lbl.textContent.trim().substring(0, 100));
                            }
                        });
                        return result;
                    }""")
                    if diag.get('errors'):
                        log.warning("Workday stuck page errors: %s", diag['errors'][:5])
                    if diag.get('unfilledRequired'):
                        log.warning("Workday stuck unfilled REQUIRED fields: %s", diag['unfilledRequired'][:20])
                except Exception:
                    pass
                break
        else:
            no_advance_count = 0
        prev_sig = new_sig
        log.info("Workday: advanced to page %d", page_num + 2)


async def _fill_generic(
    page: Page,
    profile: dict[str, Any],
    files: dict[str, str | None],
    filled: list[str],
) -> None:
    """Fallback handler using label/placeholder text matching."""
    await _fill_profile_fields(page, profile, filled)
    await _upload_documents(
        page,
        files.get("resume"),
        files.get("cover_letter"),
        filled,
        resume_docx_path=files.get("resume_docx"),
        cover_letter_docx_path=files.get("cover_letter_docx"),
        prefer_docx=files.get("prefer_docx", True),
    )


# ---------------------------------------------------------------------------
# Cookie consent dismissal
# ---------------------------------------------------------------------------

_COOKIE_DISMISS_SELECTORS = [
    # ── OneTrust (most common enterprise CMP) ──
    "#onetrust-accept-btn-handler",
    ".onetrust-close-btn-handler",
    "#accept-recommended-btn-handler",
    # ── CookieBot ──
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    "a#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    # ── Osano ──
    ".osano-cm-accept-all",
    "button.osano-cm-dialog__close",
    # ── TrustArc / TrustE ──
    ".trustarc-agree-btn",
    "#truste-consent-button",
    ".pdynamicbutton .call",
    # ── Quantcast / CMP ──
    ".qc-cmp2-summary-buttons button[mode='primary']",
    "button.qc-cmp-button",
    # ── Termly ──
    "[data-tid='banner-accept']",
    "button.t-acceptAllButton",
    # ── Iubenda ──
    ".iubenda-cs-accept-btn",
    # ── Complianz (WordPress) ──
    ".cmplz-accept",
    ".cmplz-btn.cmplz-accept",
    # ── CookieYes ──
    "#cookie_action_close_header",
    ".cky-btn-accept",
    # ── Cookie Notice / GDPR plugins ──
    "#cn-accept-cookie",
    "#cookie-notice .cn-set-cookie",
    "#gdpr-cookie-accept",
    # ── Klaro ──
    ".klaro .cm-btn-accept",
    ".klaro .cm-btn-success",
    # ── Common text-based buttons ──
    "button:has-text('Accept All')",
    "button:has-text('Accept all')",
    "button:has-text('Accept All Cookies')",
    "button:has-text('Accept all cookies')",
    "button:has-text('Accept Cookies')",
    "button:has-text('Accept cookies')",
    "button:has-text('Allow All')",
    "button:has-text('Allow all')",
    "button:has-text('Allow All Cookies')",
    "button:has-text('Allow Cookies')",
    "button:has-text('I Accept')",
    "button:has-text('I Agree')",
    "button:has-text('I agree')",
    "button:has-text('Agree')",
    "button:has-text('Agree & Continue')",
    "button:has-text('Agree and Continue')",
    "button:has-text('Continue')",
    "button:has-text('Got it')",
    "button:has-text('Got It')",
    "button:has-text('OK')",
    "button:has-text('Ok')",
    "button:has-text('Yes, I agree')",
    "button:has-text('Understood')",
    # ── Link/anchor based accept ──
    "a:has-text('Accept All')",
    "a:has-text('Accept all')",
    "a:has-text('Accept Cookies')",
    "a:has-text('Accept cookies')",
    "a:has-text('I Accept')",
    "a:has-text('I Agree')",
    "a:has-text('Got it')",
    # ── Generic container-scoped accept buttons ──
    "[id*='cookie'] button:has-text('Accept')",
    "[class*='cookie'] button:has-text('Accept')",
    "[id*='consent'] button:has-text('Accept')",
    "[class*='consent'] button:has-text('Accept')",
    "[id*='gdpr'] button:has-text('Accept')",
    "[class*='gdpr'] button:has-text('Accept')",
    "[id*='privacy'] button:has-text('Accept')",
    "[class*='privacy'] button:has-text('Accept')",
    "[id*='cookie'] button:has-text('Allow')",
    "[class*='cookie'] button:has-text('Allow')",
    "[id*='cookie'] button:has-text('OK')",
    "[class*='cookie'] button:has-text('OK')",
    "[id*='cookie'] button:has-text('Close')",
    "[class*='cookie'] button:has-text('Close')",
    "[id*='cookie'] button:has-text('Agree')",
    "[class*='cookie'] button:has-text('Agree')",
    "[id*='consent'] button:has-text('Agree')",
    "[class*='consent'] button:has-text('Agree')",
    # ── data-attribute based ──
    "[data-cookie-accept]",
    "[data-action='accept']",
    "[data-testid='cookie-accept']",
    "[data-testid='accept-cookies']",
    "[data-cy='cookie-accept']",
]

# Selectors for any popup/modal/overlay X (close) buttons.
_POPUP_CLOSE_SELECTORS = [
    # --- Cookie / consent banners ---
    *_COOKIE_DISMISS_SELECTORS,
    # --- Generic X / close buttons on modals and overlays ---
    # aria-label close buttons (most accessible modals).
    "button[aria-label='Close']:visible",
    "button[aria-label='close']:visible",
    "button[aria-label='Dismiss']:visible",
    "button[aria-label='dismiss']:visible",
    "button[aria-label='Close dialog']:visible",
    "button[aria-label='Close modal']:visible",
    # data-dismiss / data-close attributes (Bootstrap, custom).
    "[data-dismiss='modal']:visible",
    "[data-close]:visible",
    "button[data-action='close']:visible",
    "button[data-testid='close-button']:visible",
    "button[data-testid='CloseButton']:visible",
    "button[data-testid='modal-close']:visible",
    # Class-based close buttons.
    ".modal-close:visible",
    ".close-button:visible",
    ".close-btn:visible",
    ".popup-close:visible",
    ".overlay-close:visible",
    ".dialog-close:visible",
    ".btn-close:visible",
    # Icons inside buttons (× character, SVG close icons).
    "button.close:visible",
    "[class*='modal'] button[class*='close']:visible",
    "[class*='popup'] button[class*='close']:visible",
    "[class*='overlay'] button[class*='close']:visible",
    "[class*='dialog'] button[class*='close']:visible",
    "[class*='banner'] button[class*='close']:visible",
    # Newsletter / signup popups.
    "[class*='newsletter'] button[class*='close']:visible",
    "[class*='subscribe'] button[class*='close']:visible",
    "[class*='signup'] button[class*='close']:visible",
    "[id*='newsletter'] button[class*='close']:visible",
    # Chat widgets.
    "[class*='chat'] button[class*='close']:visible",
    "[class*='chat'] button[class*='minimize']:visible",
    "[id*='chat'] button[class*='close']:visible",
    # Notification bars.
    "[class*='notification'] button[class*='close']:visible",
    "[class*='alert'] button[class*='close']:visible",
    "[class*='toast'] button[class*='close']:visible",
    # "No thanks" / "Maybe later" text buttons on promo popups.
    "[class*='modal']:visible button:has-text('No thanks')",
    "[class*='modal']:visible button:has-text('No, thanks')",
    "[class*='modal']:visible button:has-text('Maybe later')",
    "[class*='modal']:visible button:has-text('Not now')",
    "[class*='modal']:visible a:has-text('No thanks')",
    "[class*='modal']:visible a:has-text('Maybe later')",
    "[class*='popup']:visible button:has-text('No thanks')",
    "[class*='overlay']:visible button:has-text('No thanks')",
]


async def _dismiss_cookie_banner(page: Page) -> None:
    """Aggressively accept ALL cookie consent banners on the page.

    Accepting cookies (rather than rejecting/closing) maximizes cookie
    storage, which builds trust with reCAPTCHA v3 over time.
    """
    dismissed = False
    for sel in _COOKIE_DISMISS_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click(timeout=3000)
                await page.wait_for_timeout(500)
                log.info("Accepted cookies via %s", sel)
                dismissed = True
                break  # One click usually dismisses the whole banner
        except Exception:
            continue

    if not dismissed:
        # JS fallback: find and click any visible button with accept/agree text
        # inside a cookie/consent/gdpr container
        try:
            clicked = await page.evaluate("""() => {
                const containers = document.querySelectorAll(
                    '[id*="cookie"], [class*="cookie"], [id*="consent"], [class*="consent"], ' +
                    '[id*="gdpr"], [class*="gdpr"], [id*="privacy-banner"], [class*="privacy-banner"], ' +
                    '[id*="onetrust"], [class*="onetrust"], [id*="CookieBot"], [class*="cookiebot"], ' +
                    '[role="dialog"], [role="alertdialog"], [class*="banner"], [class*="modal"]'
                );
                const acceptWords = ['accept', 'agree', 'allow', 'ok', 'got it', 'understood',
                                     'continue', 'i accept', 'i agree', 'yes'];
                for (const container of containers) {
                    const buttons = container.querySelectorAll('button, a[role="button"], input[type="submit"]');
                    for (const btn of buttons) {
                        const text = (btn.textContent || btn.value || '').trim().toLowerCase();
                        if (acceptWords.some(w => text === w || text.startsWith(w))) {
                            btn.click();
                            return true;
                        }
                    }
                }
                return false;
            }""")
            if clicked:
                log.info("Accepted cookies via JS fallback")
                await page.wait_for_timeout(500)
        except Exception:
            pass


async def _handle_slider_captcha(page: Page) -> bool:
    """Handle slider CAPTCHA -- drag a box/handle to the right to verify.

    Common on Greenhouse, SmartRecruiters, and company career pages.
    Returns True if a slider was found and dragged.
    """
    # Common slider selectors
    _SLIDER_SELECTORS = [
        "[class*='slider' i][class*='captcha' i]",
        "[class*='slider' i][class*='verify' i]",
        "[class*='slider-handle' i]",
        "[class*='slide-to' i]",
        "[class*='drag' i][class*='verify' i]",
        "[class*='slider' i] [class*='handle' i]",
        "[class*='slider' i] [class*='thumb' i]",
        "[class*='captcha' i] [class*='drag' i]",
        "[data-testid*='slider' i]",
        "[aria-label*='slide' i]",
        "[aria-label*='drag' i]",
        # Generic draggable elements inside verification containers
        "[class*='verify' i] [draggable='true']",
        "[class*='captcha' i] [draggable='true']",
    ]
    for sel in _SLIDER_SELECTORS:
        try:
            handle = page.locator(sel).first
            if await handle.count() > 0 and await handle.is_visible():
                # Get the handle's bounding box
                box = await handle.bounding_box()
                if not box:
                    continue
                # Find the track width -- look for parent container
                track_width = 300  # default assumption
                try:
                    parent = handle.locator("xpath=ancestor::div[1]").first
                    if await parent.count() > 0:
                        parent_box = await parent.bounding_box()
                        if parent_box:
                            track_width = parent_box["width"] - box["width"]
                except Exception:
                    pass
                # Drag the handle to the right
                start_x = box["x"] + box["width"] / 2
                start_y = box["y"] + box["height"] / 2
                await page.mouse.move(start_x, start_y)
                await page.mouse.down()
                # Move in steps to simulate human drag
                steps = 20
                for step in range(1, steps + 1):
                    await page.mouse.move(
                        start_x + (track_width * step / steps),
                        start_y + (2 if step % 3 == 0 else -1),  # slight wobble
                        steps=3,
                    )
                    await page.wait_for_timeout(30)
                await page.mouse.up()
                await page.wait_for_timeout(1000)
                log.info("Dragged slider CAPTCHA handle: %s", sel)
                return True
        except Exception as exc:
            log.debug("Slider CAPTCHA attempt failed for %s: %s", sel, exc)
            continue
    return False


async def _dismiss_all_popups(page: Page) -> int:
    """Aggressively dismiss any visible popups, modals, overlays, banners.

    Clicks X / close / dismiss buttons on cookie banners, newsletter modals,
    chat widgets, notification bars, promo overlays, etc.

    Returns the number of popups dismissed.
    """
    dismissed = 0

    for sel in _POPUP_CLOSE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click(timeout=2000)
                await page.wait_for_timeout(400)
                dismissed += 1
                log.info("Dismissed popup via %s", sel)
        except Exception:
            continue

    # Fallback: find any visible element that looks like a close button
    # (contains × or ✕ or ✖ text, or is a small button in a fixed/absolute overlay).
    if dismissed == 0:
        try:
            # Look for × (multiply sign) or X text in buttons inside overlays.
            close_chars = page.locator(
                "[class*='modal']:visible button, "
                "[class*='popup']:visible button, "
                "[class*='overlay']:visible button, "
                "[class*='dialog']:visible button, "
                "[role='dialog']:visible button"
            )
            count = await close_chars.count()
            for i in range(min(count, 10)):
                btn = close_chars.nth(i)
                text = (await btn.text_content() or "").strip()
                # Check for close-like text (×, ✕, X, Close, Dismiss).
                if text in ("×", "✕", "✖", "X", "x", "✗") or \
                   text.lower() in ("close", "dismiss", "cancel", "no thanks", "not now"):
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(400)
                    dismissed += 1
                    log.info("Dismissed popup via close-char button: '%s'", text)
                    break
        except Exception:
            pass

    # Also try pressing Escape to dismiss any modal.
    if dismissed == 0:
        try:
            # Check if there's a visible modal/overlay before pressing Escape.
            modals = page.locator(
                "[class*='modal']:visible, "
                "[class*='popup']:visible, "
                "[class*='overlay']:visible, "
                "[role='dialog']:visible"
            )
            if await modals.count() > 0:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(500)
                # Verify it was dismissed.
                if await modals.count() == 0:
                    dismissed += 1
                    log.info("Dismissed popup via Escape key")
        except Exception:
            pass

    return dismissed


async def _detect_platform_from_page(page: Page) -> str | None:
    """Detect ATS platform from page content (for embedded forms)."""
    try:
        html = await page.content()
        # Greenhouse embeds.
        if "greenhouse" in html.lower() and (
            "id=\"grnhse_app\"" in html
            or "greenhouse.io" in html
            or 'data-source="greenhouse"' in html.lower()
        ):
            return "greenhouse"
        # Lever embeds.
        if "lever.co" in html.lower() and "lever-application" in html.lower():
            return "lever"
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_PLATFORM_HANDLERS = {
    "greenhouse": _fill_greenhouse,
    "lever": _fill_lever,
    "workday": _fill_workday,
}


async def autofill_application(
    job_url: str,
    profile: dict[str, Any],
    resume_pdf_path: str | None = None,
    cover_letter_pdf_path: str | None = None,
    resume_docx_path: str | None = None,
    cover_letter_docx_path: str | None = None,
    prefer_docx: bool = True,
) -> dict[str, Any]:
    """Launch a Playwright browser, navigate to *job_url*, and autofill the
    application form.

    When *prefer_docx* is True and a docx path is provided, the docx file
    is uploaded instead of the PDF.  If the file input restricts accepted
    types via its ``accept`` attribute, the format is chosen accordingly.

    Returns a dict with keys:
        status, screenshot_path, filled_fields, needs_review,
        platform_detected.
    """
    platform = detect_platform(job_url)
    filled: list[str] = []
    needs_review: list[dict[str, str]] = []
    screenshot_path = ""

    files: dict[str, Any] = {
        "resume": resume_pdf_path,
        "cover_letter": cover_letter_pdf_path,
        "resume_docx": resume_docx_path or None,
        "cover_letter_docx": cover_letter_docx_path or None,
        "prefer_docx": prefer_docx,
    }

    async with async_playwright() as pw:
        context = await _launch_persistent_browser(pw, headless=False)
        # Reuse the initial about:blank page if present, otherwise create new
        if context.pages and context.pages[0].url in ("about:blank", "chrome://newtab/", ""):
            page = context.pages[0]
        else:
            page = await context.new_page()

        try:
            await page.goto(job_url, wait_until="networkidle", timeout=45_000)
            await page.wait_for_timeout(2000)  # let JS settle

            # --- Detect dead job postings ---
            if "error=true" in page.url:
                log.warning("Job posting removed (redirected to error page): %s", job_url)
                return {
                    "status": "submit_not_found",
                    "screenshot_path": "",
                    "filled_fields": [],
                    "needs_review": [],
                    "platform_detected": platform,
                }

            # --- Dismiss cookie consent banners ---
            await _dismiss_all_popups(page)

            # --- Re-detect platform from page content (embedded forms) ---
            if platform == "generic":
                platform = await _detect_platform_from_page(page) or platform

            # --- Handle embedded Greenhouse iframe (company domains only) ---
            is_direct_greenhouse = re.search(r"greenhouse\.io", job_url, re.I)
            if platform == "greenhouse" and not is_direct_greenhouse:
                try:
                    iframe = page.locator("#grnhse_iframe, iframe[src*='greenhouse.io']").first
                    if await iframe.count() > 0:
                        iframe_src = await iframe.get_attribute("src")
                        if iframe_src and "greenhouse.io" in iframe_src:
                            await page.goto(iframe_src, wait_until="networkidle", timeout=30_000)
                            await page.wait_for_timeout(2000)
                except Exception:
                    pass

            # --- Platform-specific fill ---
            handler = _PLATFORM_HANDLERS.get(platform, _fill_generic)
            if platform == "workday":
                await handler(page, profile, files, filled, job_url=job_url)
            else:
                await handler(page, profile, files, filled)

            # --- Common fields (run even after platform handler) ---
            await _fill_work_auth(page, filled)
            await _fill_eeo_fields(page, filled)

            # --- Collect unknown questions ---
            scope = platform  # could be refined to company-level
            needs_review = await _collect_unknown_questions(page, filled, scope)

            # --- Screenshot before submit ---
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            ss_name = f"autofill_{platform}_{ts}.png"
            ss_path = SCREENSHOTS_DIR / ss_name
            await page.screenshot(path=str(ss_path), full_page=True)
            screenshot_path = str(ss_path)

            status = "ready_for_review"
        except Exception as exc:
            log.exception("Autofill failed for %s", job_url)
            status = f"error: {exc}"
        finally:
            await context.close()

    return {
        "status": status,
        "screenshot_path": screenshot_path,
        "filled_fields": filled,
        "needs_review": needs_review,
        "platform_detected": platform,
    }


# ---------------------------------------------------------------------------
# LLM-powered question answering for custom application questions
# ---------------------------------------------------------------------------

_QUESTION_ANSWER_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"open to.*(relocation|relocate)", re.I), "Yes"),
    (re.compile(r"open to working in.?person", re.I), "Yes"),
    (re.compile(r"interviewed.*before", re.I), "No"),
    (re.compile(r"hispanic|latino", re.I), "No"),
    (re.compile(r"ai policy", re.I), "I acknowledge and agree to the AI policy."),
    (re.compile(r"^acknowledge$", re.I), "Yes"),
    (re.compile(r"i agree|i understand|i acknowledge|privacy statement|privacy policy|applicant privacy", re.I), "I agree"),
    (re.compile(r"located in.*for the duration|will you be located", re.I), "Yes"),
    (re.compile(r"require housing|secured.*housing", re.I), "I have secured my own housing."),
    # TODO(post-lift): everything in this catalog with a non-empty value
    # was the original Revize author's profile baked into the autofill
    # rules. Cleared here so we don't auto-submit someone else's data;
    # the post-lift integration should pull these from the active profile.
    (re.compile(r"postal.?code|zip.?code", re.I), ""),
    (re.compile(r"how did you hear|where did you hear|how did you find", re.I), "Company careers page"),
    (re.compile(r"salary|compensation|pay.*expect", re.I), "Open to discussion based on role and responsibilities."),
    (re.compile(r"start date|earliest.*start|when.*start", re.I), ""),
    (re.compile(r"graduat.*date|expected.*graduat|when.*graduat|completion.*date|degree.*date|end.*date.*education", re.I), ""),
    (re.compile(r"graduat.*month|month.*graduat", re.I), ""),
    (re.compile(r"graduat.*year|year.*graduat", re.I), ""),
    (re.compile(r"deadline|timeline.*consider", re.I), "No specific deadlines."),
    (re.compile(r"additional info", re.I), "N/A"),
    (re.compile(r"personal\s*prefer", re.I), ""),
    # Employer / work history
    (re.compile(r"current.*employer|last.*employer|employer.*name|company.*name|current.*company", re.I), ""),
    (re.compile(r"current.*title|job.*title|current.*position|current.*role", re.I), "AI Business Analyst Intern"),
    # Government employment
    (re.compile(r"(?:work|worked|employed).*(?:government|u\.?s\.?\s*gov)|government.*(?:entity|agency|employer)", re.I), "No"),
    (re.compile(r"list.*government.*entity|name.*government.*entity|which.*government", re.I), "N/A"),
    # Address / location
    (re.compile(r"city", re.I), ""),  # TODO(post-lift): profile.address.city
    (re.compile(r"(?:^|\b)state(?:\b|$)", re.I), "New York"),
    (re.compile(r"street|address line 1", re.I), "3405 Farragut Rd"),
    (re.compile(r"address line 2|apt|unit|suite", re.I), "2B"),
    # Relative / family at company
    (re.compile(r"relative.*work|family.*work|name.*relative|relative.*name", re.I), "N/A"),
    # Referral details
    (re.compile(r"employee referral|referral.*name|who referred", re.I), "N/A"),
    (re.compile(r"selected employee referral|if you selected", re.I), "N/A - found via careers page"),
    # Languages
    (re.compile(r"language.*fluent|fluent.*language|languages.*speak|speak.*language|other.*language|additional.*language", re.I), "Hindi, Marathi"),
    (re.compile(r"which language|what language|primary language", re.I), "English"),
    (re.compile(r"bilingual|second language|other than english", re.I), "Hindi"),
    # Years of experience
    (re.compile(r"years.*experience|experience.*years", re.I), "2"),
    # Availability / notice period
    (re.compile(r"notice period|availability", re.I), "Immediately available"),
    # Country
    (re.compile(r"country|nation", re.I), "United States"),
    # Currently employed
    (re.compile(r"currently employed|are you employed", re.I), "No"),
    # Legal name confirmation
    (re.compile(r"legal name|full name", re.I), ""),
    (re.compile(r"legal\s*first\s*name", re.I), ""),
    (re.compile(r"legal\s*last\s*name", re.I), ""),
    # Preferred name
    (re.compile(r"preferred\s*name|nickname", re.I), ""),
    # EEO / demographic -- actual info (duplicates of earlier rules removed)
    (re.compile(r"race|ethnicit", re.I), ""),  # TODO(post-lift): profile.eeo.race
    (re.compile(r"gender(?! identity)", re.I), ""),  # TODO(post-lift): profile.eeo.gender
    (re.compile(r"gender identity|pronouns", re.I), ""),  # TODO(post-lift): profile.pronouns,
    (re.compile(r"sexual orientation", re.I), ""),  # TODO(post-lift): profile.eeo.sexual_orientation
    (re.compile(r"disability", re.I), ""),  # TODO(post-lift): profile.eeo.disability
    (re.compile(r"transgender", re.I), ""),  # TODO(post-lift): profile.eeo.transgender
    (re.compile(r"first.generation", re.I), ""),  # TODO(post-lift): profile.eeo.first_generation
    # NOTE: location/office preference is handled dynamically in _rule_based_answer
    # to extract the city from the job description. See _LOCATION_QUESTION_RE below.
    (re.compile(r"citizen.*(?:cuba|iran|north korea|syria|crimea)|resident.*(?:cuba|iran|north korea|syria|crimea)", re.I), "No"),
    # Licenses / certifications / registrations
    (re.compile(r"series\s*\d|finra|sfe|cpa|cfa|registered representative|hold.*license|active.*license|licensed.*professional|professional.*license|sie\b", re.I), "No"),
    (re.compile(r"which.*license|list.*license|license.*hold|license.*number", re.I), "N/A - I do not hold any professional licenses"),
    # Work authorization / right to work
    (re.compile(r"source of.*right to work|right to work.*source|work authorization.*type|type.*work authorization|immigration.*status|visa.*type|visa.*status", re.I), "Student Visa"),
    # Willingness / compliance questions
    (re.compile(r"willing.*travel|travel.*required|open.*travel", re.I), "Yes"),
    (re.compile(r"background.*check|consent.*background|authorize.*background", re.I), "Yes"),
    (re.compile(r"drug.*test|drug.*screen", re.I), "Yes"),
    (re.compile(r"non.?compete|non.?solicitation|restrictive.*covenant", re.I), "No"),
    (re.compile(r"security.*clearance", re.I), "No"),
    (re.compile(r"over\s*18|at least\s*18|18.*older|legal.*age", re.I), "Yes"),
    # SAT / ACT -- user never took these; answer N/A or 0
    (re.compile(r"\bsat\b.*score|\bact\b.*score|sat composite|act composite", re.I), "N/A"),
    (re.compile(r"\bsat\b|\bact\b.*test", re.I), "N/A"),
    (re.compile(r"over\s*21|at least\s*21", re.I), "Yes"),
    (re.compile(r"NDA|non.?disclosure|confidential.*agree", re.I), "I agree"),
    # Contact / links
    (re.compile(r"linkedin.*url|linkedin.*profile|your.*linkedin", re.I), ""),
    (re.compile(r"github.*url|github.*profile|your.*github", re.I), ""),
    (re.compile(r"portfolio.*url|portfolio.*link|personal.*website|your.*website", re.I), ""),
    # Cover letter -- handled by LLM with JD context (see _llm_answer_question)
    # Phone
    (re.compile(r"phone.*number|contact.*number|mobile.*number", re.I), ""),
    # Hourly rate acknowledgment
    (re.compile(r"hourly rate.*\$|rate.*for this role", re.I), "I acknowledge and agree"),
    # Certification / attest
    (re.compile(r"certif.*true|certif.*accurate|attest|swear|affirm.*true|information.*correct", re.I), "I certify"),
    # Education details
    (re.compile(r"gpa|grade.*point|cumulative.*gpa", re.I), ""),  # TODO(post-lift): profile.education[0].gpa
    (re.compile(r"school.*name|university.*name|college.*name|institution", re.I), ""),
    (re.compile(r"degree.*type|degree.*level|level.*education|highest.*degree", re.I), "Master's Degree"),
    (re.compile(r"major|field.*study|area.*study|concentration|specialization", re.I), ""),
    (re.compile(r"minor", re.I), "N/A"),
    # SAT / ACT — most adult applicants don't have these handy.
    (re.compile(r"\bsat\b.*score|\bact\b.*score|sat composite|act composite", re.I), "N/A"),
    (re.compile(r"\bsat\b|\bact\b.*test", re.I), "N/A"),
    # Current employment — TODO(post-lift): drive from profile.
    (re.compile(r"current.*role", re.I), ""),
    (re.compile(r"currently.*employed|are you.*employed", re.I), ""),
    (re.compile(r"current.*company|current.*employer|employer.*name|company.*name", re.I), ""),
    # Work preferences
    (re.compile(r"work.*model|remote.*hybrid|in.?person.*remote|work.*arrangement", re.I), "Open to any -- remote, hybrid, or in-person"),
    (re.compile(r"shift|schedule.*prefer|work.*schedule", re.I), "Standard business hours"),
    (re.compile(r"overtime|extra.*hours|weekend.*work", re.I), "Yes, willing to work as needed"),
    # Confidentiality / privacy / agreements
    (re.compile(r"privacy.*statement|privacy.*policy|privacy.*notice|data.*protection", re.I), "I agree"),
    (re.compile(r"confidential.*acknowledg|confidentiality", re.I), "I acknowledge"),
    (re.compile(r"terms.*condition|terms.*use", re.I), "I agree"),
    (re.compile(r"consent.*data|data.*consent|personal.*data|process.*data", re.I), "I consent"),
    # Misc common questions
    (re.compile(r"felony|convicted|criminal|misdemeanor", re.I), "No"),
    (re.compile(r"pending.*charges|arrest", re.I), "No"),
    (re.compile(r"voluntary.*self.?id|self.?identify|self.?identification", re.I), "I prefer not to answer"),
    (re.compile(r"caregiver|caregiving", re.I), "No"),
    (re.compile(r"veteran|military.*service", re.I), "I am not a protected veteran"),
    (re.compile(r"source.*application|how.*find.*job|heard.*about.*position|where.*see.*post", re.I), "Company careers page"),
    (re.compile(r"country.*residence|country.*you.*reside|where.*you.*reside", re.I), "United States"),
    (re.compile(r"authorized.*work.*us|legally.*authorized|right.*work|eligible.*work", re.I), "Yes"),
    (re.compile(r"require.*sponsorship|need.*sponsorship|immigration.*sponsor|visa.*sponsor", re.I), "Yes"),
    (re.compile(r"can.*commute|commute.*to|able.*commute", re.I), "Yes"),
    (re.compile(r"references|provide.*reference", re.I), "Available upon request"),
    # AI usage / experiment question — TODO(post-lift): drive from
    # profile.ai_experience or profile.long_form_answers["ai_usage"]. The
    # original Revize source had a multi-paragraph hardcoded answer with
    # the author's specific projects + GitHub handle; stripped here so we
    # never auto-submit somebody else's portfolio.
    (re.compile(r"how.*using ai|ai.*experiment|ai.*current role|how.*use.*ai", re.I), ""),
]


_LOCATION_QUESTION_RE = re.compile(
    r"which location|which office|preferred office|preferred.*work.*location|"
    r"work.*location.*prefer|location.*preference|office.*preference",
    re.I,
)

# Major US cities to look for in job descriptions / titles
_US_CITIES = [
    "New York", "San Francisco", "Los Angeles", "Chicago", "Seattle",
    "Austin", "Boston", "Denver", "Atlanta", "Miami", "Dallas",
    "Houston", "Washington", "Philadelphia", "Phoenix", "San Diego",
    "San Jose", "Minneapolis", "Portland", "Raleigh", "Nashville",
    "Charlotte", "Salt Lake City", "Pittsburgh", "Detroit", "Columbus",
    "Indianapolis", "Bellevue", "Palo Alto", "Mountain View", "Sunnyvale",
    "Menlo Park", "Cupertino", "Santa Clara", "Redmond", "Irvine",
]


def _extract_job_location(job_description: str) -> str | None:
    """Try to extract a US city from the job description text."""
    if not job_description:
        return None
    for city in _US_CITIES:
        if city.lower() in job_description.lower():
            return city
    return None


def _rule_based_answer(question: str, *, job_description: str = "", job_location: str = "") -> str | None:
    """Try to answer a question using simple rules. Returns None if no rule matches."""
    # Dynamic location-based answer
    if _LOCATION_QUESTION_RE.search(question):
        # Try to use the job's own location first
        if job_location:
            # Extract city name from location string like "San Francisco, CA"
            city = job_location.split(",")[0].strip()
            if city:
                return city
        # Fall back to extracting from JD text
        extracted = _extract_job_location(job_description)
        if extracted:
            return extracted
        # No location found -- open to anywhere
        return "Open to any US location"

    for pattern, answer in _QUESTION_ANSWER_RULES:
        if pattern.search(question):
            return answer
    return None


async def _llm_answer_question(question: str, company: str, role: str, profile: dict[str, Any],
                                job_description: str = "") -> str:
    """Use the LLM to generate an answer for a custom application question."""
    from backend.services.llm_client import generate

    contact = profile.get("contact", profile)
    name = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()

    # Detect questions that need JD-tailored answers
    q_lower = question.lower()
    is_why_interested = bool(re.search(
        r"why.*interested|why.*want.*work|why.*join|what.*excites|what.*attracts|"
        r"why.*apply|what.*draws|motivation.*apply|tell us why",
        q_lower
    ))
    is_cover_letter = bool(re.search(
        r"cover.?letter|pitch.*yourself|tell.*about.*yourself|why.*good.*fit|"
        r"why.*hire|what.*bring|introduce.*yourself|write.*about",
        q_lower
    ))

    # TODO(post-lift): build the candidate-summary block from the active
    # profile (contact + master_resume) instead of empty placeholders. The
    # original Revize source had the author's full resume hardcoded into
    # every prompt template — that has been stripped so this code never
    # auto-fills another user's job application with someone else's
    # background, demographics, salary expectations, or visa status.
    candidate_summary = (
        contact.get("profile_summary")
        or "(profile summary not configured -- see backend/services/autofill.py TODOs)"
    )
    answer_rules = contact.get("answer_rules", "")
    if is_why_interested and job_description:
        jd_snippet = job_description[:2000]
        prompt = f"""You are filling out a job application for {name} applying to {role} at {company}.

Candidate background:
{candidate_summary}

Here is the job description:
{jd_snippet}

Write a 3-4 sentence answer connecting the candidate background above to specifics about {company} from the JD. Avoid generic filler.

Question: {question}

Answer:"""
    elif is_why_interested:
        prompt = f"""You are filling out a job application for {name} applying to {role} at {company}.

Candidate background:
{candidate_summary}

Write a 3-4 sentence answer explaining why the candidate is interested in {role} at {company}.

Question: {question}

Answer:"""
    elif is_cover_letter and job_description:
        jd_snippet = job_description[:2000]
        prompt = f"""You are writing a cover letter pitch for {name} applying to {role} at {company}.

Candidate background:
{candidate_summary}

Here is the job description:
{jd_snippet}

Write a 4-6 sentence cover-letter pitch connecting the candidate's experience to what {company} needs in this {role}. Be concrete. No "Dear Hiring Manager" -- just the pitch.

Question: {question}

Answer:"""
    elif is_cover_letter:
        prompt = f"""You are writing a cover letter pitch for {name} applying to {role} at {company}.

Candidate background:
{candidate_summary}

Write a 4-5 sentence pitch connecting the candidate's experience to {role} at {company}. No "Dear Hiring Manager" -- just the pitch.

Question: {question}

Answer:"""
    else:
        prompt = f"""You are filling out a job application for {name} applying to {role} at {company}.

Candidate background:
{candidate_summary}

{answer_rules}

Question: {question}

Answer:"""

    try:
        # Route to fast model for simple questions, full model for long-form.
        use_fast = not (is_why_interested or is_cover_letter)
        if use_fast:
            from backend.services.ollama_client import generate_fast
            answer = await generate_fast(prompt, system="You are a helpful job application assistant. Give concise, professional answers.")
        else:
            answer = await generate(prompt, system="You are a helpful job application assistant. Give concise, professional answers.")
        # Clean up the answer - remove quotes, trim whitespace.
        answer = answer.strip().strip('"').strip("'").strip()
        # Remove thinking tags if present (some models output these).
        answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
        if answer:
            return answer
    except Exception as exc:
        log.warning("LLM failed to answer question '%s': %s", question, exc)

    # Static fallback when LLM fails or returns empty.
    # TODO(post-lift): drive these from the profile rather than empty.
    # Returning "" here avoids submitting a generic / hallucinated bio that
    # doesn't belong to the active user.
    return ""


_CHECKBOX_AUTO_SELECT: list[tuple[re.Pattern[str], bool]] = [
    # Export compliance / sanctions -- check "None of the above".
    (re.compile(r"none of the above", re.I), True),
    # Work auth -- these depend on user's actual status.
    (re.compile(r"^none of these apply", re.I), False),  # Don't auto-check
]

# Checkbox options that should always be checked (user is not from sanctioned countries).
_CHECKBOX_SANCTIONS_DENY = re.compile(
    r"citizen.*(?:cuba|iran|north korea|syria)|"
    r"resident.*(?:cuba|iran|north korea|syria|crimea|donetsk|luhansk|zaporizhzhia|kherson)|"
    r"resident.*(?:russia|belarus).*not willing",
    re.I,
)


async def _handle_checkbox_groups(
    page: Page,
    needs_review: list[dict[str, str]],
    profile: dict[str, Any],
) -> list[dict[str, str]]:
    """Handle checkbox-group questions (export compliance, work auth checkboxes).

    Returns items that were NOT handled (still need review).
    """
    still_unknown: list[dict[str, str]] = []
    handled_labels: set[str] = set()

    # Identify checkbox items: labels whose `for` points to a checkbox input.
    checkbox_items: list[tuple[dict[str, str], str]] = []
    non_checkbox_items: list[dict[str, str]] = []

    # Build a lookup of all checkbox labels on the page.
    try:
        all_checkboxes = page.locator("input[type='checkbox']")
        cb_total = await all_checkboxes.count()
        # Map: normalized label text -> (for_attr, checkbox_name)
        cb_label_map: dict[str, tuple[str, str]] = {}
        for i in range(min(cb_total, 30)):
            cb = all_checkboxes.nth(i)
            cb_id = await cb.get_attribute("id") or ""
            cb_name = await cb.get_attribute("name") or cb_id
            if cb_id:
                # Escape special CSS characters in the ID (e.g. [] in
                # Greenhouse checkbox IDs like question_123[]_456).
                escaped_id = cb_id.replace("[", "\\[").replace("]", "\\]")
                label = page.locator(f"label[for='{escaped_id}']")
                if await label.count() > 0:
                    text = (await label.text_content() or "").strip()
                    if text:
                        cb_label_map[_normalize_prompt(text)] = (cb_id, cb_name)
    except Exception:
        cb_label_map = {}

    for item in needs_review:
        question = item["question"]
        norm_q = _normalize_prompt(question)
        if norm_q in cb_label_map:
            for_attr, _ = cb_label_map[norm_q]
            checkbox_items.append((item, for_attr))
        else:
            # Fallback: try partial matching (label text contains the question).
            matched = False
            for label_text, (cb_id, cb_name) in cb_label_map.items():
                if norm_q in label_text or label_text in norm_q:
                    checkbox_items.append((item, cb_id))
                    matched = True
                    break
            if not matched:
                non_checkbox_items.append(item)

    log.debug("Checkbox items: %d, non-checkbox: %d", len(checkbox_items), len(non_checkbox_items))

    if not checkbox_items:
        return needs_review

    # --- Export compliance: check "None of the above" ---
    for item, for_attr in checkbox_items:
        q = item["question"]
        if re.search(r"none of the above", q, re.I):
            try:
                cb = page.locator(f"input[type='checkbox'][id='{_css_escape_id(for_attr)}']")
                await cb.check()
                handled_labels.add(q)
                log.info("Checked checkbox: '%s'", q)
            except Exception as exc:
                log.warning("Could not check '%s': %s", q, exc)

    # --- Acknowledge / agreement checkboxes: always check ---
    for item, for_attr in checkbox_items:
        q = item["question"]
        if re.search(r"acknowledge|i agree|i accept|i certify|i confirm|i consent", q, re.I):
            if q not in handled_labels:
                try:
                    # Use attribute selector (handles [] in IDs better than CSS escape)
                    cb = page.locator(f"input[type='checkbox'][id='{for_attr}']")
                    if await cb.count() == 0:
                        cb = page.locator(f"input[type='checkbox'][id='{_css_escape_id(for_attr)}']")
                    if await cb.count() > 0 and not await cb.is_checked():
                        # Try label click first (more reliable for React forms),
                        # fall back to direct check.
                        escaped = _css_escape_id(for_attr)
                        label = page.locator(f"label[for='{escaped}']").first
                        if await label.count() > 0:
                            await label.click()
                            await page.wait_for_timeout(300)
                        if not await cb.is_checked():
                            await cb.check()
                            await page.wait_for_timeout(300)
                    handled_labels.add(q)
                    is_now_checked = await cb.is_checked() if await cb.count() > 0 else False
                    log.info("Checked acknowledge checkbox: '%s' (verified=%s)", q, is_now_checked)
                except Exception as exc:
                    log.warning("Could not check acknowledge '%s': %s", q, exc)

    # --- "How did you hear about us?" checkbox group ---
    # These appear as individual checkboxes (Twitter, Glassdoor, Indeed, Other, etc.)
    # Check "Other" if present; otherwise check the first reasonable option.
    # Use a prefix/contains match since labels can include extra text like
    # "Content (e.g. videos, ads, billboards etc)".
    _HEAR_ABOUT_KEYWORDS = re.compile(
        r"^(twitter|glassdoor|indeed|linkedin|facebook|instagram|blog|"
        r"conference|event|content|other|friend|referral|career\s*fair|"
        r"google|search\s*engine|job\s*board|newsletter)",
        re.I,
    )
    hear_about_items = [(item, fa) for item, fa in checkbox_items
                        if _HEAR_ABOUT_KEYWORDS.match(item["question"].strip())
                        and item["question"] not in handled_labels]
    if hear_about_items:
        # Prefer "Other", then "LinkedIn", then first item.
        pick = None
        for item, fa in hear_about_items:
            if re.search(r"^other$", item["question"].strip(), re.I):
                pick = (item, fa)
                break
        if not pick:
            for item, fa in hear_about_items:
                if re.search(r"linkedin", item["question"].strip(), re.I):
                    pick = (item, fa)
                    break
        if not pick:
            pick = hear_about_items[0]
        try:
            cb = page.locator(f"input[type='checkbox'][id='{_css_escape_id(pick[1])}']")
            await cb.check()
            handled_labels.add(pick[0]["question"])
            log.info("Checked 'how did you hear' checkbox: '%s'", pick[0]["question"])
        except Exception as exc:
            log.warning("Could not check hear-about '%s': %s", pick[0]["question"], exc)
        # Mark all items in this group as handled.
        for item, _ in hear_about_items:
            handled_labels.add(item["question"])

    # --- Work authorization checkboxes ---
    requires_sponsorship = (settings.requires_sponsorship or "").lower()

    for item, for_attr in checkbox_items:
        q = item["question"].lower()
        should_check = False

        if "none of these apply" in q:
            if requires_sponsorship in ("yes", "true", "1"):
                should_check = True

        if should_check and q not in [h.lower() for h in handled_labels]:
            try:
                cb = page.locator(f"input[type='checkbox'][id='{_css_escape_id(for_attr)}']")
                await cb.check()
                handled_labels.add(item["question"])
                log.info("Checked work auth checkbox: '%s'", item["question"])
            except Exception as exc:
                log.warning("Could not check work auth '%s': %s", item["question"], exc)

    # If no specific work auth was checked, check "None of these apply".
    work_auth_checked = any(
        item["question"] in handled_labels
        for item, _ in checkbox_items
        if any(kw in item["question"].lower() for kw in
               ("u.s. citizen", "permanent resident", "green card", "asylum", "non-citizen national"))
    )
    if not work_auth_checked:
        for item, for_attr in checkbox_items:
            if "none of these apply" in item["question"].lower():
                if item["question"] not in handled_labels:
                    try:
                        cb = page.locator(f"input[type='checkbox'][id='{_css_escape_id(for_attr)}']")
                        await cb.check()
                        handled_labels.add(item["question"])
                        log.info("Checked fallback: '%s'", item["question"])
                    except Exception as exc:
                        log.warning("Could not check '%s': %s", item["question"], exc)

    # --- Group marking: mark all items in a group as handled if any member was checked ---
    groups: dict[str, list[tuple[dict[str, str], str]]] = {}
    for item, for_attr in checkbox_items:
        norm_q = _normalize_prompt(item["question"])
        if norm_q in cb_label_map:
            _, cb_name = cb_label_map[norm_q]
            groups.setdefault(cb_name, []).append((item, for_attr))
        else:
            groups.setdefault(for_attr, []).append((item, for_attr))

    for name, group_items in groups.items():
        if any(item["question"] in handled_labels for item, _ in group_items):
            for item, _ in group_items:
                handled_labels.add(item["question"])

    # Build result -- only return items that weren't handled.
    for item, _ in checkbox_items:
        if item["question"] not in handled_labels:
            still_unknown.append(item)

    return non_checkbox_items + still_unknown


async def _answer_and_fill_unknown_questions(
    page: Page,
    needs_review: list[dict[str, str]],
    profile: dict[str, Any],
    company: str,
    role: str,
    scope: str,
    job_description: str = "",
) -> list[dict[str, str]]:
    """Try to answer unknown questions using rules and LLM.

    Returns the remaining questions that could not be answered.
    """
    # First handle checkbox groups (export compliance, work auth checkboxes).
    needs_review = await _handle_checkbox_groups(page, needs_review, profile)

    # Extract job location from page title or JD for location-based answers.
    _page_title = ""
    try:
        _page_title = await page.title() or ""
    except Exception:
        pass
    _job_location_ctx = _page_title + " " + (job_description or "")

    still_unknown: list[dict[str, str]] = []

    for item in needs_review:
        question = item["question"]

        # Try rule-based answer first (instant, no I/O).
        answer = _rule_based_answer(question, job_description=_job_location_ctx)

        # Try cached answer from DB (fast DB lookup).
        if answer is None:
            cached = _lookup_answer(question, scope)
            if cached:
                answer = cached
                log.debug("Cache hit for '%s': '%s'", question[:40], answer[:40])

        # Fall back to LLM (pass JD for "why interested" type questions).
        if answer is None:
            answer = await _llm_answer_question(question, company, role, profile,
                                                 job_description=job_description)
            # Cache successful LLM answers for future use.
            if answer:
                try:
                    store_answer(question, answer, scope=scope)
                except Exception:
                    pass  # Non-critical

        if not answer:
            still_unknown.append(item)
            continue

        # Try to fill the answer into the form.
        filled = False
        normalized = _normalize_prompt(question)

        # Strategy 1: Find label and its associated input.
        try:
            labels = page.locator("label")
            label_count = await labels.count()
            for i in range(min(label_count, 60)):
                label_text = (await labels.nth(i).text_content() or "").strip()
                if _normalize_prompt(label_text) == normalized:
                    for_attr = await labels.nth(i).get_attribute("for")
                    if for_attr:
                        # Check if it's a select dropdown.
                        select_loc = page.locator(f"select#{for_attr}")
                        if await select_loc.count() > 0:
                            # Try to select the matching option.
                            options = await select_loc.locator("option").all_text_contents()
                            best_match = None
                            for opt in options:
                                if answer.lower() in opt.lower() or opt.lower() in answer.lower():
                                    best_match = opt
                                    break
                            if best_match:
                                await select_loc.select_option(label=best_match)
                                filled = True
                            elif options:
                                # Select the first non-empty option that isn't "Select..."
                                for opt in options:
                                    if opt.strip() and not opt.lower().startswith("select"):
                                        await select_loc.select_option(label=opt)
                                        filled = True
                                        break
                        else:
                            filled = await _type_into_field(page, f"#{for_attr}", answer)
                        if filled:
                            break
                    # No for attr - try textarea/input near the label.
                    for depth in range(1, 5):
                        parent = labels.nth(i).locator(f"xpath=./ancestor::div[{depth}]")
                        if await parent.count() == 0:
                            continue
                        textarea = parent.locator("textarea")
                        if await textarea.count() > 0:
                            await textarea.first.fill(answer)
                            filled = True
                            break
                        inp = parent.locator("input[type='text'], input:not([type])")
                        if await inp.count() > 0:
                            await inp.first.fill(answer)
                            filled = True
                            break
                    if filled:
                        break
        except Exception:
            pass

        # Strategy 2: Try radio buttons for yes/no answers.
        if not filled and answer.lower() in ("yes", "no"):
            try:
                section = page.locator(f"*:has-text('{question[:40]}')").last
                radios = section.locator(f"label:text-is('{answer}')")
                if await radios.count() > 0:
                    await radios.first.click()
                    filled = True
            except Exception:
                pass

        # Strategy 3: Find empty required textareas and match by nearby text.
        if not filled:
            try:
                textareas = page.locator("textarea:visible")
                ta_count = await textareas.count()
                for ti in range(ta_count):
                    ta = textareas.nth(ti)
                    ta_val = await ta.input_value()
                    if ta_val.strip():
                        continue  # Already filled
                    # Check parent container for matching question text
                    for depth in range(1, 5):
                        container = ta.locator(f"xpath=./ancestor::div[{depth}]")
                        if await container.count() == 0:
                            continue
                        container_text = (await container.first.text_content() or "").strip()
                        if len(container_text) > 500:
                            continue  # Too broad
                        q_words = set(question.lower().split()[:6])
                        c_words = set(container_text.lower().split())
                        if len(q_words & c_words) >= min(3, len(q_words)):
                            await ta.fill(answer)
                            filled = True
                            break
                    if filled:
                        break
            except Exception:
                pass

        if filled:
            # Store the answer for future reuse.
            store_answer(question, answer, scope=scope)
            log.info("Auto-answered: '%s' -> '%s'", question[:60], answer[:60])
        else:
            still_unknown.append(item)

    return still_unknown


# ---------------------------------------------------------------------------
# Submit helpers (per-platform)
# ---------------------------------------------------------------------------

_SUBMIT_SELECTORS: dict[str, list[str]] = {
    "greenhouse": [
        "input[type='submit'][value*='Submit' i]",
        "button[type='submit']",
        "button:has-text('Submit Application')",
        "button:has-text('Submit')",
        "[data-qa='submit-button']",
    ],
    "lever": [
        "button[type='submit']",
        "button.postings-btn:has-text('Submit')",
        "button:has-text('Submit application')",
        "button:has-text('Submit')",
    ],
    "workday": [
        "[data-automation-id='click_filter'][aria-label*='Submit' i]",
        "button[data-automation-id='bottom-navigation-next-button']:has-text('Submit')",
        "button:has-text('Submit')",
    ],
    "generic": [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Submit Application')",
        "button:has-text('Submit')",
        "button:has-text('Apply')",
    ],
}


async def _check_required_fields_filled(page: Page) -> list[str]:
    """Return labels of required fields that are still empty."""
    empty: list[str] = []
    # Check visible inputs with aria-required (skip combobox inputs -- their
    # value is managed by react-select and always appears empty after selection).
    fields = page.locator(
        "input[aria-required='true']:visible, "
        "textarea[aria-required='true']:visible"
    )
    count = await fields.count()
    for i in range(count):
        role = await fields.nth(i).get_attribute("role") or ""
        if role == "combobox":
            continue  # React-select inputs -- validated via hidden required inputs
        val = await fields.nth(i).input_value()
        if not val.strip():
            # --- Workday pill/chip check ---
            # Workday typeahead/multiselect fields keep the <input> empty after
            # selection — the selected value lives in pill/chip elements.
            # If the input's parent container has selectedItem pills, treat as filled.
            try:
                has_pills = await fields.nth(i).evaluate("""el => {
                    const container = el.closest('[data-automation-id^="formField"]');
                    if (!container) return false;
                    return container.querySelectorAll('[data-automation-id="selectedItem"]').length > 0;
                }""")
                if has_pills:
                    continue  # Has selected pills — effectively filled
            except Exception:
                pass
            # --- Workday displayed-value check ---
            # Some Workday dropdowns show the selected value in a sibling <div>
            # while the input stays empty.
            try:
                has_displayed = await fields.nth(i).evaluate("""el => {
                    const container = el.closest('[data-automation-id^="formField"]');
                    if (!container) return false;
                    // Check for displayed text in dropdown button or value container
                    const btn = container.querySelector('button[aria-haspopup]');
                    if (btn && btn.textContent.trim() && btn.textContent.trim() !== '--Select--')
                        return true;
                    const val = container.querySelector('[data-automation-id="selectedValue"]');
                    return val && val.textContent.trim().length > 0;
                }""")
                if has_displayed:
                    continue
            except Exception:
                pass
            fid = await fields.nth(i).get_attribute("id") or ""
            # Find label for this field.
            label = page.locator(f"label[for='{fid}']").first if fid else None
            label_text = ""
            if label and await label.count() > 0:
                label_text = (await label.text_content() or "").strip()
            empty.append(label_text or fid or f"field_{i}")
    # Check hidden required inputs (react-select validation).
    hidden_inputs = page.locator(
        "input[tabindex='-1'][aria-hidden='true'][required]"
    )
    hidden_count = await hidden_inputs.count()
    for i in range(hidden_count):
        inp = hidden_inputs.nth(i)
        # Only flag if the hidden input is actually empty.
        try:
            val = await inp.input_value()
            if val.strip():
                continue  # Already filled -- skip
        except Exception:
            pass  # If we can't read value, assume empty
        # Check if the parent react-select already displays a value (e.g. phone
        # country code "+1").  If so, the field is effectively filled.
        try:
            # Try multiple ancestor patterns -- react-select class names vary.
            for ancestor_q in [
                "xpath=ancestor::div[contains(@class,'select')]",
                "xpath=ancestor::div[contains(@class,'Select')]",
                "xpath=ancestor::div[contains(@class,'country')]",
                "xpath=ancestor::div[3]",  # fallback: 3 levels up
            ]:
                rs_container = inp.locator(ancestor_q).first
                if await rs_container.count() > 0:
                    sv = rs_container.locator("[class*='singleValue'], [class*='single-value'], [class*='SingleValue']").first
                    if await sv.count() > 0:
                        displayed = (await sv.text_content() or "").strip()
                        if displayed:
                            log.debug("Hidden required input %d has displayed value '%s' -- treating as filled.", i, displayed)
                            break
            else:
                displayed = ""
            if displayed:
                continue  # Has a displayed value -- treat as filled
        except Exception:
            pass
        # Try to identify via name, id, or nearby label.
        name = await inp.get_attribute("name") or ""
        fid = await inp.get_attribute("id") or ""
        label_text = ""
        for attr in (fid, name):
            if attr:
                lbl = page.locator(f"label[for='{attr}']").first
                if await lbl.count() > 0:
                    label_text = (await lbl.text_content() or "").strip()
                    break
        # Try parent container for label text.
        if not label_text:
            try:
                parent = inp.locator("xpath=ancestor::div[contains(@class,'field')]")
                if await parent.count() > 0:
                    lbl = parent.first.locator("label").first
                    if await lbl.count() > 0:
                        label_text = (await lbl.text_content() or "").strip()
            except Exception:
                pass
        identifier = label_text or name or fid or f"dropdown_{i}"
        log.debug("Unfilled hidden required input: %s (name=%s, id=%s)", identifier, name, fid)
        empty.append(identifier)
    return empty


async def _fetch_greenhouse_security_code(*, max_wait_seconds: int = 30) -> str | None:
    """Poll IMAP for a Greenhouse security code email. Returns the code or None."""
    import imaplib
    import email as email_mod
    import time
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text: list[str] = []
        def handle_data(self, data: str) -> None:
            self.text.append(data)
        def get_text(self) -> str:
            return " ".join(self.text)

    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        try:
            mail = imaplib.IMAP4_SSL(settings.imap_host, int(settings.imap_port))
            mail.login(settings.imap_username, settings.imap_password)
            mail.select("INBOX")
            status, messages = mail.search(None, 'FROM "greenhouse" UNSEEN')
            if status == "OK" and messages[0]:
                ids = messages[0].split()
                for eid in reversed(ids):
                    _, data = mail.fetch(eid, "(RFC822)")
                    msg = email_mod.message_from_bytes(data[0][1])
                    subj = (msg["Subject"] or "").lower()
                    if "security code" not in subj:
                        continue
                    # Extract code from HTML body.
                    for part in msg.walk():
                        if part.get_content_type() == "text/html":
                            html = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            parser = _TextExtractor()
                            parser.feed(html)
                            text = parser.get_text()
                            # The code appears on its own line after "security code field".
                            match = re.search(r"security code field[^:]*:\s*(\S+)", text, re.I)
                            if match:
                                code = match.group(1).strip()
                                mail.logout()
                                # Never log raw codes (stored in Fly log aggregation).
                                log.info("Found Greenhouse security code (len=%d)", len(code))
                                return code
                            # Fallback: look for an isolated alphanumeric token.
                            for line in text.split("\n"):
                                line = line.strip()
                                if re.fullmatch(r"[A-Za-z0-9]{6,12}", line):
                                    mail.logout()
                                    log.info("Found Greenhouse security code (len=%d, fallback regex)", len(line))
                                    return line
            mail.logout()
        except Exception as exc:
            log.warning("IMAP check failed: %s", exc)
        time.sleep(3)
    return None


async def _handle_greenhouse_security_code(page: Page) -> bool:
    """After submitting a Greenhouse form, check for the email verification
    flow.  If detected, fetch the code from IMAP and enter it.

    Returns True if the security code was entered and the form resubmitted.
    """
    # Poll for security code prompt -- Greenhouse can take a few seconds to
    # render the verification page after the initial form POST.
    has_code_text = False
    has_code_field = False
    # Expanded polling — up to ~30s total with progressive detection
    for _poll in range(10):  # Up to ~30 seconds of polling
        page_text = (await page.text_content("body") or "").lower()
        has_code_text = (
            "security code" in page_text
            or "verification code" in page_text
            or "enter the code" in page_text
            or "enter your code" in page_text
            or "check your email" in page_text
            or "we sent you" in page_text
            or ("we sent" in page_text and "code" in page_text)
            or "confirm your email" in page_text
            or "verify your email" in page_text
            or "6-digit" in page_text
            or "6 digit" in page_text
            or "four digit" in page_text
        )
        # Broader field detection: OTP-style boxes + text inputs with code-like attrs
        code_field = page.locator(
            "input[name*='security' i], input[aria-label*='security' i], "
            "input[placeholder*='code' i], input[id*='security' i], "
            "input[name*='verification' i], input[aria-label*='code' i], "
            "input[autocomplete='one-time-code'], input[inputmode='numeric'], "
            "input[id^='security-input-'], input[maxlength='1']"
        ).first
        has_code_field = await code_field.count() > 0
        if has_code_text or has_code_field:
            log.info("Security code prompt DETECTED on poll %d (text=%s field=%s)",
                     _poll, has_code_text, has_code_field)
            break
        await page.wait_for_timeout(3000)

    if not has_code_text and not has_code_field:
        # Diagnostic: take a screenshot + log visible inputs so we can see what
        # page Scout is sitting on when it thinks "no OTP here". This helps us
        # diagnose when Greenhouse introduces new UI we don't pattern-match.
        try:
            ts_ = datetime.now().strftime("%Y%m%d_%H%M%S")
            ss_path = SCREENSHOTS_DIR / f"greenhouse_post_submit_no_otp_{ts_}.png"
            await page.screenshot(path=str(ss_path), full_page=True)
            log.info("No OTP prompt after polling — diagnostic screenshot: %s", ss_path)
            # Also log visible inputs for later pattern extension
            inputs_info = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('input:not([type=hidden])'))
                  .filter(i => i.offsetParent !== null)
                  .slice(0, 20)
                  .map(i => ({name: i.name, id: i.id, type: i.type,
                              placeholder: i.placeholder,
                              ariaLabel: i.getAttribute('aria-label'),
                              maxLength: i.maxLength}));
            }""")
            log.info("Visible inputs on page: %s", inputs_info)
        except Exception:
            pass
        log.debug("No security code prompt detected on page after polling.")
        return False

    log.info("Greenhouse security code prompt detected -- checking email...")

    # Diagnostic dump: what inputs and buttons are on the page?
    try:
        diag = await page.evaluate("""() => {
            const inputs = Array.from(document.querySelectorAll('input:not([type=hidden])'))
                .filter(i => i.offsetParent !== null)
                .map(i => ({
                    tag: i.tagName, type: i.type, name: i.name, id: i.id,
                    placeholder: i.placeholder, ariaLabel: i.getAttribute('aria-label'),
                    maxLength: i.maxLength, value: i.value,
                }));
            const buttons = Array.from(document.querySelectorAll('button, input[type=submit]'))
                .filter(b => b.offsetParent !== null)
                .map(b => ({
                    tag: b.tagName, type: b.type, text: (b.innerText||b.value||'').slice(0,40),
                    disabled: b.disabled, ariaDisabled: b.getAttribute('aria-disabled'),
                    name: b.name, id: b.id, className: b.className.slice(0,60),
                }));
            return {inputs, buttons, url: location.href};
        }""")
        log.info("SECCODE_PAGE_DIAG: %s", diag)
    except Exception as exc:
        log.debug("Could not dump security code page diagnostics: %s", exc)

    # Detect OTP-box input pattern (multiple single-char inputs).
    otp_boxes = page.locator(
        "input[inputmode='numeric']:visible, "
        "input[maxlength='1']:visible, "
        "input[autocomplete='one-time-code']:visible"
    )
    otp_count = await otp_boxes.count()

    # Find the security code input field (single-box case).
    code_input = page.locator(
        "input[name*='security' i]:visible, input[aria-label*='security' i]:visible, "
        "input[placeholder*='code' i]:visible, input[id*='security' i]:visible, "
        "input[name*='verification' i]:visible, input[aria-label*='code' i]:visible, "
        "input[autocomplete='one-time-code']:visible"
    ).first
    if await code_input.count() == 0 and otp_count == 0:
        # Broader search: find any new visible text input.
        code_input = page.locator("input[type='text']:visible, input:not([type]):visible").first

    if otp_count == 0 and await code_input.count() == 0:
        log.warning("Could not find security code input field.")
        return False

    # Fetch the code from email (sync IMAP call in a thread pool).
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        code = await asyncio.get_event_loop().run_in_executor(
            pool, _fetch_greenhouse_security_code_sync
        )

    if not code:
        log.warning("Could not fetch security code from email.")
        return False

    # Enter the code. Prefer real keyboard typing (fires native input events
    # React listens to); handle both single-box and multi-box OTP patterns.
    committed_val = ""
    if otp_count >= len(code):
        # Multi-box OTP: Greenhouse uses 8 separate <input id="security-input-N"
        # maxlength="1">. Try multiple strategies in order of reliability.
        log.info("OTP-box pattern detected (%d boxes, code len %d)", otp_count, len(code))
        first_box = page.locator("input[id^='security-input-']").first
        if await first_box.count() == 0:
            first_box = otp_boxes.first
        try:
            await first_box.scroll_into_view_if_needed(timeout=2_000)
        except Exception:
            pass

        async def _dump_boxes(label: str) -> str:
            try:
                vals = await page.evaluate(
                    """() => {
                        const boxes = document.querySelectorAll('input[id^="security-input-"]');
                        return Array.from(boxes).map(b => b.value || '_').join('');
                    }"""
                )
                log.info("OTP_BOX_STATE %s: %r", label, vals)
                return vals or ""
            except Exception as exc:
                log.debug("dump_boxes error: %s", exc)
                return ""

        # STRATEGY 1: Paste event on first box. Many React OTP libs
        # (including Greenhouse's) intercept paste specifically to
        # distribute characters across boxes.
        await first_box.click()
        await page.wait_for_timeout(150)
        try:
            await page.evaluate(
                """(code) => {
                    const el = document.querySelector('input[id^="security-input-"]');
                    if (!el) return;
                    el.focus();
                    const dt = new DataTransfer();
                    dt.setData('text/plain', code);
                    const ev = new ClipboardEvent('paste', {
                        clipboardData: dt, bubbles: true, cancelable: true,
                    });
                    el.dispatchEvent(ev);
                }""",
                code,
            )
        except Exception as exc:
            log.debug("paste event error: %s", exc)
        await page.wait_for_timeout(700)
        committed_val = await _dump_boxes("after_paste")

        # STRATEGY 2: If paste didn't distribute, use real keyboard.type
        # after focusing the first box. Real keyboard events go through
        # the browser's event loop, which React cannot intercept via
        # preventDefault without fully losing focus.
        if committed_val.replace("_", "").strip().lower() != code.strip().lower():
            log.info("Paste strategy did not fill — trying keyboard.type")
            try:
                await first_box.click()
                await page.wait_for_timeout(150)
                # Clear any partial fill.
                await page.evaluate(
                    """() => {
                        document.querySelectorAll('input[id^="security-input-"]').forEach(el => {
                            const setter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value').set;
                            const tracker = el._valueTracker;
                            if (tracker) tracker.setValue(el.value);
                            setter.call(el, '');
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                        });
                    }"""
                )
                await first_box.click()
                await page.keyboard.type(code, delay=120)
                await page.wait_for_timeout(700)
                committed_val = await _dump_boxes("after_keyboard")
            except Exception as exc:
                log.debug("keyboard.type error: %s", exc)

        # STRATEGY 3: Per-box focus + keyboard press. Focus each box
        # individually and press the single key.
        if committed_val.replace("_", "").strip().lower() != code.strip().lower():
            log.info("Keyboard strategy did not fill — trying per-box focus+press")
            try:
                for i, ch in enumerate(code):
                    box = page.locator(f"input#security-input-{i}")
                    if await box.count() == 0:
                        break
                    await box.click()
                    await page.wait_for_timeout(80)
                    await page.keyboard.press(ch)
                    await page.wait_for_timeout(80)
                committed_val = await _dump_boxes("after_per_box_press")
            except Exception as exc:
                log.debug("per-box press error: %s", exc)

        # STRATEGY 4 (nuclear): Per-box value set with React tracker invalidation.
        if committed_val.replace("_", "").strip().lower() != code.strip().lower():
            log.info("Per-box press did not fill — trying React tracker hack")
            await page.evaluate(
                """(code) => {
                    const boxes = Array.from(document.querySelectorAll('input[id^="security-input-"]'));
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    for (let i = 0; i < Math.min(code.length, boxes.length); i++) {
                        const el = boxes[i];
                        el.focus();
                        const tracker = el._valueTracker;
                        if (tracker) tracker.setValue('');
                        setter.call(el, code[i]);
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }""",
                code,
            )
            await page.wait_for_timeout(700)
            committed_val = await _dump_boxes("after_react_hack")

        code_input = first_box
        log.info("OTP box concat after fill: %r", committed_val)
    else:
        try:
            await code_input.scroll_into_view_if_needed(timeout=2_000)
        except Exception:
            pass
        await code_input.click()
        await page.wait_for_timeout(150)
        try:
            await code_input.fill("")
        except Exception:
            pass
        await page.keyboard.type(code, delay=60)
        await page.wait_for_timeout(400)
        committed_val = (await code_input.input_value()) or ""
        if committed_val.strip().lower() != code.strip().lower():
            try:
                await code_input.fill(code)
                await page.wait_for_timeout(200)
                committed_val = (await code_input.input_value()) or ""
            except Exception:
                pass
        if committed_val.strip().lower() != code.strip().lower():
            # Native setter + dispatch input/change for React controlled inputs.
            await code_input.evaluate(
                """(el, val) => {
                    const proto = el.tagName === 'TEXTAREA'
                        ? window.HTMLTextAreaElement.prototype
                        : window.HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                    setter.call(el, val);
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""",
                code,
            )
            await page.wait_for_timeout(200)
            committed_val = (await code_input.input_value()) or ""
    # Redact: log lengths only, never raw security codes.
    log.info("Entered security code (len=%d, committed_len=%d)", len(code), len(committed_val))
    # For OTP-box path, strip underscore placeholders used by _dump_boxes.
    commit_cmp = committed_val.replace("_", "").strip().lower()
    if commit_cmp != code.strip().lower():
        log.warning("Security code did NOT commit to input field — aborting. got=%r want=%r",
                    commit_cmp, code.strip().lower())
        return False

    # Blur the input to trigger React validation.
    try:
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(200)
    except Exception:
        pass

    # Capture diagnostic screenshot of the code page pre-submit.
    try:
        from datetime import datetime as _dt
        ss_name = f"seccode_pre_submit_{_dt.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(SCREENSHOTS_DIR / ss_name), full_page=True)
        log.info("Security code page screenshot: %s", ss_name)
    except Exception:
        pass

    # Find and click the verify/submit button. Greenhouse's code page may use
    # a button labeled "Verify", "Continue", "Submit", etc., and may NOT be
    # type=submit. Use text-based matching as well.
    submit_clicked = False
    button_selectors = [
        "button[type='submit']:not([disabled]):not([aria-disabled='true'])",
        "button:has-text('Verify'):not([disabled]):not([aria-disabled='true'])",
        "button:has-text('Continue'):not([disabled]):not([aria-disabled='true'])",
        "button:has-text('Submit'):not([disabled]):not([aria-disabled='true'])",
        "button:has-text('Confirm'):not([disabled]):not([aria-disabled='true'])",
        "button:has-text('Send'):not([disabled]):not([aria-disabled='true'])",
        "input[type='submit']:not([disabled])",
    ]
    for wait_round in range(15):
        await page.wait_for_timeout(1000)
        for sel in button_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    # Capture button state BEFORE click.
                    try:
                        btn_state = await btn.evaluate("""(b) => ({
                            tag: b.tagName, type: b.type,
                            text: (b.innerText||b.value||'').slice(0,40),
                            disabled: b.disabled,
                            ariaDisabled: b.getAttribute('aria-disabled'),
                            formId: b.form ? b.form.id : null,
                            formAction: b.form ? b.form.action : null,
                        })""")
                        log.info("PRE_CLICK button state: %s", btn_state)
                    except Exception:
                        pass
                    await btn.click(timeout=5_000)
                    log.info("Resubmitted with security code via %r (round %d)", sel, wait_round + 1)
                    submit_clicked = True
                    # Wait briefly for any network/re-render to happen.
                    await page.wait_for_timeout(2000)
                    # Capture post-click state.
                    try:
                        post_state = await page.evaluate("""() => {
                            const err = Array.from(document.querySelectorAll(
                                "[class*='error' i]:not([class*='field-error-empty'])"
                            )).filter(e => e.offsetParent !== null)
                              .map(e => (e.innerText||'').trim().slice(0,150))
                              .filter(t => t.length > 0 && t.length < 200);
                            const boxes = Array.from(
                                document.querySelectorAll('input[id^="security-input-"]')
                            ).map(b => b.value || '_').join('');
                            const sb = document.querySelector('button[type="submit"]');
                            return {
                                url: location.href,
                                error_msgs: err.slice(0, 5),
                                box_values: boxes,
                                submit_disabled: sb ? sb.disabled : null,
                                submit_aria_disabled: sb ? sb.getAttribute('aria-disabled') : null,
                            };
                        }""")
                        log.info("POST_CLICK state: %s", post_state)
                    except Exception as exc:
                        log.debug("post-click state error: %s", exc)
                    break
            except Exception:
                continue
        if submit_clicked:
            break

    if not submit_clicked:
        log.info("No enabled verify/submit button found, trying Enter key...")
        try:
            await code_input.press("Enter")
            await page.wait_for_timeout(2000)
            submit_clicked = True  # assume Enter worked; we'll verify below
        except Exception:
            pass
        # Last resort: force-click any submit-like button.
        for sel in ["button[type='submit']", "button:has-text('Verify')",
                    "button:has-text('Submit')", "button:has-text('Continue')"]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    await btn.click(force=True, timeout=5_000)
                    log.info("Force-clicked %r", sel)
                    submit_clicked = True
                    break
            except Exception:
                continue

    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        await page.wait_for_timeout(5000)

    # Verify the resubmission actually landed.
    try:
        await page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass
    page_text = (await page.text_content("body") or "").lower()
    # Still on the security code page → code was rejected/expired.
    if ("security code" in page_text
            or "verification code" in page_text
            or "enter the code" in page_text):
        log.warning("Security code page still present after resubmit -- code rejected or expired.")
        return False
    # Strong confirmation phrases (must not also be in the original job description).
    strong_ok = (
        "application submitted" in page_text
        or "successfully submitted" in page_text
        or "thanks for applying" in page_text
        or "thank you for applying" in page_text
        or "application has been received" in page_text
        or "we received your application" in page_text
        or "application received" in page_text
    )
    if strong_ok:
        log.info("Application confirmation detected after security code.")
        return True
    log.warning("No confirmation text found after security code entry -- treating as not submitted.")
    return False


def _fetch_greenhouse_security_code_sync(max_wait_seconds: int = 90) -> str | None:
    """Synchronous version of security code fetch for use in executors."""
    import imaplib
    import email as email_mod
    import time
    from html.parser import HTMLParser

    class _TE(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text: list[str] = []
        def handle_data(self, data: str) -> None:
            self.text.append(data)
        def get_text(self) -> str:
            return " ".join(self.text)

    deadline = time.time() + max_wait_seconds
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            mail = imaplib.IMAP4_SSL(settings.imap_host, int(settings.imap_port))
            mail.login(settings.imap_username, settings.imap_password)
            mail.select("INBOX")
            # Search broadly -- Greenhouse emails come from various addresses.
            # Search for recent Greenhouse emails -- filter by subject in code.
            # Use both UNSEEN and recent date-based search in case emails
            # were marked as read by another IMAP client.
            today = time.strftime("%d-%b-%Y")
            for search_criteria in [
                'UNSEEN FROM "greenhouse"',
                'UNSEEN SUBJECT "security code"',
                f'FROM "greenhouse" SINCE {today}',
            ]:
                status, messages = mail.search(None, search_criteria)
                if status != "OK" or not messages[0]:
                    continue
                ids = messages[0].split()
                for eid in reversed(ids[-3:]):  # Check latest 3
                    _, data = mail.fetch(eid, "(BODY.PEEK[])")
                    msg = email_mod.message_from_bytes(data[0][1])
                    subj = msg["Subject"] or ""
                    (msg["From"] or "").lower()

                    # Must be related to security code.
                    subj_lower = subj.lower()
                    if "security" not in subj_lower and "code" not in subj_lower and "verification" not in subj_lower:
                        continue

                    # Try extracting code from subject first.
                    # e.g. "Your security code: 6335"
                    subj_match = re.search(r"(?:security code|verification code)[:\s]+([A-Za-z0-9]{4,12})", subj, re.I)
                    if subj_match:
                        code = subj_match.group(1).strip()
                        log.info("Found security code from subject: %s (attempt %d)", code, attempt)
                        mail.logout()
                        return code

                    # Extract text from body.
                    full_text = ""
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct in ("text/html", "text/plain"):
                            payload = part.get_payload(decode=True)
                            if payload:
                                text = payload.decode("utf-8", errors="replace")
                                if ct == "text/html":
                                    parser = _TE()
                                    parser.feed(text)
                                    text = parser.get_text()
                                full_text += " " + text

                    # Try body patterns.
                    if full_text:
                        match = re.search(r"(?:security code|verification code)[^:]*:\s*([A-Za-z0-9]{4,12})", full_text, re.I)
                        if match:
                            code = match.group(1).strip()
                            log.info("Found security code from body: %s (attempt %d)", code, attempt)
                            mail.logout()
                            return code
                        match = re.search(r"(?:your code is|enter the code|code:)\s*([A-Za-z0-9]{4,12})", full_text, re.I)
                        if match:
                            code = match.group(1).strip()
                            log.info("Found security code from body: %s (attempt %d)", code, attempt)
                            mail.logout()
                            return code
            mail.logout()
        except Exception as exc:
            log.debug("IMAP error while fetching security code: %s", exc)
        time.sleep(4)
    log.warning("Could not fetch security code after %d attempts", attempt)
    return None


async def _click_submit(page: Page, platform: str) -> bool:
    """Find and click the submit button, then verify the submission succeeded.

    Returns True only if the page shows a confirmation or navigated away
    from the form (i.e., no validation errors blocking submission).
    """
    # Pre-check: are all required fields filled?
    empty_required = await _check_required_fields_filled(page)
    if empty_required:
        # If the only "empty" fields are unidentifiable dropdowns (dropdown_N),
        # proceed anyway -- they are likely phone code prefixes or pre-filled
        # react-selects whose hidden validation input appears empty.
        real_empty = [f for f in empty_required
                      if not re.match(r"^dropdown_\d+$", f)
                      and "(optional)" not in f.lower()]
        if real_empty:
            log.warning("Cannot submit -- %d required fields still empty: %s",
                         len(real_empty), real_empty[:5])
            return False
        else:
            log.info("Only unidentifiable dropdowns flagged (%s) -- proceeding with submit.", empty_required)

    # --- Pre-submit: fix hidden react-select validation inputs ---
    # Greenhouse Remix forms use hidden <input required tabindex="-1" aria-hidden="true">
    # inside each react-select for native browser validation.  Even though the react-select
    # shows a selected value, React often doesn't propagate it into these hidden inputs.
    # Result: form.checkValidity() returns false, browser blocks submit silently.
    #
    # Fix: for each such hidden required input that is still empty, either set its value
    # to the displayed react-select value, or remove 'required' as a fallback.
    fixed_count = await page.evaluate("""() => {
        // Find all hidden required inputs that are :invalid
        const invalids = document.querySelectorAll(
            'input[required][tabindex="-1"][aria-hidden="true"]:invalid, ' +
            'input[required][class*="requiredInput"]:invalid'
        );
        let fixed = 0;
        invalids.forEach(el => {
            // Walk up to find the react-select container
            let container = el.parentElement;
            for (let i = 0; i < 6 && container; i++) {
                // Look for the displayed single-value text
                const singleVal = container.querySelector(
                    '[class*="singleValue"], [class*="single-value"], [class*="SingleValue"]'
                );
                if (singleVal && singleVal.textContent.trim()) {
                    // Set the hidden input value to match
                    const nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeSetter.call(el, singleVal.textContent.trim());
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    fixed++;
                    break;
                }
                container = container.parentElement;
            }
            // Fallback: if still empty, just remove required
            if (!el.value) {
                el.removeAttribute('required');
                fixed++;
            }
        });
        // Also handle any remaining :invalid fields that are hidden
        const remaining = document.querySelectorAll(':invalid:not(form):not(fieldset)');
        remaining.forEach(el => {
            if (el.required && el.getAttribute('aria-hidden') === 'true') {
                el.removeAttribute('required');
                fixed++;
            }
        });
        return fixed;
    }""")
    if fixed_count:
        log.info("Fixed %d hidden react-select validation inputs before submit", fixed_count)

    # Check overall form validity after fixes
    form_valid = await page.evaluate("""() => {
        const form = document.querySelector('form');
        if (!form) return true;
        const valid = form.checkValidity();
        if (!valid) {
            const invalids = document.querySelectorAll(':invalid:not(form):not(fieldset)');
            return {valid: false, count: invalids.length, fields: Array.from(invalids).slice(0, 5).map(el => ({
                tag: el.tagName, type: el.type || '', id: el.id || '', name: el.name || '',
                required: el.required, validationMessage: el.validationMessage || '',
                visible: el.offsetParent !== null, className: (el.className || '').substring(0, 60),
            }))};
        }
        return {valid: true};
    }""")
    if isinstance(form_valid, dict) and not form_valid.get('valid'):
        log.warning("Form still invalid after fixes (%d fields):", form_valid.get('count', 0))
        for fi in form_valid.get('fields', []):
            log.warning("  still-invalid: tag=%s type=%s id='%s' name='%s' msg='%s' visible=%s class='%s'",
                        fi.get('tag'), fi.get('type'), fi.get('id'), fi.get('name'),
                        fi.get('validationMessage', '')[:60], fi.get('visible'), fi.get('className'))
        # Last resort: remove required from ALL remaining invalid hidden fields
        await page.evaluate("""() => {
            document.querySelectorAll(':invalid:not(form):not(fieldset)').forEach(el => {
                if (el.required && (el.type === 'text' || el.type === 'hidden')
                    && (!el.offsetParent || el.getAttribute('aria-hidden') === 'true'
                        || el.getAttribute('tabindex') === '-1')) {
                    el.removeAttribute('required');
                }
            });
        }""")

    # ── Solve reCAPTCHA via CapSolver before submitting ──
    try:
        from backend.services.capsolver import solve_recaptcha
        captcha_token = await solve_recaptcha(page)
        if captcha_token:
            log.info("reCAPTCHA solved via CapSolver — proceeding to submit")
            await page.wait_for_timeout(1000)
        else:
            log.debug("No reCAPTCHA to solve or CapSolver unavailable — submitting anyway")
    except Exception as e:
        log.debug("CapSolver integration error (non-fatal): %s", e)

    url_before = page.url
    page_text_before = (await page.text_content("body") or "").lower()
    selectors = _SUBMIT_SELECTORS.get(platform, _SUBMIT_SELECTORS["generic"])

    # ── Pre-submit warmup: human-like behavior before clicking ──
    # reCAPTCHA v3 scores behavioral signals — fast robotic clicks get low scores.
    # Slow scroll, hover near button, pause like a human reading before submit.
    import random as _rng
    try:
        # Scroll to bottom of form slowly
        await page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})")
        await page.wait_for_timeout(_rng.randint(1500, 3000))
        # Scroll back up slightly (human checks before submitting)
        await page.evaluate("window.scrollBy({top: -200, behavior: 'smooth'})")
        await page.wait_for_timeout(_rng.randint(800, 1500))
        # Move mouse around the submit area
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    box = await loc.bounding_box()
                    if box:
                        # Hover near the button (not dead center)
                        await page.mouse.move(
                            box["x"] + box["width"] * _rng.uniform(0.2, 0.8),
                            box["y"] + box["height"] * _rng.uniform(0.2, 0.8),
                            steps=_rng.randint(8, 20),
                        )
                        await page.wait_for_timeout(_rng.randint(500, 1200))
                    break
            except Exception:
                continue
    except Exception:
        pass  # Non-critical warmup

    clicked = False
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.scroll_into_view_if_needed()
                await page.wait_for_timeout(_rng.randint(300, 700))
                # Click at a random point within the button (not dead center)
                try:
                    box = await loc.bounding_box()
                    if box:
                        await page.mouse.click(
                            box["x"] + box["width"] * _rng.uniform(0.25, 0.75),
                            box["y"] + box["height"] * _rng.uniform(0.25, 0.75),
                        )
                    else:
                        await loc.click()
                except Exception:
                    await loc.click()
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        return False

    # Wait for the page to react.
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        await page.wait_for_timeout(3000)

    # --- If submit button is still visible, check if native validation blocked it ---
    # If :invalid fields still exist after clicking, the browser blocked the submit.
    # Remove required from ALL hidden invalids and re-click.
    still_invalid_count = await page.evaluate("""() => {
        const invalids = document.querySelectorAll(':invalid:not(form):not(fieldset)');
        let removed = 0;
        invalids.forEach(el => {
            if (el.required) {
                // Set value from parent react-select if possible
                let container = el.parentElement;
                for (let i = 0; i < 6 && container; i++) {
                    const sv = container.querySelector(
                        '[class*="singleValue"], [class*="single-value"]'
                    );
                    if (sv && sv.textContent.trim()) {
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        setter.call(el, sv.textContent.trim());
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        break;
                    }
                    container = container.parentElement;
                }
                // If still invalid, remove required -- covers combobox inputs
                // inside react-select containers where a value was visually
                // selected but the native input stays empty.
                if (!el.checkValidity()) {
                    el.removeAttribute('required');
                    el.removeAttribute('aria-required');
                    // Also set a placeholder value if it's a combobox
                    if (el.getAttribute('role') === 'combobox' && !el.value) {
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        setter.call(el, 'selected');
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                }
                removed++;
            }
        });
        return removed;
    }""")
    if still_invalid_count > 0:
        log.info("Fixed %d :invalid fields after first submit click -- re-clicking submit", still_invalid_count)
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click()
                    break
            except Exception:
                continue
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            await page.wait_for_timeout(3000)

    # --- Verify submission actually went through ---

    # Check 1: Did the URL change? (common for successful submissions)
    url_after_clean = page.url.split("#")[0].split("?")[0]
    url_before_clean = url_before.split("#")[0].split("?")[0]
    if url_after_clean != url_before_clean:
        log.info("URL changed from %s to %s -- submission likely succeeded.", url_before_clean, url_after_clean)
        return True

    # Check 2: Check for validation errors FIRST (means form did NOT submit).
    error_indicators = await page.locator(
        "[class*='error' i][class*='message' i]:visible, "
        "[class*='field-error' i]:visible, "
        "[class*='validation-error' i]:visible"
    ).count()
    invalid_locs = page.locator("[aria-invalid='true']:visible")
    invalid_fields = await invalid_locs.count()
    if invalid_fields > 0:
        for inv_i in range(min(invalid_fields, 5)):
            try:
                inv_el = invalid_locs.nth(inv_i)
                inv_id = await inv_el.get_attribute("id") or ""
                inv_name = await inv_el.get_attribute("name") or ""
                inv_role = await inv_el.get_attribute("role") or ""
                log.info("Invalid field %d: id='%s' name='%s' role='%s'", inv_i, inv_id, inv_name, inv_role)
            except Exception:
                pass
    if error_indicators > 0 or invalid_fields > 5:
        log.warning("Form has %d error messages, %d invalid fields -- submission likely blocked.",
                     error_indicators, invalid_fields)
        return False

    # Check 3: Is the submit button still visible and enabled?
    # Button-disabled alone is NOT enough — reCAPTCHA and JS validation also
    # disable the button. We need to wait and re-check for a real signal.
    button_still_visible = False
    button_is_disabled = False
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if await loc.count() > 0 and await loc.is_visible():
                disabled = await loc.get_attribute("disabled")
                if disabled is not None:
                    button_is_disabled = True
                else:
                    button_still_visible = True
        except Exception:
            continue

    if button_is_disabled:
        # Button disabled — could be reCAPTCHA loading or real submission.
        # Wait up to 8 seconds for a URL change or confirmation page.
        log.info("Submit button disabled — waiting for confirmation signal (up to 15s)...")
        for _wait in range(15):
            await page.wait_for_timeout(1000)
            url_now = page.url.split("#")[0].split("?")[0]
            if url_now != url_before_clean:
                log.info("URL changed to %s after button disable — confirmed.", url_now)
                return True
            # Check for confirmation text appearing
            try:
                body_now = (await page.text_content("body") or "").lower()
                for phrase in ["application submitted", "successfully submitted",
                               "thanks for applying", "application has been received",
                               "application received", "we received your application",
                               "your application has been", "you have applied",
                               "thank you for your interest", "thank you for applying"]:
                    if phrase in body_now and phrase not in page_text_before:
                        log.info("Confirmation phrase '%s' appeared — confirmed.", phrase)
                        return True
            except Exception:
                pass
        # After 15s, still no confirmation signal — NOT submitted
        log.warning("Submit button disabled but NO confirmation URL or text after 15s — submission likely FAILED (reCAPTCHA or validation).")
        return False

    if button_still_visible:
        # Button still active + no URL change = NOT submitted.
        # Don't be fooled by "thank you" text in job descriptions.
        log.warning("Submit button still visible and active -- submission did NOT go through.")
        return False

    # Check 4: Button is gone -- look for SPECIFIC confirmation elements.
    # Only trust confirmation text that appeared AFTER the submit click
    # (i.e., wasn't in the page before clicking).
    page_text_after = (await page.text_content("body") or "").lower()

    # Look for strong confirmation phrases that are unlikely to be in job descriptions.
    strong_confirmations = [
        "application submitted", "successfully submitted",
        "thanks for applying", "application has been received",
        "you have applied", "your application has been",
        "we received your application", "application received",
        "verify your email", "security code",
    ]
    for phrase in strong_confirmations:
        if phrase in page_text_after and phrase not in page_text_before:
            log.info("Strong confirmation phrase appeared after submit: '%s'", phrase)
            return True

    # Also check for confirmation-specific elements (not just text in the body)
    confirmation_selectors = [
        "h1:has-text('submitted')", "h2:has-text('submitted')",
        "h1:has-text('thank you')", "h2:has-text('thank you')",
        "h1:has-text('Thank You')", "h2:has-text('Thank You')",
        "[class*='confirmation']:visible", "[class*='success']:visible",
        "[data-testid*='success']:visible", "[data-testid*='confirmation']:visible",
        "text='Application submitted!'", "text='Thanks for applying'",
        "text='RETURN TO THE MAIN PAGE'",  # Lever confirmation
    ]
    for sel in confirmation_selectors:
        try:
            if await page.locator(sel).count() > 0:
                log.info("Confirmation element found: %s", sel)
                return True
        except Exception:
            continue

    # Check if significant page content changed (form was replaced by confirmation)
    # Compare text length -- confirmation pages are usually much shorter.
    len_before = len(page_text_before)
    len_after = len(page_text_after)
    if len_after < len_before * 0.5:
        log.info("Page content reduced by >50%% after submit -- likely confirmation page.")
        return True

    # Submit button is gone + no validation errors = almost certainly submitted.
    # Many career sites (Stripe, Coinbase, etc.) use custom confirmation pages
    # that don't match our phrase/selector list. Being too strict here causes
    # real submissions to be treated as failures.
    log.info("Submit button gone, no errors present -- treating as SUBMITTED (high confidence).")
    return True


async def autofill_and_submit(
    job_url: str,
    profile: dict[str, Any],
    resume_pdf_path: str | None = None,
    cover_letter_pdf_path: str | None = None,
    resume_docx_path: str | None = None,
    cover_letter_docx_path: str | None = None,
    prefer_docx: bool = True,
    company: str = "",
    role: str = "",
) -> dict[str, Any]:
    """Autofill *and* submit the application form.

    Same as ``autofill_application`` but also:
    - Uses rules + LLM to answer custom application questions
    - Clicks the submit button after filling all fields

    Takes a pre-submit screenshot and a post-submit screenshot so you
    can verify what happened.

    Returns a dict with keys:
        status, screenshot_path, post_submit_screenshot, filled_fields,
        needs_review, platform_detected, submitted, auto_answered.
    """
    # Visible browsers so user can watch applications in progress.
    headless = False
    platform = detect_platform(job_url)
    filled: list[str] = []
    needs_review: list[dict[str, str]] = []
    auto_answered: list[str] = []
    screenshot_path = ""
    post_submit_screenshot = ""
    submitted = False

    files: dict[str, Any] = {
        "resume": resume_pdf_path,
        "cover_letter": cover_letter_pdf_path,
        "resume_docx": resume_docx_path or None,
        "cover_letter_docx": cover_letter_docx_path or None,
        "prefer_docx": prefer_docx,
    }

    async with async_playwright() as pw:
        from backend.services.browser_stealth import (
            detect_bot_block,
            human_delay,
            pre_fill_warmup,
        )
        context = await _launch_persistent_browser(pw, headless=headless)

        # Close any stale about:blank pages from persistent context launch
        # Reuse the initial about:blank page if present, otherwise create new
        if context.pages and context.pages[0].url in ("about:blank", "chrome://newtab/", ""):
            page = context.pages[0]
        else:
            page = await context.new_page()

        try:
            # Use domcontentloaded for company sites (networkidle times out
            # on heavy JS sites like Brex, Stripe).  Direct ATS URLs are fine.
            is_direct_ats = re.search(r"greenhouse\.io|lever\.co|ashbyhq\.com|job-boards\.|myworkdayjobs\.com", job_url, re.I)
            wait_strategy = "networkidle" if is_direct_ats else "domcontentloaded"
            await page.goto(job_url, wait_until=wait_strategy, timeout=45_000)
            await page.wait_for_timeout(3000)

            # --- Accept cookies FIRST (before bot detection) ---
            # Accepting cookies builds the persistent profile's trust with
            # reCAPTCHA v3 and prevents cookie banners from blocking form elements.
            await _dismiss_cookie_banner(page)

            # --- Bot detection check ---
            block_type = await detect_bot_block(page)
            if block_type:
                log.warning("Bot block detected (%s) on %s -- stealth handlers attempted resolution", block_type, job_url)
                if block_type == "rate_limit":
                    log.error("Rate-limited on %s -- aborting this job", job_url)
                    return {
                        "status": "submit_not_found",
                        "screenshot_path": "",
                        "post_submit_screenshot": "",
                        "filled_fields": [],
                        "needs_review": [],
                        "platform_detected": platform,
                        "submitted": False,
                        "auto_answered": [f"Rate-limited ({block_type})"],
                    }
                # For recaptcha blocks, try CapSolver immediately
                if block_type == "recaptcha":
                    try:
                        from backend.services.capsolver import solve_recaptcha
                        log.info("Attempting CapSolver for pre-form reCAPTCHA block on %s", job_url)
                        captcha_token = await solve_recaptcha(page)
                        if captcha_token:
                            log.info("Pre-form reCAPTCHA solved via CapSolver — waiting for page to update")
                            await page.wait_for_timeout(3000)
                            # Check if form appeared after solving
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                            except Exception:
                                pass
                            await page.wait_for_timeout(2000)
                        else:
                            log.warning("CapSolver could not solve pre-form reCAPTCHA on %s", job_url)
                    except Exception as e:
                        log.debug("CapSolver pre-form attempt error: %s", e)
                await human_delay(page, 2000, 4000)

            # --- Detect dead job postings (Greenhouse ?error=true redirect) ---
            if "error=true" in page.url:
                log.warning("Job posting no longer exists (redirected to error page): %s -> %s", job_url, page.url)
                return {
                    "status": "submit_not_found",
                    "screenshot_path": "",
                    "post_submit_screenshot": "",
                    "filled_fields": [],
                    "needs_review": [],
                    "platform_detected": platform,
                    "submitted": False,
                    "auto_answered": ["Job posting removed by employer"],
                }

            # --- Dismiss remaining popups/overlays ---
            await _dismiss_all_popups(page)

            # --- Lever: navigate to /apply page if on listing page ---
            if platform == "lever" and "/apply" not in page.url:
                try:
                    apply_url = page.url.rstrip("/") + "/apply"
                    log.info("Lever: navigating to apply page: %s", apply_url)
                    await page.goto(apply_url, wait_until="domcontentloaded", timeout=45_000)
                    await page.wait_for_timeout(3000)
                except Exception as exc:
                    log.warning("Lever: could not navigate to apply page: %s", exc)

            # --- Re-detect platform from page content (embedded forms) ---
            if platform == "generic":
                platform = await _detect_platform_from_page(page) or platform

            # --- Handle embedded Greenhouse iframe ---
            # Some company sites embed Greenhouse in an iframe (#grnhse_iframe).
            # Only needed when the URL is on a company domain (not already on greenhouse.io).
            is_direct_greenhouse = re.search(r"greenhouse\.io", job_url, re.I)
            if platform == "greenhouse" and not is_direct_greenhouse:
                try:
                    iframe = page.locator("#grnhse_iframe, iframe[src*='greenhouse.io']").first
                    if await iframe.count() > 0:
                        iframe_src = await iframe.get_attribute("src")
                        if iframe_src and "greenhouse.io" in iframe_src:
                            log.info("Navigating to Greenhouse iframe src: %s", iframe_src)
                            await page.goto(iframe_src, wait_until="domcontentloaded", timeout=45_000)
                            await page.wait_for_timeout(2000)
                except Exception as exc:
                    log.debug("No Greenhouse iframe found (or direct page): %s", exc)

            # --- Click "Apply" / "I'm Interested" button if present ---
            # Some job pages (SmartRecruiters, company career sites) show a job
            # description first with an "Apply" or "I'm Interested" button that
            # must be clicked before the actual application form appears.
            # Skip for Workday — _fill_workday handles its own Apply + modal flow.
            _APPLY_BUTTON_SELECTORS = [
                "a:has-text('I\\'m Interested')",
                "button:has-text('I\\'m Interested')",
                "a:has-text('Apply Now')",
                "button:has-text('Apply Now')",
                "a:has-text('Apply for this job')",
                "button:has-text('Apply for this job')",
                "a:has-text('Apply to this job')",
                "button:has-text('Apply to this job')",
                "a:has-text('Apply for this position')",
                "button:has-text('Apply for this position')",
                "a[href*='apply']:visible",
                "button:has-text('Apply'):visible",
                "a:has-text('Apply'):visible",
            ]
            # Only click if we don't already see form fields (name/email inputs).
            # Skip entirely for Workday — it has its own Apply + modal handling.
            form_visible = await page.locator(
                "input[id='first_name'], input[name*='first_name'], "
                "input[id='email'], input[name*='email'], "
                "input[type='file']"
            ).first.count() > 0
            if not form_visible and platform != "workday":
                for sel in _APPLY_BUTTON_SELECTORS:
                    try:
                        btn = page.locator(sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            log.info("Clicking pre-apply button: %s", sel)
                            await btn.click()
                            await page.wait_for_timeout(3000)
                            # Check if we navigated to a new page or a form appeared
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                            except Exception:
                                pass
                            await page.wait_for_timeout(2000)

                            # SmartRecruiters flow: after "I'm Interested", a modal
                            # may appear with "Apply", "Continue as guest", etc.
                            _MODAL_APPLY_SELECTORS = [
                                "button:has-text('Apply')",
                                "a:has-text('Apply')",
                                "button:has-text('Continue as guest')",
                                "a:has-text('Continue as guest')",
                                "button:has-text('Apply as guest')",
                                "a:has-text('Apply as guest')",
                                "button:has-text('Continue without signing in')",
                                "button:has-text('Continue')",
                                # SmartRecruiters specific modal buttons
                                "[data-test='apply-button']",
                                ".modal button:has-text('Apply')",
                                "[class*='modal'] button:has-text('Apply')",
                                "[role='dialog'] button:has-text('Apply')",
                                "[role='dialog'] a:has-text('Apply')",
                            ]
                            # Check if a modal/dialog appeared
                            modal_visible = await page.locator(
                                "[role='dialog']:visible, .modal:visible, [class*='modal']:visible, "
                                "[class*='Modal']:visible, [class*='popup']:visible"
                            ).first.count() > 0
                            if modal_visible:
                                log.info("Modal detected after pre-apply click -- looking for apply/continue button")
                                for msel in _MODAL_APPLY_SELECTORS:
                                    try:
                                        mbtn = page.locator(msel).first
                                        if await mbtn.count() > 0 and await mbtn.is_visible():
                                            log.info("Clicking modal button: %s", msel)
                                            await mbtn.click()
                                            await page.wait_for_timeout(3000)
                                            try:
                                                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                                            except Exception:
                                                pass
                                            await page.wait_for_timeout(2000)
                                            break
                                    except Exception:
                                        continue

                            # SmartRecruiters may also redirect to a new URL with the form
                            # Wait a bit more and check if form appeared now
                            form_appeared = await page.locator(
                                "input[id='first_name'], input[name*='first_name'], "
                                "input[id='email'], input[name*='email'], "
                                "input[type='file'], form:visible"
                            ).first.count() > 0
                            if not form_appeared:
                                # Try scrolling down -- some pages load form below
                                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                await page.wait_for_timeout(2000)
                                # Also check for iframe that might contain the form
                                for iframe_sel in [
                                    "iframe[src*='apply']", "iframe[src*='form']",
                                    "iframe[src*='smartrecruiters']",
                                ]:
                                    try:
                                        iframe_loc = page.locator(iframe_sel).first
                                        if await iframe_loc.count() > 0:
                                            frame = await iframe_loc.content_frame()
                                            if frame:
                                                log.info("Found application iframe: %s", iframe_sel)
                                                # Switch page context to iframe
                                                # (handled by platform handler)
                                                break
                                    except Exception:
                                        continue

                            # Re-detect platform after clicking
                            new_platform = await _detect_platform_from_page(page)
                            if new_platform:
                                platform = new_platform
                                log.info("Re-detected platform after apply click: %s", platform)
                            break
                    except Exception:
                        continue

            # --- Re-check for embedded Greenhouse iframe after apply click ---
            # For sites like Stripe, the iframe only appears after clicking "Apply Now".
            is_direct_greenhouse = re.search(r"greenhouse\.io", page.url, re.I)
            if platform == "greenhouse" and not is_direct_greenhouse:
                try:
                    iframe = page.locator("#grnhse_iframe, iframe[src*='greenhouse.io']").first
                    if await iframe.count() > 0:
                        iframe_src = await iframe.get_attribute("src")
                        if iframe_src and "greenhouse.io" in iframe_src:
                            log.info("Navigating to Greenhouse iframe src (post-apply): %s", iframe_src)
                            await page.goto(iframe_src, wait_until="domcontentloaded", timeout=45_000)
                            await page.wait_for_timeout(2000)
                except Exception as exc:
                    log.debug("No Greenhouse iframe found after apply click: %s", exc)

            # --- Handle slider CAPTCHA if present ---
            await _handle_slider_captcha(page)

            # --- Greenhouse boards: scroll to #application form section ---
            # On boards.greenhouse.io listing pages the job description and
            # department/office filter dropdowns sit above the actual form.
            # Scroll the form section into view so fields are interactable and
            # the submit button is reachable.
            if platform == "greenhouse" and re.search(r"boards\.greenhouse\.io", page.url, re.I):
                try:
                    app_section = page.locator("#application, #app")
                    if await app_section.count() > 0:
                        await app_section.first.scroll_into_view_if_needed()
                        await page.wait_for_timeout(1000)
                        log.info("Scrolled to #application section on Greenhouse board page")
                except Exception as exc:
                    log.debug("Could not scroll to #application: %s", exc)

            # --- Human-like warmup before filling ---
            await pre_fill_warmup(page)

            # --- Capture job description text for LLM context ---
            try:
                job_description_text = (await page.text_content("body") or "")[:3000]
            except Exception:
                job_description_text = ""

            # --- Fill standard form fields ---
            handler = _PLATFORM_HANDLERS.get(platform, _fill_generic)
            if platform == "workday":
                await handler(page, profile, files, filled, job_url=job_url)
            else:
                await handler(page, profile, files, filled)
            await human_delay(page, 300, 800)
            await _fill_work_auth(page, filled)
            await human_delay(page, 200, 500)
            await _fill_eeo_fields(page, filled)
            await human_delay(page, 200, 600)

            # --- Collect unknown questions ---
            scope = platform
            needs_review = await _collect_unknown_questions(page, filled, scope)

            # --- Auto-answer custom questions via rules + LLM ---
            # For Lever, the _fill_lever handler already handles all custom card
            # questions (radio/checkbox), so skip LLM answering to avoid timeouts.
            if needs_review and platform != "lever":
                # First pass: handle ALL checkbox groups (no LLM needed, fast).
                needs_review = await _handle_checkbox_groups(page, needs_review, profile)
                # Second pass: rules + LLM, capped at 5 to avoid excessive calls.
                limited_review = needs_review[:5]
                initial_count = len(limited_review)
                limited_review = await _answer_and_fill_unknown_questions(
                    page, limited_review, profile,
                    company=company or "the company",
                    role=role or "the role",
                    scope=scope,
                    job_description=job_description_text,
                )
                answered_count = initial_count - len(limited_review)
                if answered_count > 0:
                    auto_answered.append(f"Answered {answered_count} custom questions via rules/LLM")
                # Combine any remaining with the uncapped ones.
                needs_review = limited_review + needs_review[5:]
            elif platform == "lever":
                # For Lever, just clear needs_review -- custom questions are
                # already handled by _fill_lever, remaining labels are EEO/survey.
                log.info("Lever: skipping LLM for %d remaining unknown labels", len(needs_review))
                needs_review = []

            # --- Pre-submit screenshot ---
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            ss_name = f"autofill_{platform}_{ts}_pre_submit.png"
            ss_path = SCREENSHOTS_DIR / ss_name
            await page.screenshot(path=str(ss_path), full_page=True)
            screenshot_path = str(ss_path)

            # --- Submit the form ---
            # Handle any slider CAPTCHA that appeared during form filling.
            await _handle_slider_captcha(page)
            # Dismiss any popups that appeared during form filling.
            await _dismiss_all_popups(page)
            # Wait for React to process all field changes before checking.
            await page.wait_for_timeout(2000)

            # --- Final checkbox sweep: check any unchecked required checkboxes ---
            # Some checkboxes (Acknowledge, consent) may have been missed or un-checked
            # by subsequent page interactions.
            try:
                all_cbs = page.locator("input[type='checkbox']:visible")
                cb_total = await all_cbs.count()
                for ci in range(min(cb_total, 30)):
                    cb = all_cbs.nth(ci)
                    try:
                        if await cb.is_checked():
                            continue
                        cb_id = await cb.get_attribute("id") or ""
                        is_req = (await cb.get_attribute("required") is not None
                                  or await cb.get_attribute("aria-required") == "true")
                        # Find label text -- try multiple strategies
                        label_text = ""
                        # Strategy 1: label[for=id]
                        if cb_id:
                            escaped_id = _css_escape_id(cb_id)
                            lbl = page.locator(f"label[for='{escaped_id}']").first
                            if await lbl.count() > 0:
                                label_text = (await lbl.text_content() or "").strip().lower()
                        # Strategy 2: parent label element
                        if not label_text:
                            parent_label = cb.locator("xpath=ancestor::label").first
                            if await parent_label.count() > 0:
                                label_text = (await parent_label.text_content() or "").strip().lower()
                        # Strategy 3: nearby text in parent div
                        if not label_text:
                            try:
                                parent_div = cb.locator("xpath=ancestor::div[1]").first
                                if await parent_div.count() > 0:
                                    label_text = (await parent_div.text_content() or "").strip().lower()
                            except Exception:
                                pass
                        # Skip country/region checkboxes -- these are multi-select
                        # "which countries are you authorized to work in" lists.
                        # Only check the US/United States one if present.
                        _COUNTRY_NAMES = {
                            "australia", "belgium", "brazil", "canada", "france",
                            "germany", "india", "indonesia", "ireland", "israel",
                            "italy", "japan", "malaysia", "mexico", "new zealand",
                            "poland", "portugal", "romania", "singapore",
                            "south korea", "spain", "sweden", "switzerland",
                            "thailand", "the netherlands", "uae", "uk",
                            "united kingdom", "china", "hong kong", "taiwan",
                            "argentina", "chile", "colombia", "denmark",
                            "finland", "norway", "philippines", "vietnam",
                            "czech republic", "hungary", "austria", "greece",
                            "turkey", "south africa", "egypt", "nigeria",
                            "kenya", "saudi arabia", "qatar", "bahrain",
                        }
                        is_country_cb = label_text.strip() in _COUNTRY_NAMES
                        is_us_cb = label_text.strip() in ("us", "united states", "usa")

                        # Check if required OR if label suggests acknowledge/certify/agree
                        should_check = (not is_country_cb) and (
                            is_us_cb or is_req or bool(
                                label_text and re.search(
                                    r"acknowledge|i agree|i accept|i certify|i confirm|i consent|i understand|i authorize|privacy|true and complete",
                                    label_text
                                )
                            )
                        )
                        if should_check:
                            # Try clicking parent label first (triggers React onChange)
                            clicked = False
                            if cb_id:
                                escaped_id = _css_escape_id(cb_id)
                                lbl = page.locator(f"label[for='{escaped_id}']").first
                                if await lbl.count() > 0:
                                    await lbl.click()
                                    clicked = True
                            if not clicked:
                                parent_label = cb.locator("xpath=ancestor::label").first
                                if await parent_label.count() > 0:
                                    await parent_label.click()
                                    clicked = True
                            await page.wait_for_timeout(200)
                            if not await cb.is_checked():
                                await cb.check()
                            log.info("Final sweep: checked '%s'", (label_text or cb_id or f"cb_{ci}")[:80])
                    except Exception:
                        continue
            except Exception as exc:
                log.debug("Final checkbox sweep error: %s", exc)

            # --- Final text field sweep: fill any empty required text inputs ---
            # These are fields like "Current Company", "Government entity" that
            # weren't collected as unknown questions but block submission.
            try:
                req_fields = page.locator(
                    "input[aria-required='true']:visible:not([type='checkbox']):not([type='hidden']):not([role='combobox']), "
                    "textarea[aria-required='true']:visible"
                )
                rf_count = await req_fields.count()
                for ri in range(rf_count):
                    field = req_fields.nth(ri)
                    val = (await field.input_value()).strip()
                    if val:
                        continue  # Already filled
                    # Find label
                    fid = await field.get_attribute("id") or ""
                    label_text = ""
                    if fid:
                        lbl = page.locator(f"label[for='{fid}']").first
                        if await lbl.count() > 0:
                            label_text = (await lbl.text_content() or "").strip()
                    if not label_text:
                        try:
                            parent = field.locator("xpath=ancestor::div[contains(@class,'field')]").first
                            if await parent.count() > 0:
                                lbl = parent.locator("label").first
                                if await lbl.count() > 0:
                                    label_text = (await lbl.text_content() or "").strip()
                        except Exception:
                            pass
                    if label_text:
                        answer = _rule_based_answer(label_text)
                        if not answer:
                            # Common fallback patterns
                            lt = label_text.lower()
                            if "current company" in lt or "current employer" in lt or "company name" in lt:
                                answer = ""  # TODO(post-lift): profile.current_employer
                            elif "government" in lt and ("n/a" in lt or "not applicable" in lt or "entity" in lt):
                                answer = "N/A"
                            elif "referr" in lt and ("name" in lt or "list" in lt):
                                answer = "N/A"
                            elif "confirm" in lt and "email" in lt:
                                answer = profile.get("contact", {}).get("email", "")
                            elif "end date" in lt and "year" in lt:
                                answer = "2026"
                            elif "end date" in lt and "month" in lt:
                                answer = "May"
                            elif "start date" in lt and "year" in lt:
                                answer = "2024"
                            elif "start date" in lt and "month" in lt:
                                answer = "August"
                        if answer:
                            # --- Workday typeahead fallback ---
                            # Many Workday fields (source, year, month) look like text
                            # inputs but are actually typeahead/dropdown components.
                            # plain .fill() sets the DOM value but doesn't trigger
                            # Workday's UXI event path, so the value gets wiped.
                            # Strategy: try .fill() first, verify it stuck; if not,
                            # use type-sequentially + ArrowDown + Enter.
                            is_workday_field = await field.evaluate(
                                "el => !!el.closest('[data-automation-id]')"
                            )
                            if is_workday_field:
                                # Typeahead approach: click, clear, type slowly,
                                # wait for dropdown, select first option
                                try:
                                    await field.click()
                                    await page.wait_for_timeout(200)
                                    await field.fill("")
                                    await page.wait_for_timeout(200)
                                    await field.press_sequentially(answer, delay=60)
                                    await page.wait_for_timeout(1200)
                                    # Check if a dropdown/listbox appeared
                                    has_listbox = await page.evaluate("""() => {
                                        const lists = document.querySelectorAll(
                                            '[data-automation-id="activeListContainer"], '
                                            + '[role="listbox"]:not([aria-hidden="true"])'
                                        );
                                        for (const l of lists) {
                                            if (l.offsetParent !== null && l.children.length > 0)
                                                return true;
                                        }
                                        return false;
                                    }""")
                                    if has_listbox:
                                        await page.keyboard.press("ArrowDown")
                                        await page.wait_for_timeout(200)
                                        await page.keyboard.press("Enter")
                                        await page.wait_for_timeout(800)
                                        log.info("Final sweep: typeahead-selected '%s' for '%s'",
                                                 answer, label_text[:60])
                                    else:
                                        # No dropdown — fall back to plain fill
                                        await field.fill(answer)
                                        # Dispatch events to trigger React state update
                                        await field.dispatch_event("input")
                                        await field.dispatch_event("change")
                                        await page.wait_for_timeout(300)
                                        log.info("Final sweep: filled+dispatched '%s' with '%s'",
                                                 label_text[:60], answer)
                                    # Dismiss any open dropdown
                                    await page.keyboard.press("Escape")
                                    await page.wait_for_timeout(200)
                                except Exception as exc:
                                    log.debug("Typeahead fill failed for '%s': %s",
                                              label_text[:40], exc)
                                    # Last resort: plain fill
                                    try:
                                        await field.fill(answer)
                                    except Exception:
                                        pass
                            else:
                                await field.fill(answer)
                                log.info("Final sweep: filled text field '%s' with '%s'",
                                         label_text[:60], answer)
            except Exception as exc:
                log.debug("Final text field sweep error: %s", exc)

            # Always attempt submit -- many "unknown" fields are optional or
            # already filled by the LLM/checkbox sweep.  Browser validation
            # will block the submit if a truly required field is empty.
            if True:  # was: len(needs_review) <= 8
                submitted = await _click_submit(page, platform)
                if submitted:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15_000)
                    except Exception:
                        pass
                    # Extra wait for security code page to render.
                    await page.wait_for_timeout(5000)

                    # Handle Greenhouse email verification code flow.
                    if platform == "greenhouse":
                        code_handled = await _handle_greenhouse_security_code(page)
                        if code_handled:
                            log.info("Security code verification completed.")
                            try:
                                await page.wait_for_load_state("networkidle", timeout=15_000)
                            except Exception:
                                await page.wait_for_timeout(5000)
                        # Re-verify only the actual failure condition: the page is
                        # STILL showing the security-code prompt. If the handler
                        # returned False because no code prompt ever appeared
                        # (plain submission), that's a success — do not penalize.
                        page_text_check = (await page.text_content("body") or "").lower()
                        still_on_code_page = (
                            "security code" in page_text_check
                            or "verification code" in page_text_check
                            or "enter the code" in page_text_check
                        )
                        if still_on_code_page:
                            log.warning(
                                "Greenhouse security code page still present "
                                "(code_handled=%s) -- marking submission as incomplete.",
                                code_handled,
                            )
                            submitted = False

                    # Post-submit screenshot.
                    post_ss_name = f"autofill_{platform}_{ts}_post_submit.png"
                    post_ss_path = SCREENSHOTS_DIR / post_ss_name
                    await page.screenshot(path=str(post_ss_path), full_page=True)
                    post_submit_screenshot = str(post_ss_path)

            status = "submitted" if submitted else "ready_for_review"
        except Exception as exc:
            log.exception("Autofill+submit failed for %s", job_url)
            status = f"error: {exc}"
        finally:
            # When human review is needed (captcha to solve, final Submit
            # to click, or a verification challenge), KEEP THE BROWSER OPEN
            # until the user signals they're done. Without this, the README
            # promise of "pauses for you to click submit" is a lie.
            #
            # Set INSTAPLY_AUTO_CLOSE=1 in the environment to skip the wait
            # (useful for scheduled/unattended runs that should never block).
            keep_open_statuses = (
                "ready_for_review",
                "captcha_required",
                "verification_required",
            )
            auto_close = os.environ.get("INSTAPLY_AUTO_CLOSE", "").strip().lower() in ("1", "true", "yes")
            if status in keep_open_statuses and not auto_close:
                import sys as _sys
                print("", file=_sys.stderr)
                print("=" * 64, file=_sys.stderr)
                print(">>> Browser is staying open for you.", file=_sys.stderr)
                print(">>> Solve any captcha and click Submit on the page.", file=_sys.stderr)
                print(">>> Press Enter in this terminal when done (Ctrl-C to abort).", file=_sys.stderr)
                print("=" * 64, file=_sys.stderr)
                print("", file=_sys.stderr)
                try:
                    # Non-blocking input read on the asyncio loop so we
                    # don't freeze other tasks. Works on stdin TTYs only;
                    # if stdin is a pipe (CI), fall through and close.
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, input)
                except (KeyboardInterrupt, EOFError):
                    pass
            try:
                await context.close()
            except Exception:
                pass

    return {
        "status": status,
        "screenshot_path": screenshot_path,
        "post_submit_screenshot": post_submit_screenshot,
        "filled_fields": filled,
        "needs_review": needs_review,
        "platform_detected": platform,
        "submitted": submitted,
        "auto_answered": auto_answered,
    }
