"""Shared config + client for the iaedu.pt agent (used by multiple routers).

Agente atual: Claude Opus 4.7 com web search (Tavily). Quando usa tools, o stream
traz mensagens intermédias ai-vazias + tool_calls e uma mensagem type=tool com o
resultado da pesquisa; a resposta FINAL é a última mensagem ai não-vazia. Por isso
NÃO se pode parar na 1ª mensagem. `ask_agent`/`ask_agent_async` tratam disto."""

import os
import json
import uuid
import time
import asyncio
import logging

import httpx

# Claude Opus 4.7 com web search. Chave vem só do .env.
AI_API_URL = os.getenv(
    "AI_API_URL",
    "https://api.iaedu.pt/agent-chat//api/v1/agent/cmoss7l0f658oko01vk2egfpg/stream",
)
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_CHANNEL_ID = os.getenv("AI_CHANNEL_ID", "cmq0tu39r1b1unr01jwra3hfu")

# Fallback (ChatGPT via iaedu.pt): quando o agente Claude principal falha ou rate-limita,
# `ask_agent`/`ask_agent_async` caem neste 2º agente (GPT) em vez de devolver vazio
# ("IA indisponível"). Mesmo protocolo de streaming do agente principal. Só ativo se
# FALLBACK_AI_API_KEY estiver no .env.
FALLBACK_AI_API_URL = os.getenv(
    "FALLBACK_AI_API_URL",
    "https://api.iaedu.pt/agent-chat//api/v1/agent/cmamvd3n40000c801qeacoad2/stream",
)
FALLBACK_AI_API_KEY = os.getenv("FALLBACK_AI_API_KEY", "")
FALLBACK_AI_CHANNEL_ID = os.getenv("FALLBACK_AI_CHANNEL_ID", "cmnauzuoxjik3hv01gjna24hw")

logger = logging.getLogger(__name__)

# Estado do rate limit, para a app poder mostrar "IA em espera" em vez de parecer
# que não devolveu nada. Marcado quando o agente devolve erro de rate limit; limpo
# na 1ª resposta bem-sucedida.
_rate_limited_at: float | None = None
_rate_limit_msg: str = ""


def _note_error(content) -> None:
    global _rate_limited_at, _rate_limit_msg
    c = str(content or "")
    if "rate limit" in c.lower() or "429" in c:
        # só marca a 1ª deteção (não re-marca a cada falha) → "há X" reflete a
        # duração REAL do limite, não o instante da última sonda
        if _rate_limited_at is None:
            _rate_limited_at = time.time()
        _rate_limit_msg = c


def _clear_rate_limit() -> None:
    global _rate_limited_at
    _rate_limited_at = None


def ai_status() -> dict:
    """Estado da IA para o frontend. Fica rate_limited até uma chamada ter SUCESSO
    (limpa o flag). seconds_ago = há quanto tempo está estrangulada (desde a 1ª deteção)."""
    if _rate_limited_at is not None:
        return {"rate_limited": True, "seconds_ago": int(time.time() - _rate_limited_at), "message": _rate_limit_msg, "fallback": has_fallback()}
    return {"rate_limited": False, "seconds_ago": None, "message": "", "fallback": has_fallback()}


def _form(message: str, channel_id: str = AI_CHANNEL_ID) -> dict:
    return {
        "channel_id": channel_id,
        "thread_id": uuid.uuid4().hex[:20],
        "user_info": "{}",
        "message": message,
    }


def _parse_stream(raw_text: str) -> str:
    """Extrai a resposta final do stream (uma linha JSON por evento).

    Junta os `token` e guarda a última mensagem `ai` não-vazia. Ignora mensagens
    `type=tool` (resultado das pesquisas). Devolve "" se nada útil."""
    full_text = ""
    token_text = ""
    for line in raw_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        if etype == "token":
            token_text += event.get("content", "")
        elif etype == "message":
            content = event.get("content", {})
            if isinstance(content, dict):
                if content.get("type") in (None, "ai"):  # ignora type=="tool"
                    text = content.get("content", "")
                    if text:
                        full_text = text   # a última ai não-vazia ganha
            elif isinstance(content, str) and content:
                full_text = content
        elif etype == "error":
            logger.warning("agente devolveu erro: %s", event.get("content"))
            _note_error(event.get("content"))
    return full_text or token_text


_RETRIES = 2          # tentativas extra em caso de vazio (rate limit / transitório)
_BACKOFF = 3.0        # segundos entre tentativas


