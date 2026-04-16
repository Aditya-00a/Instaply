"""Pydantic request/response models — contract shared across MCP adapters."""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl


# ─── Profile ──────────────────────────────────────────────────────
class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    work_auth_status: Optional[Literal[
        "us_citizen", "green_card", "h1b", "f1_opt", "f1_cpt", "other"
    ]] = None
    needs_sponsorship: Optional[bool] = None
    willing_to_relocate: Optional[bool] = None
    current_city: Optional[str] = None
    current_state: Optional[str] = None
    zip_code: Optional[str] = None


class Preferences(BaseModel):
    target_titles: list[str] = Field(default_factory=list)
    target_locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    salary_min_usd: Optional[int] = None
    industries: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    fit_threshold: float = 0.65
    per_company_cap: int = 4


# ─── Jobs ─────────────────────────────────────────────────────────
class JobSearchRequest(BaseModel):
    query: str
    location: Optional[str] = None
    visa_sponsorship: Optional[bool] = None
    limit: int = Field(default=20, ge=1, le=100)


class Job(BaseModel):
    id: UUID
    source: str
    company_slug: str
    company_name: str
    title: str
    location: Optional[str]
    remote: bool
    apply_url: HttpUrl
    discovered_at: datetime
    fit_score: Optional[float] = None


class JobSearchResponse(BaseModel):
    jobs: list[Job]
    total: int


# ─── Applications ────────────────────────────────────────────────
ApplicationStatus = Literal[
    "queued", "in_progress", "submitted", "confirmed",
    "failed", "needs_review", "skipped",
]


class QueueApplicationRequest(BaseModel):
    job_id: Optional[UUID] = None
    job_url: Optional[HttpUrl] = None
    resume_id: Optional[UUID] = None
    notes: Optional[str] = None


class Application(BaseModel):
    id: UUID
    job_id: UUID
    status: ApplicationStatus
    fit_score: Optional[float]
    company_name: str
    title: str
    queued_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    confirmed_at: Optional[datetime]
    error_message: Optional[str]


class ListApplicationsResponse(BaseModel):
    applications: list[Application]
    total: int


# ─── MCP tokens ──────────────────────────────────────────────────
class McpTokenCreateRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=80)


class McpTokenCreateResponse(BaseModel):
    """The plaintext token is returned ONCE, on creation. Never again."""
    id: UUID
    token: str                       # ia_<hex>
    label: Optional[str]
    created_at: datetime
    expires_at: datetime


class McpTokenSummary(BaseModel):
    id: UUID
    label: Optional[str]
    token_prefix: str
    created_at: datetime
    expires_at: datetime
    last_used_at: Optional[datetime]
    revoked_at: Optional[datetime]


class ListMcpTokensResponse(BaseModel):
    tokens: list[McpTokenSummary]


# ─── Credits ─────────────────────────────────────────────────────
class CreditsResponse(BaseModel):
    balance: int
    plan: Literal["free", "pro", "paused"]
    free_cap: int = 10
    used: int
    next_renewal: Optional[datetime] = None
