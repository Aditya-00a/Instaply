from __future__ import annotations

import re
from typing import Any

from backend.services.matcher import extract_keywords


# ---------------------------------------------------------------------------
# Known tools / technologies for extraction
# ---------------------------------------------------------------------------

_KNOWN_TOOLS: set[str] = {
    "SQL", "Python", "R", "Excel", "Tableau", "Power BI", "Looker",
    "Jupyter", "AWS", "GCP", "Azure", "Spark", "dbt", "Airflow",
    "Snowflake", "Databricks", "Redshift", "BigQuery", "Kafka",
    "Docker", "Kubernetes", "Terraform", "Git", "GitHub", "GitLab",
    "Jira", "Confluence", "Salesforce", "HubSpot", "Segment",
    "Fivetran", "Stitch", "Looker", "Metabase", "Superset",
    "TensorFlow", "PyTorch", "Scikit-learn", "Pandas", "NumPy",
    "SciPy", "Matplotlib", "Seaborn", "Plotly", "Dash",
    "Node.js", "React", "Angular", "Vue", "TypeScript", "JavaScript",
    "Java", "Scala", "Go", "Rust", "C++", "C#", ".NET",
    "MongoDB", "PostgreSQL", "MySQL", "Redis", "Elasticsearch",
    "Cassandra", "DynamoDB", "Neo4j", "Pinecone", "Weaviate",
    "LangChain", "LlamaIndex", "OpenAI", "Hugging Face",
    "MLflow", "Weights & Biases", "SageMaker", "Vertex AI",
    "Prefect", "Dagster", "Luigi", "Celery",
    "Figma", "Sketch", "Adobe XD", "Photoshop", "Illustrator",
    "Notion", "Asana", "Trello", "Monday.com", "Linear",
    "Slack", "Teams", "Zoom",
    "Stripe", "Plaid", "Twilio",
    "FastAPI", "Flask", "Django", "Spring", "Rails",
    "GraphQL", "REST", "gRPC",
    "CI/CD", "Jenkins", "CircleCI", "GitHub Actions",
    "Datadog", "Splunk", "New Relic", "Grafana", "Prometheus",
    "Hadoop", "Hive", "Presto", "Trino", "Athena",
    "MATLAB", "SAS", "SPSS", "Stata",
    "VBA", "Google Sheets", "Google Analytics",
}

# Pre-compute lowercase lookup: lowercase -> canonical name
_TOOL_LOOKUP: dict[str, str] = {t.lower(): t for t in _KNOWN_TOOLS}


ROLE_TYPE_LABELS = {
    "ai_product": "AI/ML Engineering",
    "consulting": "Consulting",
    "product_strategy": "Product/Strategy",
    "risk_analytics": "Risk/Compliance",
    "operator_startup": "Operator/Startup",
    "data_science": "Data Science",
    "research": "Research",
}


def _detect_tone(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in ["fast-paced", "move fast", "0 to 1", "startup"]):
        return "startup"
    if any(term in lower for term in ["research", "publication", "scientist", "methodology"]):
        return "technical"
    if any(term in lower for term in ["client", "stakeholder", "advisory", "consulting"]):
        return "corporate"
    return "balanced"


def _detect_industry(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in ["fintech", "bank", "finance", "risk", "compliance"]):
        return "financial services"
    if any(term in lower for term in ["healthcare", "hospital", "clinical"]):
        return "healthcare"
    if any(term in lower for term in ["creative", "media", "video", "design"]):
        return "creative technology"
    if any(term in lower for term in ["developer tools", "infrastructure", "platform"]):
        return "software infrastructure"
    return "general technology"


def _detect_seniority(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in ["senior", "staff", "principal", "lead"]):
        return "senior"
    if any(term in lower for term in ["intern", "new grad", "entry level", "associate"]):
        return "entry"
    if any(term in lower for term in ["manager", "pm", "product manager"]):
        return "mid"
    return "mid"


