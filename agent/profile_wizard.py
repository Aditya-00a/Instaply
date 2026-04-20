"""Instaply Profile Wizard.

Drops the user from "I have a resume" to "I have data/profile.json +
data/master-resume.json that the agent can actually use."

Run:
    python setup.py profile
    python setup.py profile --resume ~/Desktop/resume.pdf
    python setup.py profile --yes              # skip prompts where defaults exist

This script is the sister of setup.py. setup.py wires the LLM runtime;
this wires the user identity. After both run, `python run.py` works.
"""
from __future__ import annotations

import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PROFILE_PATH = DATA_DIR / "profile.json"
RESUME_PATH = DATA_DIR / "master-resume.json"

# ─────────────────────────────────────────────────────────────────────
#  ANSI helpers
# ─────────────────────────────────────────────────────────────────────
_USE_COLOUR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

def _wrap(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _USE_COLOUR else s

def bold(s: str) -> str:    return _wrap(s, "1")
def green(s: str) -> str:   return _wrap(s, "32")
def yellow(s: str) -> str:  return _wrap(s, "33")
def red(s: str) -> str:     return _wrap(s, "31")
def cyan(s: str) -> str:    return _wrap(s, "36")
def dim(s: str) -> str:     return _wrap(s, "2")


# ─────────────────────────────────────────────────────────────────────
#  Prompt helpers
# ─────────────────────────────────────────────────────────────────────
def ask(prompt: str, *, default: str = "", required: bool = False) -> str:
    label = bold(prompt)
    suffix = f" [{green(default)}]" if default else (" *" if required else "")
    while True:
        raw = input(f"  {label}{suffix}: ").strip()
        if raw:
            return raw
        if default:
            return default
        if not required:
            return ""
        print(red("  This field is required."))


def ask_yes_no(prompt: str, *, default: Optional[bool] = None) -> bool:
    suffix = " [Y/n]" if default is True else (" [y/N]" if default is False else " [y/n]")
    while True:
        raw = input(f"  {bold(prompt)}{suffix}: ").strip().lower()
        if not raw and default is not None:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print(red("  Answer y or n."))


def ask_choice(prompt: str, choices: list[str], *, default: Optional[int] = None) -> int:
    print(f"  {bold(prompt)}")
    for i, c in enumerate(choices, 1):
        marker = green(" ←") if default == i - 1 else ""
        print(f"    {i}) {c}{marker}")
    while True:
        raw = input(f"  pick 1-{len(choices)}{f' [{default + 1}]' if default is not None else ''}: ").strip()
        if not raw and default is not None:
            return default
        try:
            n = int(raw)
            if 1 <= n <= len(choices):
                return n - 1
        except ValueError:
            pass
        print(red(f"  Enter a number 1 to {len(choices)}."))


# ─────────────────────────────────────────────────────────────────────
#  Resume parsing
# ─────────────────────────────────────────────────────────────────────
def parse_resume(resume_path: Optional[str]) -> dict[str, Any]:
    """Parse a resume file (PDF / DOCX / TXT). Returns the extracted bag.

    Empty dict if no path supplied or parsing failed — wizard falls back
    to fully-manual mode.
    """
    if not resume_path:
        return {}
    p = Path(resume_path).expanduser().resolve()
    if not p.exists():
        print(red(f"  Resume file not found: {p}"))
        return {}
    try:
        # resume_parser is the lifted version of mcp/instaply_mcp/resume.py
        sys.path.insert(0, str(ROOT))
        from resume_parser import extract_resume_text, analyze_resume_text
        text, _ = extract_resume_text(resume_path=str(p))
        if len(text) < 80:
            print(yellow("  Could not extract enough text from the resume — skipping autopopulate."))
            return {}
        extracted = analyze_resume_text(text)
        # Surface raw text + the analyser's structured bag
        return {
            "raw_text": text,
            "name": extracted.get("full_name"),
            "email": extracted.get("email"),
            "phone": extracted.get("phone"),
            "linkedin": extracted.get("linkedin_url"),
            "github": extracted.get("github_url"),
            "portfolio": extracted.get("portfolio_url"),
            "school": extracted.get("school"),
            "degree": extracted.get("degree"),
            "major": extracted.get("major"),
            "current_title": extracted.get("current_title"),
            "years_experience": extracted.get("years_experience"),
            "skills": (extracted.get("extracted_skills") or {}).get("skills") or [],
            "titles_held": (extracted.get("extracted_skills") or {}).get("titles_held") or [],
            "role_targets": (extracted.get("extracted_skills") or {}).get("role_targets") or [],
            "summary": (extracted.get("extracted_skills") or {}).get("summary"),
        }
    except Exception as exc:
        print(red(f"  Resume parse failed ({type(exc).__name__}): {exc}"))
        return {}


# ─────────────────────────────────────────────────────────────────────
#  Wizard
# ─────────────────────────────────────────────────────────────────────
@dataclass
class ProfileAnswers:
    # Identity
    first_name: str = ""
    last_name: str = ""
    legal_name: str = ""
    preferred_name: str = ""
    pronouns: str = ""
    # Contact
    email: str = ""
    phone: str = ""
    city: str = ""
    state: str = ""
    country: str = "United States"
    postal_code: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    # Work + sponsorship
    us_work_authorized: bool = True
    requires_sponsorship: bool = False
    willing_to_relocate: bool = True
    # Targets
    target_roles: list[str] = field(default_factory=list)
    target_locations: list[str] = field(default_factory=list)
    salary_floor: str = ""
    salary_expectation: str = "Open to discussion"
    start_date: str = ""
    # EEO (all optional)
    disclose_eeo: bool = False
    gender: str = ""
    pronouns_eeo: str = ""
    race: str = ""
    hispanic: str = ""
    veteran_status: str = ""
    disability_status: str = ""


def split_csv(s: str) -> list[str]:
    return [p.strip() for p in s.split(",") if p.strip()]


def run_wizard(parsed: dict[str, Any], *, auto_yes: bool = False) -> ProfileAnswers:
    a = ProfileAnswers()

    # Pre-populate from parser where we can
    parsed_full = (parsed.get("name") or "").strip()
    parsed_first, parsed_last = "", ""
    if parsed_full:
        bits = parsed_full.split()
        parsed_first = bits[0]
        parsed_last = " ".join(bits[1:]) if len(bits) > 1 else ""

    print(bold(cyan("\n── Identity ──\n")))
    a.first_name = ask("Legal first name", default=parsed_first, required=True)
    a.last_name  = ask("Legal last name", default=parsed_last, required=True)
    a.legal_name = f"{a.first_name} {a.last_name}".strip()
    a.preferred_name = ask("Preferred name (or blank if same as legal)", default=a.first_name)
    a.pronouns = ask("Pronouns (e.g. she/her, he/him, they/them — blank to skip)")

    print(bold(cyan("\n── Contact ──\n")))
    a.email = ask("Email (must be Gmail — the agent guards on this)",
                  default=parsed.get("email") or "", required=True)
    if "gmail" not in a.email.lower():
        print(yellow("  Note: run.py aborts unless this is a gmail address. "
                     "You can edit this later in data/profile.json if needed."))
    a.phone = ask("Phone (e.g. +1-555-555-5555)", default=parsed.get("phone") or "")
    a.city  = ask("City", required=True)
    a.state = ask("State / region (e.g. NY, CA)")
    a.country = ask("Country", default="United States")
    a.postal_code = ask("Postal / ZIP code")
    a.linkedin = ask("LinkedIn URL", default=parsed.get("linkedin") or "")
    a.github   = ask("GitHub URL",   default=parsed.get("github") or "")
    a.portfolio = ask("Portfolio URL", default=parsed.get("portfolio") or "")

    print(bold(cyan("\n── Work authorization ──\n")))
    a.us_work_authorized = ask_yes_no("Are you authorized to work in the US?", default=True)
    a.requires_sponsorship = ask_yes_no("Do you require visa sponsorship?", default=False)
    a.willing_to_relocate  = ask_yes_no("Are you willing to relocate (within US)?", default=True)

    print(bold(cyan("\n── Targets ──\n")))
    suggested_roles = ", ".join(parsed.get("role_targets") or parsed.get("titles_held") or [])
    a.target_roles = split_csv(ask(
        "Target roles (comma-separated)",
        default=suggested_roles,
        required=True,
    ))
    a.target_locations = split_csv(ask(
        "Target locations (comma-separated; e.g. Remote, New York, San Francisco)",
        default="Remote, " + (a.city or "New York"),
    ))
    a.salary_floor = ask("Salary floor (e.g. $90,000 — blank to skip)")
    a.salary_expectation = ask(
        "Salary expectation phrase",
        default="Open to discussion based on role and responsibilities.",
    )
    a.start_date = ask("Earliest start date (e.g. 06/01/2026 — blank to skip)")

    print(bold(cyan("\n── EEO / demographics (optional) ──\n")))
    print(dim("  Most ATS forms have optional EEO sections. The agent will only "
              "auto-fill these if you supply them. Skip the whole block to leave blank."))
    a.disclose_eeo = ask_yes_no("Provide EEO answers?", default=False)
    if a.disclose_eeo:
        a.gender = ["Male", "Female", "Non-binary", "Prefer not to say", ""][ask_choice(
            "Gender", ["Male", "Female", "Non-binary", "Prefer not to say", "Skip"],
            default=3,
        )]
        a.race = ["Asian", "Black or African American", "Hispanic or Latino",
                  "Native American or Alaska Native", "Native Hawaiian or Pacific Islander",
                  "White", "Two or more races", "Prefer not to say", ""][ask_choice(
            "Race / ethnicity",
            ["Asian", "Black or African American", "Hispanic or Latino",
             "Native American or Alaska Native", "Native Hawaiian or Pacific Islander",
             "White", "Two or more races", "Prefer not to say", "Skip"],
            default=7,
        )]
        a.veteran_status = ["I am not a protected veteran",
                            "I identify as one or more of the protected veteran classes",
                            "I don't wish to answer", ""][ask_choice(
            "Veteran status",
            ["Not a protected veteran", "Protected veteran",
             "Don't wish to answer", "Skip"],
            default=2,
        )]
        a.disability_status = ["No, I do not have a disability and have not had one in the past",
                               "Yes, I have a disability or have had one in the past",
                               "I do not wish to answer", ""][ask_choice(
            "Disability status",
            ["No disability", "Yes, I have a disability",
             "Don't wish to answer", "Skip"],
            default=2,
        )]

    return a


# ─────────────────────────────────────────────────────────────────────
#  JSON writers
# ─────────────────────────────────────────────────────────────────────
def to_profile_json(a: ProfileAnswers) -> dict[str, Any]:
    return {
        "name": a.legal_name,
        "preferred_name": a.preferred_name or a.first_name,
        "first_name": a.first_name,
        "last_name": a.last_name,
        "pronouns": a.pronouns,
        "contact": {
            "email": a.email,
            "phone": a.phone,
            "city": a.city,
            "state": a.state,
            "country": a.country,
            "postal_code": a.postal_code,
            "linkedin": a.linkedin,
            "github": a.github,
            "portfolio": a.portfolio,
        },
        "work_authorization": {
            "us_authorized": a.us_work_authorized,
            "requires_sponsorship": a.requires_sponsorship,
            "willing_to_relocate": a.willing_to_relocate,
        },
        "targets": {
            "roles": a.target_roles,
            "locations": a.target_locations,
            "salary_floor": a.salary_floor,
            "salary_expectation": a.salary_expectation,
            "start_date": a.start_date,
        },
        "eeo": {
            "gender": a.gender,
            "race": a.race,
            "veteran_status": a.veteran_status,
            "disability_status": a.disability_status,
        },
    }


def to_master_resume_json(a: ProfileAnswers, parsed: dict[str, Any]) -> dict[str, Any]:
    """Build a master-resume.json from parsed bag + answers.

    The tailoring engine wants `name`, `contact`, `summary`, `experience`,
    `education`, `skills`. We can populate identity from the wizard, the
    rest from the parser when we have it.
    """
    education = []
    if parsed.get("school"):
        education.append({
            "school": parsed.get("school"),
            "degree": parsed.get("degree") or "",
            "field": parsed.get("major") or "",
            "graduation": "",
        })
    return {
        "name": a.legal_name,
        "contact": {
            "email": a.email,
            "phone": a.phone,
            "linkedin": a.linkedin,
            "github": a.github,
            "portfolio": a.portfolio,
            "city": a.city,
            "state": a.state,
            "country": a.country,
        },
        "summary": parsed.get("summary") or "",
        "experience": [],   # TODO: parse experience blocks from raw text in a follow-up
        "education": education,
        "skills": parsed.get("skills") or [],
        "raw_resume_text": parsed.get("raw_text") or "",
    }


# ─────────────────────────────────────────────────────────────────────
#  Validation
# ─────────────────────────────────────────────────────────────────────
def validate(profile: dict[str, Any], resume: dict[str, Any]) -> list[str]:
    errs = []
    if not profile.get("name"):
        errs.append("profile.name is empty")
    contact = profile.get("contact", {})
    if not contact.get("email"):
        errs.append("profile.contact.email is empty")
    if not contact.get("city"):
        errs.append("profile.contact.city is empty")
    targets = profile.get("targets", {})
    if not targets.get("roles"):
        errs.append("profile.targets.roles is empty (the agent needs at least one)")
    if not resume.get("name"):
        errs.append("master-resume.name is empty")
    return errs


# ─────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Instaply profile wizard.")
    ap.add_argument("--resume", help="Path to your resume PDF / DOCX / TXT (optional — autopopulates fields).")
    ap.add_argument("--yes", "-y", action="store_true", help="Accept all defaults where possible.")
    ap.add_argument("--force", action="store_true", help="Overwrite existing profile.json / master-resume.json.")
    args = ap.parse_args(argv)

    print(bold(cyan("\nInstaply Profile Wizard\n")))
    print(dim("Walks you through ~15 questions and writes data/profile.json + data/master-resume.json."))
    print(dim("Hit Ctrl-C any time. Most fields are optional; required ones are marked *.\n"))

    if PROFILE_PATH.exists() and not args.force:
        print(yellow(f"  {PROFILE_PATH.relative_to(ROOT)} already exists."))
        if not ask_yes_no("Overwrite?", default=False):
            print(dim("  Aborted. Use --force to skip this prompt."))
            return 0

    parsed = parse_resume(args.resume)
    if parsed:
        print(green(f"\n  Resume parsed: {len(parsed.get('raw_text') or '')} chars, "
                    f"{len(parsed.get('skills') or [])} skills, "
                    f"{len(parsed.get('role_targets') or [])} role targets."))
    elif args.resume:
        print(yellow("\n  Continuing in fully-manual mode."))
    else:
        print(dim("\n  No --resume provided. All fields will be entered manually."))

    try:
        a = run_wizard(parsed, auto_yes=args.yes)
    except KeyboardInterrupt:
        print(red("\n  Aborted."))
        return 130

    profile = to_profile_json(a)
    resume = to_master_resume_json(a, parsed)

    errs = validate(profile, resume)
    if errs:
        print(yellow("\n  Validation warnings:"))
        for e in errs:
            print(f"    - {e}")
        if not ask_yes_no("Save anyway?", default=False):
            return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    RESUME_PATH.write_text(json.dumps(resume, indent=2), encoding="utf-8")

    print(bold(green(f"\n  Wrote {PROFILE_PATH.relative_to(ROOT)}")))
    print(bold(green(f"  Wrote {RESUME_PATH.relative_to(ROOT)}")))
    print(dim("\n  Next: run the agent."))
    print(f"    {bold('python run.py')}")
    print(f"  or install it as a scheduled task: {bold('python doctor.py')} first to sanity-check, then")
    print(f"    {bold('powershell -ExecutionPolicy Bypass -File scripts/setup-scheduler.ps1')}  (Windows)")
    print(f"    {bold('bash scripts/setup-scheduler.sh')}                                           (Mac / Linux)")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
