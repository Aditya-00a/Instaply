from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / "config" / ".env")


@dataclass(frozen=True)
class Settings:
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    model_name: str = os.getenv("MODEL_NAME", "gemma4:e4b")
    autofill_model_name: str = os.getenv("AUTOFILL_MODEL_NAME", "")
    app_env: str = os.getenv("APP_ENV", "development")
    database_path: str = os.getenv("DATABASE_PATH", str(ROOT_DIR / "data" / "jobs.db"))
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_cc_email: str = os.getenv("SMTP_CC_EMAIL", "")
    imap_host: str = os.getenv("IMAP_HOST", "imap.gmail.com")
    imap_port: int = int(os.getenv("IMAP_PORT", "993"))
    imap_username: str = os.getenv("IMAP_USERNAME", os.getenv("SMTP_USERNAME", ""))
    imap_password: str = os.getenv("IMAP_PASSWORD", os.getenv("SMTP_PASSWORD", ""))
    job_application_email: str = os.getenv("JOB_APPLICATION_EMAIL", os.getenv("JOB_PORTAL_ACCOUNT_EMAIL", ""))
    portal_account_email: str = os.getenv("JOB_PORTAL_ACCOUNT_EMAIL", "")
    portal_account_password: str = os.getenv("JOB_PORTAL_ACCOUNT_PASSWORD", "")
    us_work_authorized: str = os.getenv("US_WORK_AUTHORIZED", "Yes")
    requires_sponsorship: str = os.getenv("REQUIRES_SPONSORSHIP", "")
    good_job_email_threshold: float = float(os.getenv("GOOD_JOB_EMAIL_THRESHOLD", "0.82"))
    career_site_cooldown_days: int = int(os.getenv("CAREER_SITE_COOLDOWN_DAYS", "0"))
    career_discovery_cache_days: int = int(os.getenv("CAREER_DISCOVERY_CACHE_DAYS", "14"))
    company_daily_target_count: int = int(os.getenv("COMPANY_DAILY_TARGET_COUNT", "200"))
    openclaw_gateway_cmd: str = os.getenv("OPENCLAW_GATEWAY_CMD", str(Path.home() / ".openclaw" / "gateway.cmd"))
    openclaw_upload_dir: str = os.getenv("OPENCLAW_UPLOAD_DIR", r"C:\tmp\openclaw\uploads")
    auto_apply_enabled: bool = os.getenv("AUTO_APPLY_ENABLED", "false").strip().lower() in ("true", "1", "yes")
    auto_apply_min_score: float = float(os.getenv("AUTO_APPLY_MIN_SCORE", "0.60"))
    auto_apply_max_per_cycle: int = int(os.getenv("AUTO_APPLY_MAX_PER_CYCLE", "25"))


settings = Settings()
