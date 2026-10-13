"""Perguntar com continuação: "e no mês passado?" tem de saber do que se fala.

Cada pergunta chegava à IA sozinha, sem as anteriores, por isso qualquer
seguimento era ininteligível. Estes testes mockam o agente e verificam o que
lhe é realmente enviado — e que a validação do SQL continua a recusar escrita.

Corre sozinho:  python tests/test_ask_conversa.py
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routers.ask as ask


class AgenteFalso:
    """Guarda os prompts que recebeu e devolve o que lhe mandarem devolver."""
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.prompts = []

    async def __call__(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.respostas.pop(0) if self.respostas else ""


def _corre(pergunta, contexto=()):
    agente = AgenteFalso([
        '{"sql": "SELECT ROUND(SUM(amount),2) AS Total FROM expenses WHERE category = \'food\'", '
        '"title": "Comida", "chart": "table"}',
        "Gastaste 639,50€ em comida.",
    ])
    original = ask.ask_agent_async
    ask.ask_agent_async = agente
    try:
        corpo = ask.Pergunta(
            question=pergunta,
            context=[ask.Anterior(**c) for c in contexto],
        )
        r = asyncio.run(ask.perguntar(corpo, db=None))
        return r, agente.prompts
    finally:
        ask.ask_agent_async = original


def test_sem_contexto_nao_mete_conversa_no_prompt():
    _, prompts = _corre("quanto gastei em comida?")
    assert "Já nesta conversa" not in prompts[0]


def test_com_contexto_manda_as_perguntas_e_o_sql_anteriores():
    _, prompts = _corre(
        "e no mês passado?",
        [{"question": "quanto gastei em comida em maio?",
          "sql": "SELECT SUM(amount) FROM expenses WHERE category='food'"}],
    )
    p = prompts[0]
    assert "Já nesta conversa" in p
    assert "quanto gastei em comida em maio?" in p
    assert "FROM expenses WHERE category='food'" in p
    assert "e no mês passado?" in p


def test_so_as_tres_ultimas_entram():
    contexto = [{"question": f"pergunta {i}", "sql": f"SELECT {i}"} for i in range(6)]
    _, prompts = _corre("e agora?", contexto)
    p = prompts[0]
    assert "pergunta 5" in p and "pergunta 3" in p
    assert "pergunta 2" not in p          # ficou de fora, como se quer


def test_resposta_completa():
    r, prompts = _corre("quanto gastei em comida?")
    assert r["sql"].lower().startswith("select")
    assert "LIMIT" in r["sql"]            # limite imposto pela app
    assert r["answer"] == "Gastaste 639,50€ em comida."
    assert len(prompts) == 2              # uma para o SQL, outra para a frase


def test_sql_de_escrita_e_recusado():
    from fastapi import HTTPException
    for mau in ("DELETE FROM expenses", "UPDATE expenses SET amount = 0",
                "SELECT 1; DROP TABLE expenses", "PRAGMA table_info(expenses)"):
        try:
            ask._valida_sql(mau)
            assert False, f"devia ter recusado: {mau}"
        except HTTPException:
            pass


def test_select_valido_ganha_limite():
    assert ask._valida_sql("SELECT 1").endswith(f"LIMIT {ask.LIMITE_LINHAS}")
    assert ask._valida_sql("SELECT 1 LIMIT 5").endswith("LIMIT 5")


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
