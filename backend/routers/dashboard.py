from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from sqlalchemy import func
from datetime import date, datetime, timedelta
import logging
from typing import Optional

from database import get_db
from models import (
    Event, Expense, LolGame, FlowSession, Habit, HabitCompletion,
    MoodEntry, DailyJournal, WakaProjectDay, Note, Trip, ScreenTimeDailyApp,
)
import expense_kind as ek
import screen_source
import sono

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def _week_range(week_offset: int = 0) -> tuple[date, date]:
    """Get Monday–Sunday for a given week offset (0=this week, -1=last week)."""
    today = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _is_scheduled(days: str, weekday: int) -> bool:
    if days == "daily":
        return True
    if days == "weekdays":
        return weekday < 5
    try:
        allowed = {int(d.strip()) for d in days.split(",")}
        return weekday in allowed
    except ValueError:
        return True


@router.get("/weekly-review")
def weekly_review(
    week_offset: int = Query(0, ge=-52, le=0),
    db: Session = Depends(get_db),
):
    """
    Aggregate weekly stats for the report card.
    week_offset=0 is current week, -1 is last week, etc.
    """
    monday, sunday = _week_range(week_offset)
    prev_monday, prev_sunday = _week_range(week_offset - 1)

    # ── Events ───────────────────────────────────────────────────
    events = db.query(Event).filter(Event.date >= monday, Event.date <= sunday).all()
    events_total = len(events)
    events_completed = sum(1 for e in events if e.completed)

    # ── Expenses ─────────────────────────────────────────────────
    expenses = db.query(Expense).filter(Expense.date >= monday, Expense.date <= sunday,
                                        Expense.kind == ek.GASTO, Expense.extraordinary.is_(False)).all()
    expenses_total = round(sum(e.amount for e in expenses), 2)
    expenses_by_cat: dict = {}
    for e in expenses:
        cat = e.category or "other"
        expenses_by_cat[cat] = round(expenses_by_cat.get(cat, 0) + e.amount, 2)

    # Previous week for comparison
    prev_expenses = db.query(Expense).filter(Expense.date >= prev_monday, Expense.date <= prev_sunday,
                                             Expense.kind == ek.GASTO, Expense.extraordinary.is_(False)).all()
    prev_expenses_total = round(sum(e.amount for e in prev_expenses), 2)

    # ── LoL Games ────────────────────────────────────────────────
    games = db.query(LolGame).filter(LolGame.date >= monday, LolGame.date <= sunday).all()
    games_total = len(games)
    games_won = sum(1 for g in games if g.won)
    games_wr = round(games_won / games_total * 100, 1) if games_total > 0 else 0

    prev_games = db.query(LolGame).filter(LolGame.date >= prev_monday, LolGame.date <= prev_sunday).all()
    prev_wr = round(sum(1 for g in prev_games if g.won) / len(prev_games) * 100, 1) if prev_games else 0

    # ── Sleep (só as noites medidas pelo relógio) ────────────────
    sleep_entries = sono.noites(db, monday, sunday)
    sleep_avg = round(sum(s.hours for s in sleep_entries) / len(sleep_entries), 1) if sleep_entries else 0
    score_list = list(sono.pontuacoes(db, monday, sunday).values())
    sleep_score_avg = round(sum(score_list) / len(score_list)) if score_list else None

    prev_sleep = sono.noites(db, prev_monday, prev_sunday)
    prev_sleep_avg = round(sum(s.hours for s in prev_sleep) / len(prev_sleep), 1) if prev_sleep else 0

    # ── Flow Sessions ────────────────────────────────────────────
    flow_sessions = db.query(FlowSession).filter(
        FlowSession.date >= monday, FlowSession.date <= sunday
    ).all()
    flow_total_min = sum(s.actual_minutes or s.planned_minutes for s in flow_sessions)
    flow_total_hours = round(flow_total_min / 60, 1)
    flow_sessions_count = len(flow_sessions)

    prev_flow = db.query(FlowSession).filter(
        FlowSession.date >= prev_monday, FlowSession.date <= prev_sunday
    ).all()
    prev_flow_hours = round(sum(s.actual_minutes or s.planned_minutes for s in prev_flow) / 60, 1)

    # By preset
    flow_by_preset: dict = {}
    for s in flow_sessions:
        name = s.preset_name
        if name not in flow_by_preset:
            flow_by_preset[name] = {"minutes": 0, "sessions": 0, "color": s.color}
        flow_by_preset[name]["minutes"] += s.actual_minutes or s.planned_minutes
        flow_by_preset[name]["sessions"] += 1

    # ── Habits ───────────────────────────────────────────────────
    habits = db.query(Habit).filter(Habit.active == True).all()
    completions = db.query(HabitCompletion).filter(
        HabitCompletion.date >= monday, HabitCompletion.date <= sunday
    ).all()
    completion_set = {(c.habit_id, str(c.date)) for c in completions}

    # Count scheduled slots and completed
    total_scheduled = 0
    total_completed = 0
    habit_stats = []
    for h in habits:
        scheduled = 0
        completed = 0
        d = monday
        while d <= min(sunday, date.today()):
            if _is_scheduled(h.days, d.weekday()):
                scheduled += 1
                if (h.id, str(d)) in completion_set:
                    completed += 1
            d += timedelta(days=1)
        total_scheduled += scheduled
        total_completed += completed
        if scheduled > 0:
            habit_stats.append({
                "name": h.name,
                "icon": h.icon,
                "color": h.color,
                "scheduled": scheduled,
                "completed": completed,
                "rate": round(completed / scheduled * 100, 1),
            })

    habits_rate = round(total_completed / total_scheduled * 100, 1) if total_scheduled > 0 else 0

    # ── Mood (average for the week) ──────────────────────────────
    moods = db.query(MoodEntry).filter(
        MoodEntry.date >= monday, MoodEntry.date <= sunday
    ).all()
    mood_avg = round(sum(m.mood for m in moods) / len(moods), 1) if moods else None
    mood_entries = [{"date": str(m.date), "mood": m.mood, "note": m.note} for m in moods]

    return {
        "week_start": str(monday),
        "week_end": str(sunday),
        "events": {
            "total": events_total,
            "completed": events_completed,
            "rate": round(events_completed / events_total * 100, 1) if events_total > 0 else 0,
        },
        "expenses": {
            "total": expenses_total,
            "prev_total": prev_expenses_total,
            "delta": round(expenses_total - prev_expenses_total, 2),
            "by_category": expenses_by_cat,
        },
        "lol": {
            "games": games_total,
            "wins": games_won,
            "losses": games_total - games_won,
            "winrate": games_wr,
            "prev_winrate": prev_wr,
        },
        "sleep": {
            "avg_hours": sleep_avg,
            "avg_score": sleep_score_avg,
            "entries": len(sleep_entries),
            "prev_avg_hours": prev_sleep_avg,
        },
        "flow": {
            "total_hours": flow_total_hours,
            "sessions": flow_sessions_count,
            "prev_total_hours": prev_flow_hours,
            "by_preset": flow_by_preset,
        },
        "habits": {
            "total_scheduled": total_scheduled,
            "total_completed": total_completed,
            "rate": habits_rate,
            "by_habit": sorted(habit_stats, key=lambda x: x["rate"], reverse=True),
        },
        "mood": {
            "average": mood_avg,
            "entries": mood_entries,
        },
    }


