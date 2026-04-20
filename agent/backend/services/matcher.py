from __future__ import annotations

import re
from collections import Counter
from typing import Any


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "will",
    "have", "about", "role", "team", "work", "years", "year", "experience",
    "our", "you", "are", "who", "all", "job", "using", "their", "across",
    "www", "com", "etc", "monday", "built", "summary", "generated", "description",
    "requirement", "requirements", "preferred", "ability", "strong", "knowledge",
    "understanding", "ideal", "candidate", "including", "professional", "services",
    "organization", "please", "note",
    # Additional noise words that dilute ATS keyword extraction
    "may", "also", "such", "well", "new", "one", "two", "per", "other",
    "working", "related", "required", "skills", "looking", "join", "help",
    "within", "must", "should", "could", "would", "can", "been", "being",
    "more", "than", "each", "how", "what", "when", "where", "which",
    "them", "they", "these", "those", "some", "any", "both", "own",
    "take", "make", "like", "need", "use", "way", "most", "time",
    "part", "good", "great", "best", "high", "key", "open", "full",
    "based", "level", "type", "area", "various", "ensure", "support",
    "provide", "develop", "manage", "maintain", "create", "lead",
    "opportunities", "opportunity", "position", "company", "business",
    "environment", "relevant", "responsible", "responsibilities",
    "qualified", "qualifications", "minimum", "bachelor", "degree",
    "master", "equivalent", "equal", "employer",
}

POSITIVE_VISA_PHRASES = [
    "visa sponsorship",
    "sponsor visas",
    "sponsorship available",
    "will sponsor",
    "can sponsor",
]

NEGATIVE_VISA_PHRASES = [
    "no visa sponsorship",
    "not sponsor visas",
    "do not sponsor visas",
    "do not provide visa sponsorship",
    "unable to sponsor",
    "cannot sponsor",
    "not eligible for visa sponsorship",
    "no immigration sponsorship",
    "must have permanent work authorization",
    "must be authorized to work in the united states without sponsorship",
    "without current or future sponsorship",
]

BLOCKED_TITLE_TERMS = {
    "account executive",
    "sales",
    "salesforce",
    "recruiter",
    "recruiting",
    "talent acquisition",
    "talent",
    "business development",
    "partnerships",
    "customer success",
    "account manager",
    "account management",
    "legal counsel",
    "counsel",
    "attorney",
    "financial consultant",
    "compensation",
    "benefits",
    "payroll",
    "account development",
}

IRRELEVANT_FUNCTION_TITLE_TERMS = {
    "policy",
    "people analyst",
    "people ",
    "accountant",
    "accounting",
    "admin",
    "crew member",
    "document review",
    "venue",
    "client services",
    "client service center",
    "customer service",
    "customer support",
    "community support",
    "member support",
    "support specialist",
    "support engineer",
    "designer",
    "design",
    "security engineer",
    "application security",
    "infrastructure engineer",
    # REMOVED (core fit — author-specific): "ml infrastructure", "machine learning systems engineer",
    # "research engineer", "scientist", "data scientist" — these are his target roles
    "software engineer",
    "executive assistant",
    "brand",
    "communications",
    "comms",
    "marketing",
    "researcher",
    "fellow",
    "evangelist",
    "legal operations",
    "crisis management",
    "safety",
    "biological",
    # Additional irrelevant roles — not analyst/data/consulting
    "av associate",
    "audiovisual",
    "audio visual",
    "warehouse",
    "materials",
    "repair",
    "maintenance",
    "custodian",
    "janitor",
    "driver",
    "dispatcher",
    "nurse",
    "nursing",
    "physician",
    "pharmacist",
    "pharmacy",
    "clinical",
    "therapist",
    "counselor",
    "social worker",
    "teacher",
    "instructor",
    "professor",
    "inclusion",
    "diversity",
    "dei ",
    "chef",
    "cook",
    "barista",
    "bartender",
    "host",
    "hostess",
    "cashier",
    "teller",
    "real estate agent",
    "property manager",
    "leasing",
    "mechanic",
    "technician",
    "electrician",
    "plumber",
    "hvac",
    "construction",
    "forklift",
    "shipping",
    "receiving",
    "freight",
    "landscaping",
    "security guard",
    "patrol",
    "paralegal",
    "legal analyst",
    "legal assistant",
    "reporter",
    "journalist",
    "editor",
    "copywriter",
    "content writer",
    "graphic designer",
    "ux designer",
    "ui designer",
    "photographer",
    "videographer",
    "social media",
    # Niche/physical operations roles
    "global operations specialist",
    "global operations associate",
    "ocean operations",
    "freight operations",
    "supply chain",
    "customs",
    "import export",
    "logistics",
    "procurement",
    "grains",
    "oilseeds",
    "commodities trader",
    "trading analyst",
    "personal accounts",
    "workplace mental health",
    "mental health",
    "chaplain",
    "veterinarian",
    "dental",
    "optometrist",
    "radiologist",
    "phlebotomist",
    "medical assistant",
    "surgical",
    "anesthesiologist",
    "physical therapist",
    "occupational therapist",
    "speech therapist",
    # Facilities / ops roles that aren't business ops
    "facilities",
    "fleet",
    "field technician",
    "field engineer",
    "site reliability",
    "sre ",
    "devops",
    "network engineer",
    "systems administrator",
    "sysadmin",
    "help desk",
    "desktop support",
    "it support",
    "release engineer",
    "build engineer",
    "test engineer",
    "qa engineer",
    "quality engineer",
    # Delivery/courier type roles
    "courier",
    "delivery driver",
    "delivery associate",
    # IT/ERP-specific roles (not business analyst)
    "sap ",
    "sap analyst",
    "erp ",
    "workday hcm",
    "hris analyst",
    "hris ",
    "workday analyst",
    "netsuite administrator",
    "salesforce administrator",
    "inbound transportation",
    "outbound transportation",
    # Sales development
    "account development representative",
    "sales development",
    "sdr",
    "bdr",
    "business development representative",
    "demand generation",
    "lead generation",
    # HR-domain roles — consistently ATS-rejected; not a profile fit
    "hr operations",
    "hr analyst",
    "hr coordinator",
    "hr specialist",
    "human resources analyst",
    "human resources operations",
    "human resources coordinator",
    "analyst relations",
    "investor relations",
    "media relations",
    # Niche domain analyst roles — ATS rejects consistently
    "asset servicing",
    "payment integrity",
    "property operations",
    "content operations",
    "content specialist",
    "content strategist",
    "structured finance analyst",
    "capital markets analyst",
    "capital markets associate",
    "payments analyst",
    "payments business analyst",
    "credit analyst",
    "mortgage analyst",
    "loan analyst",
    "underwriter",
    "underwriting",
    "actuarial",
    "actuary",
    "claims analyst",
    "claims adjuster",
    "insurance analyst",
    "medical billing",
    "billing analyst",
    "collections analyst",
    "accounts receivable",
    "accounts payable",
    "tax analyst",
    "tax associate",
    "audit associate",
    "internal audit",
    "external audit",
    "treasury analyst",
}

