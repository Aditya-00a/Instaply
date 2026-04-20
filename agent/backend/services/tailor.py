from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import html
import re
from typing import Any

import httpx

from backend.services.config import settings
from backend.services.jd_parser import parse_job_description
from backend.services.matcher import extract_keywords, infer_role_bucket
from backend.services.resume_guardrails import (
    apply_one_page_limits,
    build_guardrail_report,
    canonicalize_master_resume,
    make_ats_notes,
)
from backend.services.resume_rules import resolve_rule_set


STRONG_ACTION_VERBS = {
    "led", "built", "delivered", "drove", "spearheaded", "architected", "optimized",
    "engineered", "designed", "launched", "scaled", "orchestrated", "negotiated",
    "transformed", "accelerated", "developed", "implemented", "created", "managed",
    "established", "authored", "integrated", "automated", "deployed", "founded",
    "directed", "streamlined", "pioneered", "executed", "analyzed",
}

WEAK_VERB_STARTS = {
    "helped", "assisted", "worked on", "was responsible", "participated",
    "was involved", "handled", "supported", "contributed to",
}

_OUTCOME_PATTERNS = re.compile(
    r"\b(?:resulting in|achieving|which led to|driving|leading to|enabling|improving|reducing|increasing|generating|delivering|producing)\b",
    re.IGNORECASE,
)

_METRIC_PATTERN = re.compile(
    r"(?:\$[\d,.]+[KMB]?|\d+[\d,.]*\s*%|\d+[\d,.]*\+?\s*(?:users|clients|students|instructors|programs|assets|members|engagements)|\d+[\d,.]*\s*(?:AUC|ROC|F1)|0\.\d+\s*(?:AUC|ROC|F1))",
    re.IGNORECASE,
)


def _score_text(text: str, keywords: list[str], tags: list[str] | None = None) -> int:
    score = 0
    lower = text.lower()

    # JD keyword density: +2 per unique keyword match
    matched_keywords: set[str] = set()
    for keyword in keywords:
        if keyword.lower() in lower:
            matched_keywords.add(keyword.lower())
    score += len(matched_keywords) * 2

    # Bonus for high keyword density (3+ matches)
    if len(matched_keywords) >= 3:
        score += 3

    # Tag relevance to role: +3 per matching tag
    for tag in tags or []:
        if any(keyword.lower() in tag.lower() for keyword in keywords):
            score += 3

    # Metric/number presence: +5 for any digit, +3 more for formatted metrics
    if any(char.isdigit() for char in text):
        score += 5
    if _METRIC_PATTERN.search(text):
        score += 3

    # Action verb strength: +3 for strong opener, -2 for weak opener
    first_word = lower.split()[0] if lower.split() else ""
    if first_word in STRONG_ACTION_VERBS:
        score += 3
    if any(lower.startswith(weak) for weak in WEAK_VERB_STARTS):
        score -= 2

    # Outcome statement: +4 if bullet describes a result
    if _OUTCOME_PATTERNS.search(text):
        score += 4

    return score


def _rewrite_bullet_for_impact(bullet_text: str, jd_keywords: list[str], role_bucket: str) -> str:
    """Deterministic string transformation to make a bullet more impactful.

    Rules applied in order:
    1. Replace weak opening verbs with strong action verbs
    2. Front-load metrics if they appear later in the bullet
    3. Add scale/scope context words based on role bucket
    """
    if not bullet_text or not bullet_text.strip():
        return bullet_text

    text = bullet_text.strip()

    # Step 1: Replace weak opening verbs with strong alternatives
    weak_to_strong = [
        (r"^Helped\s+(build|develop|create)", r"Architected"),
        (r"^Helped\s+(with|on)\s+", r"Drove "),
        (r"^Worked\s+on\s+", r"Engineered "),
        (r"^Was\s+responsible\s+for\s+", r"Led "),
        (r"^Assisted\s+(with|in)\s+", r"Drove "),
        (r"^Participated\s+in\s+", r"Spearheaded "),
        (r"^Was\s+involved\s+in\s+", r"Drove "),
        (r"^Handled\s+", r"Managed "),
        (r"^Used\s+", r"Leveraged "),
        (r"^Created\s+", r"Designed "),
        (r"^Made\s+", r"Developed "),
        (r"^Did\s+", r"Executed "),
        (r"^Wrote\s+", r"Authored "),
        (r"^Built\s+", r"Architected "),
        (r"^Ran\s+", r"Orchestrated "),
        (r"^Set\s+up\s+", r"Launched "),
        (r"^Improved\s+", r"Optimized "),
        (r"^Reduced\s+", r"Streamlined "),
    ]
    for pattern, replacement in weak_to_strong:
        new_text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        if new_text != text:
            text = _capitalize_first_alpha(new_text)
            break

    # Step 2: Front-load metrics — ONLY for truly impressive standalone numbers
    # (e.g. $10M+, 50%+, 1M+ users).  Small/mid metrics like $2M or 15% look
    # awkward when ripped out of context and prepended with an em-dash.
    if not re.match(r"^[\d$]", text):
        words = text.split()
        if len(words) > 6:
            later_text = " ".join(words[4:])
            metric_match = _METRIC_PATTERN.search(later_text)
            if metric_match:
                metric = metric_match.group(0)
                # Only front-load large dollar amounts (>=$10M) or large percentages (>=40%)
                _large_dollar = re.search(r"\$[\d,.]*(\d{2,})[KMB]", metric)
                _large_pct = re.search(r"(\d+)\s*%", metric)
                is_large = False
                if _large_dollar:
                    is_large = True  # $10K+ denominated numbers
                elif _large_pct:
                    is_large = int(_large_pct.group(1)) >= 40
                if is_large:
                    cleaned = text.replace(metric, "").replace("  ", " ").strip()
                    cleaned = re.sub(r"\s*,\s*,", ",", cleaned)
                    cleaned = re.sub(r"\(\s*\)", "", cleaned).strip()
                    if cleaned:
                        text = f"{metric} — {cleaned}"

    # Step 3: Add role-bucket-appropriate context intensifiers
    lower = text.lower()
    bucket_context = {
        "consulting": [
            (r"\bclient\b(?!\s+(?:facing|requirements|engagement))", "client engagement"),
            (r"\bpresentation\b(?!s)", "executive presentation"),
        ],
        "technical": [
            (r"\bsystem\b(?!\s+(?:tracking|monitoring|architecture))", "production system"),
        ],
        "operator_startup": [
            (r"\bteam\b(?!\s+(?:of|across|management))", "cross-functional team"),
        ],
    }
    for pattern, replacement in bucket_context.get(role_bucket, []):
        if replacement.lower() not in lower:
            text = re.sub(pattern, replacement, text, count=1, flags=re.IGNORECASE)

    # Step 4: Ensure the bullet ends with a period
    text = text.rstrip()
    if text and text[-1] not in ".!?":
        text += "."

    return text


def _project_summary(project: dict[str, Any]) -> str:
    return project.get("summary", project.get("description", ""))


