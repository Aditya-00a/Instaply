"""Gmail response tracker.

Reads Gmail via IMAP, finds application replies, updates application_tracking.

Setup (ONE TIME):
  1. Go to https://myaccount.google.com/apppasswords
  2. Generate a 16-char app password named "Scout Gmail"
  3. Set env vars:
        GMAIL_USER=[email]
        GMAIL_APP_PASSWORD=the-16-char-password
     (or put them in C:\Ravendise\Instaply\.env — python-dotenv will pick them up)

Usage:
  python scripts/gmail_response_tracker.py              # run once, process new emails
  python scripts/gmail_response_tracker.py --lookback 30  # also reprocess last 30 days
  python scripts/gmail_response_tracker.py --dry-run    # show what it would do

Scheduled via Task Scheduler (RevizeAgent-Gmail), every 30 min.
"""
from __future__ import annotations

import argparse
import email
import email.utils
import imaplib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "jobs.db"
STATE_FILE = ROOT / "artifacts" / "gmail_tracker_state.json"
LOG_FILE = ROOT / "artifacts" / "gmail_tracker.log"

# Optional: load .env from Instaply conventions (config/.env is the real one)
try:
    from dotenv import load_dotenv
    for _candidate in (ROOT / "config" / ".env", ROOT / ".env"):
        if _candidate.exists():
            load_dotenv(_candidate)
except Exception:
    pass


# ─── Classification patterns ──────────────────────────────────────────

REJECTION_PATTERNS = [
    r"\bunfortunately\b",
    r"\bnot\s+(?:moving\s+forward|selected|chosen)\b",
    r"\bdecided\s+(?:not\s+to\s+move|to\s+move\s+forward\s+with\s+other)\b",
    r"\bother\s+candidates?\b.*\b(?:strong|better|closer)\b",
    r"\bpursue\s+(?:other|another)\s+candidate",
    r"\bwill\s+not\s+be\s+moving\s+forward\b",
    r"\bwish\s+you\s+(?:the\s+best|well|success)\b",
    r"\bposition\s+has\s+been\s+filled\b",
    r"\bno\s+longer\s+considering\b",
    r"\bregret\s+to\s+inform\b",
]

# REAL interview patterns — must be assertive, not conditional
# These must be present in the SUBJECT line (strongest signal)
INTERVIEW_SUBJECT_PATTERNS = [
    r"\binterview\b",
    r"\bphone\s+screen\b",
    r"\binvit(?:e|ation)\s+to\b",
    r"\bavailability\s+for\b",
    r"\bnext\s+steps?\s+(?:with|for|at)\b",
    r"\blet'?s\s+(?:chat|talk|connect|schedule)\b",
    r"\bselected\s+for\b",
    r"\btime\s+to\s+(?:chat|talk|connect)\b",
]
# Body-level corroboration — only count as interview if subject ALSO matched
INTERVIEW_BODY_PATTERNS = [
    r"\bscheduled\s+(?:a|an|your)\s+(?:phone|video|zoom|interview)\b",
    r"\b(?:we|I)'?d?\s+like\s+to\s+schedule\b",
    r"\bplease\s+(?:book|select|choose)\s+a\s+time\b",
    r"\bcalendly\.com/",
    r"\bgoodtime\.io",
    r"\bcalendar\.app\.google",
]

# Acknowledgement patterns (application received, in review)
ACKNOWLEDGEMENT_PATTERNS = [
    r"\bthank you for (?:applying|your application|your interest)\b",
    r"\bwe\s+received\s+your\s+application\b",
    r"\byour\s+application\s+(?:has\s+been|was)\s+received\b",
    r"\bapplication\s+status:\s+under\s+review\b",
]

OFFER_PATTERNS = [
    r"\boffer\s+(?:letter|of\s+employment|package)\b",
    r"\bpleased\s+to\s+(?:offer|extend)\b",
    r"\bextending\s+you\s+an\s+offer\b",
    r"\bcongratulations.*\b(?:offer|position|role)\b",
]

