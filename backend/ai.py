"""A IA da app, toda num sítio.

Havia três caminhos diferentes para a mesma coisa: o `ai_config` (agente +
reserva), o `local_ai` (Ollama) e uma cópia inteira dentro dos sinais de
investimento. A cópia tinha um bug que o original não tinha — tratava um 404
como fatal e saltava por cima da reserva — e por causa disso os sinais saíram
**doze dias seguidos sem narração** enquanto o resto da app continuava a
funcionar pela reserva sem ninguém dar por nada.

Agora há uma porta só, com três degraus:

    1. agente principal   (iaedu.pt)
    2. agente de reserva  (2º agente iaedu.pt)
    3. modelo local       (Ollama, no Mac dele)

O terceiro degrau é o que faltava: quando os dois agentes online morrem — e
morrem, o principal chegou a ser apagado do lado deles — a app deixava de ter
IA nenhuma. O modelo local não pesquisa na web e não escreve SQL tão bem, mas
classifica, resume e escreve português; nessas coisas vale muito mais do que
não haver resposta.

Quem responde fica registado (`estado()`), porque uma app que anda a funcionar
com a rede de segurança tem de o dizer em vez de fingir que está tudo bem.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Configuração ────────────────────────────────────────────────────────

AI_API_URL = os.getenv(
    "AI_API_URL",
    "https://api.iaedu.pt/agent-chat//api/v1/agent/cmoss7l0f658oko01vk2egfpg/stream",
)
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_CHANNEL_ID = os.getenv("AI_CHANNEL_ID", "cmq0tu39r1b1unr01jwra3hfu")

FALLBACK_AI_API_URL = os.getenv(
    "FALLBACK_AI_API_URL",
    "https://api.iaedu.pt/agent-chat//api/v1/agent/cmamvd3n40000c801qeacoad2/stream",
)
FALLBACK_AI_API_KEY = os.getenv("FALLBACK_AI_API_KEY", "")
FALLBACK_AI_CHANNEL_ID = os.getenv("FALLBACK_AI_CHANNEL_ID", "cmnauzuoxjik3hv01gjna24hw")

_RETRIES = 2          # tentativas extra em caso de vazio (rate limit / transitório)
_BACKOFF = 3.0        # segundos entre tentativas
# Tecto para o degrau local, em segundos (ver `_tenta_local`).
LOCAL_TIMEOUT = float(os.getenv("AI_LOCAL_TIMEOUT", "60"))

PRINCIPAL, RESERVA, LOCAL = "principal", "reserva", "local"


# ── Estado: quem respondeu e desde quando ───────────────────────────────

_rate_limited_at: Optional[float] = None
_rate_limit_msg: str = ""
_ultimo_motor: str = ""
_ultimo_motor_em: Optional[float] = None
# Só se avisa uma vez por dia que a app anda no local — senão era ruído.
_avisado_local_em: Optional[float] = None


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


def _marca_motor(motor: str) -> None:
    global _ultimo_motor, _ultimo_motor_em
    _ultimo_motor, _ultimo_motor_em = motor, time.time()


def has_fallback() -> bool:
    return bool(FALLBACK_AI_API_KEY)


def ai_status() -> dict:
    """Estado da IA para o frontend e para o painel de saúde.

    `engine` diz quem respondeu da última vez. `degraded` é o que interessa: a
    app está a funcionar, mas não com quem devia."""
    import local_ai
    return {
        "rate_limited": _rate_limited_at is not None,
        "seconds_ago": int(time.time() - _rate_limited_at) if _rate_limited_at else None,
        "message": _rate_limit_msg,
        "fallback": has_fallback(),
        "engine": _ultimo_motor,
        "engine_seconds_ago": int(time.time() - _ultimo_motor_em) if _ultimo_motor_em else None,
        "local_available": local_ai.disponivel(),
        "degraded": _ultimo_motor in (RESERVA, LOCAL),
    }


# Nome antigo, mantido porque meia dúzia de sítios já o chamam assim.
estado = ai_status


# ── Transporte: os dois agentes online ──────────────────────────────────

def _form(message: str, channel_id: str = "") -> dict:
    return {
        "channel_id": channel_id or AI_CHANNEL_ID,
        "thread_id": uuid.uuid4().hex[:20],
        "user_info": "{}",
        "message": message,
    }


def parse_agent_stream(full: str) -> tuple[str, Optional[str]]:
    """Lê o stream do agente e devolve (resposta, erro).

    Há dois formatos: `token` a pingar pedaço a pedaço, e `message` com a
    resposta inteira de uma vez. Ler só os tokens dava "empty response" com a
    IA viva — era isto que punha os sinais a sair "sem narração IA". Quando o
    agente usa pesquisa web vêm ainda mensagens ai vazias e uma `type=tool` com
    o resultado da pesquisa: a boa é a ÚLTIMA ai não-vazia.

    Havia duas versões disto na app e só esta sabia do prefixo `data:` e dos
    eventos `end`/`done` — por isso é esta que ficou."""
    tokens = ""
    mensagem_final = ""
    erro = None
    for line in full.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if not isinstance(obj, dict):
            continue
        tipo = obj.get("type", "")
        content = obj.get("content", "")
        if tipo == "token" and content:
            tokens += content
        elif tipo == "message":
            if isinstance(content, dict):
                if content.get("type") in (None, "ai") and content.get("content"):
                    mensagem_final = content["content"]
            elif isinstance(content, str) and content:
                mensagem_final = content
        elif tipo == "error":
            erro = content or "erro desconhecido no agente"
        elif tipo in ("end", "done"):
            break
    return (mensagem_final or tokens).strip(), erro


def _parse_stream(raw_text: str) -> str:
    """Só o texto, com o erro do stream registado para o estado de rate limit."""
    texto, erro = parse_agent_stream(raw_text)
    if erro:
        logger.warning("agente devolveu erro: %s", erro)
        _note_error(erro)
    return texto


def _agentes() -> list[tuple[str, str, str, str]]:
    """(motor, url, chave, channel) por ordem de preferência. Só os configurados."""
    out = []
    if AI_API_KEY:
        out.append((PRINCIPAL, AI_API_URL, AI_API_KEY, AI_CHANNEL_ID))
    if FALLBACK_AI_API_KEY:
        out.append((RESERVA, FALLBACK_AI_API_URL, FALLBACK_AI_API_KEY, FALLBACK_AI_CHANNEL_ID))
    return out


def _http_erro(motor: str, status: int) -> None:
    # Um 404 quer dizer que o agente foi apagado do lado deles — aconteceu, e a
    # cópia do código nos sinais tratava-o como fatal em vez de passar ao
    # seguinte. Aqui nenhum código de erro trava a cascata.
    logger.warning("ia[%s]: HTTP %s%s", motor, status,
                   " (agente não existe — ver AI_API_URL)" if status == 404 else "")


# ── Degrau 3: modelo local ──────────────────────────────────────────────

def _tenta_local(message: str, *, json_mode: bool, timeout: float) -> str:
    import local_ai
    if not local_ai.disponivel():
        return ""
    # Trela curta de propósito. O modelo local gera a ~14 tokens/s: uma resposta
    # longa leva minutos, e uma página que antes dizia "IA indisponível" em 5s
    # passava a ficar pendurada 200s à espera dele. Quem tem tempo (os trabalhos
    # da noite) pede um timeout maior e leva-o.
    texto = local_ai.pergunta(message, timeout=min(timeout, LOCAL_TIMEOUT),
                              json_mode=json_mode)
    if texto:
        _avisa_que_anda_no_local()
    return texto


def _avisa_que_anda_no_local() -> None:
    """Uma vez por dia: a app estar a responder com o modelo local quer dizer que
    os dois agentes estão em baixo, e isso não pode passar despercebido."""
    global _avisado_local_em
    agora = time.time()
    if _avisado_local_em and agora - _avisado_local_em < 24 * 3600:
        return
    _avisado_local_em = agora
    try:
        from notifier import notify
        notify("IA: a funcionar com o modelo local",
               "Os agentes online não responderam e a app está a usar o modelo do Mac. "
               "Sem pesquisa web e com respostas mais fracas — vê a chave em AI_API_URL.",
               severity="warning")
    except Exception:                     # um aviso nunca pode partir a resposta
        logger.info("ia: a usar o modelo local (aviso não saiu)")


# ── A porta única ───────────────────────────────────────────────────────

def pergunta(message: str, *, timeout: float = 120.0, feature: str = "outro",
             json_mode: bool = False, permite_local: bool = True) -> str:
    """Agente principal → agente de reserva → modelo local. "" se nenhum responder.

    `feature` diz que parte da app está a pedir, para se saber quem gasta a quota
    (ver `ai_budget`). `permite_local=False` para o que não faz sentido sem
    pesquisa web."""
    import ai_budget
    ai_budget.regista(feature)

    for motor, url, chave, canal in _agentes():
        for tentativa in range(_RETRIES + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    r = client.post(url, headers={"x-api-key": chave},
                                    data=_form(message, canal))
                texto = _parse_stream(r.text) if r.status_code == 200 else ""
                if r.status_code != 200:
                    _http_erro(motor, r.status_code)
                    break                 # não vale a pena repetir um 404/401
            except httpx.HTTPError as e:
                logger.warning("ia[%s]: %s", motor, e)
                texto = ""
            if texto:
                _clear_rate_limit()
                _marca_motor(motor)
                return texto
            if tentativa < _RETRIES:
                time.sleep(_BACKOFF)

    if permite_local:
        texto = _tenta_local(message, json_mode=json_mode, timeout=timeout)
        if texto:
            _marca_motor(LOCAL)
            return texto
    logger.error("ia: nenhum motor respondeu (feature=%s)", feature)
    return ""


async def pergunta_async(message: str, *, timeout: float = 120.0, feature: str = "outro",
                         json_mode: bool = False, permite_local: bool = True) -> str:
    """Igual a `pergunta`, para quem já está dentro de um endpoint async."""
    import ai_budget
    ai_budget.regista(feature)

    for motor, url, chave, canal in _agentes():
        for tentativa in range(_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.post(url, headers={"x-api-key": chave},
                                          data=_form(message, canal))
                texto = _parse_stream(r.text) if r.status_code == 200 else ""
                if r.status_code != 200:
                    _http_erro(motor, r.status_code)
                    break
            except httpx.HTTPError as e:
                logger.warning("ia[%s]: %s", motor, e)
                texto = ""
            if texto:
                _clear_rate_limit()
                _marca_motor(motor)
                return texto
            if tentativa < _RETRIES:
                await asyncio.sleep(_BACKOFF)

    if permite_local:
        # O Ollama é síncrono e demora; fora do event loop para não prender o resto.
        texto = await asyncio.to_thread(
            _tenta_local, message, json_mode=json_mode, timeout=timeout)
        if texto:
            _marca_motor(LOCAL)
            return texto
    logger.error("ia: nenhum motor respondeu (feature=%s)", feature)
    return ""


def ping() -> bool:
    """Algum motor responde agora? Serve o painel de saúde."""
    for motor, url, chave, canal in _agentes():
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.post(url, headers={"x-api-key": chave}, data=_form("ping", canal))
            if r.status_code == 200 and _parse_stream(r.text):
                _clear_rate_limit()
                _marca_motor(motor)
                return True
        except httpx.HTTPError:
            continue
    import local_ai
    return local_ai.disponivel()


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
