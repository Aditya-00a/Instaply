"""Types shared by the rules engine, cache, and LLM fallback.

A single application run does this:
  DOM -> list[FieldCandidate] -> for each: FieldDecision -> Playwright actions

The engine's only job is FieldCandidate -> FieldDecision.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ─── What we know about the user ─────────────────────────────────
class UserProfile(BaseModel):
    """Everything the autofill engine can draw on.

    Loaded from Supabase `profiles` + `resumes.parsed_json` at job start.
    Keep flat — nested structures force rule-writers to navigate, which
    creates bugs. Flatten on load.
    """
    # Identity
    user_id: str
    first_name: str
    last_name: str
    full_name: str                                   # derived: f"{first} {last}"
    email: str
    phone_e164: Optional[str] = None                 # +14155551234
    phone_national: Optional[str] = None             # 415-555-1234

    # Links
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    website_url: Optional[str] = None

    # Location
    city: Optional[str] = None
    state: Optional[str] = None                      # "CA" or "California"
    country: Optional[str] = None                    # "United States"
    postal_code: Optional[str] = None

    # Work auth
    work_auth_status: Optional[str] = None           # 'citizen'|'gc'|'h1b'|'opt'|'cpt'|'other'|'none'
    needs_sponsorship: Optional[bool] = None
    work_auth_country: Optional[str] = "United States"

    # Experience
    current_company: Optional[str] = None
    current_title: Optional[str] = None
    years_experience: Optional[int] = None

    # Education (top entry; resume_json has full list if needed)
    school: Optional[str] = None
    degree: Optional[str] = None                     # "Master's", "Bachelor's"
    major: Optional[str] = None
    graduation_year: Optional[int] = None

    # EEO / demographics (optional; user controls what's filled)
    gender: Optional[str] = None
    race_ethnicity: Optional[str] = None
    veteran_status: Optional[str] = None
    disability_status: Optional[str] = None

    # Preferences
    salary_expectation_usd: Optional[int] = None
    willing_to_relocate: Optional[bool] = None
    remote_preference: Optional[str] = None          # 'remote'|'hybrid'|'onsite'|'any'
    earliest_start_date: Optional[str] = None        # ISO date

    # Artifacts
    resume_local_path: Optional[str] = None          # runtime-supplied; bytes on disk
    cover_letter_local_path: Optional[str] = None
    resume_parsed_json: Optional[dict[str, Any]] = None   # full structured parse


# ─── What a form field looks like to us ──────────────────────────
class FieldType(str, Enum):
    TEXT = "text"
    EMAIL = "email"
    TEL = "tel"
    URL = "url"
    TEXTAREA = "textarea"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    FILE = "file"
    DATE = "date"
    NUMBER = "number"
    HIDDEN = "hidden"
    UNKNOWN = "unknown"


class FieldCandidate(BaseModel):
    """A single form field, extracted from the DOM by the ATS adapter.

    ATS adapters (greenhouse.py, lever.py, etc.) walk the DOM and emit
    one of these per fillable input. The autofill engine is DOM-agnostic
    past this point.
    """
    dom_id: str                                      # stable id for Playwright selector
    field_type: FieldType
    label: Optional[str] = None                      # visible label text
    name_attr: Optional[str] = None                  # <input name="...">
    id_attr: Optional[str] = None                    # <input id="...">
    placeholder: Optional[str] = None
    aria_label: Optional[str] = None
    required: bool = False
    options: list[str] = Field(default_factory=list)  # for select/radio
    max_length: Optional[int] = None
    company_slug: Optional[str] = None               # for cache scoping
    question_context: Optional[str] = None           # surrounding text (for LLM fallback)


# ─── What the engine decides ─────────────────────────────────────
class DecisionSource(str, Enum):
    RULE = "rule"                                    # deterministic match
    CACHE = "cache"                                  # answered before
    LLM = "llm"                                      # NIM fallback
    SKIP = "skip"                                    # no good answer; leave blank if optional
    REVIEW = "review"                                # needs human eyes before submit


class FieldDecision(BaseModel):
    """What to do with one field.

    `value` is the string / list / filepath to type, select, or upload.
    For checkboxes/radios, value is the option string to select.
    For files, value is an absolute local path.
    """
    dom_id: str
    value: Any
    source: DecisionSource
    confidence: float = Field(ge=0.0, le=1.0)        # 0..1
    rule_id: Optional[str] = None                    # if source=rule
    model: Optional[str] = None                      # if source=llm
    reasoning: Optional[str] = None                  # why we picked this
    required_review: bool = False                    # force human approval even if filled

    class Config:
        arbitrary_types_allowed = True


# ─── Thresholds ─────────────────────────────────────────────────
class EngineConfig(BaseModel):
    """Tunable engine behaviour. Defaults are production-safe."""
    min_rule_confidence: float = 0.80
    min_cache_confidence: float = 0.85
    min_llm_confidence: float = 0.70
    required_field_threshold: float = 0.75           # required fields need this to submit
    always_review_fields: set[str] = Field(default_factory=lambda: {
        "salary_expectation",
        "cover_letter",
        "work_authorization",
        "sponsorship",
    })
