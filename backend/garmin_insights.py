"""A leitura do que o corpo andou a fazer.

Aqui não há uma regra por métrica. Há **uma** régua estatística aplicada a todas
por igual: mediana e desvio absoluto mediano das últimas semanas dele, e o desvio
robusto de cada dia contra essa régua. Acrescentar uma métrica é acrescentar uma
linha em `METRICAS` — não é escrever mais um `if`. E a régua é dele: dormir 5h30
num histórico de 7h é notícia, num histórico de 5h não é.

Os cruzamentos com o resto da app (ecrã, LoL, código, gastos) também não são
afirmações escritas à mão: é correlação de Spearman com teste de significância, e
só aparece o que passa no teste com amostra suficiente.

Ao modelo local pede-se o que ele faz bem e não pode estragar: escolher o tema do
dia de uma lista fechada e escrever uma frase de ligação onde os algarismos são
proibidos. Tentou-se deixá-lo reescrever os números e o llama3 inverteu um
condicional — os números ficam do lado de cá.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from datetime import date as _date
from datetime import timedelta
from typing import Any, Callable, Optional

from sqlalchemy import func

import cache
import local_ai
from models import AppUsageSession, Expense, GarminDay, LolGame, WakaProjectDay

logger = logging.getLogger(__name__)

# Sem isto não há régua: comparar com duas noites não diz nada.
MINIMO_BASELINE = 8
DIAS_BASELINE = 90

# Desvio robusto a partir do qual o dia deixa de ser mais um dia. 2.5 é o corte
# habitual para "fora do padrão" sem encher o ecrã de ruído.
CORTE_DESVIO = 2.5

# Correlações: abaixo disto qualquer coeficiente é sorte.
MINIMO_PARES = 14
P_MAXIMO = 0.05

VIGOROSO_ALVO_MIN = 75


# ── formatos ─────────────────────────────────────────────────────

def _hm(minutos: float) -> str:
    m = int(round(minutos))
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m}min"


def _horas(v: float) -> str:
    return _hm(v * 60)


def _inteiro(v: float) -> str:
    return f"{round(v):,}".replace(",", " ")


def _pct(v: float) -> str:
    return f"{round(v)}%"


def _relogio(minutos: float) -> str:
    """Minutos na escala das 18h às 42h de volta a horas de relógio: 1595 → 02:35."""
    m = int(round(minutos)) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


@dataclass(frozen=True)
class Metrica:
    coluna: str
    nome: str
    formato: Callable[[float], str]
    unidade: str = ""
    # +1 quando mais é melhor (sono, HRV, passos), -1 quando mais é pior
    # (frequência em repouso, stress). Serve só para dizer se o desvio é bom.
    sentido: int = 1
    # Métricas que não são uma coluna. `coluna` passa a ser só a chave do facto.
    calcula: Optional[Callable[[Any], Optional[float]]] = None
    # Uma hora não fica "acima do costume", fica mais tarde.
    acima: str = "acima do costume"
    abaixo: str = "abaixo do costume"
    # Variação abaixo da qual não vale a pena falar (ver `_desvio`).
    mad_min: float = 0.0


def _fatia(campo: str) -> Callable[[Any], Optional[float]]:
    """A fatia da noite que uma fase ocupou.

    As fases em minutos não se comparam entre noites de duração diferente: numa
    noite de 9h o sono profundo é maior em minutos sem a noite ser melhor. A
    duração já é medida à parte (`sleep_hours`), por isso aqui vale a estrutura."""
    def valor(d) -> Optional[float]:
        total = (d.sleep_hours or 0) * 60
        v = getattr(d, campo, None)
        return v / total * 100 if total and v is not None else None
    return valor


def _eficiencia(d) -> Optional[float]:
    """Quanto do tempo na cama foi mesmo a dormir. `sleep_hours` não conta o
    acordado, por isso o tempo na cama é a soma dos dois."""
    total = (d.sleep_hours or 0) * 60
    if not total or d.awake_min is None:
        return None
    return total / (total + d.awake_min) * 100


def _hora_de_deitar(d) -> Optional[float]:
    """Minutos numa escala que não parte à meia-noite: deitar às 02:35 é 26h35,
    senão a mediana de quem se deita às 23h e às 01h dava meio-dia."""
    if not d.sleep_start:
        return None
    m = d.sleep_start.hour * 60 + d.sleep_start.minute
    return float(m if m >= 18 * 60 else m + 24 * 60)


def _minutos_intensos(d) -> Optional[float]:
    if d.intensity_moderate_min is None and d.intensity_vigorous_min is None:
        return None
    return float((d.intensity_moderate_min or 0) + (d.intensity_vigorous_min or 0))


METRICAS = [
    Metrica("sleep_hours", "o sono", _horas, sentido=1),
    Metrica("sleep_score", "a pontuação do sono", _inteiro, sentido=1),
    Metrica("bedtime", "a hora a que te deitaste", _relogio, sentido=-1,
            calcula=_hora_de_deitar, acima="mais tarde do que costumas",
            abaixo="mais cedo do que costumas", mad_min=20),
    Metrica("pct_deep", "a fatia de sono profundo", _pct, sentido=1,
            calcula=_fatia("deep_min"), mad_min=2),
    Metrica("pct_rem", "a fatia de sono REM", _pct, sentido=1,
            calcula=_fatia("rem_min"), mad_min=2),
    Metrica("pct_light", "a fatia de sono leve", _pct, sentido=-1,
            calcula=_fatia("light_min"), mad_min=2),
    Metrica("sleep_efficiency", "o tempo na cama passado a dormir", _pct, sentido=1,
            calcula=_eficiencia, mad_min=1.5),
    Metrica("awake_count", "os despertares", _inteiro, sentido=-1, mad_min=1),
    Metrica("hrv_last_night", "o HRV", _inteiro, "ms", sentido=1),
    Metrica("resting_hr", "a frequência em repouso", _inteiro, "bpm", sentido=-1),
    Metrica("bb_start", "o body battery ao acordar", _inteiro, sentido=1),
    Metrica("bb_end", "o body battery ao fim do dia", _inteiro, sentido=1),
    Metrica("bb_charged", "o que a noite carregou de body battery", _inteiro,
            sentido=1, mad_min=3),
    Metrica("stress_avg", "o stress médio", _inteiro, sentido=-1),
    Metrica("stress_high_min", "o tempo em stress alto", _hm, sentido=-1),
    Metrica("stress_rest_min", "o tempo em repouso", _hm, sentido=1, mad_min=20),
    Metrica("steps", "os passos", _inteiro, sentido=1),
    Metrica("intensity_min", "os minutos de intensidade", _hm, sentido=1,
            calcula=_minutos_intensos, mad_min=10),
    Metrica("training_readiness", "a prontidão para treinar", _inteiro, sentido=1,
            mad_min=5),
    Metrica("avg_sleep_stress", "o stress durante o sono", _inteiro, sentido=-1),
    Metrica("resp_avg", "a respiração", _inteiro, "resp/min", sentido=-1),
    Metrica("spo2_avg", "o oxigénio no sangue", _inteiro, "%", sentido=1),
]

POR_CHAVE = {m.coluna: m for m in METRICAS}


def valor_da_metrica(d, m: Metrica) -> Optional[float]:
    v = m.calcula(d) if m.calcula else getattr(d, m.coluna, None)
    return None if v is None else float(v)


# ── a régua ──────────────────────────────────────────────────────

def _mediana(vals: list[float]) -> Optional[float]:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    meio = len(vals) // 2
    return vals[meio] if len(vals) % 2 else (vals[meio - 1] + vals[meio]) / 2


def _mad(vals: list[float], mediana: float) -> float:
    return _mediana([abs(v - mediana) for v in vals]) or 0.0


def _desvio(valor: float, historico: list[float],
            mad_min: float = 0.0) -> Optional[dict[str, float]]:
    """Quantos desvios robustos este valor está fora do costume dele.

    Mediana e MAD em vez de média e desvio-padrão: um único dia doido não pode
    estragar a régua com que se julgam os outros.

    `mad_min` é o quanto uma métrica tem de variar para a variação querer dizer
    alguma coisa. Sem isso, quem quase nunca acorda a meio da noite tem MAD zero
    e um único despertar vira "muito acima do costume" — a régua fica tão
    apertada que mede ruído."""
    if len(historico) < MINIMO_BASELINE:
        return None
    med = _mediana(historico)
    mad = max(_mad(historico, med), mad_min) or max(abs(med) * 0.15, 0.01)
    return {"z": 0.6745 * (valor - med) / mad, "mediana": med}


# A fronteira da faixa é a mesma que o `_desvio` usa: |z| = 1 é estar a um
# desvio robusto da mediana. Sem esta constante a faixa dos gráficos e os factos
# da leitura diriam coisas diferentes sobre o mesmo dia.
SIGMA_ROBUSTO = 1.4826


def regua(vals: list[float], *, mad_min: float = 0.0) -> Optional[dict[str, float]]:
    """A faixa do costume dele para uma métrica: mediana ± desvio robusto.

    É a régua dos gráficos do histórico, e é de propósito a mesma do `_desvio`:
    ficar fora desta faixa é exactamente ter |z| > 1."""
    vals = [v for v in vals if v is not None]
    if len(vals) < MINIMO_BASELINE:
        return {"median": None, "low": None, "high": None, "n": len(vals)}
    med = _mediana(vals)
    sigma = max(_mad(vals, med), mad_min) * SIGMA_ROBUSTO or max(abs(med) * 0.15, 0.01)
    return {"median": round(med, 2), "low": round(med - sigma, 2),
            "high": round(med + sigma, 2), "n": len(vals)}


def _serie_do_historico(db, coluna, ate: _date) -> list[float]:
    linhas = (db.query(coluna)
              .filter(GarminDay.date >= ate - timedelta(days=DIAS_BASELINE),
                      GarminDay.date < ate, coluna.isnot(None)).all())
    return [v for (v,) in linhas]


def _dias_do_historico(db, ate: _date) -> list[Any]:
    """Os dias com que se faz a régua. Vêm inteiros porque metade das métricas
    são contas sobre duas colunas — e é uma leitura em vez de uma por métrica."""
    return (db.query(GarminDay)
            .filter(GarminDay.date >= ate - timedelta(days=DIAS_BASELINE),
                    GarminDay.date < ate).all())


def _facto(chave: str, texto: str, forca: float, *, tipo: str = "desvio",
           detalhe: Optional[dict] = None) -> dict:
    return {"key": chave, "text": texto, "strength": round(forca, 2),
            "kind": tipo, **(detalhe or {})}


# ── os sinais ────────────────────────────────────────────────────

def desvios(db, dia: _date) -> list[dict[str, Any]]:
    """As métricas que hoje fugiram ao costume dele, pela mesma régua."""
    d = db.query(GarminDay).filter(GarminDay.date == dia).first()
    if d is None:
        return []

    historico = _dias_do_historico(db, dia)
    saida = []
    for m in METRICAS:
        valor = valor_da_metrica(d, m)
        if valor is None:
            continue
        serie = [v for v in (valor_da_metrica(x, m) for x in historico) if v is not None]
        r = _desvio(valor, serie, m.mad_min)
        if r is None or abs(r["z"]) < CORTE_DESVIO:
            continue
        acima = r["z"] > 0
        bom = acima if m.sentido > 0 else not acima
        u = f" {m.unidade}" if m.unidade else ""
        saida.append(_facto(
            f"desvio:{m.coluna}",
            f"{m.nome.capitalize()} {m.acima if acima else m.abaixo}: "
            f"{m.formato(valor)}{u} contra {m.formato(r['mediana'])}{u}.",
            abs(r["z"]),
            detalhe={"good": bom, "value": valor, "median": round(r["mediana"], 2),
                     "z": round(r["z"], 2)}))
    return saida


def distancias(db, dia: _date) -> list[dict[str, Any]]:
    """Distâncias a alvos que não são meus: são os que a Garmin calcula.

    O sono de que o corpo precisa naquela noite e os minutos de exercício intenso
    por semana vêm do relógio — aqui só se faz a subtracção."""
    d = db.query(GarminDay).filter(GarminDay.date == dia).first()
    if d is None:
        return []

    saida = []
    if d.sleep_hours and d.sleep_need_min:
        falta = d.sleep_need_min - d.sleep_hours * 60
        if abs(falta) >= 20:
            saida.append(_facto(
                "alvo:sono",
                (f"Dormiste {_hm(d.sleep_hours * 60)} e o corpo pedia {_hm(d.sleep_need_min)} — "
                 f"faltaram {_hm(falta)}.") if falta > 0 else
                (f"Dormiste {_hm(d.sleep_hours * 60)}, acima dos {_hm(d.sleep_need_min)} "
                 f"que o corpo pedia."),
                abs(falta) / 60, tipo="alvo",
                detalhe={"good": falta <= 0, "value": round(d.sleep_hours * 60),
                         "target": d.sleep_need_min}))

    if d.vigorous_min_avg is not None and d.vigorous_min_avg < VIGOROSO_ALVO_MIN:
        feito = round(d.vigorous_min_avg)
        extra = (f" Com o alvo cumprido, a idade de fitness descia de {round(d.fitness_age)} "
                 f"para {round(d.fitness_age_achievable)}.") if d.fitness_age and d.fitness_age_achievable else ""
        saida.append(_facto(
            "alvo:vigoroso",
            f"Exercício intenso esta semana: {feito} minutos, contra os "
            f"{VIGOROSO_ALVO_MIN} do alvo.{extra}",
            (VIGOROSO_ALVO_MIN - feito) / VIGOROSO_ALVO_MIN, tipo="alvo",
            detalhe={"good": False, "value": feito, "target": VIGOROSO_ALVO_MIN}))
    return saida


def _fora_do_normal(db, quando: _date) -> bool:
    """A frequência em repouso acima e o HRV abaixo, no mesmo dia."""
    d = db.query(GarminDay).filter(GarminDay.date == quando).first()
    if not d or d.resting_hr is None or d.hrv_last_night is None:
        return False
    rhr = _desvio(d.resting_hr, _serie_do_historico(db, GarminDay.resting_hr, quando))
    hrv = _desvio(d.hrv_last_night, _serie_do_historico(db, GarminDay.hrv_last_night, quando))
    return bool(rhr and hrv and rhr["z"] >= 1.5 and hrv["z"] <= -1.5)


def alertas_de_doenca(db, desde: _date, ate: _date) -> list[str]:
    """Os dias em que o sinal disparou, para os gráficos os poderem marcar.

    A regra é a de `_sinal_de_doenca` — vem daqui em vez de ser reescrita, senão
    a página e a leitura do dia acabam a discordar uma da outra."""
    marcados, anterior = [], None
    dia = desde
    while dia <= ate:
        agora = _fora_do_normal(db, dia)
        if agora and anterior:
            marcados.append(dia.isoformat())
        anterior, dia = agora, dia + timedelta(days=1)
    return marcados


# A régua de cada gráfico do histórico. O `mad_min` é o mesmo princípio das
# `METRICAS`: quem quase não varia numa métrica não pode ter uma faixa tão
# apertada que qualquer dia caia fora dela.
REGUAS = [
    ("hrv", GarminDay.hrv_last_night, 1.0),
    ("resting_hr", GarminDay.resting_hr, 1.0),
    ("sleep_hours", GarminDay.sleep_hours, 0.25),
    ("sleep_score", GarminDay.sleep_score, 3.0),
    ("steps", GarminDay.steps, 500.0),
    ("stress_avg", GarminDay.stress_avg, 2.0),
    ("bb_start", GarminDay.bb_start, 3.0),
    ("readiness", GarminDay.training_readiness, 3.0),
]


def baselines(db, dias: int = 30) -> dict[str, Any]:
    """A faixa do costume dele em cada métrica do histórico, e os dias marcados.

    No HRV, a faixa da própria Garmin ganha à da app **assim que existir** — ela
    é feita de 90 noites e da forma como o relógio decide o estado, e discordar
    dela na mesma página seria confuso. Hoje vem a NULL: o relógio só a calcula
    ao fim de ~19 noites."""
    desde = _date.today() - timedelta(days=dias)
    linhas = db.query(GarminDay).filter(GarminDay.date >= desde).order_by(GarminDay.date).all()
    metricas = {}
    for chave, coluna, mad_min in REGUAS:
        campo = coluna.key
        metricas[chave] = {**regua([getattr(d, campo) for d in linhas], mad_min=mad_min),
                           "source": "app"}

    ultima = next((d for d in reversed(linhas)
                   if d.hrv_baseline_low is not None and d.hrv_baseline_high is not None), None)
    if ultima:
        metricas["hrv"] = {"median": metricas["hrv"]["median"],
                           "low": ultima.hrv_baseline_low, "high": ultima.hrv_baseline_high,
                           "n": metricas["hrv"]["n"], "source": "garmin"}

    return {"days": dias, "min_days": MINIMO_BASELINE,
            "metrics": metricas,
            "alerts": alertas_de_doenca(db, desde, _date.today())}


def _sinal_de_doenca(db, dia: _date) -> list[dict[str, Any]]:
    """Frequência em repouso acima e HRV abaixo, dois dias seguidos.

    É o único padrão escrito à mão, porque não é meu: é o sinal conhecido de
    infecção a incubar, e o relógio não o dá."""
    if _fora_do_normal(db, dia) and _fora_do_normal(db, dia - timedelta(days=1)):
        return [_facto("padrao:doenca",
                       "Dois dias seguidos com a frequência em repouso acima do normal e o "
                       "HRV abaixo — é o sinal do costume de o corpo estar a lutar contra "
                       "alguma coisa.", 4.0, tipo="padrao", detalhe={"good": False})]
    return []


def _linha_do_dia(db, dia: _date) -> list[dict[str, Any]]:
    """Os blocos do dia guardados pela sincronização: sestas e movimento.

    Não passam pela régua de propósito — uma sesta não é "acima do costume", é
    uma coisa que aconteceu a uma hora concreta. Com poucos dias medidos, é isto
    que a leitura tem para dizer enquanto não há histórico com que comparar."""
    import json as _json
    from models import GarminSeries

    linha = db.query(GarminSeries).filter(GarminSeries.date == dia).first()
    if linha is None:
        return []
    try:
        blocos = _json.loads(linha.events_json or "[]")
    except (ValueError, TypeError):
        return []

    from datetime import datetime as _dt
    saida = []
    for b in blocos:
        minutos = round((b.get("end", 0) - b.get("start", 0)) / 60000)
        if minutos < 5:
            continue
        hora = _dt.fromtimestamp(b["start"] / 1000).strftime("%H:%M")
        if b.get("kind") == "sesta":
            impacto = b.get("impact")
            extra = f" e devolveu {impacto} de body battery" if impacto else ""
            saida.append(_facto("dia:sesta",
                                f"Dormiste uma sesta de {_hm(minutos)} às {hora}{extra}.",
                                1.2, tipo="dia", detalhe={"good": True, "value": minutos}))
        elif b.get("kind") == "movimento":
            tipo = {"walking": "a andar", "running": "a correr",
                    "cycling": "de bicicleta"}.get(b.get("type", ""), "em movimento")
            saida.append(_facto("dia:movimento",
                                f"O relógio apanhou {_hm(minutos)} {tipo} às {hora}, "
                                f"sem ser um treino gravado.",
                                1.0, tipo="dia", detalhe={"good": True, "value": minutos}))
    return saida


def _o_dia_em_si(db, dia: _date) -> list[dict[str, Any]]:
    """O que se pode dizer do dia sem histórico nenhum: como correu a noite,
    onde é que o body battery começou e acabou, e quanto tempo houve stress."""
    d = db.query(GarminDay).filter(GarminDay.date == dia).first()
    if d is None:
        return []

    saida = []
    if d.sleep_hours and (d.deep_min or d.rem_min):
        total = d.sleep_hours * 60
        partes = [f"{round(v / total * 100)}% {nome}"
                  for nome, v in (("profundo", d.deep_min), ("leve", d.light_min),
                                  ("REM", d.rem_min)) if v]
        saida.append(_facto("dia:fases",
                            f"A noite foi {_hm(total)}: {', '.join(partes[:-1])}"
                            f"{' e ' if len(partes) > 1 else ''}{partes[-1]}"
                            + (f", com {d.awake_count} despertares." if d.awake_count else "."),
                            0.9, tipo="dia", detalhe={"good": None}))

    if d.bb_start is not None and d.bb_end is not None:
        saida.append(_facto("dia:bateria",
                            f"O body battery acordou em {d.bb_start} e acabou o dia em "
                            f"{d.bb_end}"
                            + (f", com {d.bb_charged} carregados e {d.bb_drained} gastos."
                               if d.bb_charged and d.bb_drained else "."),
                            0.8, tipo="dia",
                            detalhe={"good": d.bb_end >= 30, "value": d.bb_end}))

    tenso = (d.stress_medium_min or 0) + (d.stress_high_min or 0)
    if d.stress_rest_min or tenso:
        saida.append(_facto("dia:stress",
                            f"Passaste {_hm(d.stress_rest_min or 0)} em repouso e "
                            f"{_hm(tenso)} em stress médio ou alto.",
                            0.7, tipo="dia", detalhe={"good": tenso < (d.stress_rest_min or 0)}))
    return saida


# ── correlações com o resto da app ───────────────────────────────

def _spearman(xs: list[float], ys: list[float]) -> Optional[tuple[float, float]]:
    """Coeficiente de Spearman e valor-p aproximado.

    Spearman e não Pearson porque o que interessa é "quanto mais disto, menos
    daquilo", sem assumir que a relação é uma recta."""
    n = len(xs)
    if n < MINIMO_PARES:
        return None

    def ranks(vals: list[float]) -> list[float]:
        ordem = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        i = 0
        while i < n:                                   # médias nos empates
            j = i
            while j + 1 < n and vals[ordem[j + 1]] == vals[ordem[i]]:
                j += 1
            media = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[ordem[k]] = media
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if vx == 0 or vy == 0:
        return None
    rho = cov / (vx * vy)
    if abs(rho) >= 1:
        return rho, 0.0
    t = abs(rho) * math.sqrt((n - 2) / (1 - rho * rho))
    # Aproximação normal da t com n-2 graus: chega para separar sinal de ruído.
    p = math.erfc(t / math.sqrt(2))
    return rho, p


