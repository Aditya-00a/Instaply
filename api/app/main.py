"""
Ravendise / Instaply — FastAPI core.

Five endpoints, shared across all three surfaces (Claude MCP, ChatGPT MCP, Web).
All business rules (credit gating, fit threshold, per-company cap) enforced here
— MCP adapters are thin shells around these routes.
"""
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .auth import current_user_id
from .db import service_client
from .razorpay_webhook import router as razorpay_router
from .resume_analyzer import router as resume_router
from .jobs_search import router as jobs_search_router
from .audit import audit
from .ratelimit import rate_limit
from fastapi import Request
from .schemas import (
    JobSearchRequest, JobSearchResponse, Job,
    QueueApplicationRequest, Application, ListApplicationsResponse,
    CreditsResponse, ProfileUpdate,
    McpTokenCreateRequest, McpTokenCreateResponse, McpTokenSummary, ListMcpTokensResponse,
)

app = FastAPI(
    title="Instaply Core API",
    description="Ravendise / Instaply — agentic job-application platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://instaply.asion.ai",
        "https://asion.ai",
        "https://www.asion.ai",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(razorpay_router)
app.include_router(resume_router)
app.include_router(jobs_search_router)


# ─── Health ───────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"ok": True, "service": "instaply-api", "version": "0.1.0"}


# ─── Billing ──────────────────────────────────────────────────────
@app.get("/billing/packs")
async def list_credit_packs(
    _rl: None = rate_limit("billing_packs", per_min=60, anon=True),
):
    """Public catalog of credit packs — safe to expose unauthenticated.

    The web /billing page fetches this to render the Paddle checkout buttons.
    """
    db = service_client()
    r = (
        db.table("credit_packs")
        .select("id, label, price_usd, credits, bonus_pct, sort_order")
        .eq("is_active", True)
        .order("sort_order", desc=False)
        .execute()
    )
    return {"packs": r.data or []}


# ─── Credits ──────────────────────────────────────────────────────
@app.get("/credits", response_model=CreditsResponse)
async def get_credits(
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("credits", per_min=120),
):
    db = service_client()
    # Balance via RPC (uses the SQL function defined in schema)
    bal = db.rpc("get_credit_balance", {"p_user_id": user_id}).execute()
    balance = bal.data if isinstance(bal.data, int) else 0

    prof = db.table("profiles").select("plan").eq("id", user_id).single().execute()
    plan = prof.data["plan"] if prof.data else "free"

    used = settings.free_credits_per_user - balance if plan == "free" else 0
    return CreditsResponse(
        balance=balance, plan=plan,
        free_cap=settings.free_credits_per_user, used=max(0, used),
    )


# ─── Profile ──────────────────────────────────────────────────────
@app.patch("/profile")
async def update_profile(
    patch: ProfileUpdate,
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("profile_update", per_min=20),
):
    db = service_client()
    updates = patch.model_dump(exclude_unset=True)
    if not updates:
        return {"ok": True, "updated": 0}
    db.table("profiles").update(updates).eq("id", user_id).execute()
    audit(
        user_id, "profile.updated",
        request=request, meta={"fields": sorted(updates.keys())},
    )
    return {"ok": True, "updated": len(updates)}


# ─── Jobs search ──────────────────────────────────────────────────
@app.post("/jobs/search", response_model=JobSearchResponse)
async def search_jobs(
    req: JobSearchRequest,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("jobs_search", per_min=60),
):
    db = service_client()
    q = db.table("jobs").select("*").eq("is_active", True)
    if req.location:
        q = q.ilike("location", f"%{req.location}%")
    q = q.ilike("title", f"%{req.query}%").limit(req.limit)
    resp = q.execute()
    jobs = [Job(**row) for row in (resp.data or [])]
    return JobSearchResponse(jobs=jobs, total=len(jobs))


# ─── Queue application ────────────────────────────────────────────
@app.post("/applications/queue", response_model=Application)
async def queue_application(
    req: QueueApplicationRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("queue_app", per_min=30),
):
    db = service_client()

    # 1. Credit gate — pre-check, worker double-checks on confirm
    bal = db.rpc("get_credit_balance", {"p_user_id": user_id}).execute()
    balance = bal.data if isinstance(bal.data, int) else 0
    if balance <= 0:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "No credits remaining. Upgrade to Pro for unlimited applications.",
        )

    # 2. Resolve job (by id or url)
    if req.job_id:
        job = db.table("jobs").select("*").eq("id", str(req.job_id)).single().execute()
        if not job.data:
            raise HTTPException(404, "Job not found")
        job_row = job.data
    elif req.job_url:
        # MVP: require job to exist in catalog; future: auto-ingest on-demand
        job = db.table("jobs").select("*").eq("apply_url", str(req.job_url)).limit(1).execute()
        if not job.data:
            raise HTTPException(404, "Job URL not in catalog yet — use search first")
        job_row = job.data[0]
    else:
        raise HTTPException(400, "Must provide job_id or job_url")

    # 3. Per-company cap — count queued/active/submitted apps at this company
    company_slug = job_row.get("company_slug", "")
    if company_slug:
        # Fetch all job IDs for this company, then count matching applications
        sibling_jobs = (
            db.table("jobs")
            .select("id")
            .eq("company_slug", company_slug)
            .execute()
        )
        sibling_ids = [r["id"] for r in (sibling_jobs.data or [])]
        if sibling_ids:
            cap_resp = (
                db.table("applications")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .in_("job_id", sibling_ids)
                .in_("status", ["queued", "in_progress", "submitted", "confirmed"])
                .execute()
            )
            if (cap_resp.count or 0) >= settings.per_company_cap:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"You've reached the {settings.per_company_cap}-application cap for "
                    f"{job_row.get('company_name', company_slug)}. Try a different company.",
                )

    # 4. Create application row
    ins = db.table("applications").insert({
        "user_id": user_id,
        "job_id": job_row["id"],
        "resume_id": str(req.resume_id) if req.resume_id else None,
        "status": "queued",
    }).execute()

    row = ins.data[0]
    audit(
        user_id, "application.queued",
        subject_id=str(row["id"]), request=request,
        meta={"job_id": str(row["job_id"]), "company": job_row.get("company_slug")},
    )
    return Application(
        id=row["id"], job_id=row["job_id"], status=row["status"],
        fit_score=row.get("fit_score"),
        company_name=job_row["company_name"], title=job_row["title"],
        queued_at=row["queued_at"],
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        confirmed_at=row.get("confirmed_at"),
        error_message=row.get("error_message"),
    )


