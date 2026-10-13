"""Endpoints para o Screen Time da Apple.

Lê o knowledgeC.db do macOS via screen_time_reader. Na prática **só traz este
Mac**: as sessões todas vêm com `device_id = '__local__'`. O leitor sabe separar
por dispositivo, mas os dados do iPhone/iPad só chegam ao knowledgeC se
"Partilhar entre dispositivos" estiver ligado no Screen Time da Apple — e, nas
versões recentes do iOS, nem sempre chegam sequer assim.
"""
from __future__ import annotations

import platform
import subprocess
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from pydantic import BaseModel
from sqlalchemy import func
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from models import ScreenTimeGoal, ScreenTimeDeviceLabel, ScreenTimeDailyApp
import screen_source
import screen_time_reader as reader
from app_icons import get_icon_png_path

router = APIRouter(prefix="/api/screen-time", tags=["Screen Time"])


def _day_to_unix_range(d: date) -> tuple[float, float]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
    end = start + 86400
    return start, end


def _range_to_unix(start_date: Optional[str], end_date: Optional[str]) -> tuple[float, float]:
    if start_date:
        sd = date.fromisoformat(start_date)
    else:
        sd = date.today() - timedelta(days=7)
    if end_date:
        ed = date.fromisoformat(end_date)
    else:
        ed = date.today()
    start_unix, _ = _day_to_unix_range(sd)
    _, end_unix = _day_to_unix_range(ed)
    return start_unix, end_unix


def _labels_map(db: Session) -> dict[str, dict]:
    rows = db.query(ScreenTimeDeviceLabel).all()
    return {
        r.device_id: {"label": r.label, "kind": r.kind}
        for r in rows
    }


def _attach_label(item: dict, labels: dict[str, dict]) -> dict:
    info = labels.get(item.get("device_id", ""), {})
    item["label"] = info.get("label", "")
    item["kind"] = info.get("kind", "unknown")
    return item


def snapshot_screen_time(days_back: int = 45) -> int:
    """Lê o knowledgeC e persiste agregados diários por app (modo 'apple') na
    tabela screen_time_daily_apps. Só sobrescreve um dia quando o knowledgeC
    ainda tem dados desse dia — dias que já saíram do knowledgeC mantêm o último
    snapshot guardado. Devolve o número de dias actualizados.

    É assim que ganhamos histórico de longo prazo: a Apple só guarda ~4 semanas."""
    ok, _ = reader.is_available()
    if not ok:
        return 0
    days_written = 0
    db = SessionLocal()
    try:
        today = date.today()
        for offset in range(days_back + 1):
            d = today - timedelta(days=offset)
            start_unix, end_unix = _day_to_unix_range(d)
            try:
                rows = reader.summary_by_app(start_unix, end_unix, mode="apple")
            except Exception:
                continue
            rows = [r for r in rows if (r.get("total_seconds") or 0) > 0]
            if not rows:
                continue  # sem dados no knowledgeC → preserva snapshot anterior
            db.query(ScreenTimeDailyApp).filter(ScreenTimeDailyApp.date == d).delete()
            for r in rows:
                db.add(ScreenTimeDailyApp(
                    date=d,
                    device_id=r.get("device_id", "__local__"),
                    bundle_id=r.get("bundle_id", "(unknown)"),
                    category=r.get("category", "") or "",
                    seconds=int(round(r.get("total_seconds") or 0)),
                ))
            days_written += 1
        db.commit()
    finally:
        db.close()
    return days_written


@router.get("/health")
def health():
    """Diz se a DB do Screen Time está acessível ao backend.

    Inclui o caminho do binário Python responsável (útil quando o utilizador
    precisa de dar FDA directamente à Python.framework como fallback).

    Na NAS o knowledgeC não existe e não tem de existir: as horas medidas chegam
    pelo agente do Mac. A página abre na mesma, só sem a leitura da Apple
    (`apple_local`), que precisa do ficheiro."""
    import os
    if os.getenv("CLOUD") == "1":
        return {"available": True, "apple_local": False, "reason": "", "db_path": "",
                "python_app_path": ""}
    ok, reason = reader.is_available()
    python_app_path = ""
    if platform.system() == "Darwin":
        import sys
        from pathlib import Path
        candidates = [
            Path(sys.exec_prefix) / "Resources" / "Python.app",
            Path("/Library/Frameworks/Python.framework/Versions") / f"{sys.version_info.major}.{sys.version_info.minor}" / "Resources" / "Python.app",
        ]
        for c in candidates:
            if c.exists():
                python_app_path = str(c)
                break
    return {
        "available": ok,
        "apple_local": ok,
        "reason": reason,
        "db_path": str(reader.KNOWLEDGE_DB),
        "python_app_path": python_app_path,
    }