def _ecra_antes_de_dormir(db, d: GarminDay) -> Optional[float]:
    if not d.sleep_start:
        return None
    segundos = (db.query(func.sum(AppUsageSession.duration_seconds))
                .filter(AppUsageSession.start_time >= d.sleep_start - timedelta(hours=1),
                        AppUsageSession.start_time < d.sleep_start).scalar() or 0)
    return round(segundos / 60)


def _jogos_do_dia(db, d: GarminDay) -> float:
    return db.query(LolGame).filter(LolGame.date == d.date).count()


def _horas_de_codigo(db, d: GarminDay) -> float:
    """A mesma tabela guarda o dia repartido por projecto, linguagem, editor,
    máquina e dependência — somar tudo conta o mesmo tempo uma dúzia de vezes.
    Sem o filtro, um dia de 8h de código dava 119h, e era esse o número que ia
    parar às correlações e ao texto da leitura."""
    segundos = (db.query(func.sum(WakaProjectDay.seconds))
                .filter(WakaProjectDay.day == d.date,
                        WakaProjectDay.kind == "project").scalar() or 0)
    return round(segundos / 3600, 2)


def _gasto_do_dia(db, d: GarminDay) -> float:
    import expense_kind as ek
    return round(db.query(func.sum(Expense.amount))
                 .filter(Expense.date == d.date, Expense.kind == ek.GASTO).scalar() or 0, 2)


