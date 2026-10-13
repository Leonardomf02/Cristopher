from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import date, datetime, time, timedelta
from typing import Optional

import expense_kind as ek
import sono
from database import get_db, SessionLocal
from models import SleepEntry, LolGame, WakaProjectDay, Expense
from schemas import SleepCreate, SleepUpdate, SleepOut

router = APIRouter(prefix="/api/sleep", tags=["Sleep"])


# Limites de sanidade da estimativa automática (o PC desligado ≠ a dormir).
MAX_SLEEP_HOURS = 12.0
MIN_SLEEP_HOURS = 3.0


def _estimate_for_night(reader_mod, prev_day: date, next_day: date) -> Optional[dict]:
    """Estimate sleep for the night between prev_day and next_day, by finding
    the longest inactivity gap in [prev_day 18:00, next_day 12:00].

    bedtime = last activity end + 45min ; wake = first activity start - 30min.
    """
    activity_start = datetime.combine(prev_day, time(12, 0)).timestamp()
    activity_end = datetime.combine(next_day, time(18, 0)).timestamp()
    try:
        sessions = reader_mod.fetch_sessions(activity_start, activity_end, min_seconds=30)
    except Exception:
        return None
    if not sessions:
        return None

    intervals = sorted([(float(s["start_unix"]), float(s["end_unix"])) for s in sessions])
    merged: list[tuple[float, float]] = []
    for st, en in intervals:
        if merged and st <= merged[-1][1] + 60:
            merged[-1] = (merged[-1][0], max(merged[-1][1], en))
        else:
            merged.append((st, en))
    if len(merged) < 2:
        return None

    sleep_win_start = datetime.combine(prev_day, time(18, 0)).timestamp()
    sleep_win_end = datetime.combine(next_day, time(12, 0)).timestamp()

    best: Optional[tuple[float, float, float]] = None
    for i in range(len(merged) - 1):
        gap_start = merged[i][1]
        gap_end = merged[i + 1][0]
        gap = gap_end - gap_start
        if gap < 2 * 3600:
            continue
        ovl_start = max(gap_start, sleep_win_start)
        ovl_end = min(gap_end, sleep_win_end)
        if ovl_end - ovl_start < 3600:
            continue
        if best is None or gap > best[2]:
            best = (gap_start, gap_end, gap)
    if best is None:
        return None

    last_end, first_start, _ = best
    bedtime_ts = last_end + 45 * 60
    waketime_ts = first_start - 30 * 60
    if waketime_ts - bedtime_ts < 2 * 3600:
        return None

    bedtime_dt = datetime.fromtimestamp(bedtime_ts)
    waketime_dt = datetime.fromtimestamp(waketime_ts)
    hours = round((waketime_ts - bedtime_ts) / 3600.0 * 10) / 10
    # O PC desligado não é o mesmo que estar a dormir: sem tecto apareciam noites
    # de 17h. Acima de MAX_SLEEP_HOURS a estimativa é cortada e fica marcada.
    suspect = hours > MAX_SLEEP_HOURS or hours < MIN_SLEEP_HOURS
    if hours > MAX_SLEEP_HOURS:
        hours = MAX_SLEEP_HOURS
    return {
        "bedtime": bedtime_dt.strftime("%H:%M"),
        "wake_time": waketime_dt.strftime("%H:%M"),
        "hours": hours,
        "suspect": suspect,
        "last_activity": datetime.fromtimestamp(last_end).strftime("%Y-%m-%d %H:%M"),
        "first_activity": datetime.fromtimestamp(first_start).strftime("%Y-%m-%d %H:%M"),
        "source": "screen_time",
    }


