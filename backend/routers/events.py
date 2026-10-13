from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import Optional
import json
import os
import subprocess
import sys
import logging
import re

from database import get_db
from models import Event
from schemas import EventCreate, EventUpdate, EventOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/events", tags=["Events"])


def _date_set(raw: str | None) -> set[str]:
    """Parse a JSON list-of-dates column into a set of 'YYYY-MM-DD' strings."""
    try:
        return {str(d) for d in json.loads(raw or "[]")}
    except (json.JSONDecodeError, TypeError):
        return set()


def _expand_recurring(event: Event, range_start: date, range_end: date) -> list[dict]:
    """Expand a recurring event into virtual instances within [range_start, range_end].

    Uma tarefa **flexível** que se repete e que não foi feita num dia passado não
    aparece nesse dia: "Projeto CS" todos os dias úteis é o que ele quer fazer
    hoje, não uma dívida a acumular para trás no calendário. Um compromisso com
    hora (fixo) continua a aparecer — aconteceu, tenha ele carimbado ou não.
    """
    rec = event.recurrence or "none"
    if rec == "none":
        return []

    exceptions = _date_set(event.recurrence_exceptions)
    completions = _date_set(getattr(event, "recurrence_completions", None))
    so_se_feita = (event.event_type or "") == "flexible" and not event.start_time
    hoje = date.today()

    rec_end = event.recurrence_end or range_end
    effective_end = min(rec_end, range_end)

    instances = []
    current = event.date

    while current <= effective_end:
        if current >= range_start and current != event.date:
            date_str = str(current)
            passada_por_fazer = so_se_feita and current < hoje and date_str not in completions
            if date_str not in exceptions and not passada_por_fazer:
                instances.append({
                    "id": event.id,
                    "title": event.title,
                    "description": event.description,
                    "date": current,
                    "start_time": event.start_time,
                    "end_time": event.end_time,
                    "event_type": event.event_type,
                    "category": event.category,
                    "color": event.color,
                    "completed": date_str in completions,
                    "recurrence": event.recurrence,
                    "recurrence_end": event.recurrence_end,
                    "is_recurring_instance": True,
                    "parent_id": event.id,
                })

        current = _next_occurrence(current, rec)
        if current is None:
            break

    return instances


def _next_occurrence(current: date, recurrence: str) -> Optional[date]:
    if recurrence == "daily":
        return current + timedelta(days=1)
    elif recurrence == "weekdays":
        nxt = current + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        return nxt
    elif recurrence == "weekly":
        return current + timedelta(weeks=1)
    elif recurrence == "biweekly":
        return current + timedelta(weeks=2)
    elif recurrence == "monthly":
        return current + relativedelta(months=1)
    elif recurrence == "yearly":
        return current + relativedelta(years=1)
    return None


def _occurs_on(ev: Event, day: date) -> bool:
    """True se o evento (ou uma sua instância recorrente) ocorre em `day`."""
    if ev.date == day:
        return True
    if ev.recurrence and ev.recurrence not in ("none", ""):
        return len(_expand_recurring(ev, day, day)) > 0
    return False


def events_due_now(db: Session, now: datetime, window_seconds: int = 90) -> list[tuple[str, str, str]]:
    """Eventos com hora de início caída na janela (now-window, now] para hoje,
    incluindo instâncias recorrentes. Devolve (chave_única, título, mensagem)."""
    today = now.date()
    due: list[tuple[str, str, str]] = []
    candidates = (
        db.query(Event)
        .filter(Event.start_time.isnot(None), Event.completed == False)  # noqa: E712
        .all()
    )
    for ev in candidates:
        if not _occurs_on(ev, today):
            continue
        try:
            sh, sm = (int(x) for x in ev.start_time.split(":")[:2])
        except (ValueError, AttributeError):
            continue
        event_dt = datetime.combine(today, datetime.min.time()).replace(hour=sh, minute=sm)
        if not (event_dt <= now < event_dt + timedelta(seconds=window_seconds)):
            continue
        key = f"{ev.id}:{today}:{ev.start_time}"
        msg = f"{ev.start_time}"
        if ev.end_time:
            msg += f"–{ev.end_time}"
        due.append((key, ev.title, msg))
    return due