def classify_role_type(jd_text: str, role_title: str = "") -> str:
    title_lower = role_title.lower()
    text = f"{role_title}\n{jd_text}".lower()

    if any(term in title_lower for term in ["product", "product analyst", "product manager", "strategy"]):
        return "ai_product"
    if any(term in title_lower for term in ["consultant", "advisory"]):
        return "consulting"
    if any(term in title_lower for term in ["risk", "compliance", "governance", "fraud"]):
        return "risk_analytics"
    if any(term in title_lower for term in ["research scientist", "research engineer", "researcher"]):
        return "research"
    if any(term in title_lower for term in ["data scientist", "data science"]):
        return "data_science"
    if any(term in title_lower for term in ["operator", "chief of staff", "founder", "growth"]):
        return "operator_startup"
    if any(term in title_lower for term in ["engineer", "developer"]):
        return "technical"

    if any(term in text for term in ["research scientist", "research engineer", "paper", "evaluation"]):
        return "research"
    if any(term in text for term in ["risk", "compliance", "fraud", "governance", "model risk"]):
        return "risk_analytics"
    if any(term in text for term in ["consult", "client", "advisory", "strategy consulting"]):
        return "consulting"
    if any(term in text for term in ["operator", "founder", "chief of staff", "growth", "gtm"]):
        return "operator_startup"
    if any(term in text for term in ["data scientist", "forecasting", "experimentation", "statistics"]):
        return "data_science"
    if any(term in text for term in ["product", "roadmap", "pm", "user adoption", "go-to-market"]):
        return "ai_product"
    if any(term in text for term in ["engineer", "python", "infrastructure", "llm", "agent", "rag"]):
        return "technical"
    return "ai_product"


# ---------------------------------------------------------------------------
# New extraction helpers
# ---------------------------------------------------------------------------


def _extract_salary(text: str) -> dict[str, Any]:
    """Extract salary range from JD text.

    Handles patterns like:
      $80,000 - $120,000  |  $80K-$120K  |  80k to 120k
      $40-$60/hr  |  $150,000 annually  |  $80,000-120,000/year
    """
    result: dict[str, Any] = {
        "min_salary": None,
        "max_salary": None,
        "currency": "USD",
        "period": "annual",
    }

    lower = text.lower()

    # Detect period from context
    is_hourly = False
    # Range pattern:  $80,000 - $120,000  or  $80K-120K  or  80k to 120k
    range_pat = re.compile(
        r"\$?\s*(\d[\d,]*\.?\d*)\s*[kK]?\s*(?:[-–—]|to)\s*\$?\s*(\d[\d,]*\.?\d*)\s*[kK]?"
        r"(?:\s*(?:/\s*(?:yr|year|annual|annum|hr|hour|mo|month)|\s+(?:per\s+(?:year|hour|month|annum)|annually|hourly|monthly)))?",
        re.IGNORECASE,
    )

    # Single value:  $150,000 annually  |  $50/hr
    single_pat = re.compile(
        r"\$\s*(\d[\d,]*\.?\d*)\s*[kK]?"
        r"(?:\s*(?:/\s*(?:yr|year|annual|annum|hr|hour|mo|month)|\s+(?:per\s+(?:year|hour|month|annum)|annually|hourly|monthly)))?",
        re.IGNORECASE,
    )

    def _parse_amount(raw: str, surrounding: str, period: str) -> int:
        """Convert a captured number string to an integer, handling K suffix."""
        clean = raw.replace(",", "").strip()
        val = float(clean)
        # Check if the original surrounding text had K/k right after the number
        if re.search(re.escape(raw) + r"\s*[kK]", surrounding):
            val *= 1000
        return int(val)

    def _detect_period(match_text: str) -> str:
        mt = match_text.lower()
        if any(tok in mt for tok in ["/hr", "/hour", "per hour", "hourly"]):
            return "hourly"
        if any(tok in mt for tok in ["/mo", "/month", "per month", "monthly"]):
            return "monthly"
        return "annual"

    range_match = range_pat.search(text)
    if range_match:
        full = range_match.group(0)
        period = _detect_period(full)
        raw_min = range_match.group(1)
        raw_max = range_match.group(2)
        min_val = _parse_amount(raw_min, full, period)
        max_val = _parse_amount(raw_max, full, period)
        if period == "hourly":
            min_val *= 2080
            max_val *= 2080
        elif period == "monthly":
            min_val *= 12
            max_val *= 12
        result["min_salary"] = min(min_val, max_val)
        result["max_salary"] = max(min_val, max_val)
        result["period"] = period
        return result

    single_match = single_pat.search(text)
    if single_match:
        full = single_match.group(0)
        period = _detect_period(full)
        raw_val = single_match.group(1)
        val = _parse_amount(raw_val, full, period)
        if period == "hourly":
            val *= 2080
        elif period == "monthly":
            val *= 12
        result["min_salary"] = val
        result["max_salary"] = val
        result["period"] = period
        return result

    return result