def _estimate_sleep_from_pc(target_date: date) -> Optional[dict]:
    """Heuristic sleep estimate from local PC activity (knowledgeC.db).

    Tries both possible nights for the given date and picks the one with usable
    activity (a clear 2h+ gap surrounded by activity on both sides):
    - night ENDING on target_date (prev_day = target_date - 1, next_day = target_date)
    - night STARTING on target_date (prev_day = target_date, next_day = target_date + 1)

    Prefers the night that has already fully ended (clearer signal). Returns
    None if neither night has a usable gap.
    """
    try:
        import screen_time_reader as reader
    except ImportError:
        return None
    ok, _ = reader.is_available()
    if not ok:
        return None

    # Tentar a noite que termina em target_date (last night, do ponto de vista
    # de quem acordou hoje). É a mais fiável porque já aconteceu inteira.
    ended = _estimate_for_night(reader, target_date - timedelta(days=1), target_date)
    if ended:
        ended["date"] = target_date.isoformat()
        ended["night_label"] = f"noite de {(target_date - timedelta(days=1)).strftime('%d/%m')} → {target_date.strftime('%d/%m')}"
        return ended

    # Fallback: a noite que começa hoje (só faz sentido se já é manhã do dia seguinte).
    starting = _estimate_for_night(reader, target_date, target_date + timedelta(days=1))
    if starting:
        starting["date"] = target_date.isoformat()
        starting["night_label"] = f"noite de {target_date.strftime('%d/%m')} → {(target_date + timedelta(days=1)).strftime('%d/%m')}"
        return starting

    return None


def auto_register_recent_sleep(days_back: int = 7) -> int:
    """Estima e regista automaticamente o sono das últimas noites a partir do
    uso do PC, criando apenas entradas em falta (source='auto'). Nunca toca em
    entradas existentes (manuais ou já auto-registadas), por isso é seguro
    correr repetidamente. Devolve o número de noites registadas.

    Cada entrada usa SÓ a noite que TERMINA nesse dia (acordar = data da entrada),
    para que cada noite seja atribuída a exactamente um dia (sem duplicados)."""
    try:
        import screen_time_reader as reader
    except ImportError:
        reader = None

    import garmin_sync
    from models import GarminDay

    created = 0
    db = SessionLocal()
    try:
        today = date.today()
        for offset in range(days_back + 1):
            d = today - timedelta(days=offset)
            if db.query(SleepEntry).filter(SleepEntry.date == d).first():
                continue
            # O relógio mediu a noite; o Mac só sabe a que horas parou de ser
            # usado. Havendo medição, o palpite não chega a correr.
            medida = (db.query(GarminDay)
                      .filter(GarminDay.date == d, GarminDay.sleep_hours.isnot(None))
                      .first())
            if medida is not None and garmin_sync.aplica_sono(db, medida):
                created += 1
                continue
            # sem relógio: primeiro o facto (paragem do Mac), depois a estimativa antiga
            est = estimativa_por_paragem(db, d)
            origem = "power"
            if not est and reader is not None and reader.is_available()[0]:
                est = _estimate_for_night(reader, d - timedelta(days=1), d)
                origem = "auto"
            if not est:
                continue
            db.add(SleepEntry(
                date=d,
                bedtime=est["bedtime"],
                wake_time=est["wake_time"],
                hours=est["hours"],
                quality=None,
                notes=est.get("fact") or ("estimativa a confirmar" if est.get("suspect") else ""),
                source=origem,
            ))
            created += 1
        if created:
            db.commit()
    finally:
        db.close()
    return created


@router.post("/auto-register")
def trigger_auto_register(days_back: int = Query(7, ge=1, le=60)):
    """Força um ciclo de auto-registo (usado pelo arranque e opcionalmente pela UI)."""
    return {"created": auto_register_recent_sleep(days_back)}