@router.get("/", response_model=list[EventOut])
def list_events(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Event)
    if category:
        q = q.filter(Event.category == category)

    # Non-recurring events in date range
    non_rec_q = q.filter(Event.recurrence.in_(["none", None, ""]))
    if start_date:
        non_rec_q = non_rec_q.filter(Event.date >= start_date)
    if end_date:
        non_rec_q = non_rec_q.filter(Event.date <= end_date)
    results = non_rec_q.order_by(Event.date, Event.start_time).all()

    out = []
    for ev in results:
        d = EventOut.model_validate(ev)
        d.is_recurring_instance = False
        d.parent_id = None
        out.append(d)

    # Recurring events — expand into virtual instances
    if start_date and end_date:
        rec_q = q.filter(Event.recurrence.notin_(["none", ""]))
        rec_q = rec_q.filter(Event.date <= end_date)
        recurring_events = rec_q.all()

        for ev in recurring_events:
            if not ev.recurrence or ev.recurrence == "none":
                continue
            rec_end = ev.recurrence_end
            if rec_end and rec_end < start_date:
                continue

            exceptions = _date_set(ev.recurrence_exceptions)

            # A primeira ocorrência segue a mesma regra das outras: uma tarefa
            # flexível por fazer não fica pendurada num dia que já passou.
            passada_por_fazer = (
                (ev.event_type or "") == "flexible" and not ev.start_time
                and ev.date < date.today() and not ev.completed
            )
            if (start_date <= ev.date <= end_date and str(ev.date) not in exceptions
                    and not passada_por_fazer):
                d = EventOut.model_validate(ev)
                d.is_recurring_instance = False
                d.parent_id = None
                out.append(d)

            # Virtual instances
            for inst in _expand_recurring(ev, start_date, end_date):
                out.append(EventOut(**inst))

    out.sort(key=lambda e: (str(e.date), e.start_time or ""))
    return out


# ── Apple Calendar Import ────────────────────────────────────────

# Color mapping for Apple Calendar calendars
_CALENDAR_COLORS: dict[str, str] = {
    "Casa": "#22C55E",
    "Emprego": "#3B82F6",
    "Feriados": "#EF4444",
    "Feriados em Portugal": "#EF4444",
    "Birthdays": "#EC4899",
    "Todoist": "#F59E0B",
}

# Category mapping
_CALENDAR_CATEGORIES: dict[str, str] = {
    "Casa": "personal",
    "Emprego": "work",
    "Feriados": "general",
    "Feriados em Portugal": "general",
    "Birthdays": "personal",
    "Todoist": "general",
}

# Reverse mapping: Cristopher category → Apple Calendar name
_CATEGORY_TO_APPLE_CALENDAR: dict[str, str] = {
    "personal": "Casa",
    "work": "Emprego",
    "general": "Casa",
    "gym": "Casa",
}

_APPLE_DATE_RE = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{4})\s+at\s+(\d{1,2}):(\d{2}):(\d{2})"
)

_MONTH_MAP = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


def _parse_apple_date(s: str) -> datetime | None:
    """Parse AppleScript date string like 'Monday, 7 April 2026 at 09:00:00'."""
    m = _APPLE_DATE_RE.search(s)
    if not m:
        return None
    day, month_name, year, hour, minute, second = m.groups()
    return datetime(int(year), _MONTH_MAP[month_name], int(day), int(hour), int(minute), int(second))


class AppleCalendarImportRequest(BaseModel):
    calendars: list[str]
    days_back: int = 30
    days_forward: int = 90


def _calendario_apple() -> bool:
    """O Calendário da Apple fala-se por AppleScript: só existe no Mac. Na NAS
    (CLOUD=1) nem se tenta — rebentava com o `open` a não existir."""
    return sys.platform == "darwin" and os.getenv("CLOUD") != "1"


def _exige_calendario_apple() -> None:
    if not _calendario_apple():
        raise HTTPException(status_code=501, detail="O Calendário da Apple só está disponível no Mac")


