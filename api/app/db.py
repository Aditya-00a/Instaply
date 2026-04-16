"""Supabase client wrappers. Service role for trusted writes, anon/JWT for user scope."""
from supabase import create_client, Client
from .config import settings


def service_client() -> Client:
    """Bypasses RLS. Use for credit ledger writes + job discovery."""
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def user_client(access_token: str) -> Client:
    """Scoped to the authenticated user via JWT. RLS enforced."""
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    client.auth.set_session(access_token, refresh_token="")
    return client