PREFERRED_EARLY_CAREER_TITLE_TERMS = {
    "analyst",
    "analytics",
    "data",
    "business systems",
    "business analyst",
    "data analyst",
    "analytics analyst",
    "operations analyst",
    "financial analyst",
    "finance analyst",
    "risk",
    "consultant",
    "consulting",
    "solutions consultant",
    "solutions analyst",
    "delivery consultant",
    "delivery",
    "associate",
    "operations",
    "strategy",
    "strategy & operations",
    "strategy and operations",
    "business operations",
    "revenue operations",
    "go to market",
    "gtm",
    "product analyst",
    "product strategy",
    # REMOVED generic "implementation" terms — only accept if AI-flavored.
    # Kept AI-specific ones below; generic implementation roles will no longer
    # get the +0.10 preferred-title boost.
    "ai implementation",
    "ai implementation consultant",
    "ai consultant",
    "ai solutions consultant",
    "ai solutions analyst",
    "customer solutions",
    "advisory",
}

FOREIGN_REGION_MARKERS = {
    "apac",
    "australia",
    "canada",
    "costa rica",
    "emea",
    "estagio",
    "estágio",
    "france",
    "mexico",
    "india",
    "korea",
    "berlin",
    "germany",
    "montreal",
    "noida",
    "tokyo",
    "japan",
    "sao paulo",
    "são paulo",
    "brazil",
    "vancouver",
    "british columbia",
    "bc,",
    "bc ",
    "london",
    "uk",
    "europe",
}

US_REGION_MARKERS = {
    "united states",
    "united states of america",
    "usa",
    "u.s.",
    "us only",
    "remote - usa",
    "remote usa",
    "remote us",
    "new york",
    "new york city",
    "new jersey",
    "jersey city",
    "hoboken",
    "san francisco",
    "california",
    "chicago",
    "illinois",
    "maryland",
    "massachusetts",
    "texas",
    "florida",
    "colorado",
    "virginia",
    "washington",
    "washington dc",
    "dc",
    "ny",
    "nj",
    "ca",
}

SENIOR_TITLE_TERMS = {
    "senior",
    "sr ",
    "sr.",
    "principal",
    "staff",
    "lead",
    "head",
    "director",
    "vp",
    "vice president",
    "chief",
    "manager",
    "architect",
}

ENTRY_LEVEL_MAX_YEARS = 3

KNOWN_SPONSOR_FRIENDLY_COMPANIES = {
    "anthropic",
    "openai",
    "figma",
    "notion",
    "cohere",
    "scale ai",
    "scaleai",
    "runway",
    "perplexity",
    "monday.com",
    "monday",
    "databricks",
    "ramp",
    "rippling",
    "plaid",
    "hubspot",
    "snowflake",
    "airbnb",
    "capital one",
    "stripe",
    "brex",
    "chime",
    "robinhood",
    "coinbase",
    "sofi",
    "block",
    "asana",
    "atlassian",
}

ROLE_FAMILY_KEYWORDS = {
    "ai_product": ["product", "pm", "strategy", "analyst", "ai product", "product analytics", "operations", "business systems"],
    "consulting": ["consultant", "consulting", "advisory", "solutions", "technical consultant", "implementation", "delivery", "customer solutions"],
    "risk_analytics": ["risk", "compliance", "fraud", "governance", "model risk", "controls", "audit"],
    "technical": ["engineer", "developer", "platform", "ml", "machine learning", "ai", "llm", "agent", "solutions architect", "systems"],
    "data_science": ["data scientist", "data science", "experimentation", "analytics", "research", "sql", "business intelligence", "dashboard"],
    "research": ["research", "scientist", "evaluation", "applied scientist"],
    "operator_startup": ["operator", "operations", "chief of staff", "growth", "strategy & operations", "business operations", "revenue operations"],
}


def _classify_role_type_local(jd_text: str, role_title: str = "") -> str:
    title_lower = role_title.lower()
    text = f"{role_title}\n{jd_text}".lower()

    if any(term in title_lower for term in ["product", "product analyst", "product manager", "strategy", "business systems", "operations analyst"]):
        return "ai_product"
    if any(term in title_lower for term in ["consultant", "advisory", "implementation", "delivery", "solutions"]):
        return "consulting"
    if any(term in title_lower for term in ["risk", "compliance", "governance", "fraud", "finance", "financial analyst"]):
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
    if any(term in text for term in ["risk", "compliance", "fraud", "governance", "model risk", "controls", "financial planning", "finance"]):
        return "risk_analytics"
    if any(term in text for term in ["consult", "client", "advisory", "strategy consulting", "implementation", "delivery", "professional services"]):
        return "consulting"
    if any(term in text for term in ["operator", "founder", "chief of staff", "growth", "gtm", "business operations", "strategy & operations"]):
        return "operator_startup"
    if any(term in text for term in ["data scientist", "forecasting", "experimentation", "statistics", "dashboard", "sql", "analytics"]):
        return "data_science"
    if any(term in text for term in ["product", "roadmap", "pm", "user adoption", "go-to-market", "business systems", "stakeholder", "operations"]):
        return "ai_product"
    if any(term in text for term in ["engineer", "python", "infrastructure", "llm", "agent", "rag"]):
        return "technical"
    return "ai_product"


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9\\-\\+]{2,}", text.lower())