@router.get("/apple-calendars")
def list_apple_calendars():
    """List available Apple Calendar calendars via AppleScript."""
    _exige_calendario_apple()
    # Ensure Calendar app is running
    subprocess.run(["open", "-a", "Calendar"], capture_output=True, timeout=5)
    import time as _time
    _time.sleep(1)
    script = '''
    tell application "Calendar"
        set output to ""
        repeat with c in calendars
            set output to output & name of c & "\\n"
        end repeat
        return output
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"AppleScript error: {result.stderr}")
        names = [n.strip() for n in result.stdout.strip().split("\n") if n.strip()]
        return {"calendars": names}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Apple Calendar timeout")
    except FileNotFoundError:
        raise HTTPException(status_code=501, detail="osascript not available")


@router.post("/import-apple-calendar")
def import_apple_calendar(req: AppleCalendarImportRequest, db: Session = Depends(get_db)):
    """Import events from Apple Calendar via AppleScript."""
    _exige_calendario_apple()
    # Ensure Calendar app is running
    subprocess.run(["open", "-a", "Calendar"], capture_output=True, timeout=5)
    import time as _time
    _time.sleep(1)
    DELIM = "|||"
    cal_names_as = ", ".join(f'"{c}"' for c in req.calendars)

    script = f'''
    tell application "Calendar"
        set output to ""
        set startDate to (current date) - {req.days_back} * days
        set endDate to (current date) + {req.days_forward} * days
        set calList to {{{cal_names_as}}}
        repeat with c in calendars
            if name of c is in calList then
                set calName to name of c
                set evts to (every event of c whose start date >= startDate and start date <= endDate)
                repeat with e in evts
                    try
                        set isAllDay to allday event of e
                    on error
                        set isAllDay to false
                    end try
                    set output to output & calName & "{DELIM}" & summary of e & "{DELIM}" & (start date of e as string) & "{DELIM}" & (end date of e as string) & "{DELIM}" & isAllDay & "\\n"
                end repeat
            end if
        end repeat
        return output
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"AppleScript error: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Apple Calendar timeout")

    lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
    imported = 0
    skipped = 0
    errors = 0

    for line in lines:
        parts = line.split(DELIM)
        if len(parts) < 5:
            errors += 1
            continue

        cal_name, title, start_str, end_str, is_all_day_str = [p.strip() for p in parts[:5]]
        title = title.strip()
        if not title:
            continue

        start_dt = _parse_apple_date(start_str)
        end_dt = _parse_apple_date(end_str)
        if not start_dt:
            errors += 1
            continue

        event_date = start_dt.date()
        is_all_day = is_all_day_str.lower() == "true"

        # Check for duplicate (same title + date)
        existing = db.query(Event).filter(
            Event.title == title,
            Event.date == event_date,
        ).first()
        if existing:
            skipped += 1
            continue

        start_time = None
        end_time = None
        event_type = "flexible"
        if not is_all_day:
            start_time = f"{start_dt.hour:02d}:{start_dt.minute:02d}"
            if end_dt:
                end_time = f"{end_dt.hour:02d}:{end_dt.minute:02d}"
            event_type = "fixed"

        color = _CALENDAR_COLORS.get(cal_name, "#3B82F6")
        category = _CALENDAR_CATEGORIES.get(cal_name, "general")

        event = Event(
            title=title,
            description=f"Importado de: {cal_name}",
            date=event_date,
            start_time=start_time,
            end_time=end_time,
            event_type=event_type,
            category=category,
            color=color,
        )
        db.add(event)
        imported += 1

    db.commit()
    logger.info(f"Apple Calendar import: {imported} imported, {skipped} skipped, {errors} errors")
    return {"imported": imported, "skipped": skipped, "errors": errors}


# ── Apple Calendar Export (Cristopher → Apple) ───────────────────

def _ensure_calendar_app():
    """Make sure Calendar.app is running (without bringing it to foreground)."""
    subprocess.run(
        ["osascript", "-e", 'tell application "Calendar" to launch'],
        capture_output=True, timeout=5,
    )
    import time as _t
    _t.sleep(0.5)


