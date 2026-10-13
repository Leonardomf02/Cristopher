"""Agendador interno da app.

Porque não launchd: os LaunchAgents chamavam `/bin/bash` para correr scripts em
~/Documents e o macOS bloqueia isso (TCC) — falharam todos os dias durante 56 dias
sem ninguém saber. O backend já corre 24/7 e já tem as permissões, por isso os
trabalhos diários passam a viver aqui.

Cada execução fica registada em `job_runs`, o que dá a base para o painel de
saúde dos dados: sabe-se sempre quando cada coisa correu e se correu bem.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable, Optional

from database import SessionLocal
from models import JobRun

logger = logging.getLogger(__name__)

JobFn = Callable[[], object] | Callable[[], Awaitable[object]]


@dataclass
class Job:
    name: str
    label: str
    fn: JobFn
    hour: int = 8
    minute: int = 30
    # Trabalhos "ao ritmo dele": em vez de uma hora do relógio, quantos minutos
    # depois de acordar. O aviso da manhã às 09:00 apanhava-o a dormir (acorda
    # por volta das 11:30) e, com a recuperação de atrasos, chegava às 02:00.
    apos_acordar_min: Optional[int] = None
    # Avisos não se enviam fora da janela em que ele está acordado.
    so_acordado: bool = False
    # Trabalhos que repetem ao longo do dia (em vez de uma vez à hora marcada):
    # os jogos de LoL só entravam quando ele abria a página do LoL, e por isso
    # "O Dia" dizia que não tinha jogado nada.
    cada_min: Optional[int] = None
    # Ao arrancar, corre se ainda não correu hoje (recupera dias em que o Mac
    # estava desligado à hora marcada).
    catch_up: bool = True
    max_age_hours: int = 36     # acima disto o painel de saúde acusa atraso


_JOBS: list[Job] = []


def register(job: Job) -> None:
    _JOBS.append(job)


def jobs() -> list[Job]:
    return list(_JOBS)


def last_run(name: str) -> Optional[JobRun]:
    db = SessionLocal()
    try:
        return (
            db.query(JobRun)
            .filter(JobRun.name == name)
            .order_by(JobRun.started_at.desc())
            .first()
        )
    finally:
        db.close()


def _record(name: str, started: datetime, ok: bool, detail: str) -> None:
    db = SessionLocal()
    try:
        db.add(JobRun(
            name=name,
            started_at=started,
            finished_at=datetime.now(),
            ok=ok,
            detail=detail[:500],
            duration_ms=int((datetime.now() - started).total_seconds() * 1000),
        ))
        # histórico curto: 30 execuções por job bastam para ver padrões
        antigos = (
            db.query(JobRun)
            .filter(JobRun.name == name)
            .order_by(JobRun.started_at.desc())
            .offset(30)
            .all()
        )
        for a in antigos:
            db.delete(a)
        db.commit()
    finally:
        db.close()


async def run_job(job: Job) -> tuple[bool, str]:
    started = datetime.now()
    try:
        result = job.fn()
        if inspect.isawaitable(result):
            result = await result
        detail = "" if result is None else str(result)
        _record(job.name, started, True, detail)
        logger.info(f"[scheduler] {job.name}: ok {detail}")
        return True, detail
    except Exception as ex:
        detail = f"{type(ex).__name__}: {ex}"
        _record(job.name, started, False, detail)
        logger.warning(f"[scheduler] {job.name} falhou: {detail}\n{traceback.format_exc(limit=3)}")
        return False, detail


def hora_de_acordar(quando: date) -> Optional[int]:
    """Minutos desde a meia-noite a que ele costuma acordar (mediana das últimas
    três semanas), ou a hora real desse dia se já estiver registada."""
    db = SessionLocal()
    try:
        from models import SleepEntry
        do_dia = (
            db.query(SleepEntry)
            .filter(SleepEntry.date == quando)
            .order_by(SleepEntry.id.desc())
            .first()
        )
        recentes = (
            db.query(SleepEntry)
            .filter(SleepEntry.date >= quando - timedelta(days=21), SleepEntry.date <= quando)
            .all()
        )
    finally:
        db.close()

    def minutos(hhmm) -> Optional[int]:
        try:
            h, m = str(hhmm)[:5].split(":")
            t = int(h) * 60 + int(m)
            return t if 4 * 60 <= t <= 15 * 60 else None
        except (ValueError, AttributeError):
            return None

    if do_dia and minutos(do_dia.wake_time) is not None:
        return minutos(do_dia.wake_time)
    horas = sorted(x for x in (minutos(e.wake_time) for e in recentes) if x is not None)
    return horas[len(horas) // 2] if horas else None


def _acordado(agora: datetime) -> bool:
    """Está acordado? Usa o acordar típico e assume que se deita ~16h depois."""
    acordar = hora_de_acordar(agora.date())
    if acordar is None:
        return 8 * 60 <= agora.hour * 60 + agora.minute <= 23 * 60
    minuto_actual = agora.hour * 60 + agora.minute
    if minuto_actual < acordar:
        minuto_actual += 24 * 60
    return acordar <= minuto_actual <= acordar + 16 * 60


def _marca_do_dia(job: Job, agora: datetime) -> datetime:
    """A que horas este trabalho deve correr hoje."""
    if job.apos_acordar_min is not None:
        acordar = hora_de_acordar(agora.date())
        if acordar is not None:
            alvo = acordar + job.apos_acordar_min
            base = agora.replace(hour=0, minute=0, second=0, microsecond=0)
            return base + timedelta(minutes=alvo)
    return agora.replace(hour=job.hour, minute=job.minute, second=0, microsecond=0)


def _ran_today(name: str, hoje: date) -> bool:
    r = last_run(name)
    return bool(r and r.started_at and r.started_at.date() == hoje and r.ok)


async def _loop() -> None:
    # Dá tempo ao arranque (tracker, migrações) antes do primeiro trabalho.
    await asyncio.sleep(90)
    while True:
        agora = datetime.now()
        for job in _JOBS:
            try:
                if job.cada_min:
                    r = last_run(job.name)
                    if r and r.started_at and (agora - r.started_at).total_seconds() < job.cada_min * 60:
                        continue
                    if job.so_acordado and not _acordado(agora):
                        continue
                    await run_job(job)
                    continue
                if _ran_today(job.name, agora.date()):
                    continue
                marca = _marca_do_dia(job, agora)
                if job.so_acordado and not _acordado(agora):
                    continue          # não se manda um "bom dia" às duas da manhã
                if agora >= marca or (job.catch_up and _atrasado(job, agora)):
                    await run_job(job)
            except Exception as ex:
                logger.warning(f"[scheduler] erro a avaliar {job.name}: {ex}")
        await asyncio.sleep(300)   # 5 min


def _atrasado(job: Job, agora: datetime) -> bool:
    """Sem execução recente (ex.: Mac desligado durante dias) → corre já."""
    r = last_run(job.name)
    if r is None or r.started_at is None:
        return True
    return agora - r.started_at > timedelta(hours=job.max_age_hours)


def start(loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    (loop or asyncio.get_event_loop()).create_task(_loop())
    logger.info(f"[scheduler] {len(_JOBS)} trabalhos registados")