def extract_keywords(jd_text: str, limit: int = 8) -> list[str]:
    tokens = [token for token in tokenize(jd_text) if token not in STOPWORDS]
    counts = Counter(tokens)
    # Boost technical/tool terms — ATS systems weight these heavily
    TECHNICAL_TERMS = {
        "python", "sql", "tableau", "excel", "powerbi", "power-bi",
        "aws", "azure", "gcp", "docker", "kubernetes", "terraform",
        "pyspark", "spark", "hadoop", "hive", "databricks", "snowflake",
        "pandas", "numpy", "scikit-learn", "sklearn", "tensorflow", "pytorch",
        "xgboost", "lightgbm", "catboost", "keras",
        "langchain", "llm", "llms", "rag", "nlp", "gpt", "bert",
        "jira", "confluence", "agile", "scrum",
        "etl", "elt", "dbt", "airflow", "kafka", "redis",
        "react", "node", "fastapi", "flask", "django",
        "sas", "spss", "stata", "matlab",
        "git", "ci-cd", "cicd", "github", "gitlab",
        "api", "apis", "rest", "graphql", "microservices",
        "looker", "redshift", "bigquery", "postgresql", "mysql", "mongodb",
        "compliance", "sox", "gaap", "ifrs", "regulatory",
        "forecasting", "regression", "classification", "clustering",
        "a-b-testing", "experimentation", "hypothesis",
    }
    boosted: Counter = Counter()
    for word, count in counts.items():
        boost = 1
        if word in TECHNICAL_TERMS:
            boost = 3  # Technical terms get 3x weight
        boosted[word] = count * boost
    return [word for word, _ in boosted.most_common(limit)]


def extract_required_keywords(jd_text: str, limit: int = 15) -> dict[str, list[str]]:
    """Extract keywords split by required vs preferred sections.

    Returns {"required": [...], "preferred": [...], "all": [...]}
    ATS systems weight required keywords much higher.
    """
    jd_lower = jd_text.lower()

    # Try to split into required vs preferred sections
    required_section = ""
    preferred_section = ""

    # Common section headers
    req_markers = [
        r"(?:required|minimum|must[\s-]have|basic)\s*(?:qualifications?|skills?|requirements?|experience)",
        r"what\s+(?:you['']ll|you\s+will)\s+(?:need|bring)",
        r"what\s+we['']?re?\s+looking\s+for",
    ]
    pref_markers = [
        r"(?:preferred|nice[\s-]to[\s-]have|desired|bonus|additional)\s*(?:qualifications?|skills?|requirements?|experience)?",
        r"what\s+would\s+(?:be\s+)?(?:nice|great|helpful)",
    ]

    for marker in req_markers:
        match = re.search(marker, jd_lower)
        if match:
            start = match.start()
            # Find end of section (next section header or end)
            end = len(jd_text)
            for pref_marker in pref_markers:
                pref_match = re.search(pref_marker, jd_lower[start + 10:])
                if pref_match:
                    end = min(end, start + 10 + pref_match.start())
                    preferred_section = jd_text[start + 10 + pref_match.start():]
                    break
            required_section = jd_text[start:end]
            break

    required_kws = extract_keywords(required_section, limit=limit) if required_section else []
    preferred_kws = extract_keywords(preferred_section, limit=limit) if preferred_section else []
    all_kws = extract_keywords(jd_text, limit=limit)

    # Deduplicate: required takes priority
    seen = set(required_kws)
    preferred_kws = [kw for kw in preferred_kws if kw not in seen]

    return {
        "required": required_kws,
        "preferred": preferred_kws,
        "all": all_kws,
    }


def _visa_language(jd_text: str) -> tuple[bool, bool]:
    jd_lower = jd_text.lower()
    blocked = any(phrase in jd_lower for phrase in NEGATIVE_VISA_PHRASES)
    likely = any(phrase in jd_lower for phrase in POSITIVE_VISA_PHRASES)
    if "visa" in jd_lower or "sponsorship" in jd_lower:
        likely = likely and not blocked
    return likely, blocked


def infer_role_bucket(jd_text: str, profile: dict[str, Any]) -> str:
    text = jd_text.lower()
    if any(term in text for term in ["risk", "compliance", "regulatory", "fraud"]):
        return "risk_analytics"
    if any(term in text for term in ["consult", "strategy", "advisory", "client"]):
        return "consulting"
    if any(term in text for term in ["product", "roadmap", "pm", "growth"]):
        return "ai_product"

    variants = profile.get("summary_variants", {})
    return next(iter(variants.keys()), "general")


