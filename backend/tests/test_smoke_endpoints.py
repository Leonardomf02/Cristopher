"""Bate em todos os GET da app e verifica que nenhum rebenta.

Existe porque houve coisas partidas durante meses sem ninguém dar por nada: o
`/expenses/by-hour` a devolver sempre vazio, o custo de IA a zero desde que o
WakaTime mudou um nome de campo, o `run_job_now` com um NameError à espera de
alguém pedir um trabalho que não existisse.

Não valida números — valida que a app responde. Endpoints que dependem de rede
(Riot, banco, IA, WakaTime) ficam de fora: falhariam por estar offline, não por
estarem partidos.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("TRACKER_AUTOSTART", "0")
os.environ.setdefault("DEALS_AUTOSCAN", "0")
os.environ.setdefault("EVENT_NOTIFY", "0")
os.environ.setdefault("NOTIFY_NUDGES", "0")

from main import app  # noqa: E402

client = TestClient(app)

# Chamam serviços de fora: sem rede (ou sem chave) dariam falso alarme.
FORA = (
    "/api/lol/riot", "/api/lol/live-client", "/api/banking/institutions",
    "/api/investments/signals/preview-", "/api/investments/signals/market-pulse",
    "/api/investments/signals/data-sources", "/api/investments/signals/health",
    "/api/investments/search-asset", "/api/wakatime/sync", "/api/screen-time/app-icon",
    "/api/events/apple-calendars", "/api/deals/ai-check", "/api/investments/suggestions",
    "/api/spotify/search", "/api/code-activity/weekly-summary", "/api/mood/journal-draft",
    "/api/mood/journal-prompts", "/api/habits/suggestions", "/api/backups/run",
    "/api/ingest/reminders/wait",   # espera longa do agente: ficava 25s pendurado
)


def _rotas_get() -> list[str]:
    """Os GET sem parâmetros obrigatórios no caminho — esses precisam de um id real."""
    out = []
    for r in app.routes:
        caminho = getattr(r, "path", "")
        if "GET" not in getattr(r, "methods", set()) or "{" in caminho:
            continue
        if not caminho.startswith("/api") or any(caminho.startswith(p) for p in FORA):
            continue
        out.append(caminho)
    return sorted(set(out))


# O que se procura é o 500 — erro de programação. Uma rota que responde "não há
# nada" ou "falta-me uma permissão do sistema" está a funcionar:
#   422 falta um parâmetro de query   404 não há dados para mostrar
#   503 depende de algo indisponível (o knowledgeC precisa de Full Disk Access,
#       que o processo de teste não tem, ao contrário do backend a sério)
ACEITES = (200, 404, 422, 503)


@pytest.mark.parametrize("caminho", _rotas_get())
def test_get_responde(caminho):
    r = client.get(caminho)
    assert r.status_code in ACEITES, f"{caminho} devolveu {r.status_code}: {r.text[:200]}"


def test_ha_rotas_para_testar():
    """Se o filtro alguma vez engolir tudo, este teste avisa em vez de passar vazio."""
    assert len(_rotas_get()) > 40


def test_saude_dos_dados_inclui_copias():
    r = client.get("/api/health/data")
    assert r.status_code == 200
    dados = r.json()
    assert "backups" in dados, "o painel de saúde deixou de olhar às cópias de segurança"
    assert {"sources", "jobs", "problems"} <= set(dados)


def test_por_hora_conta_as_despesas_sem_hora():
    """O painel esconde-se quando não há horas; o número das que faltam tem de vir."""
    r = client.get("/api/expenses/by-hour")
    assert r.status_code == 200
    d = r.json()
    assert d["with_time"] + d["without_time"] > 0 or d["total"] == 0
