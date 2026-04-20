"""Scan Gmail for rejection emails and update application_tracking."""
from __future__ import annotations

import email
import imaplib
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from email.policy import default
from email.utils import parseaddr
from html import unescape
from pathlib import Path
from typing import Any

from backend.services.config import settings

log = logging.getLogger(__name__)

# Patterns that indicate a rejection email
REJECTION_PATTERNS = [
    re.compile(r"decided\s+(to\s+)?(not\s+to\s+)?move\s+forward\s+with\s+other", re.I),
    re.compile(r"not\s+(be\s+)?mov(e|ing)\s+forward\s+with\s+your\s+application", re.I),
    re.compile(r"unfortunately.{0,80}(not|won'?t|will\s+not).{0,40}(proceed|move|advance|continue)", re.I),
    re.compile(r"decided\s+to\s+pursue\s+other\s+candidates", re.I),
    re.compile(r"not\s+selected\s+to\s+move\s+forward", re.I),
    re.compile(r"will\s+not\s+be\s+moving\s+forward", re.I),
    re.compile(r"regret\s+to\s+inform", re.I),
    re.compile(r"we('ve|'ve| have)\s+decided\s+not\s+to", re.I),
    re.compile(r"after\s+careful\s+(review|consideration).{0,60}not\s+selected", re.I),
    re.compile(r"position\s+has\s+been\s+filled", re.I),
    re.compile(r"no\s+longer\s+(being\s+)?consider", re.I),
    re.compile(r"we('re| are)\s+unable\s+to\s+offer\s+you", re.I),
]

# Patterns to extract company/role from rejection emails
ROLE_PATTERN = re.compile(
    r"(?:application\s+for\s+(?:the\s+|our\s+)?|position\s+of\s+|role\s+(?:of\s+)?)"
    r"([A-Z][A-Za-z0-9 ,&/\-–—]+?)(?:\s+(?:role|position|at\s|and\s|,\s|\.))",
    re.I,
)


def _imap_connect() -> imaplib.IMAP4_SSL:
    host = str(settings.imap_host or "imap.gmail.com").strip()
    port = int(settings.imap_port or 993)
    username = str(settings.imap_username or settings.smtp_username or "").strip()
    password = str(settings.imap_password or settings.smtp_password or "").strip()
    if not username or not password:
        raise ValueError("IMAP not configured")
    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(username, password)
    return conn


def _decode_body(msg: email.message.Message) -> str:
    """Extract plain text from email message."""
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    parts.append(payload.decode(charset, errors="replace"))
            elif ct == "text/html" and not parts:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    text = re.sub(r"<[^>]+>", " ", html)
                    parts.append(unescape(text))
        return "\n".join(parts)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                text = unescape(re.sub(r"<[^>]+>", " ", text))
            return text
    return ""


def _is_rejection(body: str, subject: str) -> bool:
    """Check if email body/subject matches rejection patterns."""
    combined = f"{subject}\n{body}"
    return any(pat.search(combined) for pat in REJECTION_PATTERNS)


def _match_to_tracked_job(
    conn: sqlite3.Connection,
    sender: str,
    subject: str,
    body: str,
) -> dict | None:
    """Try to match a rejection email to a tracked applied job."""
    combined = (subject + " " + body).lower()

    # Get all applied jobs
    rows = conn.execute("""
        SELECT at.id as track_id, at.job_id, at.applied_at,
               j.title, j.company, j.url, j.source
        FROM application_tracking at
        JOIN jobs j ON j.id = at.job_id
        WHERE at.status = 'applied' AND at.rejected_at IS NULL
        ORDER BY at.applied_at DESC
    """).fetchall()

    best_match = None
    best_score = 0

    for row in rows:
        score = 0
        company = (row["company"] or "").lower()
        title = (row["title"] or "").lower()

        # Company name in sender or body
        if company and len(company) > 2:
            if company in sender.lower():
                score += 5
            if company in combined:
                score += 3

        # Role title words in body
        if title:
            title_words = [w for w in title.split() if len(w) > 3]
            matches = sum(1 for w in title_words if w in combined)
            if title_words:
                score += (matches / len(title_words)) * 4

        if score > best_score:
            best_score = score
            best_match = dict(row)

    if best_match and best_score >= 3:
        return best_match
    return None


