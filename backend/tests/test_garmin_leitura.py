"""A leitura do dia: uma régua estatística para todas as métricas, e o modelo
local sem acesso aos números.

Não há uma regra por métrica — há mediana e desvio absoluto mediano das semanas
dele, aplicados por igual. É isso que estes testes fixam: que a régua é dele (a
mesma noite é notícia num histórico e não é noutro), que uma correlação só sai
quando passa no teste, e que uma frase do modelo com algarismos é deitada fora.

Corre sozinho:  python tests/test_garmin_leitura.py
"""
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import garmin_insights as gi
from models import AppUsageSession, Base, GarminDay

DIA = date(2026, 8, 12)


def _sessao():
    tmp = Path(tempfile.mkdtemp()) / "teste.db"
    motor = create_engine(f"sqlite:///{tmp}")
    Base.metadata.create_all(motor)
    gi.cache.cache_invalidate("garmin_leitura")
    return sessionmaker(bind=motor)()


def _dia(db, quando=DIA, **campos):
    valores = dict(date=quando, sleep_hours=7.5, sleep_need_min=450, sleep_score=80,
                   resting_hr=53, hrv_last_night=45, bb_start=85, bb_end=40, steps=8000)
    valores.update(campos)
    linha = GarminDay(**valores)
    db.add(linha)
    db.commit()
    return linha


def _historico(db, dias=12, desde=1, **campos):
    """Noites anteriores com a oscilação que a vida real tem.

    Um histórico de valores todos iguais dava desvio zero e uma régua infinitamente
    apertada — não serve para testar nada."""
    for i in range(desde, desde + dias):
        oscilado = {k: (round(v * (1 + ((i % 5) - 2) * 0.03), 2) if isinstance(v, (int, float)) else v)
                    for k, v in campos.items()}
        _dia(db, DIA - timedelta(days=i), **oscilado)


def _chaves(fs):
    return {f["key"] for f in fs}


# ── a régua é dele ───────────────────────────────────────────────

def test_sem_historico_nao_ha_desvios():
    """Com duas noites não há régua nenhuma com que comparar."""
    db = _sessao()
    _historico(db, dias=3, sleep_hours=8.0)
    _dia(db, sleep_hours=4.0)
    assert not [f for f in gi.desvios(db, DIA)]


def test_a_mesma_noite_e_noticia_ou_nao_conforme_o_historico():
    """5h30 num histórico de 8h é fora do costume; num histórico de 5h30 não é.
    É esta a razão de a régua ser a mediana dele e não uma tabela."""
    dorminhoco = _sessao()
    _historico(dorminhoco, dias=12, sleep_hours=8.0)
    _dia(dorminhoco, sleep_hours=5.5)
    assert "desvio:sleep_hours" in _chaves(gi.desvios(dorminhoco, DIA))

    noctivago = _sessao()
    _historico(noctivago, dias=12, sleep_hours=5.5)
    _dia(noctivago, sleep_hours=5.5)
    assert "desvio:sleep_hours" not in _chaves(gi.desvios(noctivago, DIA))


def test_um_dia_doido_no_historico_nao_estraga_a_regua():
    """Mediana e MAD em vez de média e desvio-padrão: uma noite de 14h no meio
    do histórico não pode calar as noites curtas que vierem a seguir."""
    db = _sessao()
    _historico(db, dias=12, desde=2, sleep_hours=8.0)
    _dia(db, DIA - timedelta(days=1), sleep_hours=14.0)
    _dia(db, DIA, sleep_hours=5.5)
    assert "desvio:sleep_hours" in _chaves(gi.desvios(db, DIA))


def test_o_desvio_sabe_o_que_e_bom_e_o_que_e_mau():
    """Menos sono é mau; menos frequência em repouso é bom. É a única coisa que
    a tabela de métricas precisa de saber."""
    db = _sessao()
    _historico(db, dias=12, sleep_hours=8.0, resting_hr=60)
    _dia(db, sleep_hours=5.0, resting_hr=48)
    por_chave = {f["key"]: f for f in gi.desvios(db, DIA)}
    assert por_chave["desvio:sleep_hours"]["good"] is False
    assert por_chave["desvio:resting_hr"]["good"] is True


def test_metrica_a_null_nao_inventa_desvio():
    db = _sessao()
    _historico(db, dias=12, hrv_last_night=45)
    _dia(db, hrv_last_night=None)
    assert "desvio:hrv_last_night" not in _chaves(gi.desvios(db, DIA))


# ── distâncias a alvos da própria Garmin ─────────────────────────

def test_defice_contra_o_sono_que_o_corpo_pediu():
    db = _sessao()
    _dia(db, sleep_hours=5.47, sleep_need_min=480)
    texto = next(f["text"] for f in gi.distancias(db, DIA) if f["key"] == "alvo:sono")
    assert "5h28" in texto and "8h00" in texto and "2h32" in texto


def test_dormir_o_que_precisa_nao_e_defice():
    db = _sessao()
    _dia(db, sleep_hours=8.0, sleep_need_min=480)
    assert "alvo:sono" not in _chaves(gi.distancias(db, DIA))