# ─── List applications ────────────────────────────────────────────
@app.get("/applications", response_model=ListApplicationsResponse)
async def list_applications(
    status_filter: str | None = None,
    limit: int = 50,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("applications_list", per_min=120),
):
    db = service_client()
    q = (
        db.table("applications")
        .select("*, jobs(company_name, title)")
        .eq("user_id", user_id)
        .order("queued_at", desc=True)
        .limit(limit)
    )
    if status_filter:
        q = q.eq("status", status_filter)
    resp = q.execute()
    rows = resp.data or []
    apps = [
        Application(
            id=r["id"], job_id=r["job_id"], status=r["status"],
            fit_score=r.get("fit_score"),
            company_name=r["jobs"]["company_name"],
            title=r["jobs"]["title"],
            queued_at=r["queued_at"],
            started_at=r.get("started_at"),
            completed_at=r.get("completed_at"),
            confirmed_at=r.get("confirmed_at"),
            error_message=r.get("error_message"),
        )
        for r in rows
    ]
    return ListApplicationsResponse(applications=apps, total=len(apps))


# ─── MCP tokens ──────────────────────────────────────────────────
import hashlib
import secrets


def _mint_mcp_token() -> tuple[str, str, str]:
    """Return (plaintext, sha256_hex, first_8_chars_after_prefix)."""
    raw = secrets.token_hex(24)                # 48 hex chars = 192 bits
    plaintext = f"ia_{raw}"
    h = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return plaintext, h, raw[:8]


@app.post("/auth/mcp-tokens", response_model=McpTokenCreateResponse)
async def create_mcp_token(
    req: McpTokenCreateRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("mcp_token_mint", per_min=10),
):
    """Mint a long-lived token for Claude Desktop / MCP clients.

    The plaintext token is returned ONCE. Store it in the MCP client config.
    We only keep a hash; if lost, create a new token and revoke the old one.
    """
    db = service_client()
    plaintext, h, prefix = _mint_mcp_token()
    ins = db.table("mcp_tokens").insert({
        "user_id": user_id,
        "token_hash": h,
        "token_prefix": prefix,
        "label": req.label,
    }).execute()
    row = ins.data[0]
    audit(
        user_id, "auth.mcp_token_created",
        subject_id=str(row["id"]), request=request,
        meta={"label": req.label, "prefix": prefix},
    )
    return McpTokenCreateResponse(
        id=row["id"],
        token=plaintext,
        label=row.get("label"),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


@app.get("/auth/mcp-tokens", response_model=ListMcpTokensResponse)
async def list_mcp_tokens(
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("mcp_token_list", per_min=60),
):
    db = service_client()
    resp = (
        db.table("mcp_tokens")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = resp.data or []
    return ListMcpTokensResponse(
        tokens=[
            McpTokenSummary(
                id=r["id"], label=r.get("label"),
                token_prefix=r["token_prefix"],
                created_at=r["created_at"], expires_at=r["expires_at"],
                last_used_at=r.get("last_used_at"),
                revoked_at=r.get("revoked_at"),
            )
            for r in rows
        ]
    )


@app.delete("/auth/mcp-tokens/{token_id}")
async def revoke_mcp_token(
    token_id: str,
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("mcp_token_revoke", per_min=20),
):
    db = service_client()
    from datetime import datetime, timezone
    db.table("mcp_tokens").update(
        {"revoked_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", token_id).eq("user_id", user_id).execute()
    audit(
        user_id, "auth.mcp_token_revoked",
        subject_id=token_id, request=request,
    )
    return {"ok": True, "revoked": token_id}