def _location_matches(location_text: str, desired_locations: list[str]) -> bool:
    location_lower = str(location_text or "").lower()
    if not desired_locations:
        return True

    us_markers = [
        # Country-level
        "united states", "united states of america", "usa", "u.s.",
        "us only", "remote - usa", "remote usa", "remote - us",
        # Tier 1 cities
        "new york", "los angeles", "chicago", "san francisco", "boston",
        "seattle", "washington, d.c.", "washington dc", "austin", "denver",
        "dallas", "houston", "atlanta", "miami", "philadelphia",
        "san jose", "san diego", "phoenix", "minneapolis", "portland",
        "detroit", "baltimore", "charlotte", "nashville", "raleigh",
        "pittsburgh", "salt lake city", "tampa", "st. louis", "st louis",
        "columbus", "indianapolis", "cleveland", "kansas city", "milwaukee",
        "cincinnati", "orlando", "sacramento", "las vegas", "richmond",
        # Tier 2 cities
        "durham", "boulder", "ann arbor", "madison", "provo",
        "des moines", "omaha", "boise", "tucson", "albuquerque",
        "jacksonville", "memphis", "louisville", "oklahoma city",
        "new orleans", "hartford", "providence", "buffalo", "rochester",
        "birmingham", "knoxville", "greenville", "charleston",
        "savannah", "spokane", "lexington", "tulsa", "little rock",
        "chattanooga", "dayton", "akron", "toledo", "grand rapids",
        "el paso", "bakersfield", "fresno", "stockton", "modesto",
        "huntsville", "pensacola", "gainesville", "tallahassee",
        # Tech hubs
        "silicon valley", "bay area", "research triangle", "palo alto",
        "mountain view", "sunnyvale", "cupertino", "menlo park",
        "santa clara", "redwood city", "berkeley", "oakland",
        "cambridge", "somerville", "bellevue", "redmond", "kirkland",
        "arlington", "mclean", "tysons", "bethesda", "herndon",
        "plano", "irving", "frisco", "round rock", "scottsdale",
        "tempe", "irvine", "santa monica", "venice", "culver city",
        "burbank", "pasadena", "long beach", "anaheim",
        # US states (2-letter)
        ", al", ", ak", ", az", ", ar", ", ca", ", co", ", ct", ", de",
        ", fl", ", ga", ", hi", ", id", ", il", ", in", ", ia", ", ks",
        ", ky", ", la", ", me", ", md", ", ma", ", mi", ", mn", ", ms",
        ", mo", ", mt", ", ne", ", nv", ", nh", ", nj", ", nm", ", ny",
        ", nc", ", nd", ", oh", ", ok", ", or", ", pa", ", ri", ", sc",
        ", sd", ", tn", ", tx", ", ut", ", vt", ", va", ", wa", ", wv",
        ", wi", ", wy",
        # US state names
        "alabama", "alaska", "arizona", "arkansas", "california",
        "colorado", "connecticut", "delaware", "florida", "georgia",
        "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas",
        "kentucky", "louisiana", "maine", "maryland", "massachusetts",
        "michigan", "minnesota", "mississippi", "missouri", "montana",
        "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
        "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
        "pennsylvania", "rhode island", "south carolina", "south dakota",
        "tennessee", "texas", "utah", "vermont", "virginia",
        "washington", "west virginia", "wisconsin", "wyoming",
        "district of columbia",
    ]
    foreign_markers = [
        "australia", "canada", "france", "india", "brazil", "china",
        "mexico", "singapore", "japan", "bangalore", "noida", "tokyo",
        "london", "milan", "rome", "ireland", "sao paulo", "são paulo",
        "tel aviv", "sydney", "europe", "uk", "united kingdom",
        "germany", "berlin", "munich", "spain", "madrid", "barcelona",
        "netherlands", "amsterdam", "portugal", "lisbon", "italy",
        "sweden", "stockholm", "denmark", "copenhagen", "norway", "oslo",
        "finland", "helsinki", "switzerland", "zurich", "dubai", "uae",
        "hong kong", "korea", "seoul", "taiwan", "vietnam", "thailand",
        "bangkok", "philippines", "manila", "indonesia", "jakarta",
        "argentina", "buenos aires", "colombia", "bogota", "chile",
        "santiago", "peru", "lima", "south africa", "nigeria", "kenya",
        "egypt", "cairo", "israel", "poland", "warsaw", "czech",
        "prague", "romania", "bucharest", "hungary", "budapest",
        "turkey", "istanbul", "new zealand", "auckland", "gibraltar",
        "malta", "cyprus", "luxembourg", "austria", "vienna", "belgium",
        "brussels", "emea", "apac", "latam", "mena",
    ]

    if any(marker in location_lower for marker in foreign_markers):
        return False
    desired = [str(loc).lower().strip() for loc in desired_locations if str(loc).strip()]
    if any(loc in location_lower for loc in desired):
        return True
    # "Remote" is only OK if it also mentions US/USA or has no country qualifier
    if "remote" in location_lower:
        # If it says "Remote - <country>" and didn't match foreign above,
        # check if it explicitly mentions US
        if any(marker in location_lower for marker in us_markers):
            return True
        # Generic "remote" with no country — check for disqualifiers
        # like "work from anywhere" (usually means global, not US-only)
        if "anywhere" in location_lower or "worldwide" in location_lower or "global" in location_lower:
            return False
        # Plain "Remote" with no country — allow (assume US company = US remote)
        return True
    if any(marker in location_lower for marker in us_markers):
        return True
    return False


def _has_blocked_title(title: str) -> bool:
    title_lower = str(title or "").lower()
    return any(term in title_lower for term in BLOCKED_TITLE_TERMS)


def _has_senior_title(title: str) -> bool:
    title_lower = f" {str(title or '').lower()} "
    return any(term in title_lower for term in SENIOR_TITLE_TERMS)


def _preferred_title_hits(title: str) -> list[str]:
    title_lower = str(title or "").lower()
    hits = [term for term in PREFERRED_EARLY_CAREER_TITLE_TERMS if term in title_lower]
    return sorted(hits, key=len, reverse=True)


def _has_irrelevant_function_title(title: str) -> bool:
    title_lower = str(title or "").lower()
    if any(term in title_lower for term in IRRELEVANT_FUNCTION_TITLE_TERMS):
        return True
    if "federal" in title_lower and "consultant" in title_lower:
        return True
    if "engineer" in title_lower and "solutions engineer" not in title_lower and "analytics engineer" not in title_lower:
        return True
    if "manager" in title_lower and "program manager" not in title_lower and "product manager" not in title_lower and "engagement manager" not in title_lower:
        return True
    # Physical/logistics operations — not business/data/revenue ops
    _PHYSICAL_OPS_MARKERS = {
        "ocean", "freight", "shipping", "warehouse", "supply chain",
        "fleet", "logistics", "customs", "import", "export",
        "transportation", "trucking", "delivery",
    }
    if "operations" in title_lower and any(marker in title_lower for marker in _PHYSICAL_OPS_MARKERS):
        return True
    # "Global Operations Specialist/Associate" at logistics companies — too generic
    # Block if "operations" is paired only with generic modifiers, not business/data context
    _BUSINESS_OPS_CONTEXT = {
        "data", "business", "revenue", "strategy", "product", "analytics",
        "financial", "ai", "go to market", "gtm", "sales", "marketing",
    }
    if ("operations specialist" in title_lower or "operations associate" in title_lower) and \
       not any(ctx in title_lower for ctx in _BUSINESS_OPS_CONTEXT):
        # Only flag if title is very generic (just "operations specialist/associate" with geographic prefix)
        # Allow through if company context makes it relevant (handled by score)
        pass  # Don't hard-block — handled by weaker preferred title match below
    return False


def _has_foreign_region_marker(title: str, location: str, url: str = "") -> bool:
    text = f"{title} {location} {url}".lower()
    return any(term in text for term in FOREIGN_REGION_MARKERS)


def _has_us_location_signal(location: str) -> bool:
    location_lower = str(location or "").lower()
    if not location_lower:
        return False
    if any(marker in location_lower for marker in FOREIGN_REGION_MARKERS):
        return False
    return any(marker in location_lower for marker in US_REGION_MARKERS) or "remote" in location_lower


