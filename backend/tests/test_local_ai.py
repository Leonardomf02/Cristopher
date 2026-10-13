"""Modelo local: só entra onde faz sentido, e nunca parte nada quando falta.

O ponto do modelo local é poupar a quota do agente partilhado no trabalho barato
(escolher uma categoria de uma lista). O que estes testes garantem é o mais
importante: sem Ollama a correr, tudo continua a funcionar pelo caminho do
costume.

Corre sozinho:  python tests/test_local_ai.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_ai


def _sem_sonda():
    local_ai._sonda = None


def test_desligado_por_variavel_nao_tenta_sequer():
    _sem_sonda()
    antigo = local_ai.LIGADO
    local_ai.LIGADO = False
    try:
        assert local_ai.disponivel() is False
        assert local_ai.pergunta("olá") == ""
        assert local_ai.pergunta_json("olá") is None
    finally:
        local_ai.LIGADO = antigo
        _sem_sonda()


def test_sem_servidor_devolve_vazio_em_vez_de_rebentar():
    _sem_sonda()
    antigo = local_ai.URL
    local_ai.URL = "http://localhost:1"          # porta onde não há nada
    try:
        assert local_ai.disponivel() is False
        assert local_ai.pergunta("olá") == ""
        assert local_ai.pergunta_json("olá") is None
    finally:
        local_ai.URL = antigo
        _sem_sonda()


def test_a_sonda_fica_guardada():
    """Perguntar "estás aí?" antes de cada chamada duplicava o trabalho."""
    _sem_sonda()
    local_ai.URL = "http://localhost:1"
    ligado = local_ai.LIGADO
    local_ai.LIGADO = True               # os testes correm com LOCAL_AI=0 (conftest)
    try:
        local_ai.disponivel()
        assert local_ai._sonda is not None
        marca = local_ai._sonda
        local_ai.disponivel()
        assert local_ai._sonda is marca      # não voltou a sondar
    finally:
        local_ai.LIGADO = ligado
        local_ai.URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
        _sem_sonda()


def test_estado_diz_o_que_esta_configurado():
    e = local_ai.estado()
    assert set(e) == {"enabled", "url", "model", "available"}
    assert isinstance(e["available"], bool)


def test_a_classificacao_de_lojas_nao_depende_do_modelo_local():
    """As regras do banco ficam guardadas para sempre: o agente vai primeiro e o
    local é só rede de segurança. Se isto mudar, é de propósito."""
    import inspect
    import bank_ai
    fonte = inspect.getsource(bank_ai.classifica_desconhecidas)
    pos_agente = fonte.index("ask_agent(")
    pos_local = fonte.index("local_ai.pergunta_json")
    assert pos_agente < pos_local, "o agente tem de ser tentado primeiro"


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {nome}")
            except AssertionError as ex:
                falhas += 1
                print(f"  FALHA {nome}: {ex}")
    print(f"\n{falhas} falhas")
    sys.exit(1 if falhas else 0)
