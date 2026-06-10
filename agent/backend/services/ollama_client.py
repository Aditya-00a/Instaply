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


# Model families that emit "thinking" preambles by default. For form
# filling and short answers that latency is pure waste, so we ask Ollama
# to disable it. "coder" variants are non-thinking despite the qwen3
# prefix — excluded so we don't send an unsupported flag.
_THINKING_FAMILIES = ("qwen3", "deepseek-r1", "magistral")


def _supports_think_toggle(model: str) -> bool:
    m = model.lower()
    return any(fam in m for fam in _THINKING_FAMILIES) and "coder" not in m


async def _generate_with_model(prompt: str, model: str, system: str | None = None) -> str:
    """Attempt generation with a specific model, retrying on transient errors."""
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    if _supports_think_toggle(model):
        payload["think"] = False

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{settings.ollama_base_url}/api/generate", json=payload
                )
                response.raise_for_status()
                return response.json().get("response", "").strip()
        except httpx.HTTPStatusError as exc:
            # Older Ollama versions (or models that reject the toggle)
            # 400 on the `think` key — drop it and retry immediately.
            if "think" in payload and exc.response.status_code == 400:
                logger.info("Model %s rejected think toggle; retrying without it.", model)
                payload.pop("think", None)
                continue
            raise
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
    """Generate short answers (yes/no, dropdown picks, field values).

    Uses AUTOFILL_MODEL_NAME when configured — a small model that fits
    fully in VRAM keeps per-field latency low across the hundreds of
    short calls an application session makes. Falls back to the main
    MODEL_NAME when no fast model is configured.
    """
    fast_model = str(settings.autofill_model_name or "").strip()
    return await generate(prompt, system, model=fast_model or None)
