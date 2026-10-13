"""O objectivo dos 3 jogos por dia.

Duas perguntas diferentes, que se confundem facilmente:
  1. quantos dias é que ele cumpre o objectivo (hábito);
  2. se jogar 3 lhe corre melhor do que jogar outro número (resultado).

A segunda só se responde com um teste — 50% em 150 jogos e 51% em 329 não é
"jogar 3 é melhor", é ruído. Por isso aqui diz-se sempre com que amostra se
está a falar e quando ainda não há prova nenhuma.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from models import Habit, HabitCompletion, LolGame

NOME_HABITO = "3 jogos de LoL"
OBJECTIVO = 3


def por_dia(db: Session, desde: Optional[date] = None) -> dict[date, dict]:
    """Jogos, vitórias e as horas a que jogou, por dia."""
    q = db.query(LolGame)
    if desde:
        q = q.filter(LolGame.date >= desde)
    dias: dict[date, dict] = {}
    for g in q.all():
        if not g.date:
            continue
        d = dias.setdefault(g.date, {"jogos": 0, "vitorias": 0, "horas": []})
        d["jogos"] += 1
        d["vitorias"] += 1 if g.won else 0
        if g.game_hour is not None:
            d["horas"].append(int(g.game_hour))
    return dias


def _hora_do_objectivo(dados: dict) -> str:
    """A que horas o objectivo ficou cumprido — a hora do 3º jogo do dia.

    Sem isto ficava tudo às 23:59 e a página dos hábitos dizia que ele joga
    sempre à meia-noite, com 100% de consistência."""
    horas = sorted(dados.get("horas") or [])
    if len(horas) >= OBJECTIVO:
        return f"{horas[OBJECTIVO - 1]:02d}:00"
    if horas:
        return f"{horas[-1]:02d}:00"
    return ""            # jogos antigos não trazem hora: melhor vazio do que inventar


def _z(v1: int, n1: int, v2: int, n2: int) -> Optional[float]:
    if n1 < 2 or n2 < 2:
        return None
    p1, p2 = v1 / n1, v2 / n2
    p = (v1 + v2) / (n1 + n2)
    se = (p * (1 - p) * (1 / n1 + 1 / n2)) ** 0.5
    return round((p1 - p2) / se, 2) if se else None


def habito(db: Session) -> Habit:
    """O hábito existe sempre; é criado à primeira vez que faz falta."""
    h = db.query(Habit).filter(Habit.name == NOME_HABITO).first()
    if not h:
        h = Habit(name=NOME_HABITO, icon="🎮", color="#3B82F6", days="daily",
                  position=99, active=True)
        db.add(h)
        db.commit()
        db.refresh(h)
    return h


def marca_dias(db: Session, dias_atras: int = 180) -> int:
    """Marca como feito os dias em que jogou o objectivo. Não se tira à mão o que
    os jogos dizem, por isso também desmarca os dias que já não cumprem."""
    h = habito(db)
    desde = date.today() - timedelta(days=dias_atras)
    contagem = por_dia(db, desde)
    feitos = {
        c.date: c for c in db.query(HabitCompletion)
        .filter(HabitCompletion.habit_id == h.id, HabitCompletion.date >= desde).all()
    }
    mudou = 0
    for d, dados in contagem.items():
        cumpriu = dados["jogos"] >= OBJECTIVO
        if cumpriu and d not in feitos:
            db.add(HabitCompletion(habit_id=h.id, date=d, completed_at=_hora_do_objectivo(dados),
                                   notes=f"{dados['jogos']} jogos"))
            mudou += 1
        elif cumpriu and (feitos[d].notes or "").endswith("jogos"):
            hora = _hora_do_objectivo(dados)
            if feitos[d].completed_at != hora:
                feitos[d].completed_at = hora       # corrige as horas antigas
                mudou += 1
        elif not cumpriu and d in feitos and (feitos[d].notes or "").endswith("jogos"):
            db.delete(feitos[d])
            mudou += 1
    # dias sem jogo nenhum que tenham ficado marcados por engano
    for d, c in feitos.items():
        if d not in contagem and (c.notes or "").endswith("jogos"):
            db.delete(c)
            mudou += 1
    db.commit()
    return mudou


def resumo(db: Session, dias: int = 180) -> dict:
    desde = date.today() - timedelta(days=dias)
    contagem = por_dia(db, desde)
    if not contagem:
        return {"target": OBJECTIVO, "days": dias, "enough": False,
                "note": "ainda não há jogos neste período"}

    dias_jogados = len(contagem)
    exactos = [d for d, v in contagem.items() if v["jogos"] == OBJECTIVO]
    acima = [d for d, v in contagem.items() if v["jogos"] > OBJECTIVO]
    abaixo = [d for d, v in contagem.items() if v["jogos"] < OBJECTIVO]

    def wr(dias_lista) -> dict:
        j = sum(contagem[d]["jogos"] for d in dias_lista)
        v = sum(contagem[d]["vitorias"] for d in dias_lista)
        return {"days": len(dias_lista), "games": j, "wins": v,
                "pct": round(v / j * 100, 1) if j else None,
                **saldo(dias_lista)}

    def saldo(dias_lista) -> dict:
        """Como acabou o dia, não como correram os jogos soltos: 2-1 é dia bom,
        1-2 é dia mau. Com 3 jogos nunca há empate."""
        pos = neg = emp = 0
        for d in dias_lista:
            v, j = contagem[d]["vitorias"], contagem[d]["jogos"]
            if v * 2 > j:
                pos += 1
            elif v * 2 < j:
                neg += 1
            else:
                emp += 1
        n = len(dias_lista)
        return {
            "positive_days": pos, "negative_days": neg, "tied_days": emp,
            "positive_pct": round(pos / n * 100, 1) if n else None,
            "negative_pct": round(neg / n * 100, 1) if n else None,
        }

    no_alvo = wr(exactos)
    fora = wr(acima + abaixo)
    z = _z(no_alvo["wins"], no_alvo["games"], fora["wins"], fora["games"])
    # o mesmo teste, mas ao dia inteiro: acabar o dia a ganhar mais do que perdeu
    z_dias = _z(no_alvo["positive_days"], no_alvo["days"], fora["positive_days"], fora["days"])
    diff_dias = (round(no_alvo["positive_pct"] - fora["positive_pct"], 1)
                 if no_alvo["positive_pct"] is not None and fora["positive_pct"] is not None else None)
    provado = bool(z is not None and abs(z) >= 1.96)
    diff = (round(no_alvo["pct"] - fora["pct"], 1)
            if no_alvo["pct"] is not None and fora["pct"] is not None else None)

    # sequência actual de dias cumpridos (só conta dias em que jogou)
    seguidos = 0
    d = date.today()
    while d >= desde:
        if d in contagem:
            if contagem[d]["jogos"] >= OBJECTIVO:
                seguidos += 1
            else:
                break
        d -= timedelta(days=1)

    por_numero = []
    for n in sorted({v["jogos"] for v in contagem.values()}):
        ds = [d for d, v in contagem.items() if v["jogos"] == n]
        por_numero.append({"games_that_day": n, **wr(ds)})

    if not provado:
        veredicto = ("sem diferença provada: jogar 3 dá praticamente o mesmo que jogar outro número"
                     if diff is not None and abs(diff) < 5
                     else "ainda sem prova — a diferença que aparece cabe no acaso")
    elif diff and diff > 0:
        veredicto = "jogar exactamente 3 corre-te mesmo melhor"
    else:
        veredicto = "jogar exactamente 3 corre-te pior do que jogar outro número"

    return {
        "target": OBJECTIVO,
        "days": dias,
        "enough": True,
        "days_played": dias_jogados,
        "days_on_target": len(exactos),
        "days_over": len(acima),
        "days_under": len(abaixo),
        "days_goal_met": len(exactos) + len(acima),
        "goal_rate_pct": round((len(exactos) + len(acima)) / dias_jogados * 100, 1),
        "exact_rate_pct": round(len(exactos) / dias_jogados * 100, 1),
        "streak": seguidos,
        "on_target": no_alvo,
        "off_target": fora,
        "diff_pp": diff,
        "z": z,
        "days_diff_pp": diff_dias,
        "days_z": z_dias,
        "days_proven": bool(z_dias is not None and abs(z_dias) >= 1.96),
        "proven": provado,
        "verdict": veredicto,
        "by_count": por_numero,
    }