def _do_relogio(chave: str) -> Callable[[Any, Any], Optional[float]]:
    """Um lado do par que também vem do relógio. A régua dos desvios diz se um dia
    fugiu ao costume; isto é outra pergunta — se duas medidas andam juntas — e há
    pares dentro do próprio relógio que valem a pena (a hora de deitar e o que a
    noite rendeu)."""
    m = POR_CHAVE[chave]
    return lambda db, d: valor_da_metrica(d, m)


# (nome do lado da app, como se calcula, chave do relógio, nome legível do par)
RELACOES = [
    ("ecrã na hora antes de deitar", _ecra_antes_de_dormir, "sleep_score",
     "minutos ao computador na hora antes de adormecer", "a pontuação do sono"),
    ("ecrã na hora antes de deitar", _ecra_antes_de_dormir, "sleep_hours",
     "minutos ao computador na hora antes de adormecer", "as horas de sono"),
    ("ecrã na hora antes de deitar", _ecra_antes_de_dormir, "pct_deep",
     "minutos ao computador na hora antes de adormecer", "a fatia de sono profundo"),
    ("ecrã na hora antes de deitar", _ecra_antes_de_dormir, "sleep_efficiency",
     "minutos ao computador na hora antes de adormecer", "o tempo na cama passado a dormir"),
    ("jogos de LoL", _jogos_do_dia, "sleep_score",
     "jogos de LoL no dia", "a pontuação do sono"),
    ("jogos de LoL", _jogos_do_dia, "stress_avg",
     "jogos de LoL no dia", "o stress médio"),
    ("jogos de LoL", _jogos_do_dia, "awake_count",
     "jogos de LoL no dia", "os despertares da noite"),
    ("horas de código", _horas_de_codigo, "bb_end",
     "horas de código", "o body battery ao fim do dia"),
    ("horas de código", _horas_de_codigo, "pct_rem",
     "horas de código", "a fatia de sono REM"),
    ("gasto do dia", _gasto_do_dia, "bb_end",
     "o dinheiro gasto no dia", "o body battery ao fim do dia"),
    ("horas de código", _horas_de_codigo, "sleep_hours",
     "horas de código", "as horas de sono"),
    ("hora de deitar", _do_relogio("bedtime"), "pct_deep",
     "tarde te deitas", "a fatia de sono profundo"),
    ("hora de deitar", _do_relogio("bedtime"), "sleep_score",
     "tarde te deitas", "a pontuação do sono"),
    ("passos", _do_relogio("steps"), "pct_deep",
     "passos dás no dia", "a fatia de sono profundo"),
    ("minutos de intensidade", _do_relogio("intensity_min"), "hrv_last_night",
     "minutos de intensidade fazes", "o HRV da noite"),
    ("fatia de sono profundo", _do_relogio("pct_deep"), "training_readiness",
     "fatia de sono profundo tens", "a prontidão para treinar da manhã"),
]


