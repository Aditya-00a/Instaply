"""Deterministic field-matching rules.

A rule fires when its matchers hit a FieldCandidate with enough confidence
and its resolver can produce a non-empty value from the UserProfile.

Design principles:
  1. Rules are data, not code. Add a rule = append to RULES list.
  2. Every matcher is a regex against one of: label, name, id, placeholder,
     aria_label. Matching is case-insensitive.
  3. Resolvers are small lambdas. If the profile lacks the needed field,
     return None and the engine falls through to cache/LLM.
  4. Confidence reflects how specific the match is, NOT how confident we
     are in the value. A perfect label match = 0.95; a loose name-attr
     match = 0.80.
  5. First rule to match wins — order matters. Put specific rules above
     general ones.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .models import FieldCandidate, FieldType, UserProfile


# ─── Rule primitive ──────────────────────────────────────────────
@dataclass
class FieldRule:
    id: str                                          # "first_name", "linkedin_url", etc.
    label_patterns: list[str] = field(default_factory=list)
    name_patterns: list[str] = field(default_factory=list)
    id_patterns: list[str] = field(default_factory=list)
    placeholder_patterns: list[str] = field(default_factory=list)
    accepts_types: Optional[set[FieldType]] = None   # None = any
    rejects_types: Optional[set[FieldType]] = None
    resolver: Callable[[UserProfile, FieldCandidate], Optional[object]] = lambda p, c: None
    confidence: float = 0.90
    requires_review: bool = False

    def match(self, cand: FieldCandidate) -> float:
        """Return match confidence in [0, 1]. 0 means no match."""
        if self.accepts_types and cand.field_type not in self.accepts_types:
            return 0.0
        if self.rejects_types and cand.field_type in self.rejects_types:
            return 0.0

        best = 0.0
        # Label match is strongest signal (what the user sees)
        if cand.label and _any_match(self.label_patterns, cand.label):
            best = max(best, self.confidence)
        # aria-label is nearly as good as label
        if cand.aria_label and _any_match(self.label_patterns, cand.aria_label):
            best = max(best, self.confidence * 0.98)
        # name/id attributes are weaker but still reliable
        if cand.name_attr and _any_match(self.name_patterns, cand.name_attr):
            best = max(best, self.confidence * 0.90)
        if cand.id_attr and _any_match(self.id_patterns, cand.id_attr):
            best = max(best, self.confidence * 0.88)
        # placeholder is the weakest — can be misleading
        if cand.placeholder and _any_match(self.placeholder_patterns, cand.placeholder):
            best = max(best, self.confidence * 0.75)
        return best


def _any_match(patterns: list[str], text: str) -> bool:
    if not patterns:
        return False
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


# ─── Resolver helpers ────────────────────────────────────────────
def _full_name(p: UserProfile, _c: FieldCandidate) -> Optional[str]:
    return p.full_name or (f"{p.first_name} {p.last_name}".strip() or None)


def _phone_best(p: UserProfile, _c: FieldCandidate) -> Optional[str]:
    return p.phone_e164 or p.phone_national


def _location_combined(p: UserProfile, _c: FieldCandidate) -> Optional[str]:
    parts = [x for x in (p.city, p.state, p.country) if x]
    return ", ".join(parts) if parts else None


def _work_auth_yesno(p: UserProfile, cand: FieldCandidate) -> Optional[str]:
    """Answer 'are you legally authorized to work?' questions.

    Returns the best-matching option string from the field's choices.
    """
    if p.work_auth_status is None:
        return None
    authorized = p.work_auth_status not in ("none", "other")
    yes_tokens = ("yes", "authorized", "eligible", "i am")
    no_tokens = ("no", "not authorized", "not eligible")
    target = yes_tokens if authorized else no_tokens
    for opt in cand.options:
        low = opt.lower()
        if any(t in low for t in target):
            return opt
    return "Yes" if authorized else "No"


def _sponsorship_yesno(p: UserProfile, cand: FieldCandidate) -> Optional[str]:
    if p.needs_sponsorship is None:
        return None
    target = ("yes", "i will", "require") if p.needs_sponsorship else ("no", "i will not", "do not")
    for opt in cand.options:
        low = opt.lower()
        if any(t in low for t in target):
            return opt
    return "Yes" if p.needs_sponsorship else "No"


# ─── The rule list ───────────────────────────────────────────────
# Order matters: specific rules first, general fallbacks last.
RULES: list[FieldRule] = [
    # ─ Names ────────────────────────────────────────────────────
    FieldRule(
        id="first_name",
        label_patterns=[r"\bfirst\s*name\b", r"\bgiven\s*name\b", r"^first$"],
        name_patterns=[r"^first[_-]?name$", r"^fname$", r"^givenname$"],
        id_patterns=[r"first[_-]?name", r"fname"],
        accepts_types={FieldType.TEXT},
        resolver=lambda p, c: p.first_name,
        confidence=0.96,
    ),
    FieldRule(
        id="last_name",
        label_patterns=[r"\blast\s*name\b", r"\bfamily\s*name\b", r"\bsurname\b", r"^last$"],
        name_patterns=[r"^last[_-]?name$", r"^lname$", r"^surname$", r"^familyname$"],
        id_patterns=[r"last[_-]?name", r"lname", r"surname"],
        accepts_types={FieldType.TEXT},
        resolver=lambda p, c: p.last_name,
        confidence=0.96,
    ),
    FieldRule(
        id="full_name",
        label_patterns=[r"\bfull\s*name\b", r"^name$", r"\byour\s*name\b"],
        name_patterns=[r"^name$", r"^fullname$", r"^full[_-]name$"],
        id_patterns=[r"^name$", r"fullname"],
        accepts_types={FieldType.TEXT},
        resolver=_full_name,
        confidence=0.88,
    ),

    # ─ Contact ───────────────────────────────────────────────────
    FieldRule(
        id="email",
        label_patterns=[r"\bemail\b", r"e-?mail\s*address"],
        name_patterns=[r"email"],
        id_patterns=[r"email"],
        accepts_types={FieldType.EMAIL, FieldType.TEXT},
        resolver=lambda p, c: p.email,
        confidence=0.97,
    ),
    FieldRule(
        id="phone",
        label_patterns=[r"\bphone\b", r"\bmobile\b", r"\btelephone\b", r"\bcell\b"],
        name_patterns=[r"phone", r"mobile", r"telephone"],
        id_patterns=[r"phone", r"mobile"],
        accepts_types={FieldType.TEL, FieldType.TEXT},
        resolver=_phone_best,
        confidence=0.95,
    ),

    # ─ Links ─────────────────────────────────────────────────────
    FieldRule(
        id="linkedin_url",
        label_patterns=[r"linkedin"],
        name_patterns=[r"linkedin"],
        id_patterns=[r"linkedin"],
        placeholder_patterns=[r"linkedin\.com"],
        accepts_types={FieldType.URL, FieldType.TEXT},
        resolver=lambda p, c: p.linkedin_url,
        confidence=0.95,
    ),
    FieldRule(
        id="github_url",
        label_patterns=[r"github"],
        name_patterns=[r"github"],
        id_patterns=[r"github"],
        placeholder_patterns=[r"github\.com"],
        accepts_types={FieldType.URL, FieldType.TEXT},
        resolver=lambda p, c: p.github_url,
        confidence=0.95,
    ),
    FieldRule(
        id="portfolio_url",
        label_patterns=[r"\bportfolio\b", r"personal\s*(site|website)"],
        name_patterns=[r"portfolio", r"personal[_-]?site"],
        id_patterns=[r"portfolio"],
        accepts_types={FieldType.URL, FieldType.TEXT},
        resolver=lambda p, c: p.portfolio_url or p.website_url,
        confidence=0.90,
    ),
    FieldRule(
        id="website_url",
        label_patterns=[r"\bwebsite\b", r"personal\s*url", r"other\s*website"],
        name_patterns=[r"website", r"url"],
        id_patterns=[r"website"],
        accepts_types={FieldType.URL, FieldType.TEXT},
        resolver=lambda p, c: p.website_url or p.portfolio_url,
        confidence=0.82,
    ),

    # ─ Location ──────────────────────────────────────────────────
    FieldRule(
        id="city",
        label_patterns=[r"^\s*city\b", r"\bcity\s*(of\s*residence)?\b"],
        name_patterns=[r"^city$", r"^current[_-]city$"],
        id_patterns=[r"city"],
        accepts_types={FieldType.TEXT},
        resolver=lambda p, c: p.city,
        confidence=0.92,
    ),
    FieldRule(
        id="state",
        label_patterns=[r"\bstate\b", r"\bprovince\b", r"\bregion\b"],
        name_patterns=[r"state", r"province", r"region"],
        id_patterns=[r"state", r"province"],
        accepts_types={FieldType.TEXT, FieldType.SELECT},
        resolver=lambda p, c: p.state,
        confidence=0.90,
    ),
    FieldRule(
        id="country",
        label_patterns=[r"\bcountry\b"],
        name_patterns=[r"country"],
        id_patterns=[r"country"],
        accepts_types={FieldType.TEXT, FieldType.SELECT},
        resolver=lambda p, c: p.country,
        confidence=0.92,
    ),
    FieldRule(
        id="postal_code",
        label_patterns=[r"\bzip\b", r"\bpostal\s*code\b", r"\bpostcode\b"],
        name_patterns=[r"zip", r"postal", r"postcode"],
        id_patterns=[r"zip", r"postal"],
        accepts_types={FieldType.TEXT, FieldType.NUMBER},
        resolver=lambda p, c: p.postal_code,
        confidence=0.92,
    ),
    FieldRule(
        id="location_combined",
        label_patterns=[r"\blocation\b", r"where.+located", r"where.+based"],
        name_patterns=[r"^location$"],
        id_patterns=[r"location"],
        accepts_types={FieldType.TEXT},
        resolver=_location_combined,
        confidence=0.80,
    ),

    # ─ Experience ────────────────────────────────────────────────
    FieldRule(
        id="current_company",
        label_patterns=[r"current\s*(company|employer)", r"^company$", r"^employer$"],
        name_patterns=[r"current[_-]?company", r"^company$", r"^employer$"],
        id_patterns=[r"current[_-]?company", r"^company$"],
        accepts_types={FieldType.TEXT},
        resolver=lambda p, c: p.current_company,
        confidence=0.88,
    ),
    FieldRule(
        id="current_title",
        label_patterns=[r"current\s*(title|role|position)", r"job\s*title", r"^title$"],
        name_patterns=[r"current[_-]?title", r"job[_-]?title", r"^title$"],
        id_patterns=[r"title", r"current[_-]?role"],
        accepts_types={FieldType.TEXT},
        resolver=lambda p, c: p.current_title,
        confidence=0.88,
    ),
    FieldRule(
        id="years_experience",
        label_patterns=[
            r"years\s*of\s*(relevant\s*)?experience",
            r"how\s*many\s*years",
            r"total\s*experience",
        ],
        name_patterns=[r"years[_-]?experience", r"experience[_-]?years"],
        id_patterns=[r"years[_-]?exp"],
        accepts_types={FieldType.NUMBER, FieldType.TEXT, FieldType.SELECT},
        resolver=lambda p, c: str(p.years_experience) if p.years_experience is not None else None,
        confidence=0.85,
    ),

    # ─ Education ─────────────────────────────────────────────────
    FieldRule(
        id="school",
        label_patterns=[r"\bschool\b", r"\buniversity\b", r"\bcollege\b", r"institution"],
        name_patterns=[r"school", r"university", r"college"],
        id_patterns=[r"school", r"university"],
        accepts_types={FieldType.TEXT, FieldType.SELECT},
        resolver=lambda p, c: p.school,
        confidence=0.88,
    ),
    FieldRule(
        id="degree",
        label_patterns=[r"\bdegree\b", r"degree\s*type", r"highest\s*(degree|education)"],
        name_patterns=[r"degree"],
        id_patterns=[r"degree"],
        accepts_types={FieldType.TEXT, FieldType.SELECT},
        resolver=lambda p, c: p.degree,
        confidence=0.88,
    ),
    FieldRule(
        id="major",
        label_patterns=[r"\bmajor\b", r"field\s*of\s*study", r"\bdiscipline\b"],
        name_patterns=[r"major", r"discipline", r"field[_-]?of[_-]?study"],
        id_patterns=[r"major"],
        accepts_types={FieldType.TEXT, FieldType.SELECT},
        resolver=lambda p, c: p.major,
        confidence=0.86,
    ),
    FieldRule(
        id="graduation_year",
        label_patterns=[r"graduation\s*year", r"year\s*of\s*graduation", r"grad\s*year"],
        name_patterns=[r"grad[_-]?year", r"graduation"],
        id_patterns=[r"grad[_-]?year"],
        accepts_types={FieldType.NUMBER, FieldType.TEXT, FieldType.SELECT},
        resolver=lambda p, c: str(p.graduation_year) if p.graduation_year else None,
        confidence=0.88,
    ),

    # ─ Work authorization (HIGH VALUE; often required) ─────────
    FieldRule(
        id="work_authorization",
        label_patterns=[
            r"legally\s*authorized.*work",
            r"authorized\s*to\s*work",
            r"work\s*authorization",
            r"eligible\s*to\s*work",
            r"right\s*to\s*work",
        ],
        name_patterns=[r"work[_-]?auth", r"authorized", r"eligible[_-]?to[_-]?work"],
        id_patterns=[r"work[_-]?auth", r"authorization"],
        accepts_types={FieldType.SELECT, FieldType.RADIO, FieldType.TEXT},
        resolver=_work_auth_yesno,
        confidence=0.90,
        requires_review=True,   # always review — wrong answer = instant reject
    ),
    FieldRule(
        id="sponsorship",
        label_patterns=[
            r"require.*sponsor",
            r"need.*sponsor",
            r"visa\s*sponsorship",
            r"will\s*you\s*(now|ever).*sponsor",
            r"sponsorship\s*now\s*or\s*in\s*the\s*future",
        ],
        name_patterns=[r"sponsor", r"visa"],
        id_patterns=[r"sponsor", r"visa"],
        accepts_types={FieldType.SELECT, FieldType.RADIO, FieldType.TEXT},
        resolver=_sponsorship_yesno,
        confidence=0.90,
        requires_review=True,
    ),

    # ─ Resume / cover letter uploads ────────────────────────────
    FieldRule(
        id="resume_upload",
        label_patterns=[r"\bresume\b", r"\bcv\b", r"curriculum\s*vitae"],
        name_patterns=[r"resume", r"\bcv\b"],
        id_patterns=[r"resume", r"\bcv\b"],
        accepts_types={FieldType.FILE},
        resolver=lambda p, c: p.resume_local_path,
        confidence=0.97,
    ),
    FieldRule(
        id="cover_letter_upload",
        label_patterns=[r"cover\s*letter"],
        name_patterns=[r"cover[_-]?letter"],
        id_patterns=[r"cover[_-]?letter"],
        accepts_types={FieldType.FILE},
        resolver=lambda p, c: p.cover_letter_local_path,
        confidence=0.95,
        requires_review=True,   # LLM-generated cover letters always get human eyes
    ),

    # ─ Salary (ALWAYS REVIEW) ───────────────────────────────────
    FieldRule(
        id="salary_expectation",
        label_patterns=[
            r"salary\s*expectation",
            r"expected\s*(salary|compensation)",
            r"desired\s*(salary|compensation|pay)",
            r"compensation\s*expectation",
        ],
        name_patterns=[r"salary", r"compensation", r"expected[_-]?pay"],
        id_patterns=[r"salary", r"compensation"],
        accepts_types={FieldType.TEXT, FieldType.NUMBER},
        resolver=lambda p, c: str(p.salary_expectation_usd) if p.salary_expectation_usd else None,
        confidence=0.88,
        requires_review=True,
    ),

    # ─ Misc ──────────────────────────────────────────────────────
    FieldRule(
        id="relocate",
        label_patterns=[r"willing\s*to\s*relocate", r"open\s*to\s*relocation"],
        name_patterns=[r"relocate", r"relocation"],
        id_patterns=[r"relocate"],
        accepts_types={FieldType.SELECT, FieldType.RADIO},
        resolver=lambda p, c: ("Yes" if p.willing_to_relocate else "No") if p.willing_to_relocate is not None else None,
        confidence=0.88,
    ),
    FieldRule(
        id="earliest_start",
        label_patterns=[r"earliest\s*start", r"start\s*date", r"when\s*can\s*you\s*start"],
        name_patterns=[r"start[_-]?date", r"earliest[_-]?start"],
        id_patterns=[r"start[_-]?date"],
        accepts_types={FieldType.DATE, FieldType.TEXT},
        resolver=lambda p, c: p.earliest_start_date,
        confidence=0.85,
    ),

    # ─ EEO (OPTIONAL; user profile drives whether to answer) ────
    FieldRule(
        id="gender",
        label_patterns=[r"\bgender\b"],
        name_patterns=[r"gender"],
        id_patterns=[r"gender"],
        accepts_types={FieldType.SELECT, FieldType.RADIO},
        resolver=lambda p, c: p.gender,
        confidence=0.85,
    ),
    FieldRule(
        id="race_ethnicity",
        label_patterns=[r"race", r"ethnicity", r"hispanic\s*or\s*latino"],
        name_patterns=[r"race", r"ethnicity"],
        id_patterns=[r"race", r"ethnicity"],
        accepts_types={FieldType.SELECT, FieldType.RADIO, FieldType.CHECKBOX},
        resolver=lambda p, c: p.race_ethnicity,
        confidence=0.85,
    ),
    FieldRule(
        id="veteran_status",
        label_patterns=[r"veteran\s*status", r"protected\s*veteran"],
        name_patterns=[r"veteran"],
        id_patterns=[r"veteran"],
        accepts_types={FieldType.SELECT, FieldType.RADIO},
        resolver=lambda p, c: p.veteran_status,
        confidence=0.88,
    ),
    FieldRule(
        id="disability_status",
        label_patterns=[r"disability\s*status", r"do\s*you\s*have\s*a\s*disability"],
        name_patterns=[r"disability"],
        id_patterns=[r"disability"],
        accepts_types={FieldType.SELECT, FieldType.RADIO},
        resolver=lambda p, c: p.disability_status,
        confidence=0.88,
    ),
]


def best_rule_match(cand: FieldCandidate) -> tuple[Optional[FieldRule], float]:
    """Return highest-confidence rule for this candidate, or (None, 0.0)."""
    best_rule: Optional[FieldRule] = None
    best_score = 0.0
    for rule in RULES:
        score = rule.match(cand)
        if score > best_score:
            best_score = score
            best_rule = rule
    return best_rule, best_score