def _is_internship_or_coop(title: str) -> bool:
    """Return True if the title is an internship or co-op — these are excluded."""
    title_lower = str(title or "").lower()
    if re.search(r"\bintern\b|\binternship\b|\bco-op\b|\bco op\b|\bcoop\b", title_lower):
        return True
    # "Summer Analyst", "Summer Associate", "Spring Analyst" etc. are internship-style
    if re.search(r"\b(summer|spring|fall|winter)\s+(analyst|associate|fellow|trainee|extern)", title_lower):
        return True
    # Year-tagged early career programs ("Analyst 2027", "Associate Program 2027")
    if re.search(r"\b(analyst|associate)\s+202[5-9]\b", title_lower):
        return True
    return False


def _entry_level_title_fit(title: str) -> bool:
    title_lower = str(title or "").lower()
    # Exclude internships and co-ops — full-time only
    if _is_internship_or_coop(title):
        return False
    strong_terms = {
        "new grad",
        "entry level",
        "early career",
        "analyst",
        "associate",
        "consultant",
        "specialist",
        "coordinator",
        "implementation",
        "operations",
        "strategy",
        "business systems",
        "financial analyst",
        "risk analyst",
        "product analyst",
    }
    return any(term in title_lower for term in strong_terms)


def _generic_qa_title_needs_context(title: str) -> bool:
    title_lower = str(title or "").lower()
    if "quality assurance" not in title_lower and not title_lower.startswith("qa "):
        return False
    allowed_context = {
        "financial crime",
        "compliance",
        "risk",
        "controls",
        "audit",
        "fraud",
        "aml",
        "analytics",
    }
    return not any(term in title_lower for term in allowed_context)


def _desired_role_families(profile: dict[str, Any]) -> set[str]:
    families: set[str] = set()
    for role in profile.get("target_roles", []):
        families.add(_classify_role_type_local("", str(role)))
    return families


def _normalize_company(company: str) -> str:
    return " ".join(str(company or "").strip().lower().split())


def _extract_min_years_required(text: str) -> int | None:
    lowered = str(text or "").lower()
    patterns = [
        r"(\d+)\+?\s*(?:years|year)\s+of\s+experience",
        r"minimum\s+of\s+(\d+)\+?\s*(?:years|year)",
        r"at\s+least\s+(\d+)\+?\s*(?:years|year)",
        r"(\d+)\+?\s*(?:years|year)\s+in\b",
    ]
    hits: list[int] = []
    for pattern in patterns:
        for match in re.findall(pattern, lowered):
            try:
                hits.append(int(match))
            except ValueError:
                continue
    return min(hits) if hits else None


# Domain-mismatch patterns: the title may look generic (e.g. "Analyst") but
# the JD reveals a niche domain the profile has no background in.  When the JD
# text is available, penalise heavily so we don't burn applications on roles
# that will ATS-reject.
_DOMAIN_MISMATCH_JD_SIGNALS = re.compile(
    r"(?:"
    # HR / HRIS / Payroll
    r"hris|human resources information system|workday hcm|peoplesoft"
    r"|adp workforce|ultipro|ceridian|paycom|kronos"
    r"|benefits administration|leave of absence management"
    # Insurance / Claims / Actuarial
    r"|claims processing|claims adjudication|medical coding|icd-10|cpt codes"
    r"|actuarial science|loss reserving|underwriting guidelines"
    # Healthcare billing
    r"|medical billing|revenue cycle management|epic ehr|cerner"
    r"|health information management"
    # Real estate / Property
    r"|property management software|yardi|realpage|appfolio|rent roll"
    r"|tenant relations|leasing operations"
    # Accounting / Audit specific
    r"|cpa required|cpa preferred|gaap accounting|sox compliance testing"
    r"|general ledger reconciliation|journal entries|month.end close"
    r"|audit workpapers|internal controls testing"
    # Tax
    r"|tax filing|tax provision|tax compliance|1099|w-2 processing"
    r"|onesource|vertex tax"
    # Highly specialised finance
    r"|asset servicing|custody operations|fund accounting"
    r"|securities lending|trade settlement|swift messaging"
    r")",
    re.I,
)


def _jd_domain_mismatch(jd_text: str | None) -> bool:
    """Return True if JD text reveals a niche domain that doesn't match profile."""
    if not jd_text:
        return False
    return bool(_DOMAIN_MISMATCH_JD_SIGNALS.search(jd_text))


_USCIS_SPONSOR_NAMES: set[str] | None = None  # lazy-loaded cache


def _load_uscis_sponsor_names() -> set[str]:
    """Load the USCIS H-1B sponsor list once, return as set of normalized names.

    Includes BOTH the company name and per-word tokens so 'amazon' matches
    'Amazon Com Services', 'google' matches 'Google LLC', etc.
    """
    global _USCIS_SPONSOR_NAMES
    if _USCIS_SPONSOR_NAMES is not None:
        return _USCIS_SPONSOR_NAMES
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent.parent / "data" / "uscis_h1b_sponsors.json"
    names: set[str] = set()
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                records = json.load(f)
            for rec in records:
                # Only include companies with meaningful approval counts (>= 3) to
                # avoid false positives from one-off filings.
                if rec.get("total_approvals", 0) < 3:
                    continue
                normed = _normalize_company(rec.get("company") or "")
                if normed and len(normed) >= 3:
                    names.add(normed)
                # Also index first-two-tokens for short-name matching
                # e.g. "amazon com services" -> also "amazon com"
                tokens = normed.split()
                if len(tokens) >= 2:
                    names.add(" ".join(tokens[:2]))
                if len(tokens) >= 1 and len(tokens[0]) >= 4:
                    names.add(tokens[0])
        except Exception:
            pass
    _USCIS_SPONSOR_NAMES = names
    return names


def _company_alignment(company: str, profile: dict[str, Any]) -> tuple[bool, bool]:
    normalized_company = _normalize_company(company)
    target_companies = {_normalize_company(entry) for entry in profile.get("target_companies", [])}
    sponsor_friendly_companies = {
        _normalize_company(entry)
        for entry in profile.get("sponsor_friendly_companies", [])
    } | KNOWN_SPONSOR_FRIENDLY_COMPANIES

    # H-1B history lookup — 82K companies from USCIS
    is_sponsor = normalized_company in sponsor_friendly_companies
    if not is_sponsor and normalized_company:
        uscis_names = _load_uscis_sponsor_names()
        # Direct match
        if normalized_company in uscis_names:
            is_sponsor = True
        else:
            # First-two-token or first-token match (handles "Amazon" vs "Amazon Com Services")
            tokens = normalized_company.split()
            if len(tokens) >= 2 and " ".join(tokens[:2]) in uscis_names:
                is_sponsor = True
            elif tokens and len(tokens[0]) >= 4 and tokens[0] in uscis_names:
                is_sponsor = True

    return normalized_company in target_companies, is_sponsor