def _extract_visa_info(text: str) -> dict[str, Any]:
    """Detect visa/sponsorship stance from JD text."""
    lower = text.lower()
    signals: list[str] = []
    sponsors: bool | None = None
    blocked = False

    positive = [
        "visa sponsorship available",
        "will sponsor",
        "can sponsor",
        "sponsorship is available",
        "open to sponsoring",
        "provide sponsorship",
        "offers visa sponsorship",
    ]
    negative = [
        "no visa sponsorship",
        "not sponsor",
        "unable to sponsor",
        "without sponsorship",
        "must be authorized to work",
        "must be legally authorized",
        "no sponsorship",
        "will not sponsor",
        "cannot sponsor",
        "does not sponsor",
        "not able to sponsor",
        "u.s. citizen",
        "us citizen",
        "permanent resident",
        "green card",
    ]

    for phrase in positive:
        if phrase in lower:
            signals.append(phrase)
            sponsors = True

    for phrase in negative:
        if phrase in lower:
            signals.append(phrase)
            sponsors = False
            blocked = True

    # Ambiguous: mentions visa/authorization without clear stance
    if sponsors is None and not blocked:
        if any(tok in lower for tok in ["visa", "authorization", "work authorization", "sponsorship"]):
            signals.append("ambiguous_mention")

    return {"sponsors": sponsors, "blocked": blocked, "signals": signals}


def _extract_years_required(text: str) -> dict[str, Any]:
    """Extract years-of-experience requirements."""
    result: dict[str, Any] = {"min_years": None, "max_years": None, "raw_text": ""}

    patterns = [
        # "3-5 years" / "3 to 5 years"
        re.compile(r"(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*\+?\s*years?\b", re.IGNORECASE),
        re.compile(r"(\d{1,2})\s+to\s+(\d{1,2})\s*\+?\s*years?\b", re.IGNORECASE),
        # "3+ years"
        re.compile(r"(\d{1,2})\s*\+\s*years?\b", re.IGNORECASE),
        # "minimum 3 years" / "at least 3 years"
        re.compile(r"(?:minimum|at\s+least|min\.?)\s*(\d{1,2})\s*\+?\s*years?\b", re.IGNORECASE),
        # "5 years of experience"
        re.compile(r"(\d{1,2})\s*years?\s+(?:of\s+)?experience", re.IGNORECASE),
    ]

    for pat in patterns:
        m = pat.search(text)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                result["min_years"] = int(groups[0])
                result["max_years"] = int(groups[1])
            else:
                result["min_years"] = int(groups[0])
            result["raw_text"] = m.group(0).strip()
            break

    return result


def _extract_education(text: str) -> dict[str, Any]:
    """Extract education requirements from JD text."""
    result: dict[str, Any] = {
        "min_degree": None,
        "preferred_degree": None,
        "fields": [],
    }

    lower = text.lower()

    degree_map = [
        (["phd", "ph.d", "doctorate", "doctoral"], "PhD"),
        (["mba"], "MBA"),
        (["master's", "masters", "master of", "ms/ma", "ms ", "m.s.", "m.a."], "Master's"),
        (["bachelor's", "bachelors", "bachelor of", "bs/ba", "bs ", "b.s.", "b.a.", "undergraduate degree"], "Bachelor's"),
        (["associate's", "associates", "associate of", "associate degree"], "Associate's"),
    ]

    # Preferred degree detection
    preferred_context = ""
    for line in text.splitlines():
        ll = line.lower()
        if any(tok in ll for tok in ["preferred", "bonus", "nice to have", "plus", "ideally"]):
            preferred_context += " " + ll

    found_degrees: list[str] = []
    for triggers, label in degree_map:
        for trigger in triggers:
            if trigger in lower:
                if label not in found_degrees:
                    found_degrees.append(label)
                break

    # The highest degree mentioned in preferred context
    for triggers, label in degree_map:
        for trigger in triggers:
            if trigger in preferred_context.lower():
                result["preferred_degree"] = label
                break
        if result["preferred_degree"]:
            break

    # Min degree is the lowest degree mentioned overall (required)
    if found_degrees:
        # Use the last one found (lowest in hierarchy)
        result["min_degree"] = found_degrees[-1]
        # If there's a preferred, min is the next lower
        if result["preferred_degree"] and len(found_degrees) > 1:
            for d in reversed(found_degrees):
                if d != result["preferred_degree"]:
                    result["min_degree"] = d
                    break

    # Field detection
    field_patterns = [
        (r"(?:in|of)\s+computer\s+science", "Computer Science"),
        (r"(?:in|of)\s+(?:data\s+science)", "Data Science"),
        (r"(?:in|of)\s+(?:machine\s+learning|ml|artificial\s+intelligence|ai)", "Machine Learning / AI"),
        (r"(?:in|of)\s+(?:statistics|mathematics|math)", "Statistics / Mathematics"),
        (r"(?:in|of)\s+(?:business(?:\s+administration)?|finance|economics)", "Business"),
        (r"(?:in|of)\s+(?:information\s+(?:systems|technology))", "Information Systems"),
        (r"(?:in|of)\s+(?:engineering)", "Engineering"),
        (r"\bstem\b", "STEM"),
        (r"(?:in|of)\s+(?:quantitative|analytical)\s+(?:field|discipline)", "Quantitative Field"),
        (r"(?:related|relevant|equivalent)\s+(?:field|discipline|degree)", "Related Field"),
    ]
    fields: list[str] = []
    for pat, label in field_patterns:
        if re.search(pat, lower):
            fields.append(label)
    result["fields"] = fields

    return result