def relacoes(db, dias: int = 90) -> list[dict[str, Any]]:
    """O que anda junto com o quê, com o teste feito.

    Só sai o que tem amostra suficiente e passa no teste de significância — uma
    correlação com oito dias não é uma descoberta, é uma coincidência."""
    linhas = (db.query(GarminDay)
              .filter(GarminDay.date >= _date.today() - timedelta(days=dias))
              .order_by(GarminDay.date).all())
    if len(linhas) < MINIMO_PARES:
        return []

    saida = []
    for _, calcula, chave, nome_a, nome_b in RELACOES:
        metrica = POR_CHAVE.get(chave)
        pares = []
        for d in linhas:
            b = valor_da_metrica(d, metrica) if metrica else getattr(d, chave, None)
            if b is None:
                continue
            a = calcula(db, d)
            if a is None:
                continue
            pares.append((float(a), float(b)))
        if len({p[0] for p in pares}) < 3:              # sem variação não há relação
            continue
        r = _spearman([p[0] for p in pares], [p[1] for p in pares])
        if r is None:
            continue
        rho, p = r
        if p > P_MAXIMO or abs(rho) < 0.3:
            continue
        saida.append({
            "key": f"rel:{chave}:{nome_a[:12]}",
            "text": f"Quanto mais {nome_a}, {'menor' if rho < 0 else 'maior'} {nome_b}.",
            "rho": round(rho, 2), "p": round(p, 4), "n": len(pares),
            "kind": "relacao", "strength": abs(rho),
        })
    return sorted(saida, key=lambda x: -x["strength"])


