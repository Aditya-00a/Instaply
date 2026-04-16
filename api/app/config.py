"""Runtime config. Reads from .env via pydantic-settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # NVIDIA NIM
    nvidia_nim_api_key: str
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_nim_primary_model: str = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
    nvidia_nim_secondary_model: str = "meta/llama-3.3-70b-instruct"
    nvidia_nim_reasoning_model: str = "moonshotai/kimi-k2-thinking"

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    # HS256 secret used by Supabase to sign access tokens.
    # Dashboard -> Settings -> API -> JWT Secret. Required for prod.
    supabase_jwt_secret: str = ""
    # Supabase JWTs use aud="authenticated" by default.
    supabase_jwt_audience: str = "authenticated"
    # Only allow skipping signature verification in explicit dev mode.
    auth_skip_jwt_verify: bool = False

    # Rate limiting
    rate_limit_per_min: int = 60          # per user, per endpoint group
    rate_limit_anon_per_min: int = 20     # per IP for anonymous routes

    # FastAPI
    api_port: int = 8000

    # Worker / business rules
    worker_concurrency: int = 2
    fit_threshold: float = 0.65
    per_company_cap: int = 4
    free_credits_per_user: int = 10

    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_webhook_skip_verify: bool = False

    # Web URL (for Stripe success/cancel redirects)
    web_url: str = "https://instaply.asion.ai"


settings = Settings()