@router.get("/", response_model=list[SleepOut])
def list_sleep(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(SleepEntry)
    if start_date:
        q = q.filter(SleepEntry.date >= start_date)
    if end_date:
        q = q.filter(SleepEntry.date <= end_date)
    return q.order_by(SleepEntry.date.desc()).all()


@router.get("/stats")
def sleep_stats(
    days: int = Query(30, ge=1, le=36500),
    db: Session = Depends(get_db),
):
    """As médias das noites que o relógio mediu. Uma estimativa pela paragem do
    Mac não tem pontuação nenhuma e não prova ninguém a dormir — não entra."""
    cutoff = date.today() - timedelta(days=days)
    entries = sorted(sono.noites(db, cutoff), key=lambda e: e.date, reverse=True)
    scores = sono.pontuacoes(db, cutoff)

    if not entries:
        return {
            "avg_hours": 0, "avg_score": None, "total_entries": 0,
            "best_day": None, "worst_day": None, "entries": [],
        }

    hours_list = [e.hours for e in entries]
    score_list = [s for s in (scores.get(e.date) for e in entries) if s is not None]

    best = max(entries, key=lambda e: e.hours)
    worst = min(entries, key=lambda e: e.hours)

    return {
        "avg_hours": round(sum(hours_list) / len(hours_list), 1),
        "avg_score": round(sum(score_list) / len(score_list)) if score_list else None,
        "total_entries": len(entries),
        "best_day": {"date": str(best.date), "hours": best.hours},
        "worst_day": {"date": str(worst.date), "hours": worst.hours},
        "entries": [
            {**SleepOut.model_validate(e).model_dump(), "score": scores.get(e.date)}
            for e in entries
        ],
    }


@router.get("/analysis")
def sleep_analysis(days: int = Query(90, ge=14, le=730), db: Session = Depends(get_db)):
    """As noites em conjunto: de que é feita uma noite dele, o que anda junto com
    a pontuação e as noites boas contra as más.

    A conta é a mesma do relógio (`garmin_insights`) — a régua é uma só na app."""
    import garmin_insights
    return garmin_insights.estatisticas_do_sono(db, days)


@router.post("/", response_model=SleepOut)
def create_sleep(data: SleepCreate, db: Session = Depends(get_db)):
    existing = db.query(SleepEntry).filter(SleepEntry.date == data.date).first()
    if existing:
        # Update if entry exists for that date
        for key, value in data.model_dump().items():
            setattr(existing, key, value)
        db.commit()
        db.refresh(existing)
        return existing
    entry = SleepEntry(**data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.put("/{entry_id}", response_model=SleepOut)
def update_sleep(entry_id: int, data: SleepUpdate, db: Session = Depends(get_db)):
    entry = db.query(SleepEntry).filter(SleepEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Sleep entry not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entry, key, value)
    entry.source = "manual"  # editado pelo utilizador deixa de ser auto
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_sleep(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(SleepEntry).filter(SleepEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Sleep entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


@router.get("/estimate")
def estimate_sleep(target_date: Optional[date] = Query(None, alias="date")):
    """Estimate sleep hours for the night following `date` based on PC activity."""
    d = target_date or (date.today() - timedelta(days=1))
    est = _estimate_sleep_from_pc(d)
    if not est:
        raise HTTPException(
            status_code=404,
            detail="Sem actividade no PC suficiente para estimar o sono dessa noite.",
        )
    return est


# ── Estimativas duvidosas ────────────────────────────────────────

@router.get("/suspect")
def suspect_entries(days: int = Query(60, ge=1, le=365), db: Session = Depends(get_db)):
    """Noites automáticas fora do plausível (ou marcadas na altura) — para confirmar."""
    since = date.today() - timedelta(days=days)
    rows = (
        db.query(SleepEntry)
        .filter(SleepEntry.date >= since, SleepEntry.source == "auto")
        .order_by(SleepEntry.date.desc())
        .all()
    )
    out = []
    for e in rows:
        marcada = (e.notes or "").startswith("estimativa a confirmar")
        fora = e.hours is not None and (e.hours >= MAX_SLEEP_HOURS or e.hours < MIN_SLEEP_HOURS)
        if marcada or fora:
            out.append({
                "id": e.id,
                "date": str(e.date),
                "hours": e.hours,
                "bedtime": e.bedtime,
                "wake_time": e.wake_time,
                "reason": "demasiadas horas" if (e.hours or 0) >= MAX_SLEEP_HOURS else
                          "poucas horas" if (e.hours or 0) < MIN_SLEEP_HOURS else "estimativa incerta",
            })
    return out


@router.post("/{entry_id}/confirm")
def confirm_entry(entry_id: int, db: Session = Depends(get_db)):
    """Confirma uma estimativa: passa a contar como registo meu."""
    e = db.query(SleepEntry).filter(SleepEntry.id == entry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Entrada não encontrada")
    e.source = "manual"
    if (e.notes or "").startswith("estimativa a confirmar"):
        e.notes = ""
    db.commit()
    db.refresh(e)
    return e

# ── Ritmo (cronotipo) ─────────────────────────────────────────────
# "Horas dormidas" esconde o essencial: ele deita-se sempre de madrugada e o que
# muda de semana para semana é a hora, não a duração. Isto mostra o relógio dele
# e o que acontece no dia seguinte conforme a hora a que se deitou.

def _minutos(hhmm: Optional[str]) -> Optional[int]:
    if not hhmm or ":" not in str(hhmm):
        return None
    try:
        h, m = str(hhmm)[:5].split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _deitar_continuo(hhmm: Optional[str]) -> Optional[int]:
    """Hora de deitar em minutos, com a madrugada como continuação do dia anterior
    (02:30 → 26h30). Sem isto, a média de 23h50 com 00h10 dava meio-dia."""
    m = _minutos(hhmm)
    if m is None:
        return None
    return m + 24 * 60 if m < 12 * 60 else m


def _hhmm(minutos: float) -> str:
    m = int(round(minutos)) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def _mediana(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


@router.get("/rhythm")
def rhythm(days: int = Query(120, ge=21, le=730), db: Session = Depends(get_db)):
    """O relógio dele, só com as noites que o relógio de pulso mediu.

    Antes entrava aqui o palpite do Mac, e ele trazia sestas e noites impossíveis
    que era preciso marcar como "estranhas" e deixar de fora das medianas. Sendo
    tudo medido, não há nada a excluir: cada noite é uma noite."""
    fim = date.today()
    inicio = fim - timedelta(days=days - 1)
    pontuacoes = sono.pontuacoes(db, inicio, fim)

    pontos = []
    for n in sono.noites(db, inicio, fim):
        deitar = _deitar_continuo(n.bedtime)
        acordar = _minutos(n.wake_time)
        if deitar is None and acordar is None and not n.hours:
            continue
        pontos.append({
            "date": n.date.isoformat(),
            "weekday": n.date.weekday(),
            "bedtime": n.bedtime,
            "wake_time": n.wake_time,
            "bed_min": deitar,
            "wake_min": acordar,
            "hours": round(n.hours, 2) if n.hours else None,
            "score": pontuacoes.get(n.date),
        })

    deitares = [p["bed_min"] for p in pontos if p["bed_min"] is not None]
    acordares = [p["wake_min"] for p in pontos if p["wake_min"] is not None]
    horas = [p["hours"] for p in pontos if p["hours"]]

    def desvio_medio(vals: list[float], centro: float) -> float:
        return round(sum(abs(v - centro) for v in vals) / len(vals) / 60, 2) if vals else 0.0

    med_deitar = _mediana(deitares) if deitares else None
    med_acordar = _mediana(acordares) if acordares else None

    # semana vs fim-de-semana (noite de sexta e sábado = fim-de-semana)
    fds = [p["bed_min"] for p in pontos if p["bed_min"] is not None and p["weekday"] in (5, 6)]
    semana = [p["bed_min"] for p in pontos if p["bed_min"] is not None and p["weekday"] not in (5, 6)]
    jetlag = None
    if fds and semana:
        jetlag = round((_mediana(fds) - _mediana(semana)) / 60, 1)

    # deriva: mediana da hora de deitar semana a semana
    por_semana: dict[str, list[int]] = {}
    for p in pontos:
        if p["bed_min"] is None:
            continue
        d = date.fromisoformat(p["date"])
        chave = (d - timedelta(days=d.weekday())).isoformat()
        por_semana.setdefault(chave, []).append(p["bed_min"])
    semanas = [
        {"week": k, "bedtime": _hhmm(_mediana(v)), "bed_min": round(_mediana(v)), "nights": len(v)}
        for k, v in sorted(por_semana.items())
    ]

    # o que acontece no dia seguinte conforme a hora a que se deitou
    cedo, tarde = [], []
    if med_deitar:
        for p in pontos:
            if p["bed_min"] is None:
                continue
            (cedo if p["bed_min"] <= med_deitar else tarde).append(date.fromisoformat(p["date"]))

    def dia_seguinte(dias: list[date]) -> dict:
        if not dias:
            return {"days": 0}
        jogos = db.query(LolGame).filter(LolGame.date.in_(dias)).all()
        codigo = (
            db.query(func.coalesce(func.sum(WakaProjectDay.seconds), 0))
            .filter(WakaProjectDay.day.in_(dias), WakaProjectDay.kind == "project").scalar()
        ) or 0
        gasto = (
            db.query(func.coalesce(func.sum(Expense.amount), 0))
            .filter(Expense.date.in_(dias), Expense.kind == ek.GASTO, Expense.extraordinary.is_(False)).scalar()
        ) or 0
        vitorias = sum(1 for g in jogos if g.won)
        return {
            "days": len(dias),
            "winrate": round(vitorias / len(jogos) * 100, 1) if jogos else None,
            "games": len(jogos),
            "code_hours": round(codigo / 3600 / len(dias), 2),
            "spend": round(float(gasto) / len(dias), 2),
        }

    return {
        "days": days,
        "nights": len(pontos),
        "points": pontos,
        "weeks": semanas,
        "median_bedtime": _hhmm(med_deitar) if med_deitar is not None else None,
        "median_wake": _hhmm(med_acordar) if med_acordar is not None else None,
        "median_hours": round(_mediana(horas), 2) if horas else None,
        "bed_variation_h": desvio_medio(deitares, med_deitar) if med_deitar else 0.0,
        "wake_variation_h": desvio_medio(acordares, med_acordar) if med_acordar else 0.0,
        "weekend_shift_h": jetlag,
        "early": dia_seguinte(cedo),
        "late": dia_seguinte(tarde),
    }

# ── Sono a partir do que a máquina sabe ───────────────────────────
# Metade dos registos manuais foi escrita ANTES da noite acontecer (o de 30/07
# dizia 02:30→11:00 e foi escrito às 23:09 do dia anterior) e os automáticos
# vinham de uma leitura aproximada da Apple. As paragens do Mac são factos: a
# máquina parou às 07:15 e voltou às 11:07.

def _paragens(db: Session, inicio: datetime, fim: datetime) -> list:
    from models import PowerEvent
    return (
        db.query(PowerEvent)
        .filter(PowerEvent.woke_at >= inicio, PowerEvent.slept_at <= fim)
        .order_by(PowerEvent.slept_at)
        .all()
    )


def estimativa_por_paragem(db: Session, dia: date) -> Optional[dict]:
    """A noite que acaba em `dia`, a partir da maior paragem do Mac.

    A janela vai das 18h da véspera às 16h do dia: quem se deita às 3h e acorda
    ao meio-dia não cabe numa janela "normal" de noite."""
    inicio = datetime.combine(dia - timedelta(days=1), time(18, 0))
    fim = datetime.combine(dia, time(16, 0))
    candidatas = [p for p in _paragens(db, inicio, fim) if p.minutes >= MIN_SLEEP_HOURS * 60]
    if not candidatas:
        return None
    melhor = max(candidatas, key=lambda p: p.minutes)

    horas = round(melhor.minutes / 60, 1)
    cortado = horas > MAX_SLEEP_HOURS
    return {
        "date": dia.isoformat(),
        "bedtime": melhor.slept_at.strftime("%H:%M"),
        "wake_time": melhor.woke_at.strftime("%H:%M"),
        "hours": min(horas, MAX_SLEEP_HOURS),
        "suspect": cortado or horas < MIN_SLEEP_HOURS,
        "source": "power",
        "confidence": "alta" if melhor.source == "pmset" else "media",
        "fact": f"o Mac esteve parado das {melhor.slept_at.strftime('%H:%M')} às {melhor.woke_at.strftime('%H:%M')}",
        "note": "estimado pela paragem do computador" + (" (cortado no máximo)" if cortado else ""),
    }


@router.get("/estimate-v2")
def estimate_v2(target: Optional[date] = Query(None, alias="date"), db: Session = Depends(get_db)):
    """Estimativa nova (paragem do Mac), com a antiga como recurso."""
    d = target or date.today()
    pela_maquina = estimativa_por_paragem(db, d)
    if pela_maquina:
        return pela_maquina
    antiga = _estimate_sleep_from_pc(d)
    if antiga:
        antiga["confidence"] = "baixa"
        antiga["note"] = "estimado pelo Screen Time da Apple (menos fiável)"
        return antiga
    return {"date": d.isoformat(), "source": None, "confidence": "nenhuma",
            "note": "sem dados para estimar esta noite"}


@router.get("/power-events")
def power_events(days: int = Query(14, ge=1, le=120), db: Session = Depends(get_db)):
    """As paragens do Mac, que são a matéria-prima da estimativa de sono."""
    inicio = datetime.combine(date.today() - timedelta(days=days - 1), time(0, 0))
    linhas = _paragens(db, inicio, datetime.now() + timedelta(days=1))
    return [
        {"slept_at": p.slept_at.isoformat(), "woke_at": p.woke_at.isoformat(),
         "minutes": p.minutes, "hours": round(p.minutes / 60, 1),
         "source": p.source, "detail": p.detail}
        for p in reversed(linhas)
    ]


@router.post("/reconcile")
def reconcile(days: int = Query(14, ge=1, le=180), apply: bool = Query(False),
              db: Session = Depends(get_db)):
    """Compara o que está registado com o que a máquina diz, e (com apply=true)
    corrige as noites em que a app está claramente errada.

    Só mexe onde a diferença é grande (>1h30) e onde há um facto para pôr no
    lugar — o que ele escreveu à mão fica, se estiver perto da realidade."""
    hoje = date.today()
    mudancas = []
    for i in range(days):
        d = hoje - timedelta(days=i)
        est = estimativa_por_paragem(db, d)
        if not est:
            continue
        entrada = db.query(SleepEntry).filter(SleepEntry.date == d).order_by(SleepEntry.id.desc()).first()
        if entrada is not None and entrada.source == "garmin":
            continue          # a paragem do Mac não corrige uma noite medida no pulso
        if not entrada:
            mudancas.append({"date": d.isoformat(), "acao": "criar", "novo": est, "antigo": None})
            if apply:
                db.add(SleepEntry(date=d, bedtime=est["bedtime"], wake_time=est["wake_time"],
                                  hours=est["hours"], source="power",
                                  notes=est["fact"]))
            continue
        diferenca = abs((entrada.hours or 0) - est["hours"])
        if diferenca < 1.5:
            continue
        mudancas.append({
            "date": d.isoformat(), "acao": "corrigir", "diferenca_h": round(diferenca, 1),
            "antigo": {"bedtime": entrada.bedtime, "wake_time": entrada.wake_time,
                       "hours": entrada.hours, "source": entrada.source},
            "novo": est,
        })
        if apply:
            entrada.bedtime = est["bedtime"]
            entrada.wake_time = est["wake_time"]
            entrada.hours = est["hours"]
            entrada.source = "power"
            entrada.notes = est["fact"]
    if apply:
        db.commit()
    return {"days": days, "applied": apply, "changes": mudancas}