# ── Fallback ChatGPT (2º agente iaedu.pt) ────────────────────────

def has_fallback() -> bool:
    return bool(FALLBACK_AI_API_KEY)


def _ask_fallback(message: str, *, timeout: float = 120.0) -> str:
    if not FALLBACK_AI_API_KEY:
        return ""
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(FALLBACK_AI_API_URL, headers={"x-api-key": FALLBACK_AI_API_KEY},
                            data=_form(message, FALLBACK_AI_CHANNEL_ID))
        if r.status_code != 200:
            logger.warning("fallback ChatGPT: HTTP %s", r.status_code)
            return ""
        return _parse_stream(r.text)
    except httpx.HTTPError as e:
        logger.warning("fallback ChatGPT: erro %s", e)
        return ""


async def _ask_fallback_async(message: str, *, timeout: float = 120.0) -> str:
    if not FALLBACK_AI_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(FALLBACK_AI_API_URL, headers={"x-api-key": FALLBACK_AI_API_KEY},
                                  data=_form(message, FALLBACK_AI_CHANNEL_ID))
        if r.status_code != 200:
            logger.warning("fallback ChatGPT: HTTP %s", r.status_code)
            return ""
        return _parse_stream(r.text)
    except httpx.HTTPError as e:
        logger.warning("fallback ChatGPT: erro %s", e)
        return ""


def ask_agent(message: str, *, timeout: float = 120.0) -> str:
    """Versão síncrona (para threads/scripts). Tenta o agente Claude (iaedu.pt) com retry/
    backoff; se ficar vazio (tipicamente rate limit 429) e houver FALLBACK_AI_API_KEY, cai
    no 2º agente (ChatGPT/iaedu). Devolve "" só se ambos falharem."""
    if AI_API_KEY:
        for attempt in range(_RETRIES + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(AI_API_URL, headers={"x-api-key": AI_API_KEY}, data=_form(message))
                text = _parse_stream(response.text) if response.status_code == 200 else ""
                if response.status_code != 200:
                    logger.warning("ask_agent: HTTP %s", response.status_code)
            except httpx.HTTPError as e:
                logger.warning("ask_agent: HTTPError %s", e)
                text = ""
            if text:
                _clear_rate_limit()
                return text
            if attempt < _RETRIES:
                time.sleep(_BACKOFF)
    else:
        logger.warning("ask_agent: AI_API_KEY vazia")
    fb = _ask_fallback(message, timeout=timeout)
    if fb:
        logger.info("ask_agent: usei fallback ChatGPT")
    return fb


async def ask_agent_async(message: str, *, timeout: float = 120.0) -> str:
    """Versão async (para endpoints async). Tenta o agente Claude (iaedu.pt) com retry/
    backoff; se ficar vazio (tipicamente rate limit 429) e houver FALLBACK_AI_API_KEY, cai
    no 2º agente (ChatGPT/iaedu). Devolve "" só se ambos falharem."""
    if AI_API_KEY:
        for attempt in range(_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(AI_API_URL, headers={"x-api-key": AI_API_KEY}, data=_form(message))
                text = _parse_stream(response.text) if response.status_code == 200 else ""
                if response.status_code != 200:
                    logger.warning("ask_agent_async: HTTP %s", response.status_code)
            except httpx.HTTPError as e:
                logger.warning("ask_agent_async: HTTPError %s", e)
                text = ""
            if text:
                _clear_rate_limit()
                return text
            if attempt < _RETRIES:
                await asyncio.sleep(_BACKOFF)
    else:
        logger.warning("ask_agent_async: AI_API_KEY vazia")
    fb = await _ask_fallback_async(message, timeout=timeout)
    if fb:
        logger.info("ask_agent_async: usei fallback ChatGPT")
    return fb


def ping() -> bool:
    """Sonda única (sem retry) para ver se a IA responde agora. Atualiza o estado de
    rate limit (limpa se responder, marca se ainda estiver estrangulada)."""
    if not AI_API_KEY:
        return False
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(AI_API_URL, headers={"x-api-key": AI_API_KEY}, data=_form("ping"))
        text = _parse_stream(r.text) if r.status_code == 200 else ""
    except httpx.HTTPError:
        text = ""
    if text:
        _clear_rate_limit()
        return True
    return False


def extract_json(text: str):
    """Extrai o primeiro objecto/array JSON de uma resposta da IA (tolera ```json``` e texto à volta)."""
    import re

    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if not candidate:
        m = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
        candidate = m.group() if m else None
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None