@router.get("/correlations")
def correlations(db: Session = Depends(get_db)):
    """
    Cross-data correlations: sleep vs LoL WR, sleep vs flow, expenses by weekday.
    Uses last 90 days of data.
    """
    cutoff = date.today() - timedelta(days=90)

    # Get all sleep entries
    sleep_by_date = {str(d): h for d, h in sono.horas_por_dia(db, cutoff).items()}

    # Get all LoL games
    games = db.query(LolGame).filter(LolGame.date >= cutoff).all()

    # Get all flow sessions
    flow_sessions = db.query(FlowSession).filter(FlowSession.date >= cutoff).all()

    # Get all expenses
    expenses = db.query(Expense).filter(Expense.date >= cutoff, Expense.kind == ek.GASTO, Expense.extraordinary.is_(False)).all()

    # Get all moods
    moods = db.query(MoodEntry).filter(MoodEntry.date >= cutoff).all()
    mood_by_date = {str(m.date): m.mood for m in moods}

    # ── Sleep vs LoL WR ──────────────────────────────────────────
    good_sleep_games = []  # games on days with >=7h sleep
    bad_sleep_games = []   # games on days with <6h sleep
    mid_sleep_games = []   # 6-7h

    for g in games:
        sleep_h = sleep_by_date.get(str(g.date))
        if sleep_h is None:
            continue
        if sleep_h >= 7:
            good_sleep_games.append(g.won)
        elif sleep_h < 6:
            bad_sleep_games.append(g.won)
        else:
            mid_sleep_games.append(g.won)

    def wr(lst):
        if not lst:
            return None
        return round(sum(1 for w in lst if w) / len(lst) * 100, 1)

    # ── Sleep vs Flow productivity ───────────────────────────────
    good_sleep_flow = []
    bad_sleep_flow = []
    for s in flow_sessions:
        sleep_h = sleep_by_date.get(str(s.date))
        if sleep_h is None:
            continue
        mins = s.actual_minutes or s.planned_minutes
        if sleep_h >= 7:
            good_sleep_flow.append(mins)
        elif sleep_h < 6:
            bad_sleep_flow.append(mins)

    # ── Expenses by day of week ──────────────────────────────────
    day_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    expenses_by_weekday = [0.0] * 7
    expenses_count_by_weekday = [0] * 7
    valores_por_dia: dict[int, list[float]] = {}
    for e in expenses:
        wd = e.date.weekday()
        expenses_by_weekday[wd] += e.amount
        expenses_count_by_weekday[wd] += 1
        valores_por_dia.setdefault(wd, []).append(e.amount)

    # ── Mood vs sleep ────────────────────────────────────────────
    mood_good_sleep = []
    mood_bad_sleep = []
    for m in moods:
        sleep_h = sleep_by_date.get(str(m.date))
        if sleep_h is None:
            continue
        if sleep_h >= 7:
            mood_good_sleep.append(m.mood)
        elif sleep_h < 6:
            mood_bad_sleep.append(m.mood)

    # ── Mood vs LoL (did playing affect mood?) ───────────────────
    game_dates = {str(g.date) for g in games}
    mood_game_days = [m.mood for m in moods if str(m.date) in game_dates]
    mood_no_game_days = [m.mood for m in moods if str(m.date) not in game_dates]

    def avg(lst):
        if not lst:
            return None
        return round(sum(lst) / len(lst), 2)

    return {
        "sleep_vs_lol": {
            "good_sleep_wr": wr(good_sleep_games),
            "good_sleep_games": len(good_sleep_games),
            "mid_sleep_wr": wr(mid_sleep_games),
            "mid_sleep_games": len(mid_sleep_games),
            "bad_sleep_wr": wr(bad_sleep_games),
            "bad_sleep_games": len(bad_sleep_games),
        },
        "sleep_vs_flow": {
            "good_sleep_avg_min": round(avg(good_sleep_flow) or 0, 1),
            "good_sleep_sessions": len(good_sleep_flow),
            "bad_sleep_avg_min": round(avg(bad_sleep_flow) or 0, 1),
            "bad_sleep_sessions": len(bad_sleep_flow),
        },
        # A mediana vai a par da média: uma compra de 703€ fazia a quinta parecer
        # o dia caro da semana quando a compra típica desse dia são 7€.
        "expenses_by_weekday": [
            {
                "day": day_names[i],
                "total": round(expenses_by_weekday[i], 2),
                "count": expenses_count_by_weekday[i],
                "avg": round(expenses_by_weekday[i] / max(expenses_count_by_weekday[i], 1), 2),
                "median": round(_mediana_lista(valores_por_dia.get(i, [])), 2),
            }
            for i in range(7)
        ],
        "sleep_vs_lol_test": _sono_vs_winrate(db),
        "mood_vs_sleep": {
            "good_sleep_mood": avg(mood_good_sleep),
            "bad_sleep_mood": avg(mood_bad_sleep),
        },
        "mood_vs_gaming": {
            "game_day_mood": avg(mood_game_days),
            "no_game_mood": avg(mood_no_game_days),
        },
    }