def _extract_work_mode(text: str) -> str:
    """Detect remote / hybrid / onsite work mode."""
    lower = text.lower()

    # Hybrid checks first (often mentions both remote and onsite)
    if any(tok in lower for tok in ["hybrid", "mix of remote", "partial remote", "in-office.*remote", "remote.*in-office"]):
        return "hybrid"

    remote_signals = ["remote", "work from home", "work-from-home", "wfh", "fully remote", "100% remote", "distributed"]
    onsite_signals = ["on-site", "onsite", "on site", "in-office", "in office", "in-person", "office-based"]

    has_remote = any(tok in lower for tok in remote_signals)
    has_onsite = any(tok in lower for tok in onsite_signals)

    if has_remote and has_onsite:
        return "hybrid"
    if has_remote:
        return "remote"
    if has_onsite:
        return "onsite"
    return "unknown"


def _extract_tools(text: str) -> list[str]:
    """Extract known tools/technologies mentioned in text."""
    found: set[str] = set()
    # Tokenize on word boundaries, but also check multi-word tools
    for canonical in _KNOWN_TOOLS:
        # Use word-boundary regex for accurate matching
        pattern = re.compile(r"\b" + re.escape(canonical) + r"\b", re.IGNORECASE)
        if pattern.search(text):
            found.add(canonical)

    # Also check specific abbreviations that may not word-boundary well
    abbrevs = {
        r"\bPBI\b": "Power BI",
        r"\bk8s\b": "Kubernetes",
        r"\bTF\b": "Terraform",
        r"\bGHA\b": "GitHub Actions",
        r"\bSF\b": "Snowflake",
    }
    for pat, canonical in abbrevs.items():
        if re.search(pat, text, re.IGNORECASE):
            found.add(canonical)

    return sorted(found)


def parse_job_description(jd_text: str, company_context: dict[str, Any] | None = None) -> dict[str, Any]:
    company_context = company_context or {}
    title = company_context.get("role", "")
    company = company_context.get("company", "")

    if not title:
        title_match = re.search(r"(?im)^(.*?(analyst|manager|engineer|consultant|scientist|researcher).*)$", jd_text)
        title = title_match.group(1).strip() if title_match else ""

    role_type = classify_role_type(jd_text, title)
    keywords = extract_keywords(jd_text, limit=12)
    preferred = []
    for line in jd_text.splitlines():
        if any(token in line.lower() for token in ["preferred", "bonus", "nice to have", "plus"]):
            preferred.append(line.strip())
    preferred = preferred[:5]

    return {
        "company_name": company,
        "role_title": title,
        "required_skills": keywords[:8],
        "preferred_qualifications": preferred,
        "tone": _detect_tone(jd_text),
        "industry": _detect_industry(jd_text),
        "seniority_level": _detect_seniority(jd_text),
        "role_type": role_type,
        "role_type_label": ROLE_TYPE_LABELS.get(role_type, role_type),
        # New extraction fields
        "salary": _extract_salary(jd_text),
        "visa_info": _extract_visa_info(jd_text),
        "years_required": _extract_years_required(jd_text),
        "education": _extract_education(jd_text),
        "work_mode": _extract_work_mode(jd_text),
        "tools": _extract_tools(jd_text),
    }