# ── as noites, olhadas em conjunto ───────────────────────────────

# As faixas de referência de um adulto, como a Garmin as usa. Não são objectivos
# dele: servem só para dizer se a noite dele se parece com o que é típico.
FAIXAS_DAS_FASES = {"deep_min": (13, 23), "light_min": (44, 55), "rem_min": (21, 31)}

FASES = [("deep_min", "profundo"), ("light_min", "leve"),
         ("rem_min", "REM"), ("awake_min", "acordado")]

# O que pode explicar a pontuação de uma noite. A frase é a do lado esquerdo do
# "quanto mais…", porque "quanto maior a hora a que te deitaste" não é português.
MOTORES_DA_PONTUACAO = [
    ("pct_deep", "mais fatia de sono profundo tens"),
    ("pct_rem", "mais fatia de REM tens"),
    ("pct_light", "mais fatia de sono leve tens"),
    ("sleep_hours", "mais horas dormes"),
    ("sleep_efficiency", "mais do tempo na cama passas a dormir"),
    ("awake_count", "mais vezes acordas a meio"),
    ("bedtime", "mais tarde te deitas"),
    ("avg_sleep_stress", "mais stress tens a dormir"),
    ("resp_avg", "mais depressa respiras"),
]

BOA_NOITE, MA_NOITE = 80, 60