# ── Insight da semana ────────────────────────────────────────────

@router.get("/insight")
def weekly_insight(db: Session = Depends(get_db)):
    """Uma frase por semana com o que os dados dizem — o cruzamento já existia,
    faltava alguém dizê-lo em voz alta."""
    corr = correlations(db)
    review = weekly_review(0, db)
    prev = weekly_review(-1, db)

    insights: list[dict] = []

    # Sono vs winrate: só se aguentar um teste. O número parecia enorme (+18pp)
    # mas vinha de 30 jogos e não passa (z=1.2) — dizer isso como facto era mentir.
    lol_dados = _sono_vs_winrate(db)
    if lol_dados and lol_dados["proven"]:
        insights.append({
            "key": "sono_lol", "icon": "🎮",
            "text": (f"Com {lol_dados['limite']}h+ de sono ganhas {lol_dados['wr_bom']}% das games, "
                     f"contra {lol_dados['wr_mau']}% quando dormes menos "
                     f"({lol_dados['diff']:+}pp em {lol_dados['n_bom'] + lol_dados['n_mau']} jogos)."),
            "proven": True,
        })

    # Dia mais caro pela mediana: com médias, uma compra de 703€ fazia a quinta
    # parecer o dia caro da semana quando a compra típica desse dia são 7€.
    caro = _dia_mais_caro(db)
    if caro:
        insights.append({
            "key": "gastos_dia", "icon": "💸",
            "text": (f"{caro['dia']} é o teu dia mais caro: {caro['mediana']:.0f}€ na compra típica, "
                     f"contra {caro['mediana_resto']:.0f}€ nos outros dias ({caro['n']} compras)."),
            "proven": True,
        })

    semana_sono = review.get("sleep") or {}
    if semana_sono.get("avg_hours"):
        media = semana_sono["avg_hours"]
        antes = semana_sono.get("prev_avg_hours") or 0
        # Sem noites medidas na semana passada não há comparação: dizer "5.9h a
        # mais" quando o relógio ainda não existia era inventar um antes.
        texto = f"Esta semana dormiste {media}h por noite em média ({semana_sono.get('entries', 0)} noites medidas)"
        if antes:
            texto += (f", {abs(round(media - antes, 1))}h "
                      f"{'a mais' if media >= antes else 'a menos'} que na semana passada")
        insights.append({"key": "sono_semana", "icon": "🌙", "text": texto + "."})

    g_now = (review.get("expenses") or {}).get("total", 0)
    g_prev = (prev.get("expenses") or {}).get("total", 0)
    # Só compara semanas depois de a actual ter algum registo — senão dizia
    # sempre "gastaste 100% menos" à segunda de manhã.
    if g_prev > 0 and g_now > 0:
        delta = round((g_now - g_prev) / g_prev * 100)
        if abs(delta) >= 15:
            insights.append({
                "key": "gastos_semana",
                "icon": "📊",
                "text": f"Gastaste {abs(delta)}% {'mais' if delta > 0 else 'menos'} que na semana passada ({g_now:.0f}€ vs {g_prev:.0f}€).",
            })

    # Hábitos: 2 marcações em 3 meses. Falar de uma secção que ele não usa é ruído
    # — a Consistência automática já mede o mesmo sem pedir nada.
    habitos = review.get("habits") or {}
    marcados_recentes = (
        db.query(sqlfunc.count(HabitCompletion.id))
        .filter(HabitCompletion.date >= date.today() - timedelta(days=30)).scalar() or 0
    )
    if habitos.get("total_scheduled", 0) >= 3 and marcados_recentes >= 5:
        feitos = habitos.get("total_completed", 0)
        total = habitos["total_scheduled"]
        insights.append({
            "key": "habitos", "icon": "🎯",
            "text": f"Cumpriste {round(feitos / total * 100)}% dos hábitos marcados esta semana ({feitos}/{total}).",
        })

    return {
        "week_start": review.get("week_start"),
        "week_end": review.get("week_end"),
        "insights": insights[:4],
    }


# ── Consistência automática ──────────────────────────────────────
#
# Marcar hábitos à mão não pega (1 check em 60 dias). Isto mede o mesmo a partir
# do que já é recolhido sozinho: código, sono, jogos, gastos e tempo longe do PC.

