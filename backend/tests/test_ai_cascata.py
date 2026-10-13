"""A cascata: agente principal → agente de reserva → modelo local.

O bug que isto fecha: a cópia do código da IA que vivia dentro dos sinais de
investimento tratava um 404 como fatal e saltava por cima da reserva. Quando o
agente principal foi apagado do lado do iaedu.pt, os sinais saíram doze dias
seguidos sem narração enquanto o resto da app continuava a funcionar.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai


class Resposta:
    def __init__(self, status, texto=""):
        self.status_code = status
        self.text = texto


def _stream(msg: str) -> str:
    return '{"type": "message", "content": {"type": "ai", "content": "%s"}}' % msg


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(ai, "AI_API_KEY", "chave-principal")
    monkeypatch.setattr(ai, "FALLBACK_AI_API_KEY", "chave-reserva")
    monkeypatch.setattr(ai, "_RETRIES", 0)
    monkeypatch.setattr(ai, "_BACKOFF", 0)
    monkeypatch.setattr(ai, "_ultimo_motor", "")
    yield


def _finge_agentes(monkeypatch, por_url: dict):
    """por_url: {url_parcial: Resposta}. Qualquer outra dá ligação recusada."""
    class Cliente:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def post(self, url, **kwargs):
            for pedaco, resp in por_url.items():
                if pedaco in url:
                    return resp
            raise ai.httpx.HTTPError("recusada")

    monkeypatch.setattr(ai.httpx, "Client", Cliente)


def test_principal_responde_e_fica_por_ali(monkeypatch):
    _finge_agentes(monkeypatch, {ai.AI_API_URL: Resposta(200, _stream("do principal"))})
    assert ai.pergunta("olá", permite_local=False) == "do principal"
    assert ai.ai_status()["engine"] == ai.PRINCIPAL
    assert ai.ai_status()["degraded"] is False


def test_404_no_principal_passa_a_reserva(monkeypatch):
    """O 404 é literalmente o que aconteceu: o agente foi apagado."""
    _finge_agentes(monkeypatch, {
        ai.AI_API_URL: Resposta(404, '{"detail":"Agent not found"}'),
        ai.FALLBACK_AI_API_URL: Resposta(200, _stream("da reserva")),
    })
    assert ai.pergunta("olá", permite_local=False) == "da reserva"
    assert ai.ai_status()["engine"] == ai.RESERVA
    assert ai.ai_status()["degraded"] is True


def test_rate_limit_no_principal_tambem_passa_a_reserva(monkeypatch):
    _finge_agentes(monkeypatch, {
        ai.AI_API_URL: Resposta(429, "rate limit"),
        ai.FALLBACK_AI_API_URL: Resposta(200, _stream("da reserva")),
    })
    assert ai.pergunta("olá", permite_local=False) == "da reserva"


def test_os_dois_agentes_em_baixo_cai_no_local(monkeypatch):
    _finge_agentes(monkeypatch, {
        ai.AI_API_URL: Resposta(404),
        ai.FALLBACK_AI_API_URL: Resposta(500),
    })
    monkeypatch.setattr(ai, "_tenta_local", lambda *a, **k: "do modelo local")
    assert ai.pergunta("olá") == "do modelo local"
    assert ai.ai_status()["engine"] == ai.LOCAL
    assert ai.ai_status()["degraded"] is True


def test_local_pode_ser_recusado(monkeypatch):
    """Há coisas que sem pesquisa web não valem nada — quem pede decide."""
    _finge_agentes(monkeypatch, {ai.AI_API_URL: Resposta(500)})
    monkeypatch.setattr(ai, "_tenta_local", lambda *a, **k: "do local")
    assert ai.pergunta("olá", permite_local=False) == ""


def test_tudo_em_baixo_devolve_vazio(monkeypatch):
    _finge_agentes(monkeypatch, {})
    monkeypatch.setattr(ai, "_tenta_local", lambda *a, **k: "")
    assert ai.pergunta("olá") == ""


def test_o_local_leva_trela_curta(monkeypatch):
    """Uma página que falhava em 5s não pode passar a esperar 200s pelo Ollama."""
    pedidos = {}

    class FalsoLocal:
        LIGADO = True
        @staticmethod
        def disponivel(): return True
        @staticmethod
        def pergunta(msg, *, timeout, json_mode=False):
            pedidos["timeout"] = timeout
            return "resposta"

    monkeypatch.setitem(sys.modules, "local_ai", FalsoLocal)
    monkeypatch.setattr(ai, "LOCAL_TIMEOUT", 60.0)
    monkeypatch.setattr(ai, "_avisa_que_anda_no_local", lambda: None)
    ai._tenta_local("olá", json_mode=False, timeout=600.0)
    assert pedidos["timeout"] == 60.0


def test_a_quota_conta_mesmo_quando_falha(monkeypatch):
    """Saber quem gasta é o ponto do ai_budget — falhar também é gastar tentativa."""
    import ai_budget
    _finge_agentes(monkeypatch, {})
    monkeypatch.setattr(ai, "_tenta_local", lambda *a, **k: "")
    antes = ai_budget.gastas("deals")
    ai.pergunta("olá", feature="deals")
    assert ai_budget.gastas("deals") == antes + 1


def test_estado_diz_quem_respondeu():
    e = ai.ai_status()
    for chave in ("engine", "degraded", "local_available", "rate_limited", "fallback"):
        assert chave in e