# ── o padrão que não é meu ───────────────────────────────────────

def test_dois_dias_de_rhr_alto_e_hrv_baixo_e_sinal_de_doenca():
    db = _sessao()
    _historico(db, dias=12, desde=2, resting_hr=52, hrv_last_night=50)
    _dia(db, DIA - timedelta(days=1), resting_hr=60, hrv_last_night=38)
    _dia(db, DIA, resting_hr=61, hrv_last_night=36)
    fs = gi.factos(db, DIA)
    assert "padrao:doenca" in _chaves(fs)
    assert fs[0]["key"] == "padrao:doenca"            # manda no dia
    assert gi.leitura(db, DIA)["theme"] == "doenca"


def test_um_dia_mau_isolado_nao_e_doenca():
    db = _sessao()
    _historico(db, dias=12, resting_hr=52, hrv_last_night=50)
    _dia(db, DIA, resting_hr=61, hrv_last_night=36)
    assert "padrao:doenca" not in _chaves(gi.factos(db, DIA))


# ── correlações ──────────────────────────────────────────────────

def test_spearman_apanha_relacao_monotona():
    """Spearman e não Pearson: interessa "quanto mais disto, menos daquilo",
    mesmo que a curva não seja uma recta."""
    xs = list(range(20))
    ys = [x ** 3 for x in xs]
    rho, p = gi._spearman(xs, ys)
    assert rho > 0.99 and p < 0.01
    rho, _ = gi._spearman(xs, [-y for y in ys])
    assert rho < -0.99


def test_spearman_recusa_amostra_pequena():
    assert gi._spearman([1, 2, 3], [1, 2, 3]) is None


def test_spearman_nao_ve_padrao_em_ruido():
    xs = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9, 3]
    ys = [8, 6, 7, 5, 3, 0, 9, 4, 2, 6, 4, 3, 3, 8, 7, 1]
    rho, p = gi._spearman(xs, ys)
    assert p > gi.P_MAXIMO or abs(rho) < 0.3


def test_relacoes_so_com_dias_suficientes():
    db = _sessao()
    _historico(db, dias=10)
    assert gi.relacoes(db) == []


def test_ecra_antes_de_dormir_aparece_quando_a_relacao_existe():
    """Dias com mais ecrã antes de deitar têm pior pontuação de sono: a relação
    tem de sair sozinha dos dados, sem ninguém a escrever a conclusão."""
    db = _sessao()
    for i in range(1, 25):
        quando = DIA - timedelta(days=i)
        minutos = 5 + (i % 12) * 5
        adormeceu = datetime.combine(quando, datetime.min.time()) + timedelta(hours=2)
        _dia(db, quando, sleep_start=adormeceu, sleep_score=95 - minutos)
        db.add(AppUsageSession(app_name="Chrome", date=quando,
                               start_time=adormeceu - timedelta(minutes=minutos),
                               end_time=adormeceu, duration_seconds=minutos * 60))
    db.commit()
    achadas = {r["key"] for r in gi.relacoes(db)}
    assert any("sleep_score" in k for k in achadas)


# ── o que o modelo pode e não pode fazer ─────────────────────────

def test_frase_com_algarismos_e_deitada_fora():
    import local_ai
    db = _sessao()
    _dia(db, sleep_hours=5.0, sleep_need_min=480)
    inventada = "Dormiste 3 horas a menos do que devias."
    orig_d, orig_p = local_ai.disponivel, local_ai.pergunta
    local_ai.disponivel = lambda *a, **k: True
    local_ai.pergunta = lambda *a, **k: inventada
    try:
        r = gi.leitura(db, DIA)
        assert r["text"] != inventada and not r["linked"]
        assert r["text"] == gi.texto_das_regras(gi.factos(db, DIA))
    finally:
        local_ai.disponivel, local_ai.pergunta = orig_d, orig_p


def test_sem_modelo_ha_sempre_leitura():
    import local_ai
    db = _sessao()
    _dia(db, sleep_hours=5.0, sleep_need_min=480)
    orig = local_ai.disponivel
    local_ai.disponivel = lambda *a, **k: False
    try:
        r = gi.leitura(db, DIA)
        assert r["source"] == "regras" and r["text"] and r["headline"] == "Noite curta"
    finally:
        local_ai.disponivel = orig


def test_dia_sem_dados_devolve_vazio():
    db = _sessao()
    r = gi.leitura(db, DIA)
    assert r["facts"] == [] and r["source"] == "vazio"


def test_analise_diz_quantos_dias_faltam():
    db = _sessao()
    _dia(db)
    r = gi.analise(db, DIA)
    assert r["days_measured"] == 1
    assert r["days_for_baseline"] == gi.MINIMO_BASELINE - 1
    assert r["days_for_relations"] == gi.MINIMO_PARES - 1


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {nome}")
            except AssertionError as e:
                falhas += 1
                print(f"FALHA  {nome}: {e}")
    print("tudo bem" if not falhas else f"{falhas} falhas")
    raise SystemExit(1 if falhas else 0)