@router.get("/consistency")
def consistency(days: int = Query(30, ge=7, le=180), db: Session = Depends(get_db)):
    from models import (
        WakaProjectDay, ScreenTimeDailyApp, AppUsageSession, Expense,
        HabitCompletion,
    )
    from routers.budgets import salary_plan

    hoje = date.today()
    inicio = hoje - timedelta(days=days - 1)

    codigo = {
        str(d): int(s or 0) for d, s in
        db.query(WakaProjectDay.day, func.sum(WakaProjectDay.seconds))
        .filter(WakaProjectDay.kind == "project", WakaProjectDay.day >= inicio)
        .group_by(WakaProjectDay.day).all()
    }
    noites = {str(d): h for d, h in sono.horas_por_dia(db, inicio).items()}
    jogos = {
        str(d): int(cats.get("Games", 0))
        for d, cats in screen_source.por_dia_e_categoria(db, inicio, date.today()).items()
    }
    gasto = {
        str(d): float(v or 0) for d, v in
        db.query(Expense.date, func.sum(Expense.amount))
        .filter(Expense.date >= inicio, Expense.kind == ek.GASTO, Expense.extraordinary.is_(False))
        .group_by(Expense.date).all()
    }
    habitos = {str(h.date) for h in db.query(HabitCompletion).filter(HabitCompletion.date >= inicio).all()}

    # tempo longe do PC (proxy de exercício/vida offline): maior intervalo do dia
    sessoes: dict[str, list] = {}
    for ses in db.query(AppUsageSession).filter(AppUsageSession.date >= str(inicio)).all():
        sessoes.setdefault(str(ses.date), []).append(ses)

    def maior_gap(lista) -> int:
        def m(t):
            try:
                h, mi = str(t)[11:16].split(":")
                return int(h) * 60 + int(mi)
            except Exception:
                return 0
        marcos = sorted((m(s.start_time), m(s.end_time or s.start_time)) for s in lista if s.start_time)
        anterior, maior = 7 * 60, 0
        for ini, fim in marcos:
            if 7 * 60 <= anterior < ini <= 23 * 60:
                maior = max(maior, ini - anterior)
            anterior = max(anterior, fim)
        return maior

    # alvo de gasto diário: plano do salário / dias do mês (fallback 30€)
    plano = salary_plan(hoje.month, hoje.year, start_date=None, end_date=None, salary=None, db=db)
    alvo_mes = sum(g["target"] for g in plano.get("groups", []) if g.get("kind") == "spend")
    alvo_dia = (alvo_mes / 30) if alvo_mes else 30.0

    serie = []
    for i in range(days):
        d = inicio + timedelta(days=i)
        k = str(d)
        partes = []
        partes.append({"key": "codigo", "label": "código ≥30min", "ok": codigo.get(k, 0) >= 1800})
        h = noites.get(k)
        if h:
            partes.append({"key": "sono", "label": "sono ≥7h", "ok": h >= 7})
        partes.append({"key": "jogos", "label": "jogos ≤2h", "ok": jogos.get(k, 0) <= 2 * 3600})
        if k in gasto:
            partes.append({"key": "gastos", "label": "gasto no alvo", "ok": gasto[k] <= alvo_dia})
        partes.append({
            "key": "offline",
            "label": "1h fora do PC",
            "ok": (k in habitos) or maior_gap(sessoes.get(k, [])) >= 60,
        })
        feitos = sum(1 for p in partes if p["ok"])
        score = round(feitos / len(partes) * 100) if partes else 0
        serie.append({"date": k, "score": score, "parts": partes, "done": feitos, "total": len(partes)})

    # streak: dias consecutivos com 60+ (a contar do fim, ignorando hoje se ainda vai a meio)
    streak = 0
    for dia in reversed(serie[:-1] if serie else []):
        if dia["score"] >= 60:
            streak += 1
        else:
            break
    melhor, corrente = 0, 0
    for dia in serie:
        if dia["score"] >= 60:
            corrente += 1
            melhor = max(melhor, corrente)
        else:
            corrente = 0

    hoje_dia = serie[-1] if serie else None
    media = round(sum(d["score"] for d in serie) / len(serie)) if serie else 0
    return {
        "today": hoje_dia,
        "streak": streak,
        "best_streak": melhor,
        "average": media,
        "series": [{"date": d["date"], "score": d["score"]} for d in serie],
    }


# ── Retrospectiva mensal em PDF ──────────────────────────────────

@router.get("/monthly-review")
def monthly_review(month: Optional[int] = Query(None), year: Optional[int] = Query(None),
                   db: Session = Depends(get_db)):
    """Números do mês, de todas as áreas — a base da retrospectiva."""
    from calendar import monthrange
    from models import (
        WakaProjectDay, MoodEntry, Expense, LolGame, Trip,
        ScreenTimeDailyApp, CodeProjectNote, ListItem, DailyJournal,
    )

    hoje = date.today()
    m = month or hoje.month
    y = year or hoje.year
    inicio = date(y, m, 1)
    fim = date(y, m, monthrange(y, m)[1])
    dias = (min(fim, hoje) - inicio).days + 1

    def soma(col, modelo, campo_data, **filtros):
        q = db.query(func.coalesce(func.sum(col), 0)).filter(campo_data >= inicio, campo_data <= fim)
        for k, v in filtros.items():
            q = q.filter(getattr(modelo, k) == v)
        return q.scalar() or 0

    codigo_seg = soma(WakaProjectDay.seconds, WakaProjectDay, WakaProjectDay.day, kind="project")
    por_projecto = (
        db.query(WakaProjectDay.project, func.sum(WakaProjectDay.seconds))
        .filter(WakaProjectDay.kind == "project", WakaProjectDay.day >= inicio, WakaProjectDay.day <= fim)
        .group_by(WakaProjectDay.project).order_by(func.sum(WakaProjectDay.seconds).desc()).limit(5).all()
    )
    noites = sono.noites(db, inicio, fim)
    moods = db.query(MoodEntry).filter(MoodEntry.date >= inicio, MoodEntry.date <= fim).all()
    despesas = db.query(Expense).filter(Expense.date >= inicio, Expense.date <= fim,
                                        Expense.kind == ek.GASTO, Expense.extraordinary.is_(False)).all()
    jogos = db.query(LolGame).filter(LolGame.date >= inicio, LolGame.date <= fim).all()
    viagens = db.query(Trip).filter(Trip.start_date <= fim, Trip.end_date >= inicio).all()
    por_cat_mes = screen_source.por_categoria(db, inicio, fim)
    ecra_seg = sum(por_cat_mes.values())
    jogos_seg = por_cat_mes.get("Games", 0)
    notas = db.query(CodeProjectNote).filter(
        CodeProjectNote.created_at >= datetime.combine(inicio, datetime.min.time()),
        CodeProjectNote.created_at <= datetime.combine(fim, datetime.max.time()),
    ).all()
    tarefas = db.query(ListItem).filter(ListItem.due_date >= inicio, ListItem.due_date <= fim).all()
    diarios = db.query(DailyJournal).filter(DailyJournal.date >= inicio, DailyJournal.date <= fim).all()

    por_categoria = {}
    for e in despesas:
        if e.amount > 0:
            por_categoria[e.category or "other"] = round(por_categoria.get(e.category or "other", 0) + e.amount, 2)

    return {
        "month": m, "year": y, "days_counted": dias,
        "code": {"seconds": int(codigo_seg), "projects": [{"name": p, "seconds": int(s)} for p, s in por_projecto],
                 "notes": len(notas)},
        "sleep": {"nights": len(noites),
                  "avg_hours": round(sum(n.hours or 0 for n in noites) / len(noites), 2) if noites else 0,
                  "best": max((n.hours or 0) for n in noites) if noites else 0,
                  "worst": min((n.hours or 0) for n in noites) if noites else 0},
        "mood": {"entries": len(moods),
                 "avg": round(sum(x.mood or 0 for x in moods) / len(moods), 1) if moods else 0},
        "money": {"spent": round(sum(e.amount for e in despesas if e.amount > 0), 2),
                  "income": round(sum(-e.amount for e in despesas if e.amount < 0), 2),
                  "transactions": len(despesas),
                  "by_category": sorted(([{"category": k, "amount": v} for k, v in por_categoria.items()]),
                                        key=lambda x: -x["amount"])[:6]},
        "screen": {"seconds": int(ecra_seg), "games_seconds": int(jogos_seg)},
        "lol": {"games": len(jogos), "wins": sum(1 for g in jogos if g.won),
                "winrate": round(sum(1 for g in jogos if g.won) / len(jogos) * 100, 1) if jogos else 0},
        "trips": [{"destination": t.destination, "start": str(t.start_date), "end": str(t.end_date)} for t in viagens],
        "tasks": {"total": len(tarefas), "done": sum(1 for t in tarefas if t.checked)},
        "journals": len(diarios),
    }