# ATS / HR sender domain hints (speed up filtering)
ATS_SENDER_HINTS = [
    "greenhouse.io", "lever.co", "myworkdayjobs.com", "myworkday.com",
    "smartrecruiters.com", "ashbyhq.com", "jobvite.com", "icims.com",
    "successfactors.com", "oraclecloud.com", "brassring.com",
    "no-reply", "noreply", "donotreply", "talent", "careers",
    "recruiting", "recruitment", "hiring", "hr@", "people@",
    "talentacquisition", "human-resources",
]


def classify(subject: str, body: str) -> str | None:
    subj_l = (subject or "").lower()
    body_l = (body or "").lower()
    blob = f"{subj_l}\n{body_l}"
    # Offers first (highest stakes, most distinctive)
    if any(re.search(p, blob, re.I) for p in OFFER_PATTERNS):
        return "offer"
    # Rejections (strong signals — distinctive phrases)
    if any(re.search(p, blob, re.I) for p in REJECTION_PATTERNS):
        return "rejection"
    # Interview: STRICT — subject must assert interview, OR body has scheduling action
    subject_asserts_interview = any(
        re.search(p, subj_l, re.I) for p in INTERVIEW_SUBJECT_PATTERNS
    )
    body_asserts_interview = any(
        re.search(p, body_l, re.I) for p in INTERVIEW_BODY_PATTERNS
    )
    if subject_asserts_interview or body_asserts_interview:
        return "interview_invite"
    # Acknowledgement (application received, no response yet)
    if any(re.search(p, blob, re.I) for p in ACKNOWLEDGEMENT_PATTERNS):
        return "acknowledgement"
    return None


# ─── Company extraction & matching ────────────────────────────────────

def normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_COMPANY_SUFFIXES = re.compile(
    r"\b(inc|llc|ltd|corp|co|company|corporation|limited|gmbh|plc|technologies|labs|ai)\b",
    re.I,
)


def company_candidates(subject: str, sender: str, body_head: str) -> set[str]:
    """Extract likely company names from subject/sender for matching."""
    out: set[str] = set()
    # Subject pattern: "Thank you for applying to <Company>"
    for pat in [
        r"applying to\s+([A-Z][\w& ]{2,40})",
        r"application\s+(?:to|at)\s+([A-Z][\w& ]{2,40})",
        r"your\s+application\s+(?:to|at|for)\s+([A-Z][\w& ]{2,40})",
        r"position\s+at\s+([A-Z][\w& ]{2,40})",
        r"interview\s+(?:with|at)\s+([A-Z][\w& ]{2,40})",
        r"from\s+([A-Z][\w& ]{2,40})\s+(?:regarding|about|on)\b",
    ]:
        for m in re.finditer(pat, subject + "\n" + body_head[:400]):
            c = _COMPANY_SUFFIXES.sub("", m.group(1)).strip()
            if len(c) >= 3:
                out.add(normalize(c))
    # Sender domain stem
    m = re.search(r"@([a-z0-9-]+)\.", sender or "", re.I)
    if m:
        stem = m.group(1).lower()
        if stem not in {
            "gmail", "yahoo", "outlook", "hotmail", "proton", "icloud",
            "greenhouse", "lever", "workday", "smartrecruiters", "ashbyhq",
            "jobvite", "icims", "workable",
        }:
            out.add(stem)
    return out


def match_application(cur: sqlite3.Cursor, candidates: set[str], received_at: datetime) -> str | None:
    """Find the best-matching applied job_id for these company candidates within 45 days."""
    if not candidates:
        return None
    window_start = (received_at - timedelta(days=45)).isoformat()
    rows = cur.execute(
        "SELECT j.id, j.company "
        "FROM jobs j "
        "INNER JOIN application_tracking t ON t.job_id = j.id "
        "WHERE t.applied_at >= ? AND t.response_type IS NULL "
        "ORDER BY t.applied_at DESC LIMIT 500",
        (window_start,),
    ).fetchall()
    for job_id, company in rows:
        co_norm = normalize(company or "")
        if not co_norm:
            continue
        for cand in candidates:
            # Either candidate contains the DB company or vice versa (with min length)
            if len(cand) >= 4 and (cand in co_norm or co_norm in cand):
                return job_id
    return None


