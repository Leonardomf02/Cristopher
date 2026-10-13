"""Modelo local (Ollama) para o trabalho barato de IA.

O agente iaedu.pt é partilhado, tem rate limit e é o recurso mais escasso da app.
Mas nem tudo o que ele faz precisa de um modelo grande com pesquisa web: pôr
"Żabka" em `groceries` ou resumir três notas de projecto é trabalho que um modelo
de 8B faz no Mac dele, de graça, sem sair da máquina e sem fila.

Fica para o agente o que só ele consegue: pesquisar na web (deals, histórias,
sinais de investimento) e escrever SQL para o Perguntar.

Sem Ollama a correr, `pergunta()` devolve "" e quem chama cai no agente do
costume — nada deixa de funcionar por isto estar desligado.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODELO = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
LIGADO = os.getenv("LOCAL_AI", "1") != "0"

# O Ollama corta o prompt a 4096 sem avisar e o modelo responde à mesma, com
# confiança, a partir de metade do texto: num teste com 60 anúncios inventou o
# preço e o código de contacto. Aos 32k acerta, e custa ~9 GB de RAM.
CONTEXTO = int(os.getenv("OLLAMA_NUM_CTX", "32768"))

# Quanto tempo se guarda o resultado da sonda: perguntar "estás aí?" antes de
# cada chamada duplicava o trabalho.
_TTL_SONDA = 120.0
_sonda: tuple[float, bool] | None = None


def disponivel(forcar: bool = False) -> bool:
    """O Ollama está a responder e tem o modelo? Resultado guardado 2 minutos."""
    global _sonda
    if not LIGADO:
        return False
    if not forcar and _sonda and (time.time() - _sonda[0]) < _TTL_SONDA:
        return _sonda[1]
    ok = False
    try:
        r = httpx.get(f"{URL}/api/tags", timeout=2.0)
        if r.status_code == 200:
            nomes = {m.get("name", "") for m in r.json().get("models", [])}
            # "llama3:8b" está lá como "llama3:8b"; aceita-se também sem a etiqueta
            ok = MODELO in nomes or any(n.split(":")[0] == MODELO.split(":")[0] for n in nomes)
    except httpx.HTTPError:
        ok = False
    _sonda = (time.time(), ok)
    return ok


def estado() -> dict:
    return {"enabled": LIGADO, "url": URL, "model": MODELO, "available": disponivel()}


def pergunta(prompt: str, *, timeout: float = 60.0, json_mode: bool = False,
             feature: str = "local") -> str:
    """Uma resposta do modelo local. "" quando não está disponível ou falha.

    `json_mode` obriga o modelo a devolver JSON válido (o Ollama garante-o), que
    é o que interessa para classificar coisas."""
    if not disponivel():
        return ""
    corpo = {
        "model": MODELO,
        "prompt": prompt,
        "stream": False,
        # Modelos com raciocínio (o Qwen3.5 é um) mandam a resposta para o campo
        # `thinking` e devolvem `response` vazio quando se pede JSON — tudo o que
        # é local deixava de funcionar sem um único erro.
        "think": False,
        # temperatura baixa: isto é para classificar e resumir, não para inventar
        "options": {"temperature": 0.1, "num_predict": 800, "num_ctx": CONTEXTO},
    }
    if json_mode:
        corpo["format"] = "json"
    try:
        r = httpx.post(f"{URL}/api/generate", json=corpo, timeout=timeout)
        if r.status_code != 200:
            logger.warning("modelo local: HTTP %s", r.status_code)
            return ""
        return (r.json().get("response") or "").strip()
    except httpx.HTTPError as ex:
        logger.warning("modelo local: %s", ex)
        return ""


def pergunta_json(prompt: str, *, timeout: float = 60.0) -> Optional[dict | list]:
    """Como `pergunta`, já com o JSON lido. None se não vier nada de jeito."""
    texto = pergunta(prompt, timeout=timeout, json_mode=True)
    if not texto:
        return None
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        from ai_config import extract_json
        return extract_json(texto)
