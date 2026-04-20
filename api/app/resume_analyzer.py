"""Resume analysis — extract text + LLM skill extraction via Cerebras.

Flow:
  1. POST /profile/analyze-resume (authenticated)
  2. Download user's primary resume PDF from Supabase Storage
  3. Extract raw text from PDF using PyPDF2
  4. Call Cerebras (llama-3.3-70b) to extract structured skills/experience
  5. Store resume_text + extracted_skills on the profile row
  6. Return the extracted skills to the frontend

The extracted_skills JSON shape:
{
  "skills": ["Python", "SQL", "Excel", "Risk Analysis", ...],
  "experience_years": 3,
  "education": {"degree": "MS", "major": "Data Science", "school": "NYU"},
  "industries": ["fintech", "banking", "consulting"],
  "titles_held": ["Data Analyst", "Research Assistant"],
  "certifications": ["CFA Level 1"],
  "summary": "Data analyst with 3 years in fintech..."
}
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from xml.etree import ElementTree as ET

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import current_user_id
from .config import settings
from .db import service_client
from .ratelimit import rate_limit

log = logging.getLogger("resume_analyzer")

router = APIRouter(tags=["profile"])

CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"

EXTRACTION_PROMPT = """You are a conservative resume analysis expert. Extract the following from this resume text and return ONLY valid JSON, no markdown, no explanation.

Rules:
- Use ONLY facts explicitly supported by the resume text.
- If a field is not clearly stated, return null (or [] for lists), do not guess.
- Do NOT infer a major or field of study from skills, tools, or job titles.
- Do NOT infer a computer-science or software-engineering background unless the resume text clearly states it.
- For experience_years, prefer a conservative lower-bound estimate from clearly dated professional experience. If unclear, return null.
- Keep the summary factual and grounded in the resume text only.

{
  "skills": ["list of technical and soft skills mentioned"],
  "experience_years": <number or null>,
  "education": {"degree": "<highest degree or null>", "major": "<field of study or null>", "school": "<university name or null>"},
  "industries": ["list of industries the person has worked in"],
  "titles_held": ["list of job titles held"],
  "certifications": ["list of certifications or licenses"],
  "summary": "<1-2 sentence factual professional summary or null>"
}

Resume text:
---
{resume_text}
---

Return ONLY the JSON object. No markdown code blocks, no explanation."""


async def _call_cerebras(prompt: str) -> str:
    """Call Cerebras LLM for resume analysis."""
    api_key = settings.cerebras_api_key or ""
    if not api_key:
        # Fall back to OPENAI_API_KEY which might be set to Cerebras key
        import os
        api_key = os.getenv("OPENAI_API_KEY", "")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            CEREBRAS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                # Cerebras returns 404 for `llama-3.3-70b` on this account
                # (only `llama3.1-8b` and `qwen-3-235b-a22b-instruct-2507`
                # are entitled — verified live on 2026-04-19 and previously
                # in worker/autofill/llm.py). Match the worker's primary
                # model so resume analysis and autofill grounding stay
                # in sync on the same Cerebras tier.
                "model": "qwen-3-235b-a22b-instruct-2507",
                "messages": [
                    {"role": "system", "content": "You extract structured data from resumes. Always return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 1024,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes."""
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text_parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)
    return "\n".join(text_parts)


def _extract_docx_text(docx_bytes: bytes) -> str:
    """Extract visible text from a DOCX payload without extra dependencies."""
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


def _extract_resume_text(file_name: str, blob: bytes) -> str:
    lower = (file_name or "").lower()
    if lower.endswith(".pdf"):
        return _extract_pdf_text(blob)
    if lower.endswith(".docx"):
        return _extract_docx_text(blob)
    try:
        return blob.decode("utf-8", errors="ignore")
    except Exception:
        return ""


@router.post("/profile/analyze-resume")
async def analyze_resume(
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("analyze_resume", per_min=5),
):
    """Download user's resume, extract text, analyze with LLM, save skills."""
    db = service_client()

    # 1. Find primary resume
    resume_resp = (
        db.table("resumes")
        .select("storage_path, file_name")
        .eq("user_id", user_id)
        .eq("is_primary", True)
        .limit(1)
        .execute()
    )
    if not resume_resp.data:
        raise HTTPException(404, "No resume uploaded. Upload a resume first.")

    storage_path = resume_resp.data[0]["storage_path"]
    file_name = resume_resp.data[0]["file_name"]

    # 2. Download from Supabase Storage
    try:
        resume_bytes = db.storage.from_("resumes").download(storage_path)
    except Exception as e:
        log.error("Failed to download resume %s: %s", storage_path, e)
        raise HTTPException(500, "Could not download resume file")

    # 3. Extract text
    resume_text = _extract_resume_text(file_name, resume_bytes)

    if not resume_text or len(resume_text) < 50:
        raise HTTPException(400, "Could not extract text from resume. Try uploading a different format.")

    # 4. Call Cerebras for skill extraction
    prompt = EXTRACTION_PROMPT.replace("{resume_text}", resume_text[:4000])
    try:
        llm_response = await _call_cerebras(prompt)
        # Parse the JSON response
        # Strip markdown code blocks if present
        cleaned = llm_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            cleaned = cleaned.rsplit("```", 1)[0] if "```" in cleaned else cleaned
        extracted = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("LLM returned invalid JSON: %s", llm_response[:200])
        # Try to salvage partial data
        extracted = {"skills": [], "summary": "Analysis failed — please retry"}
    except Exception as e:
        log.error("Cerebras analysis failed: %s", e)
        raise HTTPException(500, f"Resume analysis failed: {e}")

    # 5. Save to profile
    db.table("profiles").update({
        "resume_text": resume_text[:10000],  # cap at 10k chars
        "extracted_skills": extracted,
    }).eq("id", user_id).execute()

    log.info("Resume analyzed for user %s: %d skills extracted", user_id[:8], len(extracted.get("skills", [])))

    return {
        "ok": True,
        "file_name": file_name,
        "text_length": len(resume_text),
        "extracted": extracted,
    }


@router.get("/profile/skills")
async def get_skills(
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("get_skills", per_min=60),
):
    """Return the user's extracted skills (for search scoring)."""
    db = service_client()
    resp = (
        db.table("profiles")
        .select("extracted_skills")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not resp.data:
        return {"extracted_skills": {}}
    return {"extracted_skills": resp.data.get("extracted_skills") or {}}
