"""Local resume import + conservative extraction for the MCP package.

This path is intentionally zero-maintenance:
  - no hosted API
  - no remote LLM
  - no user API key required

The goal is not a perfect ATS-grade parser. The goal is to extract
enough grounded data from a user's resume so the local MCP agent can:
  1. populate the Instaply profile safely
  2. derive plausible job-search queries without inventing a background
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET



_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_URL_RE = re.compile(r"(https?://[^\s]+|(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?)", re.I)
_PHONE_RE = re.compile(
    r"(?:(?:\+?\d{1,3}[\s\-().]*)?(?:\(?\d{3}\)?[\s\-().]*)\d{3}[\s\-().]*\d{4})"
)
_YEAR_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")
_TITLE_RE = re.compile(
    r"\b(?:senior|sr\.?|junior|jr\.?|lead|principal|staff|associate|assistant|intern)?\s*"
    r"(?:software engineer|data scientist|data analyst|business analyst|"
    r"risk analyst|research assistant|research analyst|machine learning engineer|"
    r"devops engineer|site reliability engineer|product analyst|product manager|"
    r"program manager|project manager|designer|consultant|developer|engineer|"
    r"analyst|scientist|manager|coordinator|specialist|administrator)\b",
    re.I,
)
_SCHOOL_RE = re.compile(
    r"\b(?:university|college|institute|school|polytechnic|academy)\b", re.I
)

_SKILL_PATTERNS: dict[str, list[str]] = {
    "Python": [r"\bpython\b"],
    "SQL": [r"\bsql\b", r"\bpostgres(?:ql)?\b", r"\bmysql\b"],
    "Excel": [r"\bexcel\b"],
    "Tableau": [r"\btableau\b"],
    "Power BI": [r"\bpower\s*bi\b"],
    "R": [r"\br\b"],
    "Java": [r"\bjava\b"],
    "JavaScript": [r"\bjavascript\b"],
    "TypeScript": [r"\btypescript\b"],
    "React": [r"\breact\b"],
    "Node.js": [r"\bnode(?:\.js)?\b"],
    "AWS": [r"\baws\b", r"\bamazon web services\b"],
    "Docker": [r"\bdocker\b"],
    "Kubernetes": [r"\bkubernetes\b", r"\bk8s\b"],
    "Git": [r"\bgit\b"],
    "Machine Learning": [r"\bmachine learning\b"],
    "Deep Learning": [r"\bdeep learning\b"],
    "Data Analysis": [r"\bdata analysis\b", r"\banalytics\b"],
    "Risk Analysis": [r"\brisk analysis\b", r"\brisk analytics\b", r"\brisk management\b"],
    "Automation": [r"\bautomation\b", r"\bworkflow\b"],
    "LLMs": [r"\bllm\b", r"\blarge language model\b", r"\bprompt engineering\b"],
    "NLP": [r"\bnlp\b", r"\bnatural language processing\b"],
    "Statistics": [r"\bstatistics?\b"],
    "A/B Testing": [r"\ba/?b testing\b", r"\bexperiment(?:ation)?\b"],
}


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text_parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)
    return "\n".join(text_parts)


def _extract_docx_text(docx_bytes: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
            xml_bytes = zf.read("word/document.xml")
    except Exception:
        return ""

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", ns):
        parts: list[str] = []
        for node in para.findall(".//w:t", ns):
            if node.text:
                parts.append(node.text)
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def extract_resume_text(*, resume_path: str | None = None, resume_text: str | None = None) -> tuple[str, str | None]:
    if resume_text and resume_text.strip():
        return resume_text.strip(), None
    if not resume_path:
        raise ValueError("Provide either resume_path or resume_text.")

    path = Path(resume_path).expanduser()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Resume file not found: {path}")

    blob = path.read_bytes()
    lower = path.name.lower()
    if lower.endswith(".pdf"):
        text = _extract_pdf_text(blob)
    elif lower.endswith(".docx"):
        text = _extract_docx_text(blob)
    else:
        text = blob.decode("utf-8", errors="ignore")
    return text.strip(), str(path)


def _clean_url(raw: str) -> str:
    u = raw.strip().rstrip(").,;")
    if u.lower().startswith(("http://", "https://")):
        return u
    return "https://" + u


def _extract_name(lines: list[str]) -> str | None:
    for line in lines[:5]:
        s = re.sub(r"\s+", " ", line).strip()
        if not s or len(s) > 60 or any(ch.isdigit() for ch in s) or "@" in s or "http" in s.lower():
            continue
        parts = s.split()
        if 1 < len(parts) <= 4 and all(re.match(r"^[A-Za-z'.-]+$", p) for p in parts):
            return s
    return None


def _extract_first_url(text: str, keyword: str) -> str | None:
    for match in _URL_RE.finditer(text):
        u = match.group(1)
        if keyword.lower() in u.lower():
            return _clean_url(u)
    return None


def _extract_school(lines: list[str]) -> str | None:
    for line in lines:
        if _SCHOOL_RE.search(line):
            return re.sub(r"\s+", " ", line).strip(" -|,")
    return None


def _extract_degree(text: str) -> str | None:
    patterns = [
        (r"\bmaster(?:'s)?\b|\bm\.?s\.?\b|\bmba\b|\bma\b", "Master's"),
        (r"\bbachelor(?:'s)?\b|\bb\.?s\.?\b|\bba\b", "Bachelor's"),
        (r"\bph\.?d\b|\bdoctorate\b", "PhD"),
        (r"\bassociate(?:'s)?\b", "Associate's"),
    ]
    for pattern, value in patterns:
        if re.search(pattern, text, re.I):
            return value
    return None


def _extract_major(lines: list[str]) -> str | None:
    for line in lines:
        lowered = line.lower()
        if not any(token in lowered for token in ("major", "degree", "bachelor", "master", "bs", "ms", "mba")):
            continue
        cleaned = re.sub(r"\s+", " ", line).strip()
        match = re.search(
            r"(?:in|major:?|degree:?|concentration:?|specialization:?)[\s:]+([A-Za-z&/,\- ]{4,80})",
            cleaned,
            re.I,
        )
        if match:
            return match.group(1).strip(" -|,")
    return None


def _extract_titles(text: str) -> list[str]:
    seen: list[str] = []
    for match in _TITLE_RE.finditer(text):
        title = re.sub(r"\s+", " ", match.group(0)).strip()
        title = title.title().replace("Sr.", "Sr").replace("Jr.", "Jr")
        if title not in seen:
            seen.append(title)
    return seen[:8]


def _extract_skills(text: str) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    for skill, patterns in _SKILL_PATTERNS.items():
        if any(re.search(pattern, lowered, re.I) for pattern in patterns):
            found.append(skill)
    return found


def _estimate_experience_years(text: str) -> int | None:
    years = sorted({int(y) for y in _YEAR_RE.findall(text)})
    if len(years) < 2:
        return None
    span = years[-1] - years[0]
    if span <= 0 or span > 40:
        return None
    return span


def _extract_summary(titles: list[str], skills: list[str], school: str | None) -> str | None:
    if not titles and not skills:
        return None
    lead = f"Experience includes {', '.join(titles[:2])}" if titles else "Resume highlights parsed locally"
    tail_parts: list[str] = []
    if skills:
        tail_parts.append("skills like " + ", ".join(skills[:4]))
    if school:
        tail_parts.append(f"education at {school}")
    tail = " and ".join(tail_parts)
    return f"{lead}{' with ' + tail if tail else ''}."


def _infer_role_targets(titles: list[str], skills: list[str], major: str | None, summary: str | None) -> list[str]:
    targets: list[str] = []

    def add(title: str) -> None:
        if title and title not in targets:
            targets.append(title)

    for title in titles[:4]:
        add(title)

    skill_set = {s.lower() for s in skills}
    major_l = (major or "").lower()
    summary_l = (summary or "").lower()

    if {"python", "sql"} <= skill_set and ("data analysis" in skill_set or "analytics" in major_l or "analyst" in summary_l):
        add("Data Analyst")
    if {"python", "sql"} <= skill_set and ("machine learning" in skill_set or "data scientist" in summary_l):
        add("Data Scientist")
    if "risk analysis" in skill_set or "risk" in major_l:
        add("Risk Analyst")
    if {"javascript", "react"} <= skill_set or "software engineer" in summary_l:
        add("Software Engineer")
    if ("aws" in skill_set or "docker" in skill_set) and ("kubernetes" in skill_set or "devops" in summary_l):
        add("DevOps Engineer")
    if "product manager" in summary_l:
        add("Product Manager")

    if not targets:
        if "analytics" in major_l or "data" in major_l:
            add("Data Analyst")
        elif "computer science" in major_l or "software" in major_l:
            add("Software Engineer")
        elif major:
            add(major.strip())

    return targets[:5]


def analyze_resume_text(text: str) -> dict[str, Any]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]

    email = _EMAIL_RE.search(normalized)
    phone = _PHONE_RE.search(normalized)
    linkedin = _extract_first_url(normalized, "linkedin")
    github = _extract_first_url(normalized, "github")
    portfolio = None
    for match in _URL_RE.finditer(normalized):
        url = _clean_url(match.group(1))
        lower = url.lower()
        if "linkedin" in lower or "github" in lower:
            continue
        portfolio = url
        break

    name = _extract_name(lines)
    school = _extract_school(lines)
    degree = _extract_degree(normalized)
    major = _extract_major(lines)
    skills = _extract_skills(normalized)
    titles = _extract_titles(normalized)
    exp_years = _estimate_experience_years(normalized)
    summary = _extract_summary(titles, skills, school)
    role_targets = _infer_role_targets(titles, skills, major, summary)

    return {
        "full_name": name,
        "email": email.group(0) if email else None,
        "phone": phone.group(0).strip() if phone else None,
        "linkedin_url": linkedin,
        "github_url": github,
        "portfolio_url": portfolio,
        "resume_text": normalized[:20000],
        "resume_text_excerpt": normalized[:4000],
        "extracted_skills": {
            "skills": skills,
            "experience_years": exp_years,
            "education": {
                "degree": degree,
                "major": major,
                "school": school,
            },
            "industries": [],
            "titles_held": titles,
            "certifications": [],
            "summary": summary,
            "role_targets": role_targets,
        },
        "school": school,
        "degree": degree,
        "major": major,
        "years_experience": exp_years,
        "current_title": titles[0] if titles else None,
    }