@router.get("/app-icon")
def app_icon(bundle_id: str):
    """Devolve o PNG do ícone da app pelo bundle_id (extraído de /Applications).

    Cacheado em disco em uploads/app_icons. 404 se a app não estiver instalada
    localmente ou se o .icns não for extraível.
    """
    path = get_icon_png_path(bundle_id)
    if not path:
        return Response(status_code=404)
    # Cache forte: ícones quase nunca mudam — 1 dia
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/open-settings")
def open_fda_settings():
    """Abre System Settings → Privacy & Security → Full Disk Access (só macOS)."""
    if platform.system() != "Darwin":
        raise HTTPException(400, "Só funciona em macOS")
    url = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
    try:
        subprocess.Popen(["open", url])
    except Exception as e:
        raise HTTPException(500, f"Falhou: {e}")
    return {"opened": True}


@router.get("/devices")
def list_devices(db: Session = Depends(get_db)):
    """Devices distintos vistos no Screen Time + label humana se existir."""
    try:
        items = reader.list_devices()
    except reader.ScreenTimeUnavailable as e:
        raise HTTPException(503, str(e))
    labels = _labels_map(db)
    return [_attach_label(it, labels) for it in items]


@router.put("/devices/{device_id}")
def label_device(
    device_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Guarda etiqueta humana ('iPhone do Cris', kind=iphone) para um device_id."""
    label = (payload.get("label") or "").strip()
    kind = (payload.get("kind") or "unknown").strip()
    if kind not in ("mac", "iphone", "ipad", "watch", "unknown"):
        raise HTTPException(400, "kind inválido")
    row = db.query(ScreenTimeDeviceLabel).filter_by(device_id=device_id).first()
    if row is None:
        row = ScreenTimeDeviceLabel(device_id=device_id, label=label, kind=kind)
        db.add(row)
    else:
        row.label = label
        row.kind = kind
    db.commit()
    db.refresh(row)
    return {"device_id": row.device_id, "label": row.label, "kind": row.kind}


def _range_to_dates(start_date: Optional[str], end_date: Optional[str]) -> tuple[date, date]:
    fim = date.fromisoformat(end_date) if end_date else date.today()
    ini = date.fromisoformat(start_date) if start_date else fim - timedelta(days=6)
    return ini, fim


@router.get("/by-app")
def by_app(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    device_id: Optional[str] = None,
    mode: str = Query("raw", pattern="^(raw|apple)$"),
    source: str = Query("tracker", pattern="^(tracker|apple)$"),
    weekday: Optional[int] = Query(None, ge=0, le=6, description="0 = segunda"),
    category: Optional[str] = Query(None, description="categoria no vocabulário da Apple"),
    db: Session = Depends(get_db),
):
    """Agregado por app + device. Default: últimos 7 dias.

    `source=tracker` (omissão) usa o tracker próprio — é a fonte que bate certo
    com a duração real dos jogos. `source=apple` mantém a leitura do knowledgeC,
    que é a única que vê outros dispositivos.
    """
    if source == "tracker" and not device_id:
        ini, fim = _range_to_dates(start_date, end_date)
        return [
            {"bundle_id": r["bundle_id"], "app_name": r["app_name"], "category": r["category"],
             "total_seconds": r["seconds"], "session_count": r["sessions"],
             "device_id": "__local__", "label": "Mac", "kind": "mac"}
            for r in screen_source.por_app(db, ini, fim,
                                            dia_da_semana=weekday, categoria=category)
        ]
    try:
        s, e = _range_to_unix(start_date, end_date)
        items = reader.summary_by_app(s, e, device_id=device_id, mode=mode)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))
    labels = _labels_map(db)
    return [_attach_label(it, labels) for it in items]


@router.get("/by-category")
def by_category(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    device_id: Optional[str] = None,
    mode: str = Query("raw", pattern="^(raw|apple)$"),
    source: str = Query("tracker", pattern="^(tracker|apple)$"),
    db: Session = Depends(get_db),
):
    """Agregado por categoria. Por omissão vem do tracker (ver `/by-app`)."""
    if source == "tracker" and not device_id:
        ini, fim = _range_to_dates(start_date, end_date)
        totais = screen_source.por_categoria(db, ini, fim)
        return [{"category": c, "total_seconds": seg} for c, seg in
                sorted(totais.items(), key=lambda kv: -kv[1])]
    try:
        s, e = _range_to_unix(start_date, end_date)
        return reader.summary_by_category(s, e, device_id=device_id, mode=mode)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))


@router.get("/by-hour")
def by_hour(
    category: str = Query(...),
    days: int = Query(30, ge=7, le=90),
    db: Session = Depends(get_db),
):
    """A que horas do dia se usa esta categoria, somado nos últimos N dias —
    para a aba de um hábito associado a ela (ver habits.py). Soma bruta, não
    média: o histograma normaliza pelo máximo, não pela escala absoluta."""
    fim = date.today()
    inicio = fim - timedelta(days=days - 1)
    por_hora = screen_source.por_hora_e_categoria(db, inicio, fim)
    return {"hours": [por_hora[h].get(category, 0) for h in range(24)], "window_days": days}


@router.get("/by-device")
def by_device(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    mode: str = Query("raw", pattern="^(raw|apple)$"),
    source: str = Query("apple", pattern="^(tracker|apple)$"),
    db: Session = Depends(get_db),
):
    """Total agregado por device no intervalo. Default: últimos 7 dias.

    Com `source=tracker` é o total do tracker (só existe o Mac): é o número por
    cima da lista das apps, e vindo do knowledgeC discordava dela."""
    if source == "tracker":
        ini, fim = _range_to_dates(start_date, end_date)
        apps = screen_source.por_app(db, ini, fim)
        segundos = sum(a["seconds"] for a in apps)
        if not segundos:
            return []
        return [{"device_id": "__local__", "total_seconds": segundos,
                 "session_count": sum(a["sessions"] for a in apps), "app_count": len(apps),
                 "label": "Mac", "kind": "mac"}]
    try:
        s, e = _range_to_unix(start_date, end_date)
        items = reader.summary_by_device(s, e, mode=mode)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))
    labels = _labels_map(db)
    return [_attach_label(it, labels) for it in items]


@router.get("/timeseries")
def timeseries(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    bucket: str = Query("hour", pattern="^(hour|day)$"),
    device_id: Optional[str] = None,
    mode: str = Query("raw", pattern="^(raw|apple)$"),
):
    """Soma por hora ou por dia. Default: últimos 7 dias por dia."""
    try:
        s, e = _range_to_unix(start_date, end_date)
        items = reader.summary_timeseries(s, e, bucket=bucket, device_id=device_id, mode=mode)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))
    return items


def _stacked_do_tracker(db: Session, ini: date, fim: date, bucket: str) -> list[dict]:
    """O mesmo gráfico empilhado, mas com as sessões medidas pela app. Uma sessão
    que atravessa a hora é repartida pelos buckets que toca."""
    from models import AppUsageSession
    from routers.app_usage import _resolve_category

    passo = 3600 if bucket == "hour" else 86400
    baldes: dict[int, dict[str, float]] = {}
    sessoes = (
        db.query(AppUsageSession)
        .filter(AppUsageSession.date >= ini, AppUsageSession.date <= fim)
        .all()
    )
    for s in sessoes:
        if not s.start_time or not s.end_time:
            continue
        cat = screen_source.para_apple(_resolve_category(db, s))
        ini_ts, fim_ts = s.start_time.timestamp(), s.end_time.timestamp()
        t = ini_ts - (ini_ts % passo)
        while t < fim_ts:
            fatia = min(t + passo, fim_ts) - max(t, ini_ts)
            if fatia > 0:
                baldes.setdefault(int(t), {})[cat] = baldes.setdefault(int(t), {}).get(cat, 0) + fatia
            t += passo
    return [
        {"bucket_start": ts, "categories": {c: round(v) for c, v in cats.items()}}
        for ts, cats in sorted(baldes.items())
    ]


@router.get("/timeseries-stacked")
def timeseries_stacked(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    bucket: str = Query("hour", pattern="^(hour|day)$"),
    device_id: Optional[str] = None,
    mode: str = Query("raw", pattern="^(raw|apple)$"),
    source: str = Query("tracker", pattern="^(tracker|apple)$"),
    db: Session = Depends(get_db),
):
    """Soma por bucket E por categoria (gráfico empilhado)."""
    if source == "tracker" and not device_id:
        ini, fim = _range_to_dates(start_date, end_date)
        return _stacked_do_tracker(db, ini, fim, bucket)
    try:
        s, e = _range_to_unix(start_date, end_date)
        return reader.timeseries_stacked_by_category(s, e, bucket=bucket, device_id=device_id, mode=mode)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))


@router.get("/sessions")
def sessions(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    device_id: Optional[str] = None,
    min_seconds: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db),
):
    """Sessões raw, mais recentes primeiro. Útil para debug/verificação."""
    try:
        s, e = _range_to_unix(start_date, end_date)
        items = reader.fetch_sessions(s, e, device_id=device_id, min_seconds=min_seconds)
    except reader.ScreenTimeUnavailable as ex:
        raise HTTPException(503, str(ex))
    return items[:limit]


@router.post("/snapshot")
def trigger_snapshot(days_back: int = Query(45, ge=1, le=730)):
    """Força um snapshot dos agregados diários (arranque chama isto periodicamente)."""
    return {"days_written": snapshot_screen_time(days_back)}


@router.get("/insights")
def insights(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    bucket: str = Query("day"),
    db: Session = Depends(get_db),
):
    """Estatísticas a partir dos snapshots diários guardados (histórico longo).

    Período em [start_date, end_date] (omitir start = desde o 1º dia guardado).
    bucket='day' → série por dia; bucket='month' → série por mês (períodos longos).
    """
    all_rows = db.query(ScreenTimeDailyApp).all()
    all_dates = {r.date for r in all_rows}
    tracked_days = len(all_dates)
    total_all = sum(r.seconds for r in all_rows)

    today = date.today()
    end = date.fromisoformat(end_date) if end_date else today
    if start_date:
        start = date.fromisoformat(start_date)
    elif all_dates:
        start = min(all_dates)
    else:
        start = end
    if start > end:
        start = end

    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)

    period = [r for r in all_rows if start <= r.date <= end]
    prev = [r for r in all_rows if prev_start <= r.date <= prev_end]

    by_day: dict[date, int] = defaultdict(int)
    for r in period:
        by_day[r.date] += r.seconds

    if bucket == "month":
        by_month: dict[str, int] = defaultdict(int)
        for d_, sec in by_day.items():
            by_month[d_.strftime("%Y-%m")] += sec
        timeseries = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            key = f"{y:04d}-{m:02d}"
            timeseries.append({"date": key, "seconds": by_month.get(key, 0)})
            m += 1
            if m > 12:
                m, y = 1, y + 1
    else:
        timeseries = [
            {"date": (start + timedelta(days=i)).isoformat(), "seconds": by_day.get(start + timedelta(days=i), 0)}
            for i in range(span)
        ]
    total_period = sum(by_day.values())
    tracked_in_period = len(by_day)
    daily_avg = round(total_period / tracked_in_period) if tracked_in_period else 0
    total_prev = sum(r.seconds for r in prev)
    delta_pct = round((total_period - total_prev) / total_prev * 100) if total_prev else None

    busiest = max(by_day.items(), key=lambda kv: kv[1], default=None)
    quietest = min(by_day.items(), key=lambda kv: kv[1], default=None)

    by_app: dict[str, dict] = defaultdict(lambda: {"seconds": 0, "category": ""})
    for r in period:
        e = by_app[r.bundle_id]
        e["seconds"] += r.seconds
        if r.category:
            e["category"] = r.category
    top_apps = sorted(
        ({"bundle_id": k, "seconds": v["seconds"], "category": v["category"]} for k, v in by_app.items()),
        key=lambda x: x["seconds"], reverse=True,
    )[:12]

    by_cat: dict[str, int] = defaultdict(int)
    for r in period:
        by_cat[r.category or "Other"] += r.seconds
    by_category = sorted(
        ({"category": k, "seconds": v} for k, v in by_cat.items()),
        key=lambda x: x["seconds"], reverse=True,
    )

    wd_total: dict[int, int] = defaultdict(int)
    wd_days: dict[int, set] = defaultdict(set)
    for d_, sec in by_day.items():
        wd_total[d_.weekday()] += sec
        wd_days[d_.weekday()].add(d_)
    by_weekday = [
        {"weekday": wd, "avg_seconds": round(wd_total[wd] / len(wd_days[wd])) if wd_days[wd] else 0}
        for wd in range(7)
    ]

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "bucket": bucket,
        "tracked_days": tracked_days,
        "first_date": min(all_dates).isoformat() if all_dates else None,
        "last_date": max(all_dates).isoformat() if all_dates else None,
        "total_all_seconds": total_all,
        "total_period_seconds": total_period,
        "daily_avg_seconds": daily_avg,
        "total_prev_seconds": total_prev,
        "delta_pct": delta_pct,
        "busiest_day": {"date": busiest[0].isoformat(), "seconds": busiest[1]} if busiest else None,
        "quietest_day": {"date": quietest[0].isoformat(), "seconds": quietest[1]} if quietest else None,
        "timeseries": timeseries,
        "top_apps": top_apps,
        "by_category": by_category,
        "by_weekday": by_weekday,
    }


# ── Metas de ecrã por categoria ────────────────────────────────────
#
# Uma meta é sempre um alvo de horas **por dia** (5h/dia de Productivity &
# Finance). Dia, semana e mês não são três metas diferentes — são três formas
# de ver o mesmo progresso: a vista semana/mês multiplica o alvo diário pelos
# dias que `days` deixa contar dentro desse período, e soma o uso real desses
# dias. Pode ter um hábito associado, que se marca sozinho quando o alvo do
# DIA é cumprido — ver `checar_metas_diarias`, chamada pelo agendador.

class GoalIn(BaseModel):
    category: str
    target_hours: float  # por dia
    days: str = "daily"  # daily | weekdays | "0,2,4" (Seg=0)
    habit_id: Optional[int] = None


def _dia_conta(days: str, weekday: int) -> bool:
    """Este dia da semana conta para a meta? (0 = segunda)"""
    if days == "daily":
        return True
    if days == "weekdays":
        return weekday < 5
    try:
        return weekday in {int(d.strip()) for d in days.split(",") if d.strip() != ""}
    except ValueError:
        return True


def _periodo(period: str, hoje: date) -> tuple[date, date]:
    if period == "week":
        inicio = hoje - timedelta(days=hoje.weekday())
        return inicio, inicio + timedelta(days=6)
    if period == "month":
        inicio = hoje.replace(day=1)
        fim = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return inicio, fim
    return hoje, hoje


def _vista(db: Session, categoria: str, dias_filtro: str, target_hours: float, period: str, hoje: date) -> dict:
    """Progresso desta meta vista a um ritmo (dia/semana/mês): soma o uso real
    dos dias que contam dentro do período, e o alvo é o diário × esses mesmos
    dias — não o período inteiro, senão um fim-de-semana de dias úteis dava
    metade do alvo por nada."""
    inicio, fim = _periodo(period, hoje)
    if period == "day":
        dias_com_conta = 1 if _dia_conta(dias_filtro, hoje.weekday()) else 0
        segundos = screen_source.por_categoria(db, inicio, fim).get(categoria, 0) if dias_com_conta else 0
    else:
        por_dia = screen_source.por_dia_e_categoria(db, inicio, fim)
        dias_com_conta = sum(
            1 for i in range((fim - inicio).days + 1)
            if _dia_conta(dias_filtro, (inicio + timedelta(days=i)).weekday())
        )
        segundos = sum(
            dados.get(categoria, 0) for d, dados in por_dia.items()
            if _dia_conta(dias_filtro, d.weekday())
        )
    alvo_seg = target_hours * 3600 * dias_com_conta
    return {
        "used_seconds": segundos,
        "target_seconds": alvo_seg,
        "pct": round(segundos / alvo_seg * 100) if alvo_seg else None,
        "remaining_seconds": max(0, int(alvo_seg - segundos)),
        "reached": alvo_seg > 0 and segundos >= alvo_seg,
        "period_start": str(inicio),
        "period_end": str(fim),
    }


@router.get("/goals")
def list_goals(db: Session = Depends(get_db)):
    from models import Habit
    goals = db.query(ScreenTimeGoal).order_by(ScreenTimeGoal.category).all()
    habits = {h.id: h for h in db.query(Habit).all()}
    return [
        {
            "id": g.id, "category": g.category, "target_hours": g.target_hours,
            "days": g.days, "active": g.active, "habit_id": g.habit_id,
            "habit_name": habits[g.habit_id].name if g.habit_id in habits else None,
            "habit_icon": habits[g.habit_id].icon if g.habit_id in habits else None,
        }
        for g in goals
    ]


@router.put("/goals")
def upsert_goal(data: GoalIn, db: Session = Depends(get_db)):
    row = db.query(ScreenTimeGoal).filter(ScreenTimeGoal.category == data.category).first()
    if data.target_hours <= 0:
        if row:
            db.delete(row)
            db.commit()
        return {"removed": True, "category": data.category}
    if not row:
        row = ScreenTimeGoal(category=data.category)
        db.add(row)
    row.target_hours = data.target_hours
    row.days = data.days or "daily"
    row.habit_id = data.habit_id
    row.active = True
    db.commit()
    db.refresh(row)
    return row


@router.get("/goals/status")
def goals_status(ref_date: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Devolve as três vistas (dia/semana/mês) de cada meta de uma vez — o
    frontend troca de vista sem pedir nada de novo ao servidor. `ref_date`
    ancora as três noutro dia (ex: Julho passado); sem ele fica em hoje. O
    hábito (marcado/por marcar) é sempre do dia real, não do `ref_date` — não
    faz sentido perguntar se o hábito "está marcado" num mês antigo."""
    from models import Habit, HabitCompletion
    hoje = date.today()
    ref = date.fromisoformat(ref_date) if ref_date else hoje
    goals = db.query(ScreenTimeGoal).filter(ScreenTimeGoal.active == True).order_by(ScreenTimeGoal.category).all()
    habits = {h.id: h for h in db.query(Habit).all()}
    feitos_hoje = {c.habit_id for c in db.query(HabitCompletion).filter(HabitCompletion.date == hoje).all()}

    out = []
    for g in goals:
        habit = habits.get(g.habit_id) if g.habit_id else None
        out.append({
            "category": g.category,
            "target_hours": g.target_hours,
            "days": g.days,
            "scheduled_today": _dia_conta(g.days, hoje.weekday()),
            "views": {p: _vista(db, g.category, g.days, g.target_hours, p, ref) for p in ("day", "week", "month")},
            "habit_id": g.habit_id,
            "habit_name": habit.name if habit else None,
            "habit_icon": habit.icon if habit else None,
            "habit_checked_today": (g.habit_id in feitos_hoje) if g.habit_id else None,
        })
    return {"date": str(ref), "goals": out}


# Aviso é uma vez por categoria por dia — em memória, como `_garmin_avisado`
# no main.py: reinicia com o backend, o que não é problema para um aviso pontual.
_metas_avisadas_hoje: dict[str, date] = {}


def checar_metas_diarias(db: Session) -> str:
    """Vê se alguma meta foi atingida HOJE (o alvo diário, não a vista semana/
    mês): avisa sempre, e tendo hábito associado marca-o sozinho — uma vez por
    dia, sem duplicar. Chamada pelo agendador de 15 em 15 minutos."""
    from models import Habit, HabitCompletion
    from notifier import notify

    hoje = date.today()
    metas = [
        m for m in db.query(ScreenTimeGoal).filter(ScreenTimeGoal.active == True).all()
        if _dia_conta(m.days, hoje.weekday())
    ]
    if not metas:
        return "sem metas activas hoje"

    usados = screen_source.por_categoria(db, hoje, hoje)
    avisados = []
    for meta in metas:
        if usados.get(meta.category, 0) < meta.target_hours * 3600:
            continue

        habit = db.query(Habit).filter(Habit.id == meta.habit_id).first() if meta.habit_id else None
        marcou_habito = False
        if habit:
            ja_feito = db.query(HabitCompletion).filter(
                HabitCompletion.habit_id == meta.habit_id,
                HabitCompletion.date == hoje,
            ).first()
            if not ja_feito:
                db.add(HabitCompletion(
                    habit_id=meta.habit_id, date=hoje, completed_at=datetime.now().strftime("%H:%M"),
                    notes=f"Marcado sozinho: {meta.category} chegou às {meta.target_hours:g}h hoje.",
                ))
                db.commit()
                marcou_habito = True

        if _metas_avisadas_hoje.get(meta.category) == hoje:
            continue
        _metas_avisadas_hoje[meta.category] = hoje
        avisados.append(meta.category)
        corpo = f"{meta.category} chegou às {meta.target_hours:g}h hoje."
        if habit:
            corpo += f" Hábito {habit.name} marcado sozinho." if marcou_habito else f" Hábito {habit.name} já estava marcado."
        notify(f"🎯 Meta de ecrã atingida: {meta.category}", corpo, severity="info")

    return f"meta(s) atingida(s) hoje: {', '.join(avisados)}" if avisados else "meta(s) ainda não atingida(s)"
