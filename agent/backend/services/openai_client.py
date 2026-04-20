from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from backend.services.config import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1, 2, 4]
_TIMEOUT = 90.0


def _headers() -> dict[str, str]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }


async def health_check() -> bool:
    if not settings.openai_api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.openai_base_url.rstrip('/')}/models",
                headers=_headers(),
            )
            response.raise_for_status()
        return True
    except Exception:
        return False


async def generate(prompt: str, system: str | None = None) -> str:
    """Call the OpenAI-compatible /chat/completions endpoint.

    Works with: OpenAI, Cerebras, Groq, Together AI, NIM, Mistral, etc.
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": settings.model_name,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 512,
    }

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(
                    f"{settings.openai_base_url.rstrip('/')}/chat/completions",
                    headers=_headers(),
                    json=payload,
                )
                # Handle rate limiting with Retry-After header
                if response.status_code == 429:
                    retry_after = response.headers.get("retry-after")
                    delay = float(retry_after) if retry_after else _BACKOFF_SECONDS[attempt]
                    logger.warning(
                        "Rate limited (429). Retry %d/%d, waiting %.1fs...",
                        attempt + 1, _MAX_RETRIES, delay,
                    )
                    if attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(delay)
                        continue
                    response.raise_for_status()

                response.raise_for_status()
                data = response.json()

                # Standard chat completions response format
                try:
                    return data["choices"][0]["message"]["content"].strip()
                except (KeyError, IndexError, AttributeError):
                    logger.warning("Unexpected response shape: %s", str(data)[:200])
                    return ""

        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                delay = _BACKOFF_SECONDS[attempt]
                logger.warning(
                    "LLM generate retry %d/%d: %s. Retrying in %ds...",
                    attempt + 1, _MAX_RETRIES, exc, delay,
                )
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]