def _title_alignment_hits(title: str, families: set[str]) -> list[str]:
    title_lower = str(title or "").lower()
    hits: list[str] = []
    for family in families:
        for term in ROLE_FAMILY_KEYWORDS.get(family, []):
            if term in title_lower:
                hits.append(term)
    seen: set[str] = set()
    deduped: list[str] = []
    for hit in hits:
        if hit not in seen:
            seen.add(hit)
            deduped.append(hit)
    return deduped


# Languages the user speaks — jobs requiring other languages are excluded.
_KNOWN_LANGUAGES = {"english", "hindi", "marathi"}
_FOREIGN_LANGUAGE_REQUIREMENTS = re.compile(
    r"(?:fluency|fluent|proficien|native|bilingual|must speak|required.*language"
    r"|language.*required|ability to speak|speak and write)"
    r"[^.]{0,60}"
    r"(?:mandarin|chinese|cantonese|russian|japanese|korean|french|german"
    r"|spanish|portuguese|arabic|turkish|italian|dutch|polish|thai"
    r"|vietnamese|tagalog|swahili|hebrew)",
    re.I,
)

def _requires_foreign_language(jd_text: str, title: str = "") -> bool:
    """Return True if the JD or title requires a language the user doesn't speak."""
    text = f"{title}\n{jd_text}"
    # Check title first — e.g. "Mandarin-Speaking Analyst"
    title_lower = title.lower()
    for lang in ["mandarin", "chinese", "cantonese", "russian", "japanese",
                 "korean", "french", "german", "spanish", "portuguese",
                 "arabic", "turkish", "italian", "dutch", "hebrew",
                 "polish", "thai", "vietnamese", "tagalog", "swahili"]:
        if lang in title_lower and lang not in _KNOWN_LANGUAGES:
            return True
    # "Bilingual" in title almost always means a non-English language is required
    if "bilingual" in title_lower:
        return True
    # Check JD for language requirements
    return bool(_FOREIGN_LANGUAGE_REQUIREMENTS.search(text))