def _noites_medidas(db, dias: int) -> list[Any]:
    return (db.query(GarminDay)
            .filter(GarminDay.date >= _date.today() - timedelta(days=dias),
                    GarminDay.sleep_hours.isnot(None))
            .order_by(GarminDay.date).all())


def _composicao(noites: list[Any]) -> list[dict[str, Any]]:
    """De que é feita uma noite dele, em mediana. A fatia e os minutos: 22% não
    diz o mesmo numa noite de 5h e numa de 8h, e ele quer ver as duas coisas."""
    saida = []
    for campo, nome in FASES:
        fatias = [v for v in (_fatia(campo)(n) for n in noites) if v is not None]
        minutos = [getattr(n, campo) for n in noites if getattr(n, campo) is not None]
        if not fatias:
            continue
        faixa = FAIXAS_DAS_FASES.get(campo)
        med = _mediana(fatias)
        saida.append({
            "key": campo, "name": nome, "nights": len(fatias),
            "pct": round(med, 1), "minutes": round(_mediana(minutos)) if minutos else None,
            "reference": list(faixa) if faixa else None,
            "verdict": None if not faixa else
                       ("baixo" if med < faixa[0] else "alto" if med > faixa[1] else "típico"),
        })
    return saida


def _motores_da_pontuacao(noites: list[Any]) -> tuple[list[dict], list[dict]]:
    """O que anda junto com a pontuação da noite, e o que foi testado e não deu.

    O que não passa no teste é informação: diz que aquela medida não explica as
    noites boas dele, em vez de ficar de fora sem se saber se foi vista."""
    passou, testado = [], []
    for chave, frase in MOTORES_DA_PONTUACAO:
        m = POR_CHAVE[chave]
        pares = [(v, float(n.sleep_score)) for n in noites if n.sleep_score is not None
                 and (v := valor_da_metrica(n, m)) is not None]
        if len(pares) < MINIMO_PARES or len({p[0] for p in pares}) < 3:
            testado.append({"key": chave, "name": m.nome, "n": len(pares), "reason": "poucas noites"})
            continue
        r = _spearman([p[0] for p in pares], [p[1] for p in pares])
        if r is None:
            continue
        rho, p = r
        linha = {"key": chave, "name": m.nome, "rho": round(rho, 2),
                 "p": round(p, 4), "n": len(pares),
                 "text": f"Quanto {frase}, {'maior' if rho > 0 else 'menor'} a pontuação da noite."}
        if p <= P_MAXIMO and abs(rho) >= 0.3:
            passou.append(linha)
        else:
            testado.append({**linha, "reason": "não passou no teste"})
    return sorted(passou, key=lambda x: -abs(x["rho"])), testado


def _boas_contra_mas(noites: list[Any]) -> Optional[dict[str, Any]]:
    """As noites boas contra as más, medida a medida. Não é um teste — é a
    mediana dos dois grupos lado a lado, que é o que se quer olhar."""
    boas = [n for n in noites if n.sleep_score is not None and n.sleep_score >= BOA_NOITE]
    mas = [n for n in noites if n.sleep_score is not None and n.sleep_score < MA_NOITE]
    if len(boas) < 3 or len(mas) < 3:
        return {"good": len(boas), "bad": len(mas), "rows": []}

    linhas = []
    for chave, _ in MOTORES_DA_PONTUACAO:
        m = POR_CHAVE[chave]
        a = [v for v in (valor_da_metrica(n, m) for n in boas) if v is not None]
        b = [v for v in (valor_da_metrica(n, m) for n in mas) if v is not None]
        if len(a) < 3 or len(b) < 3:
            continue
        ma, mb = _mediana(a), _mediana(b)
        linhas.append({"key": chave, "name": m.nome,
                       "good": m.formato(ma), "bad": m.formato(mb),
                       "gap": round(abs(ma - mb), 1),
                       # O destaque é a diferença que a régua dele considera real.
                       "notable": abs(ma - mb) >= max(m.mad_min, abs(_mediana(a + b)) * 0.1)})
    return {"good": len(boas), "bad": len(mas),
            "rows": sorted(linhas, key=lambda x: (not x["notable"], -x["gap"]))}


def estatisticas_do_sono(db, dias: int = 90) -> dict[str, Any]:
    """As noites em conjunto: de que é feita uma noite dele, o que anda junto com
    a pontuação, e as noites boas contra as más."""
    noites = _noites_medidas(db, dias)
    resumo = []
    for chave in ("sleep_score", "sleep_hours", "sleep_efficiency", "awake_count",
                  "bedtime", "avg_sleep_stress", "hrv_last_night", "resting_hr", "resp_avg"):
        m = POR_CHAVE[chave]
        vals = [v for v in (valor_da_metrica(n, m) for n in noites) if v is not None]
        if vals:
            resumo.append({"key": chave, "name": m.nome, "n": len(vals),
                           "median": m.formato(_mediana(vals)) + (f" {m.unidade}" if m.unidade else "")})

    motores, testados = _motores_da_pontuacao(noites)
    return {
        "days": dias,
        "nights": len(noites),
        "min_nights": MINIMO_PARES,
        "composition": _composicao(noites),
        "summary": resumo,
        "drivers": motores,
        "tested": testados,
        "good_vs_bad": _boas_contra_mas(noites),
    }


# ── juntar tudo ──────────────────────────────────────────────────

