"""Confirmation-email verifier.

After submit, we poll the user's inbox for a confirmation email from the
employer. A credit is decremented ONLY when verification succeeds — this
is the financial integrity gate baked into the app.

Two backends:
  GmailVerifier   — user granted Gmail OAuth; we search their inbox via Gmail API
  NullVerifier    — returns False always; for users who haven't connected Gmail yet.
                    In that mode, applications end up status='submitted' and the
                    user can manually mark them 'confirmed' later (credit decrements then).

Matching heuristics (AND of at least two):
  1. Subject or body contains the company name or job title
  2. From-domain matches the company (or a known ATS domain: greenhouse.io,
     hire.lever.co, smartrecruiters.com, ashbyhq.com)
  3. Received in the lookback window (default: 30 minutes after submit)
  4. Body contains positive signal: "received", "application", "thank you",
     "we'll be in touch", "we have received"

A match returns a ConfirmationHit with the message id + snippet for audit.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Protocol

log = logging.getLogger(__name__)


# Known ATS sender domains — if the From domain matches, signal is strong
ATS_SENDER_DOMAINS = {
    "greenhouse.io",
    "hire.greenhouse.io",
    "us.greenhouse-mail.io",
    "lever.co",
    "hire.lever.co",
    "smartrecruiters.com",
    "us.smartrecruiters.com",
    "ashbyhq.com",
    "mail.ashbyhq.com",
    "workday.com",
    "myworkday.com",
    "icims.com",
    "taleo.net",
    "successfactors.com",
}

POSITIVE_TOKENS = (
    "we have received",
    "we received",
    "thank you for applying",
    "thanks for applying",
    "application received",
    "your application",
    "we'll be in touch",
    "we will be in touch",
    "application has been submitted",
    "we appreciate your interest",
)


@dataclass
class ConfirmationHit:
    message_id: str
    from_address: str
    subject: str
    received_at: datetime
    snippet: str
    score: int   # 0-100, for debugging


class EmailVerifier(Protocol):
    def verify(
        self,
        user_email: str,
        company_name: str,
        job_title: str,
        submitted_at: datetime,
        lookback_minutes: int = 30,
    ) -> Optional[ConfirmationHit]: ...


# ─── Null implementation (used when Gmail not connected) ─────────
class NullVerifier:
    def verify(self, user_email, company_name, job_title, submitted_at, lookback_minutes=30):
        return None


# ─── Gmail implementation ────────────────────────────────────────
class GmailVerifier:
    """Uses Gmail API with user-scoped OAuth credentials.

    Pass a `gmail_service` — a googleapiclient.discovery.Resource — built
    from the user's stored OAuth refresh token. We never see plaintext
    passwords; Google auth flow happens in the dashboard.
    """

    def __init__(self, gmail_service):
        self.svc = gmail_service

    def verify(
        self,
        user_email: str,
        company_name: str,
        job_title: str,
        submitted_at: datetime,
        lookback_minutes: int = 30,
    ) -> Optional[ConfirmationHit]:
        # Gmail `after:` queries use epoch seconds
        after_ts = int(submitted_at.timestamp())
        before_ts = int((submitted_at + timedelta(minutes=lookback_minutes)).timestamp())
        # Build a permissive query — we filter precisely in Python
        query = f"after:{after_ts} before:{before_ts}"
        try:
            results = self.svc.users().messages().list(
                userId="me", q=query, maxResults=25
            ).execute()
        except Exception as e:
            log.exception("gmail_list_failed", extra={"err": str(e)})
            return None

        msgs = results.get("messages") or []
        best: Optional[ConfirmationHit] = None
        best_score = 0
        for ref in msgs:
            msg_id = ref.get("id")
            try:
                m = self.svc.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()
            except Exception:
                continue

            headers = _headers_dict(m.get("payload", {}).get("headers", []))
            from_addr = headers.get("From", "")
            subject = headers.get("Subject", "")
            snippet = m.get("snippet", "") or ""
            received = _parse_internal_date(m.get("internalDate"))

            score = _score_match(
                from_addr=from_addr,
                subject=subject,
                snippet=snippet,
                company_name=company_name,
                job_title=job_title,
            )
            if score >= 60 and score > best_score:
                best = ConfirmationHit(
                    message_id=msg_id,
                    from_address=from_addr,
                    subject=subject,
                    received_at=received,
                    snippet=snippet,
                    score=score,
                )
                best_score = score
        return best


# ─── Scoring ────────────────────────────────────────────────────
def _score_match(
    from_addr: str, subject: str, snippet: str, company_name: str, job_title: str
) -> int:
    """Score a single message in [0, 100]. ≥60 considered a match."""
    score = 0
    subj_low = (subject or "").lower()
    snip_low = (snippet or "").lower()
    from_low = (from_addr or "").lower()
    from_domain = _extract_domain(from_low)
    company_low = (company_name or "").lower()
    job_low = (job_title or "").lower()

    # Sender signals (up to 40)
    if from_domain:
        if company_low and company_low.split()[0] in from_domain:
            score += 30
        if from_domain in ATS_SENDER_DOMAINS:
            score += 25
        elif any(from_domain.endswith(d) for d in ATS_SENDER_DOMAINS):
            score += 25

    # Subject signals (up to 30)
    if company_low and company_low in subj_low:
        score += 15
    if job_low and any(tok in subj_low for tok in job_low.split()[:3] if len(tok) > 3):
        score += 10
    if any(p in subj_low for p in ("application", "received", "thank you", "thanks for", "applying")):
        score += 12

    # Body / snippet signals (up to 30)
    body_hits = sum(1 for t in POSITIVE_TOKENS if t in snip_low)
    if body_hits:
        score += min(20, body_hits * 8)
    if company_low and company_low in snip_low:
        score += 10

    return min(100, score)


def _extract_domain(from_addr: str) -> str:
    m = re.search(r"@([\w\.\-]+)", from_addr)
    return m.group(1).lower() if m else ""


def _headers_dict(headers: list) -> dict[str, str]:
    return {h.get("name", ""): h.get("value", "") for h in headers or []}


def _parse_internal_date(ms) -> datetime:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(tz=timezone.utc)


# ─── Unit tests for the scorer (no network) ──────────────────────
if __name__ == "__main__":
    cases = [
        ("noreply@hire.lever.co", "Thanks for applying to Beta Co", "We have received your application for Staff Engineer.", "Beta Co", "Staff Engineer"),
        ("no-reply@greenhouse.io", "Acme Inc — Application received", "Thank you for applying.", "Acme Inc", "Senior Engineer"),
        ("hr@gamma-corp.com", "Your Gamma Corp application", "We have received your application.", "Gamma Corp", "Engineering Manager"),
        ("spam@example.com", "Buy now!!!", "Unrelated marketing.", "Acme Inc", "Senior Engineer"),
    ]
    for f, s, body, co, title in cases:
        print(f"{_score_match(f, s, body, co, title):3d}  <- {f}  |  {s}")