# ─── Gmail IMAP ───────────────────────────────────────────────────────

def fetch_messages(lookback_days: int) -> list[dict]:
    # Prefer Instaply's existing IMAP_* convention; fall back to GMAIL_* names.
    user = (
        os.environ.get("GMAIL_USER", "").strip()
        or os.environ.get("IMAP_USERNAME", "").strip()
    )
    pwd = (
        os.environ.get("GMAIL_APP_PASSWORD", "").strip()
        or os.environ.get("IMAP_PASSWORD", "").strip()
    )
    if not user or not pwd:
        raise RuntimeError(
            "No Gmail credentials found. "
            "Set GMAIL_USER/GMAIL_APP_PASSWORD or IMAP_USERNAME/IMAP_PASSWORD in config/.env"
        )
    since_str = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%d-%b-%Y")

    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    imap.login(user, pwd)
    imap.select("INBOX")

    # Run multiple targeted server-side searches; union the UID results.
    # Each query returns only a few hundred candidates max, keeping this fast.
    base_since = f'SINCE "{since_str}"'
    queries = [
        # Recruiter/ATS sender patterns
        f'({base_since} FROM "no-reply")',
        f'({base_since} FROM "noreply")',
        f'({base_since} FROM "donotreply")',
        f'({base_since} FROM "talent")',
        f'({base_since} FROM "recruiting")',
        f'({base_since} FROM "recruitment")',
        f'({base_since} FROM "careers")',
        f'({base_since} FROM "greenhouse")',
        f'({base_since} FROM "lever.co")',
        f'({base_since} FROM "myworkday")',
        f'({base_since} FROM "smartrecruiters")',
        f'({base_since} FROM "ashbyhq")',
        f'({base_since} FROM "icims")',
        f'({base_since} FROM "workable")',
        # Subject patterns
        f'({base_since} SUBJECT "your application")',
        f'({base_since} SUBJECT "thank you for applying")',
        f'({base_since} SUBJECT "application received")',
        f'({base_since} SUBJECT "application status")',
        f'({base_since} SUBJECT "next step")',
        f'({base_since} SUBJECT "interview")',
        f'({base_since} SUBJECT "offer")',
        f'({base_since} SUBJECT "phone screen")',
    ]

    all_ids: set[bytes] = set()
    for q in queries:
        try:
            typ, data = imap.search(None, q)
            if typ == "OK" and data and data[0]:
                for uid in data[0].split():
                    all_ids.add(uid)
        except Exception as e:
            print(f"  query failed: {q} → {e}")
            continue
    print(f"Targeted IMAP searches matched {len(all_ids)} unique messages")
    sys.stdout.flush()

    msgs: list[dict] = []
    if not all_ids:
        imap.logout()
        return msgs

    # Hard cap to protect against runaway — 600 is plenty for 30-day window
    ids_list = list(all_ids)[:600]
    if len(all_ids) > 600:
        print(f"  capping to first 600 of {len(all_ids)}")

    # Fetch bodies — now it's a small bounded set
    for i, mid in enumerate(ids_list):
        try:
            typ, raw = imap.fetch(mid, "(RFC822)")
            if typ != "OK" or not raw or not raw[0]:
                continue
            m = email.message_from_bytes(raw[0][1])
            subject = _decode(m.get("Subject", ""))
            sender = _decode(m.get("From", ""))
            date_raw = m.get("Date", "")
            try:
                dt = email.utils.parsedate_to_datetime(date_raw)
            except Exception:
                dt = datetime.now(timezone.utc)
            body = _extract_body(m)
            msgs.append({
                "id": mid.decode() if isinstance(mid, bytes) else str(mid),
                "subject": subject,
                "from": sender,
                "date": dt,
                "body": body[:8000],
            })
            if (i + 1) % 50 == 0:
                print(f"  fetched {i+1}/{len(ids_list)}")
                sys.stdout.flush()
        except Exception:
            continue
    imap.logout()
    return msgs


