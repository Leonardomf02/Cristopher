"""Ligação ao relógio Garmin.

A Garmin não abre a API oficial a pessoas: o programa de developers exige uma
entidade legal e recusa uso pessoal. O caminho é a biblioteca `garminconnect`,
que faz o mesmo login que a app Android.

O cuidado deste módulo existe por uma razão concreta: o limite de pedidos da
Garmin é no **login**, é **por conta** (mudar de rede ou de IP não safa) e
bloqueia **48 horas**. Por isso o backend nunca faz login com password — só
carrega o token que o `scripts/garmin_login.py` gravou uma vez. Se o token
morrer, isto falha com uma mensagem a pedir novo login em vez de tentar de novo
e queimar a conta.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

TOKENS_DIR_DEFAULT = "~/.garminconnect"

# Sem tantas noites o relógio não tem baseline de HRV e o estado vem vazio —
# a app diz quantas faltam em vez de mostrar uma caixa vazia.
NOITES_PARA_BASELINE_HRV = 19


class GarminIndisponivel(RuntimeError):
    """Não dá para falar com a Garmin agora (sem token, token morto, rate limit)."""


def token_dir() -> Path:
    return Path(os.getenv("GARMIN_TOKENS_DIR") or TOKENS_DIR_DEFAULT).expanduser()


def tem_token() -> bool:
    d = token_dir()
    return d.is_dir() and any(d.glob("*.json"))


def activo() -> bool:
    return os.getenv("GARMIN_SYNC", "1") != "0" and tem_token()


_cliente = None


def cliente(*, forcar: bool = False):
    """Sessão autenticada, reutilizada entre chamadas.

    Reutilizar é o ponto todo: cada `login()` novo é um pedido ao SSO, e é o SSO
    que bloqueia contas.
    """
    global _cliente
    if _cliente is not None and not forcar:
        return _cliente

    try:
        from garminconnect import Garmin
    except ImportError as e:                                    # pragma: no cover
        raise GarminIndisponivel(f"biblioteca garminconnect não instalada: {e}")

    if not tem_token():
        raise GarminIndisponivel(
            f"sem token em {token_dir()} — correr `python scripts/garmin_login.py` uma vez"
        )

    # Sem email/password: se o token não servir, a biblioteca não tem por onde
    # tentar um login novo. É essa a garantia que queremos.
    api = Garmin()
    try:
        api.login(tokenstore=str(token_dir()))
    except Exception as e:
        raise GarminIndisponivel(_explica(e)) from e

    _cliente = api
    return api


def _explica(e: Exception) -> str:
    nome = type(e).__name__
    if "TooManyRequests" in nome:
        return ("a Garmin está a recusar por excesso de pedidos (bloqueio por conta, "
                "costuma durar horas) — não voltar a fazer login até passar")
    if "Authentication" in nome:
        return "token do Garmin expirou — correr `python scripts/garmin_login.py` outra vez"
    return f"{nome}: {e}"


def _tenta(fn: Callable[..., Any], *args: Any) -> Optional[Any]:
    """Chama um endpoint e devolve None quando não há dados para esse dia.

    Um dia sem sono medido, ou uma métrica que este relógio não calcula, devolve
    404 ou vazio — isso não é erro e não pode derrubar a sincronização toda.
    """
    try:
        return fn(*args)
    except Exception as e:
        nome = type(e).__name__
        if "TooManyRequests" in nome or "Authentication" in nome:
            raise GarminIndisponivel(_explica(e)) from e
        logger.debug("garmin: %s falhou (%s: %s)", getattr(fn, "__name__", fn), nome, e)
        return None


def dia(quando: date) -> dict[str, Any]:
    """Tudo o que a Garmin sabe sobre um dia, em cru.

    Cada peça é opcional: o Forerunner 70 não calcula limiar de lactato nem
    Endurance Score, e o Training Readiness só aparece depois de ~19 noites.
    """
    api = cliente()
    d = quando.isoformat()
    return {
        "date": d,
        "sono": _tenta(api.get_sleep_data, d),
        "hrv": _tenta(api.get_hrv_data, d),
        "stress": _tenta(api.get_all_day_stress, d),
        "resumo": _tenta(api.get_user_summary, d),
        "fc": _tenta(api.get_heart_rates, d),
        "prontidao": _tenta(api.get_training_readiness, d),
        # A prontidão da manhã traz o **peso de cada factor** (sono, HRV, carga,
        # stress) — é o que explica o número em vez de o afirmar.
        "prontidao_manha": _tenta(api.get_morning_training_readiness, d),
        "estado_treino": _tenta(api.get_training_status, d),
        "vo2max": _tenta(api.get_max_metrics, d),
        # Idade de fitness: diz a quantos anos o corpo está e, melhor, o que
        # falta para lá chegar (minutos vigorosos por semana, dias por semana).
        "idade": _tenta(api.get_fitnessage_data, d),
        "peso": _tenta(api.get_daily_weigh_ins, d),
        "passos": _tenta(api.get_steps_data, d),
        # A linha do dia da app da Garmin: onde começou e acabou cada sono, cada
        # sesta e cada movimento. As sestas não vêm no sono — só aqui.
        "eventos": _tenta(api.get_body_battery_events, d),
        # Move IQ: o que o relógio detectou sozinho (uma caminhada de 25 minutos)
        # e que não é uma actividade gravada — `get_activities_by_date` devolve
        # vazio nesses dias.
        "movimentos": _tenta(api.get_all_day_events, d),
    }


def actividades(desde: date, ate: Optional[date] = None) -> list[dict[str, Any]]:
    api = cliente()
    ate = ate or date.today()
    return _tenta(api.get_activities_by_date, desde.isoformat(), ate.isoformat()) or []


def snapshots(inicio: date, fim: Optional[date] = None) -> list[dict[str, Any]]:
    """Health Snapshots — os dois minutos parado que ele grava no relógio.

    Não são actividades e não estão em nenhum endpoint REST: só saem pelo
    gateway GraphQL do Garmin Connect. É o único sítio da conta onde há HRV
    (RMSSD e SDRR) sem esperar as 19 noites de linha de base.
    """
    api = cliente()
    fim = fim or date.today()
    pergunta = {
        "query": ('query{healthSnapshotScalar('
                  f'startDate:"{inicio.isoformat()}", endDate:"{fim.isoformat()}")}}')
    }
    resposta = _tenta(api.query_garmin_graphql, pergunta) or {}
    dados = (resposta.get("data") or {}).get("healthSnapshotScalar")
    return dados if isinstance(dados, list) else []


def ultimo_upload() -> Optional[int]:
    """Quando é que o relógio passou pelo telemóvel, em milissegundos.

    Um pedido só, para responder a "vale a pena ir buscar tudo?". Sem isto, a
    alternativa era pedir os dez endereços de hora a hora e receber o mesmo de
    sempre — assim a sondagem pode ser frequente e a leitura pesada só acontece
    quando há mesmo coisa nova."""
    api = cliente()
    quando = (_tenta(api.get_device_last_used) or {}).get("lastUsedDeviceUploadTime")
    try:
        return int(quando) if quando else None
    except (TypeError, ValueError):
        return None


def perfil() -> dict[str, Any]:
    """Nome e relógio ligado — serve para a página dizer de que aparelho fala."""
    api = cliente()
    aparelhos = _tenta(api.get_devices) or []
    return {
        "nome": getattr(api, "display_name", None) or getattr(api, "full_name", None),
        "aparelhos": [
            {"nome": a.get("displayName") or a.get("productDisplayName"),
             "id": a.get("deviceId")}
            for a in aparelhos if isinstance(a, dict)
        ],
    }


def zonas_fc() -> Optional[dict[str, Any]]:
    """Os limiares das zonas de frequência cardíaca configurados no relógio.

    Não é por dia — muda quando ele muda o perfil — por isso vive em cache e é
    pedido uma vez por mês. Sem isto, 140 bpm num gráfico é um número solto; com
    isto é zona 3. Vem uma linha por desporto e interessa a `DEFAULT`."""
    api = cliente()
    perfis = _tenta(api.get_heart_rate_zones) or []
    if not isinstance(perfis, list) or not perfis:
        return None
    linha = next((p for p in perfis if isinstance(p, dict) and p.get("sport") == "DEFAULT"),
                 perfis[0])
    if not isinstance(linha, dict):
        return None

    def _int(v: Any) -> Optional[int]:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    pisos = [_int(linha.get(f"zone{i}Floor")) for i in range(1, 6)]
    maximo = _int(linha.get("maxHeartRateUsed"))
    if any(p is None for p in pisos) or maximo is None:
        return None
    return {"floors": pisos, "max": maximo,
            "resting": _int(linha.get("restingHeartRateUsed")),
            "method": linha.get("trainingMethod")}


def dias_em_falta(existentes: set[date], dias: int = 7,
                  nao_antes: Optional[date] = None) -> list[date]:
    """Os dias dos últimos N que ainda não estão na base, do mais recente para trás.

    Hoje e ontem entram sempre: o dia de ontem só fica completo depois de o
    telemóvel sincronizar, e o de hoje muda a cada leitura. `nao_antes` corta os
    dias em que ele ainda não tinha o relógio — sem isso eram seis leituras por
    passagem a devolver vazio, para sempre.
    """
    hoje = date.today()
    saida = [hoje, hoje - timedelta(days=1)]
    for i in range(2, dias + 1):
        d = hoje - timedelta(days=i)
        if d in existentes or (nao_antes and d < nao_antes):
            continue
        saida.append(d)
    return saida