@router.post("/monthly-review/pdf")
async def monthly_review_pdf(month: Optional[int] = Query(None), year: Optional[int] = Query(None),
                             db: Session = Depends(get_db)):
    """Retrospectiva do mês em PDF, com texto escrito pela IA a partir dos números."""
    from fastapi.responses import StreamingResponse
    from ai_config import ask_agent_async, extract_json
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (ListFlowable, ListItem as PdfListItem, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)
    from io import BytesIO

    d = monthly_review(month, year, db)
    MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]
    nome_mes = f"{MESES[d['month']]} de {d['year']}"

    def hm(seg: int) -> str:
        h = seg // 3600
        return f"{h}h{(seg % 3600) // 60:02d}" if h else f"{seg // 60}min"

    resumo_ia, bullets = "", []
    try:
        prompt = f"""Escreve a retrospectiva do meu mês ({nome_mes}) em português de Portugal.

Números:
- Código: {hm(d['code']['seconds'])} em {len(d['code']['projects'])} projectos ({', '.join(p['name'] for p in d['code']['projects'][:3])}), {d['code']['notes']} notas
- Sono: {d['sleep']['avg_hours']}h de média em {d['sleep']['nights']} noites (melhor {d['sleep']['best']}h, pior {d['sleep']['worst']}h)
- Humor: média {d['mood']['avg']}/10 em {d['mood']['entries']} registos
- Dinheiro: gastei {d['money']['spent']}€ em {d['money']['transactions']} transacções; entrou {d['money']['income']}€.
  Maiores categorias: {', '.join(f"{c['category']} {c['amount']}€" for c in d['money']['by_category'][:4])}
- Ecrã: {hm(d['screen']['seconds'])} no total, {hm(d['screen']['games_seconds'])} em jogos
- LoL: {d['lol']['games']} games, {d['lol']['winrate']}% de vitórias
- Viagens: {', '.join(t['destination'] for t in d['trips']) or 'nenhuma'}
- Tarefas: {d['tasks']['done']} feitas de {d['tasks']['total']}

Devolve SÓ um JSON: {{"resumo": "3 a 4 frases sobre como foi o mês", "bullets": ["...", "..."]}}
Regras: bullets de 3 a 5, cada um uma observação concreta ligada aos números (não invente nada
fora deles), máximo 20 palavras. Directo, sem elogios nem enchimento."""
        resposta = await ask_agent_async(prompt, timeout=150.0, feature="aquecer")
        data = extract_json(resposta) or {}
        resumo_ia = str(data.get("resumo") or "").strip()
        bullets = [str(b).strip() for b in (data.get("bullets") or []) if str(b).strip()][:5]
    except Exception as ex:
        logger.warning(f"retrospectiva: IA indisponível ({ex})")

    base = getSampleStyleSheet()
    titulo = ParagraphStyle("T", parent=base["Title"], fontSize=22, leading=26, alignment=0,
                            textColor=colors.HexColor("#111827"), spaceAfter=2)
    meta = ParagraphStyle("M", parent=base["Normal"], fontSize=9.5, leading=13,
                          textColor=colors.HexColor("#6b7280"), spaceAfter=14)
    h2 = ParagraphStyle("H", parent=base["Heading2"], fontSize=13, leading=17,
                        textColor=colors.HexColor("#1d4ed8"), spaceBefore=14, spaceAfter=6)
    corpo = ParagraphStyle("C", parent=base["Normal"], fontSize=10.5, leading=15,
                           textColor=colors.HexColor("#1f2937"))
    rodape = ParagraphStyle("R", parent=base["Normal"], fontSize=8, leading=11,
                            textColor=colors.HexColor("#9ca3af"))

    def esc(t) -> str:
        return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = [Paragraph(f"Retrospectiva · {esc(nome_mes)}", titulo),
             Paragraph(f"{d['days_counted']} dias contabilizados", meta)]
    if resumo_ia:
        story.append(Paragraph(esc(resumo_ia), corpo))
    if bullets:
        story.append(Paragraph("O que se passou", h2))
        story.append(ListFlowable([PdfListItem(Paragraph(esc(b), corpo), leftIndent=12) for b in bullets],
                                  bulletType="bullet", start="•", leftIndent=14,
                                  bulletColor=colors.HexColor("#1d4ed8")))

    story.append(Paragraph("Números", h2))
    tabela = [
        ["Código", hm(d["code"]["seconds"]), f"{d['code']['notes']} notas"],
        ["Sono", f"{d['sleep']['avg_hours']}h/noite", f"{d['sleep']['nights']} noites"],
        ["Humor", f"{d['mood']['avg']}/10", f"{d['mood']['entries']} registos"],
        ["Gastos", f"{d['money']['spent']:.2f}€", f"{d['money']['transactions']} transacções"],
        ["Entradas", f"{d['money']['income']:.2f}€", ""],
        ["Ecrã", hm(d["screen"]["seconds"]), f"jogos {hm(d['screen']['games_seconds'])}"],
        ["LoL", f"{d['lol']['games']} games", f"{d['lol']['winrate']}% wins"],
        ["Tarefas", f"{d['tasks']['done']}/{d['tasks']['total']}", ""],
        ["Viagens", ", ".join(t["destination"] for t in d["trips"]) or "—", ""],
    ]
    t = Table(tabela, colWidths=[70 * mm, 45 * mm, 45 * mm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#374151")),
        ("TEXTCOLOR", (1, 0), (-1, -1), colors.HexColor("#111827")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f7f8fa")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#e5e7eb")),
    ]))
    story.append(t)

    if d["money"]["by_category"]:
        story.append(Paragraph("Para onde foi o dinheiro", h2))
        story.append(ListFlowable(
            [PdfListItem(Paragraph(f"{esc(c['category'])} — {c['amount']:.2f}€", corpo), leftIndent=12)
             for c in d["money"]["by_category"]],
            bulletType="bullet", start="•", leftIndent=14, bulletColor=colors.HexColor("#059669")))

    story.append(Spacer(1, 16))
    story.append(Paragraph(f"Gerado pelo Cristopher em {datetime.now().strftime('%d/%m/%Y às %H:%M')}", rodape))

    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                      topMargin=20 * mm, bottomMargin=18 * mm,
                      title=f"Retrospectiva {nome_mes}", author="Cristopher").build(story)
    nome = f"retrospectiva-{d['year']}-{d['month']:02d}.pdf"
    return StreamingResponse(iter([buf.getvalue()]), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{nome}"'})


def _dia_resumo(db: Session, dia: date) -> dict:
    gastos = db.query(Expense).filter(Expense.date == dia, Expense.kind == ek.GASTO).all()
    total_gasto = round(sum(e.amount for e in gastos), 2)
    maior = max(gastos, key=lambda e: e.amount) if gastos else None

    noite = sono.noite(db, dia)
    humor = db.query(MoodEntry).filter(MoodEntry.date == dia).first()
    diario = db.query(DailyJournal).filter(DailyJournal.date == dia).first()

    codigo = db.query(sqlfunc.coalesce(sqlfunc.sum(WakaProjectDay.seconds), 0)).filter(
        WakaProjectDay.day == dia, WakaProjectDay.kind == "project"
    ).scalar() or 0
    projecto = (
        db.query(WakaProjectDay.project, WakaProjectDay.seconds)
        .filter(WakaProjectDay.day == dia, WakaProjectDay.kind == "project")
        .order_by(WakaProjectDay.seconds.desc()).first()
    )

    jogos = db.query(LolGame).filter(LolGame.date == dia).all()
    eventos = [
        e.title for e in db.query(Event).filter(Event.date == dia, Event.completed == True)  # noqa: E712
        .order_by(Event.start_time).limit(4).all()
    ]
    viagem = db.query(Trip).filter(Trip.start_date <= dia, Trip.end_date >= dia).first()
    notas = db.query(sqlfunc.count(Note.id)).filter(
        sqlfunc.date(Note.created_at) == dia.isoformat()
    ).scalar() or 0

    return {
        "date": dia.isoformat(),
        "spent": total_gasto,
        "top_expense": (
            {"description": maior.description, "amount": round(maior.amount, 2),
             "category": maior.category} if maior else None
        ),
        "sleep_hours": round(noite.hours, 2) if noite and noite.hours else None,
        "mood": humor.mood if humor else None,
        "mood_note": (humor.note or "")[:140] if humor else None,
        "journal": (diario.content or "")[:220] if diario else None,
        "code_seconds": int(codigo),
        "top_project": {"name": projecto[0], "seconds": int(projecto[1])} if projecto else None,
        "lol": {"games": len(jogos), "wins": sum(1 for g in jogos if g.won)} if jogos else None,
        "events": eventos,
        "trip": viagem.destination if viagem else None,
        "notes": int(notas),
    }


def _tem_conteudo(r: dict) -> bool:
    return bool(
        r["spent"] or r["sleep_hours"] or r["mood"] or r["journal"]
        or r["code_seconds"] or r["lol"] or r["events"] or r["trip"] or r["notes"]
    )


def _menos_meses(d: date, meses: int) -> date:
    m = d.month - meses
    ano = d.year + (m - 1) // 12
    mes = (m - 1) % 12 + 1
    dia = d.day
    while dia > 1:
        try:
            return date(ano, mes, dia)
        except ValueError:
            dia -= 1
    return date(ano, mes, 1)


@router.get("/on-this-day")
def on_this_day(day: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """O mesmo dia há um mês, seis meses e um/dois anos — só o que tem conteúdo."""
    hoje = date.fromisoformat(day) if day else date.today()
    periodos = [
        ("há um mês", _menos_meses(hoje, 1)),
        ("há 6 meses", _menos_meses(hoje, 6)),
        ("há um ano", _menos_meses(hoje, 12)),
        ("há 2 anos", _menos_meses(hoje, 24)),
    ]
    out = []
    for etiqueta, dia in periodos:
        if dia >= hoje:
            continue
        r = _dia_resumo(db, dia)
        if _tem_conteudo(r):
            r["label"] = etiqueta
            out.append(r)
    return {"today": hoje.isoformat(), "entries": out}


# ── Honestidade estatística ───────────────────────────────────────
# A app dizia "com 7h+ de sono ganhas mais 18pp" — mas isso não passa num teste
# (z=1.2) e vinha de 30 jogos. E dizia que quinta é o dia mais caro, quando essa
# média vinha de uma única compra de 703€ (a mediana da quinta é 7€ contra 5€).
# Antes de afirmar seja o que for, passa por aqui.

def _z_duas_proporcoes(v1: int, n1: int, v2: int, n2: int) -> Optional[float]:
    if n1 < 2 or n2 < 2:
        return None
    p1, p2 = v1 / n1, v2 / n2
    p = (v1 + v2) / (n1 + n2)
    se = (p * (1 - p) * (1 / n1 + 1 / n2)) ** 0.5
    return round((p1 - p2) / se, 2) if se else None


def _mediana_lista(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2




def _sono_vs_winrate(db: Session, limite_h: float = 7.0, dias: int = 180) -> Optional[dict]:
    """Winrate com e sem sono suficiente, com o teste feito. `proven` diz se a
    diferença aguenta um teste de duas proporções a 95%."""
    desde = date.today() - timedelta(days=dias)
    noites = sono.horas_por_dia(db, desde)
    bom = mau = v_bom = v_mau = 0
    for g in db.query(LolGame).filter(LolGame.date >= desde).all():
        h = noites.get(g.date)
        if h is None:
            continue
        if h >= limite_h:
            bom += 1
            v_bom += 1 if g.won else 0
        else:
            mau += 1
            v_mau += 1 if g.won else 0
    if bom < 20 or mau < 20:
        return None
    z = _z_duas_proporcoes(v_bom, bom, v_mau, mau)
    wr_bom = round(v_bom / bom * 100, 1)
    wr_mau = round(v_mau / mau * 100, 1)
    return {
        "limite": limite_h, "n_bom": bom, "n_mau": mau,
        "wr_bom": wr_bom, "wr_mau": wr_mau, "diff": round(wr_bom - wr_mau, 1),
        "z": z, "proven": bool(z is not None and abs(z) >= 1.96),
    }


def _dia_mais_caro(db: Session, dias: int = 180) -> Optional[dict]:
    """Dia da semana com a compra típica mais alta (mediana, não média), e só
    quando a diferença é grande o suficiente para valer a pena dizer."""
    nomes = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    desde = date.today() - timedelta(days=dias)
    por_dia: dict[int, list[float]] = {}
    for e in db.query(Expense).filter(Expense.date >= desde, Expense.kind == ek.GASTO, Expense.extraordinary.is_(False)).all():
        por_dia.setdefault(e.date.weekday(), []).append(e.amount)
    candidatos = {d: v for d, v in por_dia.items() if len(v) >= 8}
    if len(candidatos) < 4:
        return None
    medianas = {d: _mediana_lista(v) for d, v in candidatos.items()}
    pior = max(medianas, key=lambda d: medianas[d])
    resto = [x for d, v in candidatos.items() if d != pior for x in v]
    mediana_resto = _mediana_lista(resto)
    if mediana_resto <= 0 or medianas[pior] < mediana_resto * 1.4:
        return None           # sem diferença que valha a pena mencionar
    return {
        "dia": nomes[pior], "mediana": round(medianas[pior], 2),
        "mediana_resto": round(mediana_resto, 2), "n": len(candidatos[pior]),
    }


# ── Fora do padrão ────────────────────────────────────────────────
# A app já sabe o que é normal para ele (meses de gastos, sono, ecrã, jogos e
# código). Isto avisa quando um dia foge disso, em vez de esperar pelo relatório
# do mês. Usa mediana + desvio absoluto mediano: um único dia doido não estraga
# a régua, ao contrário da média.

def _mediana(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if not n:
        return 0.0
    meio = n // 2
    return s[meio] if n % 2 else (s[meio - 1] + s[meio]) / 2


def _mad(vals: list[float], mediana: float) -> float:
    if not vals:
        return 0.0
    return _mediana([abs(v - mediana) for v in vals])


def _desvio(valor: float, historico: list[float], minimo: int = 8) -> Optional[dict]:
    """Quantas 'medianas de desvio' o valor está fora do normal (z robusto)."""
    if len(historico) < minimo:
        return None
    med = _mediana(historico)
    mad = _mad(historico, med)
    if mad <= 0:
        mad = max(med * 0.15, 0.01)
    z = 0.6745 * (valor - med) / mad
    return {"z": round(z, 2), "median": round(med, 2)}


def _minutos_da_noite(hhmm: Optional[str]) -> Optional[int]:
    """Hora de deitar em minutos, com a madrugada a contar como continuação da noite."""
    if not hhmm or ":" not in str(hhmm):
        return None
    try:
        h, m = str(hhmm)[:5].split(":")
        t = int(h) * 60 + int(m)
    except ValueError:
        return None
    return t + 24 * 60 if t < 12 * 60 else t


@router.get("/anomalies")
def anomalies(
    days: int = Query(14, ge=1, le=60),
    baseline_days: int = Query(120, ge=30, le=730),
    db: Session = Depends(get_db),
):
    hoje = date.today()
    inicio_janela = hoje - timedelta(days=days - 1)
    inicio_base = hoje - timedelta(days=baseline_days - 1)
    saida: list[dict] = []

    def junta(dia: date, key: str, icon: str, titulo: str, texto: str, z: float) -> None:
        saida.append({
            "date": dia.isoformat(),
            "key": key,
            "icon": icon,
            "title": titulo,
            "text": texto,
            "direction": "acima" if z > 0 else "abaixo",
            "score": abs(round(z, 1)),
            "severity": "alta" if abs(z) >= 6 else "media",
        })

    # ── gastos: total do dia ──
    por_dia: dict[date, float] = {}
    por_comerciante: dict[str, list[tuple[float, date]]] = {}
    for e in db.query(Expense).filter(Expense.date >= inicio_base, Expense.kind == ek.GASTO, Expense.extraordinary.is_(False)).all():
        por_dia[e.date] = por_dia.get(e.date, 0) + e.amount
        chave = (e.description or "").strip().lower()[:60]
        por_comerciante.setdefault(chave, []).append((e.amount, e.date))

    base_dias = [v for d, v in por_dia.items() if d < inicio_janela]
    for d, v in sorted(por_dia.items()):
        if d < inicio_janela:
            continue
        r = _desvio(v, base_dias)
        if r and r["z"] >= 3:
            junta(d, "gasto-dia", "💸", "Dia caro",
                  f"€{v:.0f} num dia — o teu dia normal é €{r['median']:.0f}.", r["z"])

    # ── gastos: um sítio específico muito acima do costume ──
    for nome, compras in por_comerciante.items():
        historico = [v for v, d in compras if d < inicio_janela]
        if len(historico) < 4:
            continue
        med = _mediana(historico)
        for v, d in compras:
            if d < inicio_janela or v < 10 or med <= 0:
                continue
            if v / med >= 2.5:
                junta(d, f"gasto-sitio:{nome}", "🏷️", "Gasto fora do normal",
                      f"€{v:.2f} em {nome[:28]} — costumas gastar €{med:.2f}.", v / med)

    # ── sono ──
    noites = sono.noites(db, inicio_base)
    base_horas = [n.hours for n in noites if n.hours and n.date < inicio_janela]
    base_deitar = [m for m in (_minutos_da_noite(n.bedtime) for n in noites if n.date < inicio_janela) if m]
    med_deitar = _mediana(base_deitar) if base_deitar else None
    # A hora de deitar varia todos os dias: a régua tem de sair da própria
    # dispersão dele, senão qualquer noite normal aparecia como fora do padrão.
    for n in noites:
        if n.date < inicio_janela or not n.hours:
            continue
        r = _desvio(n.hours, base_horas)
        if r and abs(r["z"]) >= 3:
            junta(n.date, "sono", "🌙", "Noite fora do padrão",
                  f"{n.hours:.1f}h — costumas dormir {r['median']:.1f}h.", r["z"])
        deitar = _minutos_da_noite(n.bedtime)
        if deitar and 12 * 60 <= deitar < 20 * 60:
            deitar = None                 # sesta ou registo trocado, não é a noite
        rd = _desvio(float(deitar), base_deitar) if deitar else None
        if rd and abs(rd["z"]) >= 3.5 and med_deitar:
            atraso = (deitar - med_deitar) / 60
            if abs(atraso) >= 1.5:
                junta(n.date, "deitar", "🕐", "Deitaste-te fora de horas",
                      f"{n.bedtime} — {abs(atraso):.0f}h {'mais tarde' if atraso > 0 else 'mais cedo'} "
                      f"que o teu normal ({int(med_deitar % (24 * 60)) // 60:02d}:{int(med_deitar) % 60:02d}).",
                      rd["z"])

    # ── ecrã ──
    ecra = {d: seg / 3600 for d, seg in screen_source.por_dia(db, inicio_base, hoje).items()}
    base_ecra = [v for d, v in ecra.items() if d < inicio_janela]
    for d, v in sorted(ecra.items()):
        if d < inicio_janela:
            continue
        r = _desvio(v, base_ecra)
        if r and r["z"] >= 3:
            junta(d, "ecra", "📱", "Dia de muito ecrã",
                  f"{v:.1f}h — o teu dia normal é {r['median']:.1f}h.", r["z"])

    # ── jogos ──
    jogos: dict[date, int] = {}
    for d, n in (
        db.query(LolGame.date, sqlfunc.count(LolGame.id))
        .filter(LolGame.date >= inicio_base).group_by(LolGame.date).all()
    ):
        jogos[d] = n
    base_jogos = [v for d, v in jogos.items() if d < inicio_janela]
    for d, v in sorted(jogos.items()):
        if d < inicio_janela:
            continue
        r = _desvio(float(v), base_jogos)
        if r and r["z"] >= 3:
            junta(d, "jogos", "🎮", "Muitas games",
                  f"{v} games — o teu dia de jogo normal são {r['median']:.0f}.", r["z"])

    # ── código ──
    codigo: dict[date, float] = {}
    for d, s in (
        db.query(WakaProjectDay.day, sqlfunc.sum(WakaProjectDay.seconds))
        .filter(WakaProjectDay.day >= inicio_base, WakaProjectDay.kind == "project")
        .group_by(WakaProjectDay.day).all()
    ):
        codigo[d] = (s or 0) / 3600
    base_codigo = [v for d, v in codigo.items() if d < inicio_janela]
    for d, v in sorted(codigo.items()):
        if d < inicio_janela:
            continue
        r = _desvio(v, base_codigo)
        if r and r["z"] >= 3:
            junta(d, "codigo", "💻", "Dia forte de código",
                  f"{v:.1f}h — o teu dia normal é {r['median']:.1f}h.", r["z"])

    saida.sort(key=lambda a: (a["date"], -a["score"]), reverse=True)
    return {
        "days": days,
        "baseline_days": baseline_days,
        "anomalies": saida[:20],
        "count": len(saida),
    }