def factos(db, dia: _date) -> list[dict[str, Any]]:
    """Tudo o que se destaca no dia, do mais importante para o menos.

    Um padrão vem sempre à frente de uma métrica isolada: junta dois dias e duas
    medidas, e por isso diz mais do que qualquer desvio sozinho, por maior que
    ele seja. Depois dos desvios e dos alvos vem o dia contado como ele foi
    (sestas, movimento, fases, bateria) — isso não compete com o que fugiu ao
    padrão, mas é o que impede a leitura de ficar vazia enquanto não há régua."""
    fortes = _sinal_de_doenca(db, dia) + desvios(db, dia) + distancias(db, dia)
    fortes.sort(key=lambda f: (f["kind"] != "padrao", -f["strength"]))
    return fortes + _linha_do_dia(db, dia) + _o_dia_em_si(db, dia)


TEMAS = {
    "doenca":      "O corpo a avisar",
    "sono-curto":  "Noite curta",
    "recuperacao": "Recuperação em baixo",
    "stress":      "Dia tenso",
    "parado":      "Dia parado",
    "bom":         "Dia bom",
    "misto":       "O dia em números",
}

_PROMPT_TEMA = """Factos do dia de uma pessoa:
{factos}

Escolhe o tema que melhor descreve o dia, de entre estes:
- doenca (sinais de estar a adoecer)
- sono-curto (dormiu pouco)
- recuperacao (recuperação, HRV ou body battery em baixo)
- stress (muito stress)
- parado (pouco movimento ou pouco exercício)
- bom (correu bem)
- misto (várias coisas sem uma dominante)

Responde só com JSON: {{"tema": "..."}}"""

_PROMPT_LIGACAO = """Factos do dia de uma pessoa (trata-a por tu):
{factos}

Escreve UMA frase curta em português de Portugal que ligue estes factos ou diga o
que eles têm em comum.

Regras:
- Português natural, na segunda pessoa, sem escrever o pronome "tu".
- Proibido escrever números ou algarismos.
- Proibido inventar causas, dar conselhos de saúde ou repetir os factos tal e qual.
- Sem saudações, sem emojis, no máximo 20 palavras.
- Se não houver ligação nenhuma a fazer, responde exactamente: NADA

Devolve só a frase."""


def _tema_das_regras(fs: list[dict]) -> str:
    chaves = {f["key"] for f in fs}
    maus = [f for f in fs if not f.get("good", True)]
    if "padrao:doenca" in chaves:
        return "doenca"
    if any(k in chaves for k in ("alvo:sono", "desvio:sleep_hours", "desvio:sleep_score")):
        return "sono-curto"
    if any(k.startswith(("desvio:hrv", "desvio:resting_hr", "desvio:bb_")) for k in chaves):
        return "recuperacao"
    if any(k.startswith("desvio:stress") for k in chaves):
        return "stress"
    if chaves & {"alvo:vigoroso", "desvio:steps"}:
        return "parado"
    if fs and not maus:
        return "bom"
    return "misto"


def texto_das_regras(fs: list[dict]) -> str:
    return "\n".join(f["text"] for f in fs[:2])


def _pontos(texto: str) -> str:
    """Uma linha por ponto, sem o marcador. É assim que a página os mostra.

    O agente às vezes manda um parágrafo de introdução antes dos pontos ou usa
    "•"/"*" em vez de "-": tira-se o marcador e deita-se fora o que não for
    ponto, desde que haja pontos. Sem nenhum, corta-se o parágrafo em frases."""
    linhas = [re.sub(r"^\s*(?:[-*•–]|\d+[.)])\s*", "", l).strip()
              for l in texto.splitlines() if l.strip()]
    marcados = [l for l, bruta in zip(linhas, [b for b in texto.splitlines() if b.strip()])
                if re.match(r"^\s*(?:[-*•–]|\d+[.)])\s", bruta)]
    if marcados:
        linhas = marcados
    elif len(linhas) == 1:
        linhas = [f.strip() for f in re.split(r"(?<=[.!?])\s+", linhas[0]) if f.strip()]
    return "\n".join(l.rstrip(".") for l in linhas[:5])


def _numeros_do_texto(texto: str) -> set[int]:
    return {int(n) for n in re.findall(r"\d+", texto)}


_PROMPT_ANALISE = """És o assistente pessoal do Cristovão e estás a ler o que o
relógio dele mediu num dia. Trata-o por tu.

O QUE O RELÓGIO MEDIU NESSE DIA:
{factos}

O QUE A APP SABE DO MESMO DIA:
{contexto}

{historico}

Escreve a leitura do dia em **3 a 4 pontos**, um por linha, cada linha a começar
por "- ", em português de Portugal.

Regras, todas obrigatórias:
- **Máximo 14 palavras por ponto.** Frase directa, sem enchimento, sem "isto
  sugere que", sem "vale a pena notar". Nada de parágrafos.
- Um ponto diz UMA coisa. Nada de pontos com duas ideias coladas por vírgulas.
- Só podes usar números que apareçam acima. Nunca inventes, nunca estimes, nunca
  arredondes para um número que não esteja escrito.
- **Não recites a lista.** Escolhe o que mais diz sobre o dia e diz o que
  significa; o resto fica de fora — ele já vê os números todos ao lado.
- Podes ligar factos entre si ("dormiste pouco e o body battery nunca recuperou"),
  mas não podes afirmar causas que os dados não mostrem.
- Nada de conselhos médicos nem diagnósticos. Um ponto final com uma sugestão
  prática, só se sair mesmo dos dados.
- Sem saudações, sem emojis, sem títulos, sem introdução antes dos pontos.
- Se o dia não tiver quase nada medido, diz isso num ponto só.

Devolve só os pontos."""