async def scan_and_update_rejections(db_path: Path) -> dict:
    """Scan recent Gmail for rejection emails and update DB."""
    results: dict[str, Any] = {"scanned": 0, "rejections_found": 0, "updated": [], "errors": []}

    try:
        imap = _imap_connect()
    except Exception as e:
        results["errors"].append(f"IMAP connect failed: {e}")
        return results

    try:
        imap.select("INBOX", readonly=True)

        # Search for recent emails (last 14 days) with rejection-like subjects
        datetime.now(timezone.utc).strftime("%d-%b-%Y")
        # Search broadly — we'll filter with patterns
        _, msg_ids = imap.search(None, "(SINCE 25-Mar-2026)")
        if not msg_ids or not msg_ids[0]:
            results["errors"].append("No emails found in date range")
            return results

        ids = msg_ids[0].split()
        results["scanned"] = len(ids)
        log.info("Scanning %d emails for rejections", len(ids))

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        for mid in ids:
            try:
                _, data = imap.fetch(mid, "(RFC822)")
                if not data or not data[0]:
                    continue
                raw = data[0][1]
                msg = email.message_from_bytes(raw, policy=default)

                subject = str(msg.get("Subject", ""))
                sender = str(msg.get("From", ""))
                _, sender_email = parseaddr(sender)
                date_str = str(msg.get("Date", ""))

                body = _decode_body(msg)
                if not _is_rejection(body, subject):
                    continue

                results["rejections_found"] += 1
                match = _match_to_tracked_job(conn, sender_email, subject, body)

                if match:
                    # Compute hours to rejection
                    hours = None
                    if match["applied_at"]:
                        try:
                            app_dt = datetime.fromisoformat(match["applied_at"].replace("Z", "+00:00"))
                            # Parse email date
                            from email.utils import parsedate_to_datetime
                            rej_dt = parsedate_to_datetime(date_str)
                            if rej_dt.tzinfo is None:
                                rej_dt = rej_dt.replace(tzinfo=timezone.utc)
                            hours = (rej_dt - app_dt).total_seconds() / 3600
                        except Exception:
                            pass

                    rej_source = "ats_auto" if hours and hours < 24 else "email"
                    now = datetime.now(timezone.utc).isoformat()
                    rej_at = date_str

                    conn.execute("""
                        UPDATE application_tracking
                        SET status = 'rejected',
                            response_received_at = ?,
                            response_type = 'rejection',
                            rejected_at = ?,
                            rejection_source = ?,
                            hours_to_rejection = ?,
                            outcome = 'rejected',
                            updated_at = ?
                        WHERE id = ?
                    """, (rej_at, rej_at, rej_source, hours, now, match["track_id"]))

                    # Also update jobs table status
                    conn.execute(
                        "UPDATE jobs SET status = 'rejected' WHERE id = ? AND status = 'applied'",
                        (match["job_id"],),
                    )

                    # Record status event
                    conn.execute(
                        "INSERT INTO job_status_events (id, job_id, from_status, to_status, reason) VALUES (?, ?, 'applied', 'rejected', ?)",
                        (str(uuid.uuid4()), match["job_id"], f"rejection_email_from_{sender_email}"),
                    )

                    results["updated"].append({
                        "company": match["company"],
                        "title": match["title"],
                        "applied_at": match["applied_at"],
                        "hours_to_rejection": round(hours, 1) if hours else None,
                        "rejection_source": rej_source,
                        "sender": sender_email,
                    })
                    log.info(
                        "Rejection detected: %s at %s (%.1fh after apply)",
                        match["title"], match["company"], hours or 0,
                    )

            except Exception as e:
                log.warning("Error processing email %s: %s", mid, e)
                continue

        conn.commit()
        conn.close()

    except Exception as e:
        results["errors"].append(str(e))
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    return results
