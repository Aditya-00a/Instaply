"""Review screenshot-backed application requests.

Usage:
  python review_applications.py list
  python review_applications.py approve <review_id>
  python review_applications.py approve <review_id> --submit
  python review_applications.py deny <review_id>
  python review_applications.py submit-approved <review_id>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.db.jobs_repository import transition_job_status  # noqa: E402
from backend.services.application_review_gate import (  # noqa: E402
    APPROVED,
    DENIED,
    PENDING,
    get_review_request,
    list_review_requests,
    record_review_decision,
)
from backend.services.auto_apply import submit_approved_review  # noqa: E402


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _print_review(item: dict) -> None:
    print(f"{item.get('id')} | {item.get('status')} | {item.get('company')} | {item.get('title')}")
    print(f"  URL: {item.get('url', '')}")
    print(f"  Screenshot: {item.get('screenshot_path', '')}")
    needs_review = item.get("needs_review") or []
    if needs_review:
        print(f"  Needs review: {len(needs_review)} item(s)")


async def _approve(args: argparse.Namespace) -> None:
    result = record_review_decision(args.review_id, decision=APPROVED, notes=args.notes)
    _print_json({"decision": result})
    if args.submit:
        submit_result = await submit_approved_review(args.review_id)
        _print_json({"submit": submit_result})


def _deny(args: argparse.Namespace) -> None:
    result = record_review_decision(args.review_id, decision=DENIED, notes=args.notes)
    if not args.keep_job:
        review = get_review_request(args.review_id)
        job_id = str(review.get("job_id") or "").strip()
        if job_id:
            try:
                transition_job_status(job_id, "rejected", reason="application_review_denied")
            except Exception as exc:
                result["job_reject_error"] = str(exc)
    _print_json({"decision": result})


async def _submit_approved(args: argparse.Namespace) -> None:
    result = await submit_approved_review(args.review_id)
    _print_json(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review screenshot-backed application requests")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List application review requests")
    list_parser.add_argument("--status", default=PENDING, help="pending_approval, approved, denied, submitted")
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument("--json", action="store_true")

    approve_parser = sub.add_parser("approve", help="Approve a review request")
    approve_parser.add_argument("review_id")
    approve_parser.add_argument("--notes", default="")
    approve_parser.add_argument("--submit", action="store_true", help="Immediately submit after recording approval")

    deny_parser = sub.add_parser("deny", help="Deny a review request")
    deny_parser.add_argument("review_id")
    deny_parser.add_argument("--notes", default="")
    deny_parser.add_argument("--keep-job", action="store_true", help="Do not reject the job after denial")

    submit_parser = sub.add_parser("submit-approved", help="Submit an already approved review request")
    submit_parser.add_argument("review_id")

    args = parser.parse_args()

    if args.command == "list":
        result = list_review_requests(status=args.status, limit=args.limit)
        if args.json:
            _print_json(result)
        else:
            print(f"{result['count']} review request(s)")
            for item in result["items"]:
                _print_review(item)
        return

    if args.command == "approve":
        asyncio.run(_approve(args))
        return

    if args.command == "deny":
        _deny(args)
        return

    if args.command == "submit-approved":
        asyncio.run(_submit_approved(args))
        return


if __name__ == "__main__":
    main()

