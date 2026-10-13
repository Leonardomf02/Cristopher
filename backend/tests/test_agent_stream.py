"""O stream do agente iaedu.pt vem em dois formatos e o motor de sinais só lia um.

Durante dias os sinais saíram com o cabeçalho "Sinais do motor (sem narração IA)"
com a IA perfeitamente viva: o agente respondia numa mensagem inteira em vez de
tokens e o parser devolvia vazio.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routers.investment_signals import parse_agent_stream  # noqa: E402


def _linhas(*eventos) -> str:
    return "\n".join(json.dumps(e) for e in eventos)


def test_tokens_soltos():
    stream = _linhas(
        {"type": "token", "content": "Risk-on "},
        {"type": "token", "content": "moderado"},
        {"type": "end"},
    )
    assert parse_agent_stream(stream) == ("Risk-on moderado", None)


def test_mensagem_inteira():
    """O formato que rebentava: nenhum token, só a mensagem no fim."""
    stream = _linhas(
        {"type": "message", "content": {"type": "ai", "content": "Reforçar BTC este mês"}},
    )
    texto, erro = parse_agent_stream(stream)
    assert texto == "Reforçar BTC este mês"
    assert erro is None


def test_pesquisa_web_ignora_ai_vazia_e_tool():
    """Com pesquisa web vêm mensagens ai vazias + o resultado da tool pelo meio.
    A resposta é a última ai não-vazia, não a primeira nem a da tool."""
    stream = _linhas(
        {"type": "message", "content": {"type": "ai", "content": ""}},
        {"type": "message", "content": {"type": "tool", "content": "[{\"url\": \"reuters.com\"}]"}},
        {"type": "message", "content": {"type": "ai", "content": "Fed manteve juros"}},
    )
    assert parse_agent_stream(stream)[0] == "Fed manteve juros"


def test_mensagem_ganha_aos_tokens_parciais():
    stream = _linhas(
        {"type": "token", "content": "pens"},
        {"type": "message", "content": {"type": "ai", "content": "resposta completa"}},
    )
    assert parse_agent_stream(stream)[0] == "resposta completa"


def test_erro_de_rate_limit():
    stream = _linhas({"type": "error", "content": "Rate limit reached (429)"})
    texto, erro = parse_agent_stream(stream)
    assert texto == ""
    assert "Rate limit" in erro


def test_formato_sse_com_prefixo_data():
    stream = "data: " + json.dumps({"type": "token", "content": "olá"}) + "\ndata: [DONE]"
    assert parse_agent_stream(stream)[0] == "olá"


def test_lixo_nao_rebenta():
    assert parse_agent_stream("<html>502 Bad Gateway</html>") == ("", None)
    assert parse_agent_stream("") == ("", None)
