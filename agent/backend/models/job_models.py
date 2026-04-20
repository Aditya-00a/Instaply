from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JobRecord(BaseModel):
    id: str
    title: str
    company: str
    location: str = ""
    url: str = ""
    source: str = ""
    jd_text: str = ""
    match_score: float = 0.0
    match_reasons: list[str] = Field(default_factory=list)
    top_keywords: list[str] = Field(default_factory=list)
    role_bucket: str = "general"
    visa_sponsorship_likely: bool = False
    visa_sponsorship_blocked: bool = False
    date_found: str = ""
    status: str = "new"
    source_urls: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class ScoutRunRequest(BaseModel):
    greenhouse_companies: list[str] = Field(default_factory=list)
    lever_companies: list[str] = Field(default_factory=list)
    workday_companies: list[str] = Field(default_factory=list)
    linkedin_keywords: list[str] = Field(default_factory=list)
    linkedin_location: str = ""
    indeed_keywords: list[str] = Field(default_factory=list)
    indeed_location: str = ""
    glassdoor_keywords: list[str] = Field(default_factory=list)
    glassdoor_location: str = ""
    limit_per_source: int = 20


class ScoutRunResponse(BaseModel):
    fetched: int
    inserted: int
    skipped: int
    skipped_companies_due_to_cooldown: int = 0
    jobs: list[JobRecord]


class ApplicationPipelineRequest(BaseModel):
    greenhouse_companies: list[str] = Field(default_factory=list)
    lever_companies: list[str] = Field(default_factory=list)
    workday_companies: list[str] = Field(default_factory=list)
    limit_per_source: int = 20
    max_packets: int = 5
    output_dir: str | None = None
    date_text: str = ""


class ApplicationPipelineResponse(BaseModel):
    fetched: int
    inserted: int
    skipped: int
    skipped_companies_due_to_cooldown: int = 0
    ranked_jobs: list[dict[str, Any]]
    generated_packets: int
    skipped_existing_packets: int
    review_queue: list[dict[str, Any]]