# ── a leitura são pontos, não um parágrafo ───────────────────────

def test_pontos_tira_marcadores_e_introducao():
    bruto = ("Aqui vai a leitura do dia:\n"
             "- Dormiste 6h15 quando o corpo pedia 8h00.\n"
             "* Body battery caiu de 93 para 40.\n"
             "1. Sem exercício intenso registado.")
    assert gi._pontos(bruto).split("\n") == [
        "Dormiste 6h15 quando o corpo pedia 8h00",
        "Body battery caiu de 93 para 40",
        "Sem exercício intenso registado",
    ]


def test_paragrafo_do_agente_e_partido_em_frases():
    p = gi._pontos("Dormiste 6h15. Houve movimento real. Não entrou exercício intenso.")
    assert len(p.split("\n")) == 3 and p.startswith("Dormiste 6h15")


# ── as medidas novas da noite entram na mesma régua ──────────────

def test_fatia_de_profundo_e_medida_a_par_da_duracao():
    """A mesma noite de 7h pode ter metade do sono profundo do costume — e é
    isso que as fases em minutos escondem, porque sobem e descem com a duração."""
    db = _sessao()
    _historico(db, dias=12, sleep_hours=7.0, deep_min=84, light_min=252, rem_min=84)
    _dia(db, sleep_hours=7.0, deep_min=25, light_min=311, rem_min=84)
    fs = gi.factos(db, DIA)
    assert "desvio:pct_deep" in _chaves(fs)
    assert "desvio:sleep_hours" not in _chaves(fs)
    assert "desvio:pct_light" in _chaves(fs)


def test_hora_de_deitar_nao_parte_a_meia_noite():
    db = _sessao()
    for i in range(1, 13):
        quando = DIA - timedelta(days=i)
        _dia(db, quando, sleep_start=datetime.combine(quando, datetime.min.time())
             .replace(hour=23, minute=10 + i % 4) - timedelta(days=1))
    _dia(db, sleep_start=datetime.combine(DIA, datetime.min.time()).replace(hour=3, minute=40))
    facto = next(f for f in gi.factos(db, DIA) if f["key"] == "desvio:bedtime")
    assert "mais tarde do que costumas" in facto["text"]
    assert "03:40" in facto["text"] and "23:1" in facto["text"]


def test_um_despertar_a_mais_nao_e_noticia():
    """Sem piso na régua, quem quase nunca acorda tinha MAD zero e um único
    despertar disparava um facto."""
    db = _sessao()
    _historico(db, dias=12, awake_count=0)
    _dia(db, awake_count=1)
    assert "desvio:awake_count" not in _chaves(gi.factos(db, DIA))


def test_eficiencia_do_sono_desce_com_o_tempo_acordado():
    db = _sessao()
    _historico(db, dias=12, sleep_hours=7.0, awake_min=6)
    _dia(db, sleep_hours=7.0, awake_min=95)
    facto = next(f for f in gi.factos(db, DIA) if f["key"] == "desvio:sleep_efficiency")
    assert facto["good"] is False and "%" in facto["text"]


def test_relacao_entre_duas_medidas_do_relogio():
    """Um dos lados do par também pode vir do relógio — a hora de deitar contra o
    que a noite rendeu é a pergunta mais útil que há aqui."""
    db = _sessao()
    for i in range(20):
        quando = DIA - timedelta(days=i)
        tarde = i % 2 == 0
        _dia(db, quando,
             sleep_start=datetime.combine(quando, datetime.min.time())
             .replace(hour=2 if tarde else 22, minute=i * 3) - timedelta(days=0 if tarde else 1),
             sleep_hours=7.0, deep_min=(40 if tarde else 100) + i, light_min=300, rem_min=80)
    chaves = {r["key"] for r in gi.relacoes(db, dias=40)}
    assert any("bedtime" not in k and "pct_deep" in k for k in chaves)


# ── as noites em conjunto (a análise da página do Sono) ──────────

def test_analise_do_sono_ve_a_composicao_e_o_que_puxa_a_pontuacao():
    db = _sessao()
    for i in range(20):
        quando = DIA - timedelta(days=i)
        boa = i % 2 == 0
        _dia(db, quando, sleep_hours=7.0, sleep_score=85 - (0 if boa else 25),
             deep_min=(110 if boa else 40) + i, light_min=250, rem_min=80, awake_min=8,
             awake_count=1)
    r = gi.estatisticas_do_sono(db, dias=40)
    assert r["nights"] == 20
    fases = {f["key"]: f for f in r["composition"]}
    assert fases["deep_min"]["pct"] > 0 and fases["deep_min"]["reference"] == [13, 23]
    assert {d["key"] for d in r["drivers"]} >= {"pct_deep"}
    # O que não passou fica dito, em vez de sumir sem se saber se foi olhado.
    assert any(t["key"] == "bedtime" for t in r["tested"])


def test_analise_do_sono_sem_noites_nao_inventa():
    db = _sessao()
    r = gi.estatisticas_do_sono(db, dias=40)
    assert r["nights"] == 0 and r["drivers"] == [] and r["composition"] == []