def match_job(
    jd_text: str,
    profile: dict[str, Any],
    *,
    title: str = "",
    location: str = "",
    company: str = "",
    url: str = "",
) -> dict[str, Any]:
    jd_lower = jd_text.lower()
    keywords = profile.get("keywords", [])
    target_roles = profile.get("target_roles", [])
    locations = profile.get("location", [])
    title_lower = str(title or "").lower()
    desired_families = _desired_role_families(profile)
    title_hits = _title_alignment_hits(title, desired_families)
    internship_title = _is_internship_or_coop(title)
    blocked_title = _has_blocked_title(title)
    senior_title = _has_senior_title(title)
    irrelevant_function_title = _has_irrelevant_function_title(title)
    preferred_title_hits = _preferred_title_hits(title)
    foreign_region = _has_foreign_region_marker(title, location, url)
    location_match = _location_matches(location, locations)
    us_location_signal = _has_us_location_signal(location)
    visa_likely, visa_blocked = _visa_language(jd_text)
    target_company_match, sponsor_company_match = _company_alignment(company, profile)
    min_years_required = _extract_min_years_required(f"{title}\n{jd_text}")
    beyond_entry_level = min_years_required is not None and min_years_required > ENTRY_LEVEL_MAX_YEARS
    entry_level_only = bool(profile.get("entry_level_only", False))
    entry_title_fit = _entry_level_title_fit(title)
    strong_title_alignment = bool(title_hits or preferred_title_hits or entry_title_fit)
    generic_qa_title = _generic_qa_title_needs_context(title)
    foreign_language_required = _requires_foreign_language(jd_text, title)
    domain_mismatch = _jd_domain_mismatch(jd_text)

    keyword_hits = [kw for kw in keywords if kw.lower() in jd_lower]
    def _role_matches_jd(role: str, jd: str) -> bool:
        words = role.lower().split()
        if len(words) >= 2:
            # Multi-word role: require at least 2 consecutive words to match
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i+1]}"
                if bigram in jd:
                    return True
            return False
        else:
            # Single-word role: single word match is fine
            return words[0] in jd if words else False

    role_hits = [role for role in target_roles if _role_matches_jd(role, jd_lower)]
    location_hits = [loc for loc in locations if loc.lower() in jd_lower or loc.lower() in str(location or "").lower()]

    score = 0.15
    score += min(len(keyword_hits) * 0.05, 0.20)
    score += min(len(role_hits) * 0.06, 0.18)
    score += 0.08 if visa_likely else 0.0
    score += 0.12 if target_company_match else 0.0
    # H-1B SPONSORSHIP SIGNAL — applies when profile.requires_sponsorship is true.
    # Strong boost for companies on USCIS H-1B approval list; heavy penalty for no history
    score += 0.18 if sponsor_company_match else -0.15
    score += 0.12 if title_hits else 0.0
    score += 0.10 if preferred_title_hits else -0.18
    score += 0.07 if location_match else -0.10
    score += 0.08 if any(term in jd_lower for term in ["ai", "llm", "machine learning", "nlp"]) else 0.0
    if internship_title:
        score -= 0.50  # Full-time only — no internships or co-ops
    if blocked_title:
        score -= 0.35
    if senior_title:
        score -= 0.30
    if irrelevant_function_title:
        score -= 0.45
    if beyond_entry_level:
        score -= 0.40
    if visa_blocked:
        score -= 0.25
    if foreign_region:
        score -= 0.25
    if not title_hits and title_lower:
        score -= 0.10
    if not strong_title_alignment:
        score -= 0.35
    if entry_level_only and not entry_title_fit:
        score -= 0.20
    if location and not us_location_signal and not location_match:
        score -= 0.20
    if generic_qa_title:
        score -= 0.25
    if domain_mismatch:
        score -= 0.40

    # Salary-floor proxy — avoid roles that overwhelmingly pay under $80K
    # (warehouse, retail, entry-ops, coordinator, associate in non-analytics contexts)
    LOW_SALARY_TITLE_HINTS = (
        "warehouse", "fulfillment", "shipping", "receiving", "picker", "packer",
        "retail", "cashier", "barista", "server", "host ", "hostess",
        "customer service representative", "customer service associate",
        "customer service specialist", "customer service agent",
        # Customer Experience / Success in non-analyst capacity (Associate/Specialist/Rep)
        # — these are consistently support roles, not analyst work
        "customer experience associate", "customer experience specialist",
        "customer experience representative", "customer experience rep ",
        "customer success associate", "customer support associate",
        "customer support specialist", "customer support representative",
        "customer care", "client care", "member services associate",
        "call center", "dispatcher",
        "scheduler", "coordinator", "receptionist", "front desk",
        "concierge", "greeter", "mailroom", "clerk", "janitor", "custodian",
        "security officer", "security guard", "patrol",
        "delivery driver", "driver", "courier",
        "field tech", "field service tech", "installer",
        "inventory control", "inventory associate", "inventory specialist",
        "teller", "personal banker", "bank teller",
        "loan officer", "leasing agent", "leasing consultant",
        "administrative assistant", "office assistant", "admin assistant",
    )
    title_l = title_lower
    if any(hint in title_l for hint in LOW_SALARY_TITLE_HINTS):
        score -= 0.35  # strong penalty — these roles typically pay below $80K

    # Salary-floor from JD — explicit low pay
    import re as _re_salary
    salary_match = _re_salary.search(
        r"\$\s*(\d{1,3}(?:,\d{3})?|\d{2,3})\s*(?:to|-|–|—)\s*\$?\s*(\d{1,3}(?:,\d{3})?|\d{2,3})\s*(?:k\b|thousand|/\s*(?:yr|year))",
        jd_lower, flags=_re_salary.IGNORECASE,
    )
    if salary_match:
        try:
            hi_raw = salary_match.group(2).replace(",", "")
            hi = int(hi_raw)
            if hi < 200:  # "50k to 70k"
                hi *= 1000
            if hi < 80_000:
                score -= 0.30
        except Exception:
            pass

    # Niche-but-relevant role boosts — specific titles to catch
    # These are modern AI-industry roles that don't always match generic patterns
    # but tend to fit a Risk Analytics + AI background. TODO(post-lift): profile-driven.
    NICHE_ROLE_BOOSTS = (
        # AI Safety / Trust & Safety
        "trust and safety", "trust & safety", "safeguards analyst",
        "ai safety", "ai policy", "responsible ai", "ai governance",
        "model policy", "ai evaluator", "red team", "content policy",
        "abuse analyst", "integrity analyst", "platform integrity",
        # Forward-deployed / Solutions (Palantir, Scale AI, Anthropic)
        "forward deployed", "forward-deployed", "deployment engineer",
        "solutions architect", "ai solutions", "solutions engineer",
        "implementation consultant", "ai implementation",
        # Applied / Research (he has 2 peer-reviewed papers)
        "applied ai", "applied research", "applied scientist",
        "ml researcher", "ai researcher", "research scientist",
        "research analyst", "research engineer",
        # AI Strategy / Product (his Fulcrum work)
        "ai strategy", "ai product", "ai operations",
        "genai strategy", "genai product", "llm strategy",
        # Risk Analytics specifics
        "model risk", "model validation", "quantitative risk",
        "financial risk analyst", "enterprise risk",
        "operational risk", "systemic risk",
        # RAG / LLM / embeddings (his published tools)
        "rag engineer", "retrieval augmented", "llm engineer",
        "prompt engineer", "knowledge engineer",
        # Founding roles at AI startups
        "founding engineer", "founding analyst", "founding data",
        "founding product",
        # Go-to-market / Strategy at AI companies
        "go to market", "go-to-market", "gtm engineer",
        "gtm operations", "strategy and operations at",
    )
    niche_hits = [kw for kw in NICHE_ROLE_BOOSTS if kw in title_lower or kw in jd_lower[:2000]]
    if niche_hits:
        # Strong boost, but capped — max +0.20 across all niche hits
        score += min(len(niche_hits) * 0.08, 0.20)

    # ── STRICT TIERED ROLE ALLOWLIST (the user's preferences, 2026-04-19) ──
    # Tier 1: LOVES (highest boost +0.20)
    # Tier 2: GOOD (standard boost +0.10)
    # Tier 3: OK (neutral, no boost)
    # Not in any tier: hard penalty -0.50 → drops below apply threshold

    # TIER 1 — high-priority role keywords (was the original author's
    # explicit favourites; treat as a default and override per-profile).
    TIER1_LOVES = (
        # Applied/Research Scientist family
        "applied scientist", "applied ai scientist", "applied ml scientist",
        "ai scientist", "research scientist", "applied research",
        # AI Product/Business/Strategy (his Fulcrum wheelhouse)
        "ai product analyst", "ai business analyst", "ai product manager",
        "ai strategy", "ai strategist", "ai product",
        "generative ai product", "genai product", "llm product",
    )

    # TIER 2 — Good fit
    TIER2_GOOD = (
        # Data Science
        "data scientist", "associate data scientist", "junior data scientist",
        "decision scientist",
        # Data/Analytics/BI
        "data analyst", "analytics analyst", "bi analyst",
        "business intelligence analyst", "product analyst", "insights analyst",
        "growth analyst", "marketing analyst", "strategy analyst",
        # Risk family
        "risk analyst", "risk analytics", "model risk", "model validation",
        "quantitative risk", "market risk", "credit risk",
        "operational risk", "financial risk analyst", "enterprise risk analyst",
        # Trust & Safety / AI Policy
        "trust and safety", "trust & safety", "safeguards analyst",
        "integrity analyst", "ai policy", "policy analyst",
        "content policy", "platform integrity",
        # Quant
        "quantitative analyst", "quant analyst", "quant researcher",
        "quantitative researcher",
        # Research Analyst (for his published-author profile)
        "research analyst",
        # AI-flavored consultant (only if AI-prefixed)
        "ai consultant", "ai solutions consultant", "ai implementation consultant",
        "ai strategy consultant", "genai consultant",
    )

    # TIER 3 — OK, but keep capped (he said "not too technical")
    TIER3_OK_CAPPED = (
        "ai engineer", "ml engineer", "machine learning engineer",
        "ai research engineer", "ml research engineer",
        "generative ai engineer", "genai engineer",
    )

    # Anti-patterns — even if title LOOKS like a TIER3 role, reject these:
    TOO_TECHNICAL_BLOCKERS = (
        "ml systems engineer", "ml infrastructure", "ml platform engineer",
        "ml ops engineer", "mlops engineer", "ml devops",
        "ai infrastructure", "ai platform engineer", "ai systems engineer",
        "software engineer", "backend engineer", "frontend engineer",
        "full stack", "fullstack", "full-stack",
        "devops", "sre", "site reliability", "reliability engineer",
        "kubernetes", "distributed systems",
    )

    # Determine which tier the title falls into
    tier = 0  # 0 = no tier / not in allowlist
    if any(kw in title_lower for kw in TOO_TECHNICAL_BLOCKERS):
        tier = -1  # explicit block — too technical
    elif any(kw in title_lower for kw in TIER1_LOVES):
        tier = 1
    elif any(kw in title_lower for kw in TIER2_GOOD):
        tier = 2
    elif any(kw in title_lower for kw in TIER3_OK_CAPPED):
        tier = 3

    # Apply tier scoring
    if tier == 1:
        score += 0.20   # Loves it
    elif tier == 2:
        score += 0.10   # Solid fit
    elif tier == 3:
        score += 0.00   # Keep neutral — no boost
        # Cap so it can't easily reach 0.90+ (won't dominate the queue)
        score = min(score, 0.80)
    elif tier == -1:
        score -= 0.60   # Too technical — hard reject
    elif title_lower:   # Has a title but not in any tier
        score -= 0.50   # Hard-no role; profile-driven post-lift

    # Additional guards
    # Generic "Business Analyst" (no AI prefix) = not wanted unless AI-heavy JD
    if "business analyst" in title_lower and "ai business analyst" not in title_lower:
        ai_heavy = sum(
            1 for kw in ("machine learning", "artificial intelligence",
                         "llm", "genai", "model", "python", "ml/ai")
            if kw in jd_lower[:3000]
        )
        if ai_heavy < 2:
            score -= 0.25  # Plain BA needs AI context

    # "Business Systems Analyst" = IT systems config, not analytics
    if "business systems analyst" in title_lower or "systems analyst" in title_lower:
        score -= 0.35

    # Generic "Consultant" needs AI/tech/strategy context
    if ("consultant" in title_lower or "consulting" in title_lower) and tier < 2:
        consultant_ok = any(
            kw in jd_lower[:3000]
            for kw in ("artificial intelligence", "machine learning", "llm",
                       "genai", "data science", "python", "ml ")
        )
        if not consultant_ok:
            score -= 0.50
        for bad in ("real estate", "acumatica", "sap implementation", "workday hcm",
                    "mortgage", "insurance broker", "retail consultant",
                    "commercial cleaning", "hvac", "public sector"):
            if bad in title_lower or bad in jd_lower[:2000]:
                score -= 0.50
                break
    # Penalty when job title contains none of the profile's target role keywords
    if title_lower:
        _any_role_kw_in_title = any(
            token in title_lower
            for role in target_roles
            for token in role.lower().split()
        )
        if not _any_role_kw_in_title:
            score -= 0.15
    if beyond_entry_level:
        score = min(score, 0.35)
    if senior_title:
        score = min(score, 0.30)
    if irrelevant_function_title:
        score = min(score, 0.20)
    if foreign_region:
        score = min(score, 0.20)
    if not strong_title_alignment:
        score = min(score, 0.20)
    if entry_level_only and not entry_title_fit:
        score = min(score, 0.25)
    if location and not us_location_signal and not location_match:
        score = min(score, 0.20)
    if generic_qa_title:
        score = min(score, 0.25)
    if blocked_title:
        score = min(score, 0.10)
    if foreign_language_required:
        score = min(score, 0.10)
    if domain_mismatch:
        score = min(score, 0.30)
    score = round(min(score, 0.95), 2)
    score = max(score, 0.0)

    reasons = []
    if title_hits:
        reasons.append(f"Title alignment: {', '.join(title_hits[:3])}")
    if preferred_title_hits:
        reasons.append(f"Preferred title fit: {', '.join(preferred_title_hits[:3])}")
    if keyword_hits:
        reasons.append(f"Keyword overlap: {', '.join(keyword_hits[:4])}")
    if role_hits:
        reasons.append(f"Role alignment: {', '.join(role_hits[:2])}")
    if location_match and location_hits:
        reasons.append(f"Location fit: {', '.join(location_hits[:2])}")
    elif location and not location_match:
        reasons.append(f"Location mismatch: {location}")
    if target_company_match:
        reasons.append(f"Target company match: {company}")
    elif sponsor_company_match:
        reasons.append(f"Sponsor-friendly company: {company}")
    if visa_likely:
        reasons.append("JD indicates visa sponsorship support")
    elif visa_blocked:
        reasons.append("JD explicitly states no visa sponsorship")
    elif "visa" in jd_lower or "sponsorship" in jd_lower:
        reasons.append("JD mentions visa or sponsorship language")
    if internship_title:
        reasons.append(f"Internship/Co-op excluded (full-time only): {title}")
    if foreign_language_required:
        reasons.append(f"Foreign language required (only know English/Hindi/Marathi): {title}")
    if blocked_title:
        reasons.append(f"Blocked title family detected: {title}")
    if senior_title:
        reasons.append(f"Senior-level title filtered: {title}")
    if irrelevant_function_title:
        reasons.append(f"Irrelevant title family filtered: {title}")
    if foreign_region:
        reasons.append(f"Foreign-region title/location filtered: {title or location}")
    if not strong_title_alignment:
        reasons.append(f"Weak title fit for target entry-level roles: {title}")
    if entry_level_only and not entry_title_fit:
        reasons.append(f"Title does not read as entry-level enough: {title}")
    if generic_qa_title:
        reasons.append(f"Generic QA title without risk/compliance/analytics context: {title}")
    if beyond_entry_level:
        reasons.append(f"Experience requirement too senior: {min_years_required}+ years")
    if domain_mismatch:
        reasons.append(f"JD reveals niche domain mismatch (HR/insurance/real-estate/accounting/tax): {title}")
    if not reasons:
        reasons.append("General overlap with target profile and role family")

    inferred_role = _classify_role_type_local(jd_text, title)
    normalized_role = "ai_product" if inferred_role == "product_strategy" else inferred_role
    return {
        "match_score": score,
        "match_reasons": reasons,
        "top_keywords": extract_keywords(jd_text),
        "role_bucket": normalized_role or infer_role_bucket(jd_text, profile),
        "visa_sponsorship_likely": visa_likely,
        "visa_sponsorship_blocked": visa_blocked,
    }