def _decode(s: str) -> str:
    if not s:
        return ""
    parts = decode_header(s)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            try:
                out.append(chunk.decode(enc or "utf-8", errors="replace"))
            except Exception:
                out.append(chunk.decode("utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _extract_body(m: email.message.Message) -> str:
    if m.is_multipart():
        for part in m.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except Exception:
                    continue
        # fallback to HTML stripped
        for part in m.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    return re.sub(r"<[^>]+>", " ", html)
                except Exception:
                    continue
        return ""
    try:
        return m.get_payload(decode=True).decode(
            m.get_content_charset() or "utf-8", errors="replace"
        )
    except Exception:
        return ""


# ─── DB update ────────────────────────────────────────────────────────

def update_application(
    cur: sqlite3.Cursor, job_id: str, response_type: str, received_at: datetime
) -> None:
    if response_type == "interview_invite":
        cur.execute(
            "UPDATE application_tracking "
            "SET response_type=?, response_received_at=?, "
            "    interview_scheduled_at=?, outcome=?, updated_at=? "
            "WHERE job_id=? AND response_type IS NULL",
            (
                response_type, received_at.isoformat(),
                received_at.isoformat(), "in_interview",
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ),
        )
    elif response_type == "rejection":
        cur.execute(
            "UPDATE application_tracking "
            "SET response_type=?, response_received_at=?, "
            "    rejected_at=?, outcome=?, rejection_source=?, updated_at=? "
            "WHERE job_id=? AND response_type IS NULL",
            (
                response_type, received_at.isoformat(),
                received_at.isoformat(), "rejected", "employer_email",
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ),
        )
    elif response_type == "offer":
        cur.execute(
            "UPDATE application_tracking "
            "SET response_type=?, response_received_at=?, "
            "    offer_received_at=?, outcome=?, updated_at=? "
            "WHERE job_id=? AND response_type IS NULL",
            (
                response_type, received_at.isoformat(),
                received_at.isoformat(), "offer",
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ),
        )


# ─── Dedup state ──────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"processed_ids": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Keep last 5000 processed ids only (prevent unbounded growth)
    state["processed_ids"] = state.get("processed_ids", [])[-5000:]
    STATE_FILE.write_text(json.dumps(state, indent=2))


def log_line(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{ts}  {msg}\n")
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


# ─── Main ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=7,
                    help="days of email history to scan (default 7)")
    ap.add_argument("--dry-run", action="store_true",
                    help="don't write DB, just log what would happen")
    args = ap.parse_args()

    state = load_state()
    seen = set(state.get("processed_ids", []))

    log_line(f"gmail_tracker start (lookback={args.lookback}d, dry_run={args.dry_run})")

    try:
        msgs = fetch_messages(args.lookback)
    except Exception as e:
        log_line(f"fetch_failed: {e}")
        return 2

    log_line(f"fetched {len(msgs)} messages since {args.lookback}d ago")

    matched_count = 0
    updated_count = 0

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    for m in msgs:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        # Fast path: skip clearly-not-ATS mail
        sender_l = (m["from"] or "").lower()
        looks_hiring = any(h in sender_l for h in ATS_SENDER_HINTS)
        looks_hiring = looks_hiring or re.search(
            r"\b(application|interview|role|position|opportunity|recruit|hiring|job\s+at)\b",
            m["subject"] + " " + m["body"][:300], re.I,
        )
        if not looks_hiring:
            continue

        response_type = classify(m["subject"], m["body"])
        if not response_type:
            continue
        # Acknowledgements are not "responses" — they're just receipts.
        # Skip them for now (could track as application_confirmed later).
        if response_type == "acknowledgement":
            continue

        candidates = company_candidates(m["subject"], m["from"], m["body"][:1200])
        if not candidates:
            continue

        job_id = match_application(cur, candidates, m["date"])
        if not job_id:
            continue

        matched_count += 1
        log_line(f"MATCH [{response_type}] {m['from'][:50]} / {m['subject'][:60]} -> job_id={job_id[:12]}")

        if not args.dry_run:
            update_application(cur, job_id, response_type, m["date"])
            if cur.rowcount:
                updated_count += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    state["processed_ids"] = list(seen)
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["last_run_matched"] = matched_count
    state["last_run_updated"] = updated_count
    save_state(state)

    log_line(f"done — matched={matched_count}, updated={updated_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