def _escape_applescript(s: str) -> str:
    """Escape a string for AppleScript."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _sync_event_to_apple(event: Event):
    """Create or update an event in Apple Calendar via AppleScript."""
    if not _calendario_apple():
        return False
    try:
        _ensure_calendar_app()
        cal_name = _CATEGORY_TO_APPLE_CALENDAR.get(event.category or "general", "Casa")
        title = _escape_applescript(event.title)
        desc = _escape_applescript(event.description or "")

        # Build date strings for AppleScript
        d = event.date
        if event.start_time and event.end_time:
            sh, sm = event.start_time.split(":")
            eh, em = event.end_time.split(":")
            start_date_expr = f'date "01/01/2000 00:00" '
            # Use AppleScript's date constructor
            script = f'''
            tell application "Calendar"
                set targetCal to first calendar whose name is "{_escape_applescript(cal_name)}"
                set startD to current date
                set year of startD to {d.year}
                set month of startD to {d.month}
                set day of startD to {d.day}
                set hours of startD to {int(sh)}
                set minutes of startD to {int(sm)}
                set seconds of startD to 0
                set endD to current date
                set year of endD to {d.year}
                set month of endD to {d.month}
                set day of endD to {d.day}
                set hours of endD to {int(eh)}
                set minutes of endD to {int(em)}
                set seconds of endD to 0
                -- Check if event already exists
                set existingEvents to (every event of targetCal whose summary is "{title}" and start date is startD)
                if (count of existingEvents) is 0 then
                    make new event at end of events of targetCal with properties {{summary:"{title}", description:"{desc}", start date:startD, end date:endD}}
                end if
            end tell
            '''
        else:
            # All-day event
            script = f'''
            tell application "Calendar"
                set targetCal to first calendar whose name is "{_escape_applescript(cal_name)}"
                set startD to current date
                set year of startD to {d.year}
                set month of startD to {d.month}
                set day of startD to {d.day}
                set hours of startD to 0
                set minutes of startD to 0
                set seconds of startD to 0
                set endD to startD + (1 * days)
                -- Check if event already exists
                set existingEvents to (every event of targetCal whose summary is "{title}" and start date is startD)
                if (count of existingEvents) is 0 then
                    make new event at end of events of targetCal with properties {{summary:"{title}", description:"{desc}", start date:startD, end date:endD, allday event:true}}
                end if
            end tell
            '''

        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.warning(f"Apple Calendar sync failed for '{event.title}': {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.warning(f"Apple Calendar sync error for '{event.title}': {e}")
        return False


def _delete_event_from_apple(title: str, event_date: date, start_time: str | None, category: str | None):
    """Delete an event from Apple Calendar."""
    if not _calendario_apple():
        return
    try:
        _ensure_calendar_app()
        cal_name = _CATEGORY_TO_APPLE_CALENDAR.get(category or "general", "Casa")
        escaped_title = _escape_applescript(title)
        d = event_date

        if start_time:
            sh, sm = start_time.split(":")
            script = f'''
            tell application "Calendar"
                set targetCal to first calendar whose name is "{_escape_applescript(cal_name)}"
                set targetD to current date
                set year of targetD to {d.year}
                set month of targetD to {d.month}
                set day of targetD to {d.day}
                set hours of targetD to {int(sh)}
                set minutes of targetD to {int(sm)}
                set seconds of targetD to 0
                set matchingEvents to (every event of targetCal whose summary is "{escaped_title}" and start date is targetD)
                repeat with e in matchingEvents
                    delete e
                end repeat
            end tell
            '''
        else:
            script = f'''
            tell application "Calendar"
                set targetCal to first calendar whose name is "{_escape_applescript(cal_name)}"
                set targetD to current date
                set year of targetD to {d.year}
                set month of targetD to {d.month}
                set day of targetD to {d.day}
                set hours of targetD to 0
                set minutes of targetD to 0
                set seconds of targetD to 0
                set matchingEvents to (every event of targetCal whose summary is "{escaped_title}" and start date is targetD)
                repeat with e in matchingEvents
                    delete e
                end repeat
            end tell
            '''

        subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    except Exception as e:
        logger.warning(f"Apple Calendar delete error for '{title}': {e}")


class ExportAppleCalendarRequest(BaseModel):
    calendars: list[str] = ["Casa", "Emprego"]
    days_back: int = 30
    days_forward: int = 90


@router.post("/export-apple-calendar")
def export_to_apple_calendar(req: ExportAppleCalendarRequest, db: Session = Depends(get_db)):
    """Export Cristopher events to Apple Calendar."""
    _exige_calendario_apple()
    today = date.today()
    start = today - timedelta(days=req.days_back)
    end = today + timedelta(days=req.days_forward)

    events = db.query(Event).filter(
        Event.date >= start,
        Event.date <= end,
    ).all()

    exported = 0
    skipped = 0
    errors = 0

    for ev in events:
        apple_cal = _CATEGORY_TO_APPLE_CALENDAR.get(ev.category or "general", "Casa")
        if apple_cal not in req.calendars:
            skipped += 1
            continue
        if _sync_event_to_apple(ev):
            exported += 1
        else:
            errors += 1

    return {"exported": exported, "skipped": skipped, "errors": errors}


# ── CRUD ─────────────────────────────────────────────────────────

@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    d = EventOut.model_validate(event)
    d.is_recurring_instance = False
    d.parent_id = None
    return d


@router.post("/", response_model=EventOut)
def create_event(data: EventCreate, db: Session = Depends(get_db)):
    event = Event(**data.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    # Sync to Apple Calendar (fire-and-forget)
    _sync_event_to_apple(event)
    d = EventOut.model_validate(event)
    d.is_recurring_instance = False
    d.parent_id = None
    return d


@router.put("/{event_id}", response_model=EventOut)
def update_event(event_id: int, data: EventUpdate, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    # Remove old version from Apple Calendar before updating
    old_title = event.title
    old_date = event.date
    old_start = event.start_time
    old_category = event.category
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(event, key, value)
    db.commit()
    db.refresh(event)
    # Sync: delete old, create new in Apple Calendar
    _delete_event_from_apple(old_title, old_date, old_start, old_category)
    _sync_event_to_apple(event)
    d = EventOut.model_validate(event)
    d.is_recurring_instance = False
    d.parent_id = None
    return d


@router.post("/{event_id}/exclude-date")
def exclude_recurring_date(event_id: int, target_date: date = Query(...), db: Session = Depends(get_db)):
    """Exclude a specific date from a recurring event (delete this instance only)."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    exceptions = _date_set(event.recurrence_exceptions)
    date_str = str(target_date)
    if date_str not in exceptions:
        exceptions.add(date_str)
        event.recurrence_exceptions = json.dumps(sorted(exceptions))
        db.commit()

    return {"ok": True}