MONTH_LOOKUP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _clean_sentence(text: str) -> str:
    cleaned = html.unescape(str(text or "").strip())
    cleaned = cleaned.replace("â€“", "–").replace("â€”", "—").replace("â€™", "'").replace("â€œ", '"').replace("â€", '"')
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(
        r"\b(?:quot|amp|nbsp|lt|gt|span|div|class|aria|labelledby|describedby|href|src)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _strip_recruiting_partner_mentions(text: str) -> str:
    cleaned = _clean_sentence(text)
    patterns = [
        r"\bboards?\.greenhouse\.io\b",
        r"\bjobs?\.lever\.co\b",
        r"\bmyworkdayjobs\b",
        r"\bgreenhouse\b",
        r"\blever\b",
        r"\bworkday\b",
        r"\bjob[- ]boards?\b",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bjobs?\.\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"([,.;:]){2,}", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _limit_words(text: str, max_words: int) -> str:
    words = _clean_sentence(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",;:") + "..."


def _pretty_term(term: str) -> str:
    lower = term.lower().strip()
    mapping = {
        "ai": "AI",
        "apis": "APIs",
        "ml": "ML",
        "llm": "LLM",
        "sql": "SQL",
        "nlp": "NLP",
        "rag": "RAG",
        "api": "API",
    }
    return mapping.get(lower, term)


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            ordered.append(item)
    return ordered


def _score_project(project: dict[str, Any], keywords: list[str], favored_names: set[str]) -> int:
    score = _score_text(
        f"{project.get('name', '')} {_project_summary(project)}",
        keywords,
        project.get("tags", []),
    )
    if project.get("name", "") in favored_names:
        score += 8
    return score


def _score_skill(skill: str, keywords: list[str]) -> int:
    return _score_text(skill, keywords)


def _lookup_preference_score(name: str, boosts: dict[str, Any] | None) -> int:
    if not boosts:
        return 0
    direct = boosts.get(name)
    if direct is not None:
        return int(direct)
    lowered = name.lower().strip()
    for key, value in boosts.items():
        if str(key).lower().strip() == lowered:
            return int(value)
    return 0


def _merge_preference_boosts(defaults: dict[str, Any] | None, overrides: dict[str, Any] | None) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for source in [defaults or {}, overrides or {}]:
        for key, value in source.items():
            merged[str(key)] = int(value)
    return merged or None


def _default_experience_preferences(*, higher_education_role: bool) -> dict[str, int]:
    # TODO(post-lift): pull from profile.experience_preferences. The
    # original Revize source had the author's specific company boosts
    # (specific company boost weights) hardcoded here. Empty default so
    # nothing is unfairly boosted or penalised for the next user.
    return {}


def _parse_end_date(value: str) -> tuple[int, int]:
    text = _clean_sentence(value).lower()
    if not text:
        return (0, 0)
    parts = [part.strip() for part in re.split(r"\s*-\s*|–|—", text) if part.strip()]
    end_part = parts[-1] if parts else text
    if "present" in end_part or "current" in end_part:
        now = datetime.now()
        return (now.year, now.month)

    year_match = re.search(r"(20\d{2}|19\d{2})", end_part)
    year = int(year_match.group(1)) if year_match else 0
    month = 12 if year else 0
    for token, month_num in MONTH_LOOKUP.items():
        if token in end_part:
            month = month_num
            break
    return (year, month)


def _sort_items_newest_first(items: list[dict[str, Any]], date_key: str = "dates") -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: _parse_end_date(str(item.get(date_key, ""))), reverse=True)


def _top_matching_terms(text: str, keywords: list[str], limit: int = 3) -> list[str]:
    lower = text.lower()
    matches = [keyword for keyword in keywords if keyword.lower() in lower]
    return _dedupe_preserve(matches)[:limit]


def _all_resume_skills(skills: dict[str, list[str]] | list[str]) -> list[str]:
    if isinstance(skills, dict):
        flattened: list[str] = []
        for items in skills.values():
            flattened.extend(str(item).strip() for item in items if str(item).strip())
        return flattened
    return [str(item).strip() for item in skills if str(item).strip()]


def _supported_jd_skill_terms(keywords: list[str], skills: dict[str, list[str]] | list[str]) -> list[str]:
    supported = _all_resume_skills(skills)
    aliases = {
        "api": ["API", "APIs"],
        "apis": ["API", "APIs"],
        "python": ["Python"],
        "sql": ["SQL"],
        "pyspark": ["PySpark"],
        "hive": ["Hive"],
        "docker": ["Docker"],
        "kubernetes": ["Kubernetes"],
        "aws": ["AWS"],
        "fastapi": ["FastAPI"],
        "node": ["Node.js"],
        "rag": ["RAG Systems"],
        "llm": ["LLMs (Llama, GPT-4, Claude)"],
        "llms": ["LLMs (Llama, GPT-4, Claude)"],
        "prompt engineering": ["Prompt Engineering"],
        "fine-tuning": ["Fine-Tuning"],
        "tensorflow": ["TensorFlow"],
        "pytorch": ["PyTorch"],
        "anomaly detection": ["Anomaly Detection"],
        "etl": ["ETL Pipelines"],
        "microservices": ["Microservices Architecture"],
        "stakeholder management": ["Stakeholder Management"],
        "product analytics": ["Product Analytics"],
        "databricks": ["Databricks"],
        "supabase": ["Supabase"],
        "vercel": ["Vercel"],
    }
    matches: list[str] = []
    supported_lower = {item.lower(): item for item in supported}
    for keyword in keywords:
        lower = keyword.lower().strip()
        if not lower:
            continue
        direct = supported_lower.get(lower)
        if direct:
            matches.append(direct)
            continue
        for alias in aliases.get(lower, []):
            if alias.lower() in supported_lower:
                matches.append(supported_lower[alias.lower()])
    return _dedupe_preserve(matches)


def _company_context_line(company_context: dict[str, Any], company_background: str) -> str:
    values = [
        company_context.get("company", ""),
        company_context.get("role", ""),
        company_context.get("product_or_initiative", ""),
        _strip_recruiting_partner_mentions(company_background),
    ]
    return " ".join(str(value).strip() for value in values if str(value).strip())


def _capitalize_first_alpha(text: str) -> str:
    value = str(text or "").strip()
    for index, char in enumerate(value):
        if char.isalpha():
            return value[:index] + char.upper() + value[index + 1 :]
    return value


def _anonymize_client_mentions(text: str) -> str:
    cleaned = _clean_sentence(text)
    # Replace named clients with generic descriptors when the user has not
    # explicitly opted to name-drop them. TODO(post-lift): make the allow
    # list profile-driven (was hardcoded to keep JPMorgan Chase visible).
    replacements = [
        (r"\bJPMorgan Chase\b|\bJPMC\b", "a major financial institution"),
        (r"\bMorgan Stanley\b", "a major financial institution"),
        (r"\bGoldman Sachs\b", "a major financial institution"),
        (r"\bBank of America\b", "a major financial institution"),
        (r"\bCitibank\b|\bCiti\b", "a major financial institution"),
    ]
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return cleaned


def _clean_company_name(value: str) -> str:
    cleaned = _strip_recruiting_partner_mentions(value)
    cleaned = re.sub(r"\b(?:inc|llc|ltd|corp|corporation)\.?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return _capitalize_first_alpha(cleaned or _clean_sentence(value))


def _extract_company_research_summary(jd_text: str, company_background: str, company_context: dict[str, Any]) -> str:
    source_text = " ".join(
        part for part in [
            _strip_recruiting_partner_mentions(company_background),
            _strip_recruiting_partner_mentions(jd_text),
            _clean_sentence(company_context.get("team", "")),
            _clean_sentence(company_context.get("department", "")),
            _clean_sentence(company_context.get("product_or_initiative", "")),
        ] if part
    )
    cleaned = _clean_sentence(source_text)
    if not cleaned:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    keepers: list[str] = []
    for sentence in sentences:
        lower = sentence.lower()
        if re.search(r"\b(?:quot|amp|nbsp|span|div|class|aria)\b", lower):
            continue
        if " opportunity for " in lower or lower.startswith("location:"):
            continue
        if any(
            token in lower
            for token in [
                "mission",
                "product",
                "platform",
                "customers",
                "teams",
                "build",
                "deliver",
                "ai",
                "analytics",
                "workflow",
                "operations",
                "infrastructure",
                "planning",
                "roadmap",
            ]
        ):
            cleaned_sentence = re.sub(r"^about\s+[A-Za-z0-9_.&-]+\s*", "", sentence.strip(), flags=re.IGNORECASE)
            keepers.append(_anonymize_client_mentions(cleaned_sentence))
        if len(keepers) >= 3:
            break

    summary = " ".join(keepers[:2]) if keepers else cleaned
    summary = _strip_recruiting_partner_mentions(summary)
    summary_sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", summary)
        if part.strip() and len(part.strip().split()) >= 5
    ]
    summary = " ".join(summary_sentences[:2]) if summary_sentences else summary
    summary = summary.strip()
    if re.match(r"^We want AI to be safe and beneficial", summary, flags=re.IGNORECASE):
        company = _clean_company_name(company_context.get("company", "the company"))
        return f"{company} is focused on building AI systems that are safe, reliable, and useful in practice."
    summary = re.sub(r"\bOur\.$", "", summary, flags=re.IGNORECASE).strip()
    return summary


def _quality_guard_cover_letter(text: str) -> bool:
    raw = str(text or "").strip()
    cleaned = _clean_sentence(raw)
    if len(cleaned.split()) < 120:
        return False
    if raw.count("\n\n") < 2:
        return False
    bad_phrases = [
        "the work your team is building",
        "i am excited to apply",
        "i'm excited to apply",
        "greenhouse recruiting team",
        "lever hiring team",
        "workday hiring team",
        "at [previous-employer],",
        "the user's work",
    ]
    lower = cleaned.lower()
    return not any(phrase in lower for phrase in bad_phrases)


def _cover_letter_theme_terms(jd_text: str, company_context: dict[str, Any]) -> str:
    generic = {
        "team",
        "teams",
        "end",
        "work",
        "role",
        "company",
        "position",
        "build",
        "building",
        "strong",
        "experience",
        "customer",
        "customers",
        "technical",
        "consultant",
        "help",
        "quot",
        "amp",
        "nbsp",
        "span",
        "div",
        "class",
        "aria",
    }
    jd_lower = jd_text.lower()
    preferred_phrases: list[str] = []
    for phrase in [
        "professional services",
        "enterprise implementations",
        "apis",
        "integrations",
        "generative ai",
        "agentic ai",
        "customer-facing communication",
        "technical documentation",
    ]:
        if phrase in jd_lower:
            preferred_phrases.append(phrase)
    preferred = []
    for term in extract_keywords(jd_text, limit=16):
        cleaned = _clean_sentence(term).lower()
        if not cleaned or cleaned in generic or len(cleaned) < 3:
            continue
        if cleaned not in preferred:
            preferred.append(cleaned)
    context_terms = [
        _clean_sentence(company_context.get("team", "")),
        _clean_sentence(company_context.get("department", "")),
        _clean_sentence(company_context.get("product_or_initiative", "")),
    ]
    merged = preferred_phrases + [term for term in context_terms if term] + preferred
    merged = _dedupe_preserve([term for term in merged if term])
    return ", ".join(_pretty_term(term) for term in merged[:4]) or "technical execution and customer-facing delivery"


def _sync_llm_generate(prompt: str, system: str | None = None) -> str:
    provider = str(settings.llm_provider or "ollama").strip().lower()
    if provider == "openai":
        if not settings.openai_api_key:
            return ""
        input_items: list[dict[str, Any]] = []
        if system:
            input_items.append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system}],
                }
            )
        input_items.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        )
        payload = {
            "model": settings.model_name,
            "input": input_items,
            "store": False,
        }
        with httpx.Client(timeout=90.0) as client:
            response = client.post(
                f"{settings.openai_base_url.rstrip('/')}/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            if str(data.get("output_text", "")).strip():
                return str(data.get("output_text", "")).strip()
            output = data.get("output", [])
            text_parts: list[str] = []
            if isinstance(output, list):
                for item in output:
                    if not isinstance(item, dict) or item.get("type") != "message":
                        continue
                    for content in item.get("content", []):
                        if isinstance(content, dict) and content.get("type") == "output_text":
                            text = str(content.get("text", "")).strip()
                            if text:
                                text_parts.append(text)
            return "\n".join(text_parts).strip()

    payload: dict[str, Any] = {
        "model": settings.model_name,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    with httpx.Client(timeout=90.0) as client:
        response = client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
        response.raise_for_status()
        return str(response.json().get("response", "")).strip()


def _cover_letter_fact_lines(experiences: list[dict[str, Any]], projects: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for exp in experiences[:3]:
        company = _capitalize_first_alpha(_clean_sentence(exp.get("company", "")))
        title = _clean_sentence(exp.get("title", ""))
        dates = _clean_sentence(exp.get("dates", ""))
        bullets = []
        for bullet in exp.get("bullets", [])[:3]:
            text = bullet.get("text", "") if isinstance(bullet, dict) else bullet
            text = _anonymize_client_mentions(_clean_sentence(text))
            if text:
                bullets.append(text)
        if company or title:
            lines.append(f"Experience: {title} at {company} ({dates})")
        for bullet in bullets:
            lines.append(f"- {bullet}")
    for project in projects[:2]:
        name = _clean_sentence(project.get("name", ""))
        summary = _anonymize_client_mentions(_clean_sentence(project.get("summary", project.get("description", ""))))
        if name or summary:
            lines.append(f"Project: {name} — {summary}")
    return lines


def _normalize_clause_start(text: str) -> str:
    clause = str(text or "").strip()
    if not clause:
        return clause
    replacements = {
        "identified": "identifying",
        "qualified": "qualifying",
        "converted": "converting",
        "made": "making",
        "led": "leading",
        "delivered": "delivering",
        "built": "building",
        "tracked": "tracking",
        "optimized": "optimizing",
        "created": "creating",
        "collaborated": "collaborating",
        "partnered": "partnering",
        "developed": "developing",
    }
    lower = clause.lower()
    for key, value in replacements.items():
        if lower.startswith(key + " "):
            return value + clause[len(key):]
    return clause[0].lower() + clause[1:] if len(clause) > 1 else clause.lower()


def _lowercase_leading_verb(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return value
    verbs = [
        "Built",
        "Analyzed",
        "Designed",
        "Developed",
        "Created",
        "Tracked",
        "Integrated",
        "Implemented",
        "Delivered",
        "Led",
        "Managed",
        "Authored",
        "Optimized",
    ]
    for verb in verbs:
        if value.startswith(verb + " "):
            return verb.lower() + value[len(verb):]
    return value


def _render_cover_letter_with_llm(
    *,
    company: str,
    role: str,
    product: str,
    company_research_summary: str,
    tone: str,
    intro_terms: str,
    summary_variant: str,
    experiences: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    jd_text: str,
    length_mode: str,
) -> str:
    word_target = {"short": "190-240", "default": "250-340", "long": "300-380"}.get(length_mode, "250-340")
    fact_block = "\n".join(_cover_letter_fact_lines(experiences, projects))
    clean_jd_excerpt = _strip_recruiting_partner_mentions(jd_text)
    prompt = (
        f"Write a cover letter for [user] applying to {company} for the role {role}.\n\n"
        "Requirements:\n"
        "- 4 short paragraphs.\n"
        f"- Total length: {word_target} words.\n"
        "- Make it sound human, sharp, and confident.\n"
        "- Give it personality: warm, intellectually curious, and specific, not stiff.\n"
        "- Do not include any greeting, date block, or sign-off. The renderer handles that.\n"
        "- Do not use generic openings like 'I am writing to express my interest', 'I am excited to apply', or 'I’m excited about the opportunity'.\n"
        "- Write in first person only. Use 'I', 'my', and 'I've'. Never refer to the candidate in third person.\n"
        "- Ground everything in the factual experience below.\n"
        "- Do not invent companies, titles, metrics, dates, projects, technologies, or outcomes.\n"
        "- IMPORTANT: Naturally incorporate key terms from the job description (tools, technologies, domain terms) into the letter where they genuinely apply to your experience. This helps with ATS keyword matching.\n"
        "- Use concrete company/role fit and actual evidence.\n"
        "- Mention why this company/role is compelling in a way that feels tailored, not copied from the JD.\n"
        "- Add one grounded personal point of view about why this kind of work fits how I operate, based on my actual background.\n"
        "- Avoid raw company-background fragments, scraped HTML, or website boilerplate.\n"
        "- Keep the writing clean and grammatically polished.\n\n"
        f"Target tone: {tone}\n"
        f"Company/product context: {company} | {role} | {product}\n"
        f"Company research summary: {company_research_summary}\n"
        f"Relevant themes from the JD: {intro_terms}\n"
        f"Critical JD keywords (weave naturally into the letter where truthful): {', '.join(extract_keywords(jd_text, limit=10))}\n"
        f"Profile summary: {summary_variant}\n\n"
        "Facts you may use:\n"
        f"{fact_block}\n\n"
        "Job description excerpt:\n"
        f"{clean_jd_excerpt[:3500]}\n\n"
        "Return only the cover letter body."
    )
    system = "You write elite cover letters that are specific, natural, and fact-faithful."
    try:
        text = _sync_llm_generate(prompt, system=system)
    except Exception:
        return ""
    cleaned = _clean_sentence(text)
    return text.strip() if cleaned else ""


def _polish_cover_letter_text(letter: str, *, company: str, role: str, product: str) -> str:
    lines = [line.rstrip() for line in str(letter or "").splitlines()]
    filtered: list[str] = []
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("dear ") or lowered in {"best,", "best", "sincerely,", "sincerely", "warm regards,", "warm regards"}:
            continue
        if False:  # TODO(post-lift): if stripped == first_name or stripped == possessive_first_name:
            continue
        filtered.append(line)

    text = "\n".join(filtered).strip()
    text = _strip_recruiting_partner_mentions(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\bthe user's\b", "my", text, flags=re.IGNORECASE)
    # text = re.sub(rf"\\b{first_name}\\b", "I", text, flags=re.IGNORECASE)
    text = re.sub(r"\bthe candidate's\b", "my", text, flags=re.IGNORECASE)
    text = re.sub(r"\bthe candidate\b", "I", text, flags=re.IGNORECASE)
    replacements = [
        (
            r"^(With a background in .*?, I am excited about the opportunity to join .*? as .*?\.)",
            f"What draws me to {company} is the chance to contribute to {product} in a {role} role that sits right at the intersection of technical execution and customer impact.",
        ),
        (
            r"^(I am excited about the opportunity to join .*? as .*?\.)",
            f"What draws me to {company} is the chance to contribute to {product} in a {role} role that rewards technical depth and practical execution.",
        ),
        (
            r"^(I am excited to apply for .*?\.)",
            f"What draws me to {company} is the chance to contribute in a {role} role where strong judgment, execution, and technical fluency all matter.",
        ),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, count=1, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\bGreenhouse Recruiting Team\b", f"{company} Recruiting Team", text, flags=re.IGNORECASE)
    text = re.sub(r"\bLever Hiring Team\b", f"{company} Recruiting Team", text, flags=re.IGNORECASE)
    text = re.sub(r"\bWorkday Hiring Team\b", f"{company} Recruiting Team", text, flags=re.IGNORECASE)
    text = re.sub(r"\bthe work your team is building\b", product, text, flags=re.IGNORECASE)
    if "\n\n" not in text:
        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
        if len(sentences) >= 6:
            groups = [
                " ".join(sentences[:2]),
                " ".join(sentences[2:4]),
                " ".join(sentences[4:6]),
                " ".join(sentences[6:]) if len(sentences) > 6 else "",
            ]
            text = "\n\n".join(group for group in groups if group.strip())
    return text.strip()


def _apply_experience_rules(
    experience: list[dict[str, Any]],
    keywords: list[str],
    include_companies: set[str],
    exclude_companies: set[str],
    preference_boosts: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[tuple[int, dict[str, Any]]] = []
    excluded: list[dict[str, Any]] = []

    for recency_index, exp in enumerate(experience):
        company = exp.get("company", "")
        if company in exclude_companies:
            excluded.append({"type": "experience", "name": company, "reason": "excluded_by_role_rule"})
            continue

        bullets = exp.get("bullets", [])
        # Score and sort bullets within each role: highest-impact bullets first
        scored_bullets = sorted(
            bullets,
            key=lambda b: _score_text(b.get("text", ""), keywords, b.get("tags", [])),
            reverse=True,
        )
        score = sum(_score_text(bullet.get("text", ""), keywords, bullet.get("tags", [])) for bullet in bullets)
        if include_companies and company in include_companies:
            score += 10
        score += _lookup_preference_score(company, preference_boosts)
        score += max(0, 8 - recency_index)

        exp_copy = deepcopy(exp)
        exp_copy["bullets"] = scored_bullets
        kept.append((score, exp_copy))

    kept_sorted = [item for _, item in sorted(kept, key=lambda pair: pair[0], reverse=True)]
    return kept_sorted, excluded


def _prefer_primary_over_filler(
    experience: list[dict[str, Any]],
    excluded: list[dict[str, Any]] | None = None,
    *,
    higher_education_role: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    primary_name = "PrimaryCompany"
    filler_name = "FillerCompany"
    has_primary = any(str(item.get("company", "")).strip() == primary_name for item in experience)
    if not has_primary:
        return experience, excluded or []
    kept = [item for item in experience if str(item.get("company", "")).strip() != filler_name]
    dropped = len(experience) - len(kept)
    updated_excluded = list(excluded or [])
    if dropped:
        updated_excluded.append(
            {
                "type": "experience",
                "name": filler_name,
                "reason": "replaced_by_primary_preference",
            }
        )
    return kept, updated_excluded


def _apply_project_rules(
    projects: list[dict[str, Any]],
    keywords: list[str],
    favored_names: set[str],
    preference_boosts: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scored = sorted(
        projects,
        key=lambda project: _score_project(project, keywords, favored_names) + _lookup_preference_score(project.get("name", ""), preference_boosts),
        reverse=True,
    )
    # Keep top 4 projects (was 2) — more projects shows breadth of hands-on work
    max_projects = 4
    kept = scored[:max_projects]
    excluded = [{"type": "project", "name": project.get("name", ""), "reason": "not_selected_for_one_page"} for project in scored[max_projects:]]
    return kept, excluded


def _score_publication(publication: dict[str, Any], keywords: list[str]) -> int:
    return _score_text(
        f"{publication.get('title', '')} {publication.get('summary', '')} {publication.get('venue', '')}",
        keywords,
        publication.get("tags", []),
    ) + 4


def _apply_publication_rules(
    publications: list[dict[str, Any]],
    keywords: list[str],
    preference_boosts: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scored = sorted(
        publications,
        key=lambda publication: _score_publication(publication, keywords) + _lookup_preference_score(publication.get("title", ""), preference_boosts),
        reverse=True,
    )
    kept = scored[:]
    excluded = [
        {"type": "publication", "name": publication.get("title", ""), "reason": "not_selected_for_one_page"}
        for publication in scored[2:]
    ]
    return kept, excluded


def _rewrite_bullet_text(
    bullet: dict[str, Any],
    keywords: list[str],
    tone: str,
    supported_skill_terms: list[str] | None = None,
    role_bucket: str = "ai_product",
) -> dict[str, Any]:
    text = _anonymize_client_mentions(_clean_sentence(bullet.get("text", "")))
    tags = bullet.get("tags", [])
    if not text:
        return {"text": "", "tags": tags}

    # Apply impact rewriting first (strong verbs, front-load metrics, scope context)
    text = _rewrite_bullet_for_impact(text, keywords, role_bucket)

    text = re.sub(r"\s*;\s*", "; ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = text.replace("AI-focused", "AI")
    text = text.replace("AI-generated", "AI-generated")
    weak_verb_map = {
        r"^helped\b": "Contributed to",
        r"^worked on\b": "Built",
        r"^assisted\b": "Supported",
        r"^supported\b": "Enabled",
        r"^partnered directly with leadership on\b": "Shaped",
        r"^partnered with leadership on\b": "Shaped",
        r"^collaborated with\b": "Worked directly with",
        r"^analyzed\b": "Analyzed",
        r"^developed\b": "Built",
        r"^created\b": "Designed",
        r"^built and managed\b": "Built and managed",
        r"^tracked\b": "Tracked",
    }
    for pattern, replacement in weak_verb_map.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    matched_terms = _top_matching_terms(text, keywords, limit=2)
    if matched_terms and len(text.split()) < 28 and all(term.lower() not in text.lower() for term in matched_terms[:1]):
        text = f"{text}; aligned to {matched_terms[0]}"
    supported_skill_terms = supported_skill_terms or []
    missing_supported_terms = [term for term in supported_skill_terms if term.lower() not in text.lower()]
    if missing_supported_terms and len(text.split()) < 24:
        text = f"{text}; using {missing_supported_terms[0]}"

    if ";" in text:
        first, rest = [part.strip() for part in text.split(";", 1)]
        if rest:
            connector = "and"
            if re.match(r"^(identified|qualified|converted|made|led|delivered|built|tracked|optimized|created|developed|partnered|collaborated)\b", rest, flags=re.IGNORECASE):
                connector = "by"
                rest = _normalize_clause_start(rest)
            text = f"{first} {connector} {rest}"

    if "delivered executive presentations and technical vision documents" in text.lower():
        text = re.sub(
            r"delivered executive presentations and technical vision documents",
            "delivering executive presentations and technical vision documents to support business development",
            text,
            flags=re.IGNORECASE,
        )
    if "built conversational ai proposals comparing salesforce agentforce vs. internal platforms by leading rfp/sow development" in text.lower():
        text = re.sub(
            r"Built Conversational AI proposals comparing Salesforce Agentforce vs\. internal platforms by leading RFP/SOW development\.?",
            "Built conversational AI proposals comparing Salesforce Agentforce with internal platforms and led RFP/SOW development.",
            text,
            flags=re.IGNORECASE,
        )
    if "built and managed top-of-funnel pipeline by identified, qualified, and converted top performers through competitive sourcing" in text.lower():
        text = re.sub(
            r"Built and managed top-of-funnel pipeline by identified, qualified, and converted top performers through competitive sourcing\.?",
            "Built and managed a top-of-funnel sourcing pipeline, identifying, qualifying, and converting top performers through competitive outreach.",
            text,
            flags=re.IGNORECASE,
        )
    if "tracked performance metrics, built funnels, optimized pass-through rates by making 100+ daily decisions" in text.lower():
        text = re.sub(
            r"Tracked performance metrics, built funnels, optimized pass-through rates by making 100\+ daily decisions\.?",
            "Tracked funnel performance, optimized pass-through rates, and made 100+ daily operating decisions to improve conversion quality.",
            text,
            flags=re.IGNORECASE,
        )
    if "analyzed client requirements" in text.lower():
        text = re.sub(
            r"Analyzed client requirements and developed AI solutions architecture for Fortune 500 clients in e-commerce and financial services\.?",
            "Analyzed business requirements and designed AI solution architectures for Fortune 500 e-commerce and financial-services engagements, translating stakeholder needs into implementation-ready plans.",
            text,
            flags=re.IGNORECASE,
        )
    if "using " in text.lower() and "aligned to " in text.lower() and len(text.split()) > 30:
        text = re.sub(r"; aligned to [^;,.]+", "", text, flags=re.IGNORECASE)

    if tone == "startup" and len(text.split()) > 38:
        text = _limit_words(text, 35)
    elif tone == "corporate" and len(text.split()) > 42:
        text = _limit_words(text, 40)
    elif len(text.split()) > 45:
        text = _limit_words(text, 42)

    return {"text": text, "tags": tags}


def _ats_optimize_bullets_llm(
    experience: list[dict[str, Any]],
    jd_text: str,
    keywords: list[str],
) -> list[dict[str, Any]]:
    """Use LLM to naturally weave missing JD keywords into resume bullets.

    This is the most impactful ATS optimization: it ensures that critical
    keywords from the JD appear naturally in the resume body text, not just
    in the skills section.
    """
    # Collect all bullet texts
    all_bullets: list[str] = []
    for exp in experience:
        for b in exp.get("bullets", []):
            text = b.get("text", "") if isinstance(b, dict) else str(b)
            if text:
                all_bullets.append(text)

    if not all_bullets or not keywords:
        return experience

    # Find keywords missing from the resume entirely
    resume_text = " ".join(all_bullets).lower()
    missing_keywords = [kw for kw in keywords if kw.lower() not in resume_text]

    if not missing_keywords:
        return experience  # All keywords already present

    # Only try to inject up to 5 missing keywords to keep it natural
    missing_keywords = missing_keywords[:5]

    bullet_block = "\n".join(f"- {b}" for b in all_bullets)
    jd_excerpt = jd_text[:2000]

    prompt = (
        "You are an ATS (Applicant Tracking System) optimization expert.\n\n"
        "Below are resume bullet points and a job description. Some critical JD keywords "
        "are MISSING from the resume bullets. Your job is to NATURALLY weave these missing "
        "keywords into the existing bullets WITHOUT changing the meaning, fabricating new "
        "achievements, or making the text sound forced.\n\n"
        "Rules:\n"
        "- Only modify bullets where the keyword fits naturally\n"
        "- Do NOT invent new achievements, metrics, or experiences\n"
        "- Do NOT change the core meaning of any bullet\n"
        "- Keep the same number of bullets\n"
        "- Keep bullet length similar (don't make them much longer)\n"
        "- Prefer adding keywords as method/tool descriptions (e.g., 'using Python' → 'using Python and SQL')\n"
        "- If a keyword truly doesn't fit any bullet, skip it\n"
        "- Return ONLY the modified bullets, one per line, prefixed with '- '\n\n"
        f"Missing keywords to inject: {', '.join(missing_keywords)}\n\n"
        f"Current resume bullets:\n{bullet_block}\n\n"
        f"Job description excerpt:\n{jd_excerpt}\n\n"
        "Return the optimized bullets (same count, same order):"
    )
    system = "You optimize resumes for ATS keyword matching while keeping content truthful and natural."

    try:
        result = _sync_llm_generate(prompt, system=system)
    except Exception:
        return experience  # Fail silently, use original

    if not result or not result.strip():
        return experience

    # Parse LLM response back into bullets
    new_bullets = []
    for line in result.strip().split("\n"):
        line = line.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if line.startswith("• "):
            line = line[2:].strip()
        if line:
            new_bullets.append(line)

    # Map optimized bullets back to experience entries
    idx = 0
    optimized_experience = deepcopy(experience)
    for exp in optimized_experience:
        bullets = exp.get("bullets", [])
        for i, bullet in enumerate(bullets):
            text = bullet.get("text", "") if isinstance(bullet, dict) else str(bullet)
            if text and idx < len(new_bullets):
                new_text = new_bullets[idx]
                # Sanity check: new bullet shouldn't be wildly different in length
                if 0.5 < len(new_text) / max(len(text), 1) < 2.0:
                    if isinstance(bullet, dict):
                        bullets[i]["text"] = new_text
                    else:
                        bullets[i] = new_text
                idx += 1
            elif text:
                idx += 1

    return optimized_experience


def _rewrite_project_summary(project: dict[str, Any], keywords: list[str], tone: str) -> dict[str, Any]:
    summary = _clean_sentence(_project_summary(project))
    if not summary:
        return project

    matched_terms = _top_matching_terms(f"{project.get('name', '')} {summary}", keywords, limit=2)
    display_summary = summary
    if matched_terms and all(term.lower() not in summary.lower() for term in matched_terms):
        display_summary = f"{summary} Focused on {', '.join(matched_terms)}."

    word_limit = 32 if tone == "startup" else 38
    project_copy = deepcopy(project)
    project_copy["display_summary"] = _limit_words(display_summary, word_limit)
    return project_copy


def _rewrite_publication(publication: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
    publication_copy = deepcopy(publication)
    summary = _clean_sentence(publication.get("summary", ""))
    matched_terms = _top_matching_terms(f"{publication.get('title', '')} {summary}", keywords, limit=2)
    if matched_terms and all(term.lower() not in summary.lower() for term in matched_terms):
        summary = f"{summary} Emphasizes {', '.join(_pretty_term(term) for term in matched_terms)}."
    publication_copy["display_summary"] = _limit_words(summary, 20)
    return publication_copy


def _extract_top_metric_from_experience(kept_experience: list[dict[str, Any]]) -> str:
    """Pull the single most impressive metric from experience bullets for the summary."""
    for exp in kept_experience[:3]:
        for bullet in exp.get("bullets", []):
            text = bullet.get("text", "") if isinstance(bullet, dict) else str(bullet)
            match = _METRIC_PATTERN.search(text)
            if match:
                metric = match.group(0)
                # Return metrics that have dollar signs, percentages, or AUC scores
                if "$" in metric or "%" in metric or "AUC" in metric.upper():
                    return metric
    return ""


def _best_summary_variant_for_bucket(summaries: dict[str, str], role_bucket: str) -> str:
    """Select the best summary variant based on role bucket with fallback chain."""
    # Direct match
    if role_bucket in summaries:
        return summaries[role_bucket]
    # Bucket-to-variant mapping for indirect matches
    bucket_fallbacks = {
        "consulting": ["consulting", "ai_product", "risk_analytics"],
        "corporate": ["consulting", "ai_product", "risk_analytics"],
        "technical": ["ai_product", "risk_analytics", "consulting"],
        "ai_product": ["ai_product", "consulting", "risk_analytics"],
        "risk_analytics": ["risk_analytics", "ai_product", "consulting"],
        "research": ["risk_analytics", "ai_product", "consulting"],
        "operator_startup": ["operator", "ai_product", "consulting"],
    }
    for candidate in bucket_fallbacks.get(role_bucket, []):
        if candidate in summaries:
            return summaries[candidate]
    return next(iter(summaries.values()), "")


def _build_generated_summary(
    canonical_resume: dict[str, Any],
    kept_experience: list[dict[str, Any]],
    kept_projects: list[dict[str, Any]],
    keywords: list[str],
    company_context: dict[str, Any],
    role_bucket: str,
) -> str:
    summaries = canonical_resume.get("summary_variants", {})
    base_summary = _best_summary_variant_for_bucket(summaries, role_bucket)
    fallback = base_summary or next(iter(summaries.values()), "")

    role_label = str(company_context.get("role", "")).strip()
    company = str(company_context.get("company", "")).strip()

    # Extract JD-relevant technical/domain terms
    skill_terms = _dedupe_preserve(
        [
            keyword
            for keyword in keywords
            if any(token in keyword.lower() for token in ["ai", "ml", "product", "analytics", "risk", "llm", "sql", "python", "rag", "agent", "data", "strategy", "consulting"])
        ]
    )[:4]

    # Find the most impressive metric from experience for the summary
    top_metric = _extract_top_metric_from_experience(kept_experience)

    # Build experience anchors with more specific language
    anchors: list[str] = []
    for exp in kept_experience[:2]:
        title = str(exp.get("title", "")).strip()
        company_name = str(exp.get("company", "")).strip()
        if title and company_name:
            anchors.append(f"{title} at {company_name}")
    for project in kept_projects[:1]:
        name = str(project.get("name", "")).strip()
        if name:
            anchors.append(name)

    # Find the most relevant experience/skill for this specific role
    most_relevant_skill = ""
    if skill_terms:
        most_relevant_skill = _pretty_term(skill_terms[0])

    # Build a richer, more tailored summary
    if role_label and company and skill_terms and anchors:
        skills_str = ", ".join(_pretty_term(term) for term in skill_terms[:3])
        metric_clause = f" ({top_metric})" if top_metric else ""
        summary = (
            f"MS Analytics candidate with hands-on {skills_str} experience{metric_clause}, "
            f"including {anchors[0]}. "
        )
        # Add a second sentence bridging to the target role
        if len(anchors) > 1 and most_relevant_skill:
            summary += f"Combines {most_relevant_skill} depth with stakeholder-ready communication, demonstrated through {anchors[-1]}."
        elif most_relevant_skill:
            summary += f"Brings {most_relevant_skill} expertise and a track record of translating complex analysis into actionable business decisions."
        return _limit_words(summary, 42)

    if role_label and anchors:
        metric_clause = f" ({top_metric})" if top_metric else ""
        return _limit_words(
            f"MS Analytics candidate with {anchors[0]} experience{metric_clause} and a track record of turning analytical work into measurable business outcomes.",
            38,
        )

    # Fallback: enhance the base variant with JD keywords
    if skill_terms and fallback:
        jd_addition = f" with expertise in {', '.join(_pretty_term(t) for t in skill_terms[:2])}"
        # Insert the JD keywords naturally into the base summary
        if fallback.endswith("."):
            enhanced = fallback[:-1] + jd_addition + "."
        else:
            enhanced = fallback + jd_addition + "."
        return _limit_words(enhanced, 38)

    return _limit_words(fallback, 38)


def _build_skills_display(
    skills: dict[str, list[str]] | list[str],
    role_bucket: str,
    keywords: list[str],
    education: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    flattened: list[tuple[str, str]] = []
    supported_keyword_skills = _supported_jd_skill_terms(keywords, skills)
    if isinstance(skills, dict):
        for category, items in skills.items():
            for item in items:
                flattened.append((category, item))
    else:
        flattened = [("core", item) for item in skills]

    label_templates = {
        "consulting": [
            ("Consulting & Strategy", ["stakeholder", "strategy", "rfp", "sow", "problem solving", "product analytics"]),
            ("AI & Machine Learning", ["llm", "rag", "xgboost", "machine", "shap", "agent", "uplift", "fine-tuning", "prompt", "tensorflow", "pytorch", "anomaly"]),
            ("Programming & Data", ["python", "sql", "r", "fastapi", "node", "databricks", "etl", "pyspark", "hive"]),
            ("Cloud & DevOps", ["aws", "docker", "kubernetes", "vercel", "supabase", "microservices"]),
        ],
        "corporate": [
            ("Consulting & Strategy", ["stakeholder", "strategy", "rfp", "sow", "problem solving", "product analytics"]),
            ("AI & Machine Learning", ["llm", "rag", "xgboost", "machine", "shap", "agent", "uplift", "fine-tuning", "prompt", "tensorflow", "pytorch", "anomaly"]),
            ("Programming & Data", ["python", "sql", "r", "fastapi", "node", "databricks", "etl", "pyspark", "hive"]),
            ("Cloud & DevOps", ["aws", "docker", "kubernetes", "vercel", "supabase", "microservices"]),
        ],
        "ai_product": [
            ("Product, Strategy & Analytics", ["product", "analytics", "stakeholder", "experimentation", "strategy"]),
            ("AI & Machine Learning", ["llm", "rag", "xgboost", "machine", "shap", "agent", "uplift", "fine-tuning", "prompt", "tensorflow", "pytorch", "anomaly"]),
            ("Programming & Data", ["python", "sql", "r", "fastapi", "node", "databricks", "etl", "pyspark", "hive"]),
            ("Cloud & DevOps", ["aws", "docker", "kubernetes", "vercel", "supabase", "microservices"]),
        ],
        "technical": [
            ("AI & Machine Learning", ["llm", "rag", "xgboost", "machine", "shap", "agent", "uplift"]),
            ("Programming & Data", ["python", "sql", "r", "pyspark", "node", "fastapi", "etl", "databricks"]),
            ("Cloud & Deployment", ["aws", "docker", "kubernetes", "vercel", "supabase", "microservices"]),
        ],
        "research": [
            ("Research & Modeling", ["research", "xgboost", "machine", "shap", "tensorflow", "anomaly"]),
            ("AI & Systems", ["llm", "rag", "agent", "knowledge graph"]),
            ("Data & Technology Stack", ["python", "sql", "r", "fastapi", "aws", "docker"]),
        ],
        "risk_analytics": [
            ("Risk & Analytics", ["risk", "compliance", "analytics", "model risk", "sr 11-7", "experimentation"]),
            ("AI & Machine Learning", ["llm", "rag", "xgboost", "machine", "shap", "agent"]),
            ("Data & Technology Stack", ["python", "sql", "r", "fastapi", "aws", "docker", "supabase"]),
        ],
        "operator_startup": [
            ("Operations & Strategy", ["operations", "strategy", "stakeholder", "hiring", "experimentation"]),
            ("AI & Analytics", ["llm", "rag", "xgboost", "analytics", "agent"]),
            ("Tools & Platforms", ["python", "sql", "fastapi", "aws", "docker", "vercel", "supabase"]),
        ],
    }
    groups = label_templates.get(role_bucket, label_templates["ai_product"])

    # Score each category group by JD relevance to determine display order
    def _category_jd_relevance(themes: list[str]) -> int:
        relevance = 0
        for keyword in keywords:
            kw_lower = keyword.lower()
            for theme in themes:
                if theme in kw_lower or kw_lower in theme:
                    relevance += 3
        # Also count how many supported JD skills fall in this category
        for skill in supported_keyword_skills:
            skill_lower = skill.lower()
            for theme in themes:
                if theme in skill_lower:
                    relevance += 2
                    break
        return relevance

    # Reorder categories: most JD-relevant category first
    groups_with_scores = [(label, themes, _category_jd_relevance(themes)) for label, themes in groups]
    groups_with_scores.sort(key=lambda x: x[2], reverse=True)
    groups = [(label, themes) for label, themes, _ in groups_with_scores]

    grouped: list[dict[str, Any]] = []
    used: set[str] = set()
    for label, themes in groups:
        scored_items: list[tuple[int, str]] = []
        for category, item in flattened:
            haystack = f"{category} {item}".lower()
            if item in used:
                continue
            score = sum(4 for theme in themes if theme in haystack)
            score += sum(2 for keyword in keywords if keyword.lower() in haystack)
            # Strong boost for skills that directly match JD keywords
            if any(item.lower() == matched.lower() for matched in supported_keyword_skills):
                score += 10
            # Moderate boost for partial JD keyword matches
            elif any(keyword.lower() in item.lower() or item.lower() in keyword.lower() for keyword in keywords):
                score += 4
            if score > 0:
                scored_items.append((score, item))
        # Within each category, JD-matching skills come first (sorted by score)
        chosen = [item for _, item in sorted(scored_items, key=lambda pair: pair[0], reverse=True)[:7]]
        chosen = _dedupe_preserve(chosen)
        used.update(chosen)
        grouped.append({"label": label, "items": chosen})

    if grouped:
        leftovers = [item for _, item in flattened if item not in used]
        leftovers = _dedupe_preserve(supported_keyword_skills + leftovers)[:4]
        for item in leftovers:
            grouped[-1]["items"].append(item)
        grouped[-1]["items"] = _dedupe_preserve(grouped[-1]["items"])

    # Add certifications/relevant coursework line if applicable
    education_entries = education or []
    awards_and_certs: list[str] = []
    for edu in education_entries:
        for award in edu.get("awards", []):
            award_text = str(award).strip()
            if award_text:
                awards_and_certs.append(award_text)
    # Filter to awards/certs that match JD keywords
    relevant_certs = [
        cert for cert in awards_and_certs
        if any(keyword.lower() in cert.lower() for keyword in keywords)
    ]
    if relevant_certs:
        grouped.append({
            "label": "Awards & Certifications",
            "items": _dedupe_preserve(relevant_certs)[:3],
        })

    return [group for group in grouped if group["items"]]


def _section_heading_for_role(role_bucket: str) -> str:
    if role_bucket in {"consulting", "corporate", "ai_product"}:
        return "CONSULTING & PROFESSIONAL EXPERIENCE"
    if role_bucket == "operator_startup":
        return "OPERATING & PROFESSIONAL EXPERIENCE"
    return "PROFESSIONAL EXPERIENCE"


def _default_section_priority(role_bucket: str) -> dict[str, int]:
    defaults = {
        "experience": 10,
        "skills": 8,
        "projects": 5,
        "publications": 3,
        "leadership": 4,
    }
    if role_bucket == "research":
        defaults["publications"] = 9
    if role_bucket == "operator_startup":
        defaults["projects"] = 6
        defaults["publications"] = 1
    return defaults


def _derive_priority_engine(
    rule_set: dict[str, Any],
    jd_parse: dict[str, Any],
    keywords: list[str],
    learning_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_priority = _default_section_priority(jd_parse["role_type"])
    rule_priority = rule_set.get("section_priority", {})
    merged = {**base_priority, **rule_priority}
    if any(term.lower() in {"research", "paper", "publication", "methodology"} for term in keywords):
        merged["publications"] = max(merged.get("publications", 0), 8)
    if any(term.lower() in {"stakeholder", "client", "strategy", "consulting"} for term in keywords):
        merged["experience"] += 1
        merged["skills"] += 1
    for section, boost in (learning_profile or {}).get("section_boosts", {}).items():
        merged[section] = merged.get(section, 0) + int(boost)
    ordered = [
        {"section": section, "priority": score}
        for section, score in sorted(merged.items(), key=lambda pair: pair[1], reverse=True)
    ]
    return {"ordered_sections": ordered, "weights": merged}


def _selection_summary(
    jd_parse: dict[str, Any],
    kept_experience: list[dict[str, Any]],
    kept_projects: list[dict[str, Any]],
    kept_publications: list[dict[str, Any]],
    excluded_items: list[dict[str, Any]],
    selected_summary: str,
    rule_set: dict[str, Any],
    priority_engine: dict[str, Any],
) -> dict[str, Any]:
    return {
        "role_type": jd_parse["role_type"],
        "role_type_label": jd_parse["role_type_label"],
        "tone": jd_parse["tone"],
        "industry": jd_parse["industry"],
        "selected_summary_variant": rule_set.get("summary_variant", ""),
        "selected_summary_text": selected_summary,
        "included_experience": [
            {"company": exp.get("company", ""), "title": exp.get("title", "")} for exp in kept_experience
        ],
        "included_projects": [project.get("name", "") for project in kept_projects[:2]],
        "included_publications": [publication.get("title", "") for publication in kept_publications[:2]],
        "excluded_items": excluded_items,
        "emphasis": rule_set.get("emphasize", []),
        "priority_engine": priority_engine,
    }


def _is_higher_education_role(jd_text: str, company_context: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            _clean_sentence(jd_text),
            _clean_sentence(company_context.get("company", "")),
            _clean_sentence(company_context.get("role", "")),
            _clean_sentence(company_context.get("product_or_initiative", "")),
            _clean_sentence(company_context.get("department", "")),
            _clean_sentence(company_context.get("team", "")),
        ]
    ).lower()
    keywords = {
        "higher education",
        "university",
        "college",
        "academic",
        "campus",
        "student",
        "faculty",
        "education",
        "school",
    }
    return any(keyword in haystack for keyword in keywords)


def _resolve_cover_letter_tone(role_bucket: str, rule_set: dict[str, Any], learning_profile: dict[str, Any] | None) -> str:
    explicit_tone = str((learning_profile or {}).get("rules", {}).get("tone", "")).strip()
    if explicit_tone:
        return explicit_tone
    base_tone = str(rule_set.get("tone", "formal")).strip() or "formal"
    tone_preferences = (learning_profile or {}).get("tone_preferences", {})
    if not tone_preferences:
        return base_tone
    strongest_tone = max(tone_preferences.items(), key=lambda item: item[1])[0]
    if tone_preferences.get(strongest_tone, 0) > 0:
        return str(strongest_tone)
    return base_tone


def _apply_filler_rule(
    include_companies: set[str],
    exclude_companies: set[str],
    *,
    higher_education_role: bool,
    learning_profile: dict[str, Any] | None,
) -> tuple[set[str], set[str]]:
    filler_company = "FillerCompany"
    rules = (learning_profile or {}).get("rules", {})
    if str(rules.get("filler_mode", "")).strip().lower() != "university_only":
        return include_companies, exclude_companies
    if higher_education_role:
        exclude_companies.discard(filler_company)
    else:
        exclude_companies.add(filler_company)
        include_companies.discard(filler_company)
    return include_companies, exclude_companies


def _cover_letter_example_preferences(learning_profile: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    return (learning_profile or {}).get(key)


def _cover_letter_paragraph_order(learning_profile: dict[str, Any] | None) -> list[str]:
    defaults = ["business_fit", "execution", "technical_alignment", "closing"]
    emphasis = (learning_profile or {}).get("paragraph_emphasis_boosts", {})
    ranked = sorted(defaults, key=lambda item: emphasis.get(item, 0), reverse=True)
    return ranked if ranked else defaults


def _check_ats_keyword_coverage(tailored: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
    """Check what percentage of JD keywords appear in the final tailored resume.

    Returns a report with matched/missing keywords and coverage percentage.
    """
    # Build full resume text from all sections
    resume_parts: list[str] = []

    # Summary
    resume_parts.append(str(tailored.get("selected_summary", "")))

    # Experience bullets
    for exp in tailored.get("experience", []):
        resume_parts.append(str(exp.get("title", "")))
        for bullet in exp.get("bullets", []):
            text = bullet.get("text", "") if isinstance(bullet, dict) else str(bullet)
            resume_parts.append(text)

    # Projects
    for proj in tailored.get("projects", []):
        resume_parts.append(str(proj.get("name", "")))
        resume_parts.append(str(proj.get("display_summary", proj.get("summary", ""))))

    # Skills
    for group in tailored.get("skills_display", []):
        for item in group.get("items", []):
            resume_parts.append(str(item))

    # Publications
    for pub in tailored.get("publications", []):
        resume_parts.append(str(pub.get("title", "")))
        resume_parts.append(str(pub.get("display_summary", "")))

    resume_text = " ".join(resume_parts).lower()

    matched = [kw for kw in keywords if kw.lower() in resume_text]
    missing = [kw for kw in keywords if kw.lower() not in resume_text]
    coverage = len(matched) / max(len(keywords), 1) * 100

    return {
        "total_keywords": len(keywords),
        "matched": matched,
        "missing": missing,
        "coverage_pct": round(coverage, 1),
    }


def _resolve_cover_letter_length(learning_profile: dict[str, Any] | None) -> str:
    value = str((learning_profile or {}).get("rules", {}).get("length", "")).strip().lower()
    if value in {"short", "long"}:
        return value
    return "default"


def tailor_resume(
    master_resume: dict[str, Any],
    jd_text: str,
    company_context: dict[str, Any] | None = None,
    company_background: str = "",
    learning_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical_resume = canonicalize_master_resume(master_resume)
    tailored = deepcopy(canonical_resume)
    company_context = company_context or {}

    company_signal = _company_context_line(company_context, company_background)
    scoring_text = f"{jd_text}\n{company_signal}".strip()
    jd_parse = parse_job_description(jd_text, company_context)

    keywords = extract_keywords(scoring_text, limit=18)
    supported_jd_skills = _supported_jd_skill_terms(keywords, canonical_resume.get("skills", {}))
    role_bucket = jd_parse["role_type"]
    role_bucket = "ai_product" if role_bucket == "product_strategy" else role_bucket
    summaries = canonical_resume.get("summary_variants", {})
    rule_set = resolve_rule_set(role_bucket)
    selected_summary = summaries.get(rule_set.get("summary_variant", role_bucket)) or summaries.get(role_bucket) or next(iter(summaries.values()), "")

    tailored["selected_summary"] = selected_summary
    tailored["role_bucket"] = role_bucket
    tailored["keyword_hits"] = keywords[:6]
    tailored["resume_format"] = "ATS_SINGLE_COLUMN"
    tailored["company_background_used"] = bool(company_background.strip())

    higher_education_role = _is_higher_education_role(jd_text, company_context)
    include_companies = set(rule_set.get("include_experience_companies", []))
    exclude_companies = set(rule_set.get("exclude_experience_companies", []))
    include_companies, exclude_companies = _apply_filler_rule(
        include_companies,
        exclude_companies,
        higher_education_role=higher_education_role,
        learning_profile=learning_profile,
    )
    experience_preference_boosts = _merge_preference_boosts(
        _default_experience_preferences(higher_education_role=higher_education_role),
        (learning_profile or {}).get("experience_boosts"),
    )
    favored_projects = set(rule_set.get("prefer_project_names", []))
    priority_engine = _derive_priority_engine(rule_set, jd_parse, keywords, learning_profile)

    kept_experience, excluded_experience = _apply_experience_rules(
        canonical_resume.get("experience", []),
        keywords,
        include_companies,
        exclude_companies,
        experience_preference_boosts,
    )
    kept_experience, excluded_experience = _prefer_primary_over_filler(
        kept_experience,
        excluded_experience,
        higher_education_role=higher_education_role,
    )
    selected_experience = []
    for exp in kept_experience:
        exp_out = {
            **exp,
            "bullets": [
                _rewrite_bullet_text(
                    bullet,
                    keywords,
                    jd_parse["tone"],
                    supported_jd_skills,
                    role_bucket,
                )
                for bullet in exp.get("bullets", [])
            ],
        }
        # Flexible title: adapt the primary-company role title to match the target role bucket,
        # with JD-keyword fallback so operations/consulting/finance JDs get a
        # matching title even when the role_bucket is generic (e.g. "ai_product").
        if exp.get("flexible_title"):
            variants = exp.get("title_variants", {})
            chosen = variants.get(role_bucket)
            if not chosen or chosen == variants.get("default"):
                # Try JD-keyword heuristic for a more specific title
                _jd_combined = jd_text.lower()
                _FLEX_KEYWORD_MAP = [
                    # --- AI/ML specific (HIGHEST PRIORITY — check first) ---
                    # GenAI/LLM/RAG roles
                    (["llm engineer", "large language model engineer"], "llm_engineer"),
                    (["genai engineer", "generative ai engineer", "generative ai"], "genai_engineer"),
                    (["rag engineer", "retrieval augmented", "rag system"], "rag_engineer"),
                    (["foundation model engineer", "foundation models"], "foundation_model_engineer"),
                    (["prompt engineer", "prompt engineering"], "prompt_engineer"),
                    # AI Risk ([university] concentration + [previous-employer] experience)
                    (["ai risk analyst", "ai risk management"], "ai_risk_analyst"),
                    (["model risk analyst", "model risk management", "mrm analyst"], "model_risk_analyst"),
                    (["model validation", "model governance"], "model_validation_analyst"),
                    # AI Business / Product
                    (["ai business analyst"], "ai_business_analyst"),
                    (["ai product analyst", "ai product manager"], "ai_product_analyst"),
                    (["ai solutions analyst", "ai solutions engineer"], "ai_solutions_analyst"),
                    (["ai strategy analyst", "ai strategy"], "ai_strategy_analyst"),
                    (["ai operations analyst", "ai operations"], "ai_operations_analyst"),
                    # Core AI/ML engineer roles
                    (["machine learning engineer", "ml engineer"], "ml_engineer"),
                    (["applied scientist", "applied ml scientist"], "applied_scientist"),
                    (["ai engineer", "ai developer"], "ai_engineer"),
                    (["data scientist", "data science"], "data_scientist"),
                    (["mlops engineer", "ml platform engineer", "ml infrastructure"], "mlops_engineer"),
                    (["nlp engineer", "natural language processing"], "nlp_engineer"),
                    (["ai research engineer", "research engineer"], "ai_research_engineer"),
                    (["decision scientist", "decision science"], "decision_scientist"),
                    # Quant
                    (["quantitative analyst", "quant analyst", "junior quant"], "quantitative_analyst"),
                    (["quantitative researcher", "quant researcher"], "quant_researcher"),
                    # Data Eng
                    (["data engineer", "etl engineer"], "data_engineer"),
                    (["analytics engineer"], "analytics_engineer"),
                    # --- Generic analyst/consulting (fallback) ---
                    (["operations analyst", "business operations", "operations associate"], "operations_analyst"),
                    (["business analyst", "business requirements", "process improvement"], "business_analyst"),
                    (["financial analyst", "financial modeling", "fp&a", "forecasting"], "financial_analyst"),
                    (["compliance analyst", "regulatory", "compliance monitoring"], "compliance_analyst"),
                    (["consultant", "consulting", "advisory"], "consulting"),
                    (["risk analyst", "risk management", "risk assessment"], "risk_analytics"),
                    (["data analyst", "data analysis", "dashboards", "sql"], "data_analyst"),
                ]
                for triggers, variant_key in _FLEX_KEYWORD_MAP:
                    if any(t in _jd_combined for t in triggers):
                        if variant_key in variants:
                            chosen = variants[variant_key]
                            break
            exp_out["title"] = chosen or variants.get("default") or exp.get("title", "")
            exp_out.pop("title_variants", None)
            exp_out.pop("flexible_title", None)
        selected_experience.append(exp_out)
    # ATS keyword optimization: use LLM to inject missing JD keywords into bullets
    selected_experience = _ats_optimize_bullets_llm(selected_experience, jd_text, keywords)

    tailored["experience"] = _sort_items_newest_first(selected_experience)

    kept_projects, excluded_projects = _apply_project_rules(
        canonical_resume.get("projects", []),
        keywords,
        favored_projects,
        (learning_profile or {}).get("project_boosts"),
    )
    tailored["projects"] = [
        _rewrite_project_summary(project, keywords, jd_parse["tone"]) for project in kept_projects
    ]

    kept_publications, excluded_publications = _apply_publication_rules(
        canonical_resume.get("publications", []),
        keywords,
        (learning_profile or {}).get("publication_boosts"),
    )
    tailored["publications"] = [
        _rewrite_publication(publication, keywords) for publication in kept_publications
    ]

    leadership = canonical_resume.get("leadership", [])
    hide_leadership = rule_set.get("hide_leadership", False) or str((learning_profile or {}).get("rules", {}).get("hide_leadership", "")).lower() == "true"
    if hide_leadership:
        tailored["leadership"] = []
    else:
        tailored["leadership"] = sorted(
            leadership,
            key=lambda item: _score_text(
                f"{item.get('role', '')} {item.get('organization', '')} {item.get('description', '')}",
                keywords,
            ) + _lookup_preference_score(
                " | ".join(
                    part for part in [str(item.get("role", "")).strip(), str(item.get("organization", "")).strip()] if part
                ),
                (learning_profile or {}).get("leadership_boosts"),
            ),
            reverse=True,
        )

    skills = canonical_resume.get("skills", {})
    if isinstance(skills, dict):
        scored_categories = sorted(
            skills.items(),
            key=lambda pair: sum(_score_skill(skill, keywords) for skill in pair[1]),
            reverse=True,
        )
        tailored["skills"] = {
            category: sorted(items, key=lambda skill: _score_skill(skill, keywords), reverse=True)
            for category, items in scored_categories
        }
    else:
        tailored["skills"] = {"Core Skills": sorted(skills, key=lambda skill: _score_skill(skill, keywords), reverse=True)}

    tailored["selected_summary"] = _build_generated_summary(
        canonical_resume,
        tailored["experience"],
        tailored["projects"],
        keywords,
        company_context,
        role_bucket,
    ) or selected_summary
    tailored["skills_display"] = _build_skills_display(
        tailored["skills"], role_bucket, keywords, canonical_resume.get("education", [])
    )
    tailored["jd_matched_skills"] = supported_jd_skills[:8]
    tailored["section_headings"] = {
        "education": "Education",
        "experience": "Experience",
        "projects": "Project",
        "publications": "Research Papers",
        "skills": "Skills",
        "leadership": "Leadership",
    }
    tailored["priority_engine"] = priority_engine

    tailored = apply_one_page_limits(tailored)
    guardrails = build_guardrail_report(canonical_resume, tailored)
    selection_summary = _selection_summary(
        jd_parse,
        tailored.get("experience", []),
        tailored.get("projects", []),
        tailored.get("publications", []),
        excluded_experience + excluded_projects + excluded_publications,
        tailored["selected_summary"],
        rule_set,
        priority_engine,
    )

    # ATS keyword density check — verify critical JD terms appear in the final resume
    ats_keyword_coverage = _check_ats_keyword_coverage(tailored, keywords)

    return {
        "role_bucket": role_bucket,
        "selected_summary": tailored["selected_summary"],
        "keyword_hits": keywords[:6],
        "tailored_resume": tailored,
        "ats_notes": make_ats_notes(),
        "guardrails": guardrails,
        "selection_summary": selection_summary,
        "jd_parse": jd_parse,
        "ats_keyword_coverage": ats_keyword_coverage,
        "learning_profile": learning_profile or {
            "role_bucket": role_bucket,
            "experience_boosts": {},
            "project_boosts": {},
            "publication_boosts": {},
            "leadership_boosts": {},
            "section_boosts": {},
            "feedback_counts": {},
        },
    }


def generate_cover_letter(
    jd_text: str,
    profile: dict[str, Any],
    company_context: dict[str, Any],
    master_resume: dict[str, Any],
    company_background: str = "",
) -> dict[str, Any]:
    canonical_resume = canonicalize_master_resume(master_resume)
    company = _clean_company_name(company_context.get("company", "the company"))
    role = _clean_sentence(company_context.get("role", "the role"))
    product = _clean_sentence(company_context.get("product_or_initiative", "")) or "the problems this team is solving"
    company_research_summary = _extract_company_research_summary(jd_text, company_background, company_context)
    keywords = extract_keywords(jd_text, limit=8)
    supported_jd_skills = _supported_jd_skill_terms(keywords, canonical_resume.get("skills", {}))
    role_bucket = infer_role_bucket(jd_text, {**profile, **canonical_resume})
    role_bucket = "ai_product" if role_bucket == "product_strategy" else role_bucket
    rule_set = resolve_rule_set(role_bucket)
    learning_profile = company_context.get("learning_profile") if isinstance(company_context.get("learning_profile"), dict) else None
    tone = _resolve_cover_letter_tone(role_bucket, rule_set, learning_profile)
    length_mode = _resolve_cover_letter_length(learning_profile)
    higher_education_role = _is_higher_education_role(jd_text, company_context)

    include_companies = set(rule_set.get("include_experience_companies", []))
    exclude_companies = set(rule_set.get("exclude_experience_companies", []))
    if not higher_education_role:
        exclude_companies.add("FillerCompany")
    include_companies, exclude_companies = _apply_filler_rule(
        include_companies,
        exclude_companies,
        higher_education_role=higher_education_role,
        learning_profile=learning_profile,
    )
    example_preference_boosts = _merge_preference_boosts(
        _default_experience_preferences(higher_education_role=higher_education_role),
        _cover_letter_example_preferences(learning_profile, "example_boosts"),
    )
    favored_projects = set(rule_set.get("prefer_project_names", []))
    kept_experience, _ = _apply_experience_rules(
        canonical_resume.get("experience", []),
        keywords,
        include_companies,
        exclude_companies,
        example_preference_boosts,
    )
    kept_experience, _ = _prefer_primary_over_filler(
        kept_experience,
        [],
        higher_education_role=higher_education_role,
    )
    kept_projects, _ = _apply_project_rules(
        canonical_resume.get("projects", []),
        keywords,
        favored_projects,
        _cover_letter_example_preferences(learning_profile, "project_boosts"),
    )

    cover_experience = [
        {
            **exp,
            "bullets": [
                _rewrite_bullet_text(
                    bullet,
                    keywords,
                    tone,
                    supported_jd_skills,
                    role_bucket,
                )
                for bullet in exp.get("bullets", [])
            ],
        }
        for exp in kept_experience
    ]
    top_experience = cover_experience[:3]
    summary_variant = (canonical_resume.get("summary_variants") or {}).get(role_bucket, "")
    intro_terms = _cover_letter_theme_terms(jd_text, company_context)

    def exp_line(exp: dict[str, Any], limit: int = 2) -> str:
        company_name = str(exp.get("company", "")).strip()
        title = str(exp.get("title", "")).strip()
        bullet_texts = [
            _clean_sentence(str(bullet.get("text", "") if isinstance(bullet, dict) else bullet))
            for bullet in exp.get("bullets", [])[:limit]
        ]
        bullet_texts = [text for text in bullet_texts if text]
        detail = " ".join(bullet_texts)
        detail = _lowercase_leading_verb(detail)
        if company_name and title and detail:
            return _limit_words(f"As {title} at {company_name}, {detail}", 52)
        if company_name and detail:
            return _limit_words(f"At {company_name}, {detail}", 52)
        return _limit_words(detail, 52)

    def project_line(project: dict[str, Any]) -> str:
        name = str(project.get("name", "")).strip()
        summary = str(project.get("summary", project.get("description", ""))).strip()
        summary = _lowercase_leading_verb(summary)
        if name and summary:
            return _limit_words(f"{name} also reflects that fit: {summary}", 42)
        return _limit_words(summary, 42)

    word_limits = {
        "default": {"p1": 78, "p2": 52, "p3": 82, "p4": 68},
        "short": {"p1": 62, "p2": 40, "p3": 58, "p4": 50},
        "long": {"p1": 92, "p2": 64, "p3": 96, "p4": 78},
    }
    active_limits = word_limits[length_mode]

    llm_letter = _render_cover_letter_with_llm(
        company=company,
        role=role,
        product=product,
        company_research_summary=company_research_summary,
        tone=tone,
        intro_terms=intro_terms,
        summary_variant=summary_variant,
        experiences=top_experience,
        projects=kept_projects,
        jd_text=jd_text,
        length_mode=length_mode,
    )

    if tone == "technical":
        intro_open = f"What stands out to me about {company} is how clearly the {role} role connects technical depth with real execution."
        intro_bridge = f"I do my best work where messy operational problems need structured technical thinking, and that is exactly what I see in the role's emphasis on {intro_terms}."
        closing_line = f"I would welcome the opportunity to discuss how my technical execution and client-facing delivery can contribute to {company}'s team."
    elif tone == "direct":
        intro_open = f"I'm drawn to {company} because the {role} role is close to the kind of work I like doing most."
        intro_bridge = f"It combines {product} with outcomes around {intro_terms}, which matches the builder-operator work I naturally gravitate toward."
        closing_line = f"I'd welcome the chance to discuss how I can contribute quickly and effectively at {company}."
    else:
        intro_open = f"What draws me to {company} is the chance to contribute in a {role} role where thoughtful execution really matters."
        intro_bridge = f"I am most effective in roles where I can turn ambiguous business needs into structured analysis, practical systems, and decisions teams can act on, which is exactly how I read the focus on {intro_terms}."
        closing_line = f"I would welcome the opportunity to discuss how my experience can contribute to {company}'s team."

    paragraph_1 = _limit_words(" ".join(part for part in [intro_open, intro_bridge, company_research_summary] if part), active_limits["p1"])

    paragraph_2 = exp_line(top_experience[0]) if top_experience else _limit_words(summary_variant, active_limits["p2"])
    paragraph_2 = _limit_words(paragraph_2, active_limits["p2"])

    paragraph_3_parts = []
    if len(top_experience) > 1:
        paragraph_3_parts.append(exp_line(top_experience[1]))
    if kept_projects:
        paragraph_3_parts.append(project_line(kept_projects[0]))
    paragraph_3 = _limit_words(" ".join(part for part in paragraph_3_parts if part), active_limits["p3"])

    paragraph_4_parts = []
    if len(top_experience) > 2 and length_mode != "short":
        paragraph_4_parts.append(exp_line(top_experience[2], limit=1))
    paragraph_4_parts.append(closing_line)
    paragraph_4 = _limit_words(" ".join(part for part in paragraph_4_parts if part), active_limits["p4"])

    paragraph_library = {
        "business_fit": paragraph_1,
        "execution": paragraph_2,
        "technical_alignment": paragraph_3,
        "closing": paragraph_4,
    }
    paragraphs = [paragraph_library[key] for key in _cover_letter_paragraph_order(learning_profile) if paragraph_library.get(key)]
    fallback_letter = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    letter = _polish_cover_letter_text(
        llm_letter if _quality_guard_cover_letter(llm_letter) else fallback_letter,
        company=company,
        role=role,
        product=product,
    )

    return {
        "role_bucket": role_bucket,
        "cover_letter": letter,
        "selection_summary": {
            "tone": tone,
            "length_mode": length_mode,
            "higher_education_role": higher_education_role,
            "included_examples": [str(exp.get("company", "")).strip() for exp in top_experience if str(exp.get("company", "")).strip()],
            "included_projects": [str(project.get("name", "")).strip() for project in kept_projects[:2] if str(project.get("name", "")).strip()],
            "paragraph_emphasis_order": _cover_letter_paragraph_order(learning_profile),
            "filler_allowed": higher_education_role,
        },
        "learning_profile": learning_profile or {
            "role_bucket": role_bucket,
            "tone_preferences": {},
            "example_boosts": {},
            "project_boosts": {},
            "paragraph_emphasis_boosts": {},
            "rules": {},
            "feedback_counts": {},
        },
    }
