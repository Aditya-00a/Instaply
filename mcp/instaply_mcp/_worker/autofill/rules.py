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
    # Static review flag. Use this for rules that ALWAYS need human eyes
    # regardless of the user's profile (salary, cover letter, etc.).
    requires_review: bool = False
    # Dynamic review resolver — receives the profile and returns True if
    # this specific user's answer should still be reviewed even though the
    # rule type is generally safe. Lets us auto-answer "are you authorized
    # to work?" for a US citizen but still escalate for an F-1 OPT holder
    # whose status could be misread by the employer. If both flags evaluate
    # truthy, the field is escalated. None / unset means "use static flag".
    requires_review_resolver: Optional[Callable[[UserProfile], bool]] = None

    def review_for(self, profile: UserProfile) -> bool:
        """Effective `requires_review` for this profile (static OR dynamic)."""
        if self.requires_review:
            return True
        if self.requires_review_resolver is not None:
            try:
                return bool(self.requires_review_resolver(profile))
            except Exception:
                # Fail-safe: any resolver crash defaults to review.
                return True
        return False

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


def _pronouns_resolver(p: UserProfile, cand: FieldCandidate) -> Optional[str]:
    """Auto-fill pronouns. NEVER infers from p.gender.

    Returns None when p.pronouns is unset → engine escalates to
    needs_review. Returns a value only when the user has explicitly
    chosen pronouns in their profile.

    Two layouts:
      - Single field (text/select/radio "What are your pronouns?"):
        return p.pronouns (or the matching option text).
      - Multi-checkbox (each option is its own field with label
        "She/her", "He/him", etc.): return "Yes" only when the option
        label is a substring of p.pronouns; "No" otherwise.
    """
    if not p.pronouns:
        return None
    user_p = p.pronouns.lower().strip()

    # Multi-checkbox layout — each candidate is one option to tick.
    if cand.field_type == FieldType.CHECKBOX:
        label = (cand.label or cand.aria_label or "").lower().strip()
        if not label:
            return None
        # Substring match handles "He/him" matching user "he/him/his",
        # while keeping "She/her" out of "he/him/his". Conservative.
        return "Yes" if label in user_p else "No"

    # SELECT/RADIO with explicit options — pick the matching option.
    if cand.options:
        for opt in cand.options:
            o = opt.lower().strip()
            if o == user_p or o in user_p or user_p in o:
                return opt
        # No option matched the user's pronouns → don't guess.
        return None

    # Plain TEXT field — write the user's pronouns string directly.
    return p.pronouns


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
        # Auto-answer when the user's status is unambiguously authorized
        # (US citizen, green card). Escalate for visa-dependent statuses
        # (F-1 OPT, H-1B, etc.) where the right "yes/no" depends on the
        # employer's actual question framing — a wrong yes can be an
        # instant reject. Empty profile also escalates.
        requires_review_resolver=lambda p: (p.work_auth_status not in ("us_citizen", "green_card")),
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
        # Auto-answer when the user has explicitly set needs_sponsorship
        # to True or False in onboarding. Escalate when the field is
        # blank/None — defaulting to "No" for an OPT applicant who left
        # it blank could mis-represent them and burn the application.
        requires_review_resolver=lambda p: (p.needs_sponsorship is None),
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

    # ─ Pronouns ─────────────────────────────────────────────────
    # Distinct from gender — NEVER inferred from p.gender. Only
    # auto-fills when p.pronouns is explicitly set; otherwise the
    # resolver returns None and the engine escalates to needs_review.
    #
    # Two layouts the rule handles:
    #   1. Single field "What are your pronouns?" (text/select/radio)
    #      → return p.pronouns directly (or the matching option).
    #   2. Multi-checkbox (Lever-style) where each pronoun option is
    #      its own checkbox candidate (label = "She/her", "He/him",
    #      "They/them", etc.) → return "Yes" only when the option
    #      label is a substring of p.pronouns; "No" for all others.
    FieldRule(
        id="pronouns",
        label_patterns=[
            r"\bpronoun",                                     # "Pronouns", "What are your pronouns?"
            r"^\s*(she|he|they|xe|ze|fae|per|ey)\s*/\s*"     # option labels: She/her, He/him, etc.
            r"(her|him|them|xem|hir|faer|per|em|hers|his|theirs)\b",
        ],
        name_patterns=[r"pronoun"],
        id_patterns=[r"pronoun"],
        accepts_types={FieldType.TEXT, FieldType.SELECT, FieldType.RADIO, FieldType.CHECKBOX},
        resolver=_pronouns_resolver,
        # Confidence bumped 0.90 → 0.95 so id-only matches (e.g. Lever's
        # `id="customPronounsOption"` checkbox, which has no <label> tag
        # the parser can find — only the literal value text "Custom")
        # clear `min_rule_confidence=0.80`. Previous score was
        # 0.90 * 0.88 = 0.792 → fell to LLM, which hallucinated a
        # paragraph ("Aditya Sakhale is a 3-year experienced male
        # candidate from New York, US.") into the field. New score is
        # 0.95 * 0.88 = 0.836 → resolver fires and the checkbox gets
        # the deterministic "No" answer (since the user did not pick
        # "Custom" pronouns). Anything matching /pronoun/ in id/name/
        # label is unambiguously a pronouns field, so 0.95 is justified.
        confidence=0.95,
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

    # ─ Common low-risk yes/no defaults (safe to auto-answer) ────
    # "Are you at least 18 years of age?" — an applicant who isn't
    # legally can't be hired in the US anyway, so the only sane answer
    # is Yes. Auto-answers without review.
    FieldRule(
        id="age_18_or_older",
        label_patterns=[
            r"(at\s*least|are\s*you)\s*(18|eighteen)\s*(years|or\s*older)",
            r"\b18\s*years\s*(of\s*age)?\s*(or\s*older|or\s*above)?",
            r"minimum\s*age",
            r"age\s*requirement",
        ],
        name_patterns=[r"age[_-]?18", r"minimum[_-]?age", r"of[_-]?age"],
        id_patterns=[r"age[_-]?18", r"minimum[_-]?age"],
        accepts_types={FieldType.SELECT, FieldType.RADIO, FieldType.CHECKBOX},
        resolver=lambda p, c: "Yes",
        confidence=0.85,
    ),

    # ─ Low-risk relationship/history defaults (auto-No, no review) ──
    # Per the 2026-04-18 candidate-favorable-defaults spec: factual
    # questions about a prior relationship, account status, or referral
    # default to "No" silently when we have no profile evidence of
    # "Yes". This covers the common ATS questions that block submit but
    # are almost always No for a first-time applicant.
    #
    # SAFETY ENVELOPE (do NOT extend without explicit review):
    #   Allowed: prior employment, current account/customer/client/
    #     member status, employee-referral existence, "are you a
    #     current employee" of this company.
    #   FORBIDDEN: legal/work-auth/sponsorship/disclosure/criminal/
    #     disability/veteran/salary. Those have their own rules
    #     (work_authorization, sponsorship, age_18_or_older, etc.) and
    #     MUST stay separate. Adding a pattern here that matches one of
    #     those would mis-represent the candidate in a regulated way.
    #
    # Each rule below is narrow: tight label/name/id patterns, RADIO
    # or SELECT only (never CHECKBOX — checkbox layouts repeat the
    # option text per checkbox and would be ambiguous), confidence high
    # enough to clear the 0.80 floor on label OR name match, and
    # requires_review left unset (auto-answer without holding the form).
    #
    # If we ever add a `prior_employers` or `referred_by` field to the
    # profile, swap each lambda's resolver for explicit-evidence lookup
    # (Yes if the company matches a known prior employer, etc.).
    FieldRule(
        id="previously_employed_here",
        label_patterns=[
            r"previously.{0,40}\b(work|employ)",       # "previously been employed", "previously worked"
            r"ever.{0,40}\b(work|employ)",             # "ever worked at"
            r"former\s*employee",
            r"prior\s*employment",
        ],
        name_patterns=[r"prior[_-]?employ", r"previous[_-]?employ", r"former[_-]?employ"],
        id_patterns=[r"prior[_-]?employ", r"previous[_-]?employ"],
        accepts_types={FieldType.SELECT, FieldType.RADIO},
        resolver=lambda p, c: "No",
        confidence=0.85,
    ),
    # "Are you currently a [company] client / customer / user / member /
    # subscriber / account holder?" — first-time applicants are almost
    # never existing customers of the employer. Auto-No avoids stalling
    # the form. If a user IS a customer they can correct it once and
    # the answer-vault remembers. Confidence high so we beat the LLM.
    #
    # Patterns allow an optional brand/qualifier word between "a/an"
    # and the noun ("a Wealthfront client", "a current customer", "an
    # active member"). The `\w+` allowance is intentionally narrow —
    # one bare word, no whitespace gymnastics — so we don't accidentally
    # match unrelated long sentences.
    FieldRule(
        id="current_customer_or_client_no",
        label_patterns=[
            r"(are\s*you|do\s*you)\b.{0,40}\b"
            r"(client|customer|user|member|subscriber|account\s*holder)\b",
            r"(have|do\s*you\s*have)\b.{0,40}\b"
            r"(account|membership|subscription)\b.{0,30}\b(with|at)\s+(us|our|this)\b",
        ],
        name_patterns=[
            r"(current[_-]?)?(client|customer|member|subscriber|account[_-]?holder)",
        ],
        id_patterns=[
            r"(current[_-]?)?(client|customer|member|subscriber)",
        ],
        accepts_types={FieldType.SELECT, FieldType.RADIO},
        resolver=lambda p, c: "No",
        confidence=0.85,
    ),
    # "Were you referred by an employee / current employee?" — auto-No
    # unless we have explicit referral evidence (we don't track this
    # in the profile yet). A wrong "Yes" here makes the recruiter chase
    # a non-existent referrer; a wrong "No" loses a potential bonus
    # but does not misrepresent the candidate.
    FieldRule(
        id="referred_by_employee_no",
        label_patterns=[
            r"(were|are)\s*you\s*referred\s*by",
            r"(employee\s*)?referral\s*\??$",
            r"(do\s*you\s*have\s*|is\s*there\s*)(an?\s*)?employee\s*referral",
            r"referred\s*by\s*(an?\s*|a\s*current\s*)?employee",
        ],
        name_patterns=[
            r"^referral$", r"^referred[_-]?by$", r"employee[_-]?referral",
            r"is[_-]?referral", r"has[_-]?referral",
        ],
        id_patterns=[
            r"^referral$", r"employee[_-]?referral", r"is[_-]?referred",
        ],
        accepts_types={FieldType.SELECT, FieldType.RADIO},
        resolver=lambda p, c: "No",
        confidence=0.85,
    ),
    # "Are you a current employee here?" — distinct from
    # previously_employed_here above; covers the present-tense phrasing
    # ATSes sometimes ask separately. Same auto-No rationale.
    FieldRule(
        id="current_employee_here_no",
        label_patterns=[
            r"(are\s*you|currently)\s*(a\s*|an\s*)?current\s*employee",
            r"are\s*you\s*currently\s*(work|employ).*(here|with\s*us|at\s*(us|this))",
        ],
        name_patterns=[r"current[_-]?employee", r"is[_-]?current[_-]?employee"],
        id_patterns=[r"current[_-]?employee"],
        accepts_types={FieldType.SELECT, FieldType.RADIO},
        resolver=lambda p, c: "No",
        confidence=0.85,
    ),

    # "Are you legally authorized to work in the United States?" — narrow
    # variant of the broader work_auth rule that handles the country-
    # specific phrasing many ATSes use. Reuses the same resolver.
    FieldRule(
        id="work_auth_country_specific",
        label_patterns=[
            r"authorized\s*to\s*work\s*in\s*the\s*(united\s*states|us|u\.?s\.?a)",
            r"eligible\s*to\s*work\s*in\s*the\s*(united\s*states|us|u\.?s\.?a)",
        ],
        name_patterns=[r"work[_-]?auth[_-]?us", r"us[_-]?work[_-]?auth"],
        id_patterns=[r"work[_-]?auth[_-]?us", r"us[_-]?work[_-]?auth"],
        accepts_types={FieldType.SELECT, FieldType.RADIO},
        resolver=_work_auth_yesno,
        confidence=0.92,
        requires_review_resolver=lambda p: (p.work_auth_status not in ("us_citizen", "green_card")),
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