@router.put("/{event_id}/occurrence")
def set_occurrence_completed(
    event_id: int,
    target_date: date = Query(...),
    completed: bool = Query(...),
    completed_at: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Marca/desmarca UMA ocorrência de um evento recorrente. As instâncias recorrentes
    são virtuais, por isso o estado guarda-se por data no evento-pai — marcar uma não
    pode marcar as outras nem a ocorrência original.

    `completed_at` (HH:MM) regista a hora a que foi dado check, para tarefas flexíveis
    aparecerem na timeline à hora em que foram feitas."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    date_str = str(target_date)
    # A data original do evento é uma linha real: mantém-se no campo `completed`.
    if event.date == target_date:
        event.completed = completed
        event.completed_at = completed_at if completed else None
        db.commit()
        return {"ok": True, "date": date_str, "completed": completed}

    done = _date_set(event.recurrence_completions)
    if completed:
        done.add(date_str)
    else:
        done.discard(date_str)
    event.recurrence_completions = json.dumps(sorted(done))
    db.commit()
    return {"ok": True, "date": date_str, "completed": completed}


@router.delete("/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    # Remove from Apple Calendar
    _delete_event_from_apple(event.title, event.date, event.start_time, event.category)
    db.delete(event)
    db.commit()
    return {"ok": True}
