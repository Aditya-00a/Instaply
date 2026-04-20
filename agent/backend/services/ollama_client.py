from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from backend.services.config import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1, 2, 4]


async def _get_available_models() -> list[str]:
    """Return list of installed model names from Ollama."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            return [
                str(item.get("name", "")).strip()
                for item in models
                if isinstance(item, dict) and item.get("name")
            ]
    except Exception:
        return []


async def health_check() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            installed_names = {
                str(item.get("name", "")).strip()
                for item in models
                if isinstance(item, dict)
            }
            configured_model = str(settings.model_name).strip()
            return configured_model in installed_names
    except Exception:
        return False


async def _generate_with_model(prompt: str, model: str, system: str | None = None) -> str:
    """Attempt generation with a specific model, retrying on transient errors."""
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{settings.ollama_base_url}/api/generate", json=payload
                )
                response.raise_for_status()
                return response.json().get("response", "").strip()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                delay = _BACKOFF_SECONDS[attempt]
                logger.warning(
                    "Ollama generate retry %d/%d for model %s: %s. "
                    "Retrying in %ds...",
                    attempt + 1, _MAX_RETRIES, model, exc, delay,
                )
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


async def generate(prompt: str, system: str | None = None, *, model: str | None = None) -> str:
    """Generate text using Ollama.

    Args:
        prompt: The prompt text.
        system: Optional system message.
        model: Explicit model override. If None, uses settings.model_name.
    """
    configured_model = str(model or settings.model_name).strip()
    try:
        return await _generate_with_model(prompt, configured_model, system)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.warning(
            "All retries exhausted for model %s: %s. Checking for fallback model...",
            configured_model, exc,
        )
        # Try a smaller fallback model if one is available
        available = await _get_available_models()
        fallback_candidates = [m for m in available if m != configured_model]
        if not fallback_candidates:
            raise
        fallback_model = fallback_candidates[0]
        logger.warning("Falling back to model: %s", fallback_model)
        return await _generate_with_model(prompt, fallback_model, system)


async def generate_fast(prompt: str, system: str | None = None) -> str:
    """Generate using the configured model for simple yes/no and short answers.

    Uses the same model as generate() — no downgrade to weaker models.
    """
    return await generate(prompt, system)