def _contexto_do_dia(db, dia: _date) -> list[str]:
    """O que o resto da app sabe do mesmo dia — é o que a IA não tem de adivinhar."""
    d = db.query(GarminDay).filter(GarminDay.date == dia).first()
    if d is None:
        return []
    linhas = []
    ecra = _ecra_antes_de_dormir(db, d)
    if ecra:
        linhas.append(f"- {ecra} minutos ao computador na hora antes de adormecer")
    jogos = _jogos_do_dia(db, d)
    if jogos:
        linhas.append(f"- {round(jogos)} jogos de LoL nesse dia")
    codigo = _horas_de_codigo(db, d)
    if codigo:
        linhas.append(f"- {_horas(codigo)} a programar")
    if d.steps is not None:
        linhas.append(f"- {_inteiro(d.steps)} passos"
                      + (f", meta {_inteiro(d.step_goal)}" if d.step_goal else ""))
    if d.calories:
        linhas.append(f"- {_inteiro(d.calories)} calorias no total"
                      + (f", {_inteiro(d.active_calories)} delas activas" if d.active_calories else ""))
    if d.training_readiness is not None:
        linhas.append(f"- prontidão para treinar {d.training_readiness} em 100")
    return linhas


def _historico_para_prompt(db, dia: _date) -> str:
    """Quantos dias de histórico existem — para a IA não falar de tendências que
    não pode ver. Com três dias medidos não há "o teu costume"."""
    medidos = db.query(GarminDay).filter(GarminDay.date <= dia).count()
    if medidos < MINIMO_BASELINE:
        return (f"ATENÇÃO: só há {medidos} dias medidos com este relógio. Não digas "
                f"o que é habitual nem compares com o costume dele — ainda não há "
                f"histórico que chegue. Fala só deste dia.")
    return (f"Há {medidos} dias medidos, e as comparações com o costume que estão "
            f"acima já saíram desse histórico.")


def _analise_do_agente(db, dia: _date, fs: list[dict], lista: str) -> str:
    """A leitura escrita pelo agente, com os números presos aos dados.

    O modelo local não serve para isto (chegou a inverter um condicional e a
    dizer o contrário do que os dados diziam), mas a regra continua a ser a
    mesma: qualquer algarismo no texto tem de existir nos factos ou no contexto.
    Se aparecer um número que ninguém mediu, o texto é deitado fora inteiro."""
    import ai
    import ai_budget

    if not ai_budget.permitido("relogio"):
        return ""

    contexto = _contexto_do_dia(db, dia)
    texto = ai.pergunta(
        _PROMPT_ANALISE.format(
            factos=lista,
            contexto="\n".join(contexto) or "- (nada)",
            historico=_historico_para_prompt(db, dia)),
        timeout=90.0, feature="relogio", permite_local=False).strip()
    if not texto:
        return ""

    permitidos = _numeros_do_texto(lista + "\n" + "\n".join(contexto))
    inventados = _numeros_do_texto(texto) - permitidos
    if inventados:
        logger.info("garmin: leitura do agente recusada, números fora dos dados: %s",
                    sorted(inventados))
        return ""
    pontos = _pontos(texto)
    return pontos if len(pontos) < 900 else ""


def leitura(db, dia: _date) -> dict[str, Any]:
    """Os factos do dia, o tema, e uma frase de ligação escrita pelo modelo local."""
    fs = factos(db, dia)
    if not fs:
        return {"date": dia.isoformat(), "facts": [], "theme": None,
                "headline": "", "text": "", "source": "vazio"}

    lista = "\n".join(f"- {f['text']}" for f in fs[:10])
    tema, fonte, ligacao = _tema_das_regras(fs), "regras", ""

    # v2: a leitura passou a ser pontos; as caches de parágrafo não servem.
    chave = f"garmin_leitura2:{dia}:{hashlib.sha1(lista.encode()).hexdigest()[:12]}"
    guardado = cache.cache_get(chave)
    if isinstance(guardado, dict):
        return {"date": dia.isoformat(), "facts": fs, **guardado}

    # Primeiro o agente, que escreve a leitura inteira com os factos à frente.
    # Só se ele não responder (ou inventar um número) é que se cai no modelo
    # local, que sabe fazer uma frase de ligação e mais nada.
    analise_ia = _analise_do_agente(db, dia, fs, lista)
    if analise_ia:
        escrita = {"theme": tema, "headline": TEMAS[tema], "text": analise_ia,
                   "linked": True, "source": "agente"}
        cache.cache_set(chave, escrita, 7 * 24 * 3600)
        return {"date": dia.isoformat(), "facts": fs, **escrita}

    if local_ai.disponivel():
        # Com um sinal forte o tema sai das regras: a prioridade de "podes estar
        # a adoecer" não se põe a votos.
        if fs[0]["strength"] < 3:
            escolha = local_ai.pergunta_json(_PROMPT_TEMA.format(factos=lista), timeout=60.0)
            if isinstance(escolha, dict) and escolha.get("tema") in TEMAS:
                tema, fonte = escolha["tema"], "local"

        frase = local_ai.pergunta(_PROMPT_LIGACAO.format(factos=lista),
                                  timeout=90.0, feature="garmin_leitura").strip().strip('"')
        if frase and frase.upper() != "NADA" and not _numeros_do_texto(frase) and len(frase) < 220:
            ligacao, fonte = frase, "local"

    escrita = {"theme": tema, "headline": TEMAS[tema],
               "text": ligacao or texto_das_regras(fs),
               "linked": bool(ligacao), "source": fonte}
    if fonte == "local":
        cache.cache_set(chave, escrita, 7 * 24 * 3600)
    return {"date": dia.isoformat(), "facts": fs, **escrita}


def analise(db, dia: _date, dias_relacoes: int = 90) -> dict[str, Any]:
    """Tudo o que a secção da leitura mostra."""
    r = leitura(db, dia)
    medidos = db.query(GarminDay).count()
    return {
        **r,
        "relations": relacoes(db, dias_relacoes),
        "days_measured": medidos,
        "days_for_baseline": max(0, MINIMO_BASELINE - medidos),
        "days_for_relations": max(0, MINIMO_PARES - medidos),
    }
