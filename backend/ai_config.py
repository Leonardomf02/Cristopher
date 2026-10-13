"""Compatibilidade: a IA vive toda no `ai.py`.

Quinze módulos importam daqui (`from ai_config import ask_agent, extract_json`).
Em vez de lhes mexer a todos, este ficheiro reencaminha para o `ai`, que é onde
está a cascata agente → reserva → modelo local.

Código novo deve importar de `ai` directamente.
"""
from __future__ import annotations

from ai import (                                          # noqa: F401
    AI_API_KEY, AI_API_URL, AI_CHANNEL_ID,
    FALLBACK_AI_API_KEY, FALLBACK_AI_API_URL, FALLBACK_AI_CHANNEL_ID,
    ai_status, extract_json, has_fallback, ping,
)
import ai as _ai


def ask_agent(message: str, *, timeout: float = 120.0, feature: str = "outro") -> str:
    return _ai.pergunta(message, timeout=timeout, feature=feature)


async def ask_agent_async(message: str, *, timeout: float = 120.0, feature: str = "outro") -> str:
    return await _ai.pergunta_async(message, timeout=timeout, feature=feature)


def _ask_fallback(message: str, *, timeout: float = 120.0) -> str:
    """A reserva já é o 2º degrau da cascata; isto existe só para quem a chamava
    à mão (os sinais de investimento chamavam)."""
    return _ai.pergunta(message, timeout=timeout, feature="outro")


async def _ask_fallback_async(message: str, *, timeout: float = 120.0) -> str:
    return await _ai.pergunta_async(message, timeout=timeout, feature="outro")
