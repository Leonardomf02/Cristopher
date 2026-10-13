"""As perguntas que a app faz sobre os dias fora do padrão.

O diário tinha uma entrada em 115 dias. Isto troca a folha em branco por uma
pergunta concreta sobre um dia concreto — mas só vale se a pergunta soar a
português e se não repetir o mesmo assunto quatro vezes.

Corre sozinho:  python tests/test_perguntas_do_dia.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from routers.mood import _pergunta_da_anomalia, _quando

HOJE = date(2026, 8, 2)        # domingo


def test_quando_fala_como_uma_pessoa():
    assert _quando(HOJE, HOJE) == "Hoje"
    assert _quando(date(2026, 8, 1), HOJE) == "Ontem"
    assert _quando(date(2026, 7, 30), HOJE) == "Quinta"       # 4 dias antes
    assert _quando(date(2026, 7, 13), HOJE) == "13/7"          # já longe


def test_pergunta_de_gasto():
    p = _pergunta_da_anomalia({
        "date": "2026-08-01", "key": "gasto-dia",
        "text": "€703 num dia — o teu dia normal é €18.",
    }, HOJE)
    assert p == "Ontem foi um dia caro (€703 num dia — o teu dia normal é €18.) — em quê?"


def test_pergunta_de_sono():
    p = _pergunta_da_anomalia({
        "date": "2026-08-01", "key": "sono", "text": "2.6h — costumas dormir 7.7h.",
    }, HOJE)
    assert "Ontem" in p and "2.6h" in p and p.endswith("o que aconteceu?")


def test_gasto_num_sitio_traz_o_sitio():
    p = _pergunta_da_anomalia({
        "date": "2026-07-30", "key": "gasto-sitio:vinted",
        "text": "€702.57 em vinted — costumas gastar €40.00.",
    }, HOJE)
    assert "vinted" in p                      # a chave tem sufixo, tem de ser aceite


def test_tipo_sem_molde_nao_inventa_pergunta():
    assert _pergunta_da_anomalia({"date": "2026-08-01", "key": "coisa-nova", "text": "x"}, HOJE) is None


def test_data_estragada_nao_rebenta():
    assert _pergunta_da_anomalia({"date": "ontem", "key": "sono", "text": "x"}, HOJE) is None
    assert _pergunta_da_anomalia({"key": "sono", "text": "x"}, HOJE) is None


def test_ha_molde_para_cada_anomalia_que_o_motor_produz():
    """Se o motor de anomalias ganhar um tipo novo, isto avisa — senão a pergunta
    desaparecia em silêncio."""
    from routers.mood import _MOLDES
    do_motor = {"gasto-dia", "gasto-sitio", "sono", "deitar", "ecra", "jogos", "codigo"}
    assert do_motor <= set(_MOLDES), f"sem molde: {do_motor - set(_MOLDES)}"


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
