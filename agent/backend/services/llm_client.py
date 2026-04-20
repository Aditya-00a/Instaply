from __future__ import annotations

import logging

from backend.services import ollama_client, openai_client
from backend.services.config import settings

logger = logging.getLogger(__name__)


def get_provider_name() -> str:
    return str(settings.llm_provider or "ollama").strip().lower()


def get_model_name() -> str:
    return str(settings.model_name).strip()


async def health_check() -> bool:
    provider = get_provider_name()
    if provider == "openai":
        return await openai_client.health_check()
    return await ollama_client.health_check()


async def generate(prompt: str, system: str | None = None) -> str:
    provider = get_provider_name()
    primary, fallback_mod = (
        (openai_client, ollama_client)
        if provider == "openai"
        else (ollama_client, openai_client)
    )

    try:
        return await primary.generate(prompt, system=system)
    except Exception as exc:
        logger.warning(
            "Primary provider (%s) failed: %s. Attempting fallback...",
            provider, exc,
        )
        # Only attempt fallback if the other provider is likely configured
        try:
            if await fallback_mod.health_check():
                fallback_name = "openai" if provider != "openai" else "ollama"
                logger.info("Falling back to provider: %s", fallback_name)
                return await fallback_mod.generate(prompt, system=system)
        except Exception as fallback_exc:
            logger.error("Fallback provider also failed: %s", fallback_exc)
        # Re-raise the original error if fallback didn't work
        raise
