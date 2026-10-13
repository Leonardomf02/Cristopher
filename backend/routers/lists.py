import os

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

import apple_reminders
from database import get_db
from models import UserList, ListItem
from schemas import (
    UserListCreate, UserListUpdate, UserListOut, UserListReorder,
    ListItemCreate, ListItemUpdate, ListItemOut,
)

router = APIRouter(prefix="/api/lists", tags=["Lists"])


# ── Lists CRUD ───────────────────────────────────────────────────

@router.get("/", response_model=list[UserListOut])
def get_lists(db: Session = Depends(get_db)):
    # A ordem é a que ele arrastou; a data de criação só desempata as listas
    # antigas, que nasceram todas com a mesma posição.
    lists = db.query(UserList).order_by(UserList.position, UserList.created_at).all()
    result = []
    for lst in lists:
        total = db.query(func.count(ListItem.id)).filter(ListItem.list_id == lst.id).scalar() or 0
        checked = db.query(func.count(ListItem.id)).filter(
            ListItem.list_id == lst.id, ListItem.checked == True
        ).scalar() or 0
        out = UserListOut.model_validate(lst)
        out.item_count = total
        out.checked_count = checked
        result.append(out)
    return result


@router.post("/reorder")
def reorder_lists(data: UserListReorder, db: Session = Depends(get_db)):
    """A ordem que ele arrastou. Ids desconhecidos são ignorados, e o que ficar
    de fora vai para o fim — assim uma lista criada noutro separador não
    desaparece da ordenação."""
    posicoes = {id_: i for i, id_ in enumerate(data.ids)}
    for lst in db.query(UserList).all():
        lst.position = posicoes.get(lst.id, len(posicoes) + lst.id)
    db.commit()
    return {"ok": True, "count": len(posicoes)}


@router.post("/", response_model=UserListOut)
def create_list(data: UserListCreate, db: Session = Depends(get_db)):
    maior = db.query(func.max(UserList.position)).scalar() or 0
    lst = UserList(**data.model_dump(), position=maior + 1)
    db.add(lst)
    db.commit()
    db.refresh(lst)
    out = UserListOut.model_validate(lst)
    out.item_count = 0
    out.checked_count = 0
    return out


@router.put("/{list_id}", response_model=UserListOut)
def update_list(list_id: int, data: UserListUpdate, db: Session = Depends(get_db)):
    lst = db.query(UserList).filter(UserList.id == list_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(lst, key, value)
    db.commit()
    db.refresh(lst)
    total = db.query(func.count(ListItem.id)).filter(ListItem.list_id == lst.id).scalar() or 0
    checked = db.query(func.count(ListItem.id)).filter(
        ListItem.list_id == lst.id, ListItem.checked == True
    ).scalar() or 0
    out = UserListOut.model_validate(lst)
    out.item_count = total
    out.checked_count = checked
    return out


@router.delete("/{list_id}")
def delete_list(list_id: int, db: Session = Depends(get_db)):
    lst = db.query(UserList).filter(UserList.id == list_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")
    for item in db.query(ListItem).filter(ListItem.list_id == list_id).all():
        apple_reminders.marca_apagado(db, item.apple_id)
        db.delete(item)
    apple_reminders.marca_apagado(db, lst.apple_id)
    db.delete(lst)
    db.commit()
    return {"ok": True}


# ── Reminders for Calendar ────────────────────────────────────────

@router.get("/reminders")
def get_reminders(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Return list items with due dates, enriched with list info, for calendar display."""
    from datetime import date as date_type

    q = (
        db.query(ListItem, UserList)
        .join(UserList, ListItem.list_id == UserList.id)
        .filter(ListItem.due_date.isnot(None))
    )
    if start_date:
        q = q.filter(ListItem.due_date >= start_date)
    if end_date:
        q = q.filter(ListItem.due_date <= end_date)

    results = []
    for item, lst in q.all():
        results.append({
            "id": f"reminder-{item.id}",
            "item_id": item.id,
            "title": f"{lst.icon} {item.text}",
            "date": str(item.due_date),
            "start_time": item.due_time,
            "end_time": None,
            "color": lst.color,
            "list_name": lst.name,
            "checked": item.checked,
            "priority": item.priority,
            "notes": item.notes,
            "is_reminder": True,
        })
    return results


# ── All pending items (across lists) ─────────────────────────────

@router.get("/items/pending")
def get_pending_items(db: Session = Depends(get_db)):
    """Return every unchecked item in every list, enriched with list info.

    Used by the dashboard "pick a todo for today" picker."""
    rows = (
        db.query(ListItem, UserList)
        .join(UserList, ListItem.list_id == UserList.id)
        .filter(ListItem.checked == False)
        .order_by(ListItem.priority.desc(), ListItem.due_date.is_(None), ListItem.due_date, ListItem.position)
        .all()
    )
    return [
        {
            "id": item.id,
            "text": item.text,
            "notes": item.notes,
            "due_date": str(item.due_date) if item.due_date else None,
            "due_time": item.due_time,
            "priority": item.priority,
            "list_id": lst.id,
            "list_name": lst.name,
            "list_icon": lst.icon,
            "list_color": lst.color,
        }
        for item, lst in rows
    ]


# ── List Items CRUD ──────────────────────────────────────────────

@router.get("/{list_id}/items", response_model=list[ListItemOut])
def get_items(list_id: int, db: Session = Depends(get_db)):
    return (
        db.query(ListItem)
        .filter(ListItem.list_id == list_id)
        .order_by(ListItem.checked, ListItem.position, ListItem.id)
        .all()
    )


@router.post("/{list_id}/items", response_model=ListItemOut)
def add_item(list_id: int, data: ListItemCreate, db: Session = Depends(get_db)):
    lst = db.query(UserList).filter(UserList.id == list_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")
    max_pos = db.query(func.max(ListItem.position)).filter(ListItem.list_id == list_id).scalar() or 0
    item = ListItem(
        list_id=list_id,
        text=data.text,
        position=max_pos + 1,
        notes=data.notes,
        due_date=data.due_date,
        due_time=data.due_time,
        priority=data.priority,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/items/{item_id}", response_model=ListItemOut)
def update_item(item_id: int, data: ListItemUpdate, db: Session = Depends(get_db)):
    item = db.query(ListItem).filter(ListItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    campos = data.model_dump(exclude_unset=True)
    if "list_id" in campos and campos["list_id"] != item.list_id:
        if not db.query(UserList).filter(UserList.id == campos["list_id"]).first():
            raise HTTPException(status_code=404, detail="List not found")
        # entra no fim da lista de destino
        campos["position"] = (db.query(func.max(ListItem.position))
                              .filter(ListItem.list_id == campos["list_id"]).scalar() or 0) + 1
    # A data em que foi feito é medida aqui, não pedida: quem carimba um reminder
    # não vai escrever a hora a seguir.
    if "checked" in campos and bool(campos["checked"]) != bool(item.checked):
        item.checked_at = datetime.now() if campos["checked"] else None
    for key, value in campos.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(ListItem).filter(ListItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    apple_reminders.marca_apagado(db, item.apple_id)
    db.delete(item)
    db.commit()
    return {"ok": True}


# ── Reminders da Apple ───────────────────────────────────────────

@router.get("/apple/status")
def apple_status():
    """O que a página mostra antes de sincronizar: se dá, e o que há do outro lado."""
    import scheduler

    if os.getenv("CLOUD") == "1":
        # Na NAS quem fala com a Apple é o agente do Mac.
        ag = apple_reminders.estado_do_agente()
        info = {"disponivel": True, "via": "mac"}
        if ag["quando"]:
            info.update(last_run=ag["quando"].isoformat(), last_ok=ag["ok"], last_detail=ag["detalhe"])
        return info
    info = apple_reminders.estado()
    ultima = scheduler.last_run("sync_reminders")
    if ultima:
        info["last_run"] = ultima.started_at.isoformat()
        info["last_ok"] = bool(ultima.ok)
        info["last_detail"] = ultima.detail or ""
    return info


@router.post("/apple/sync")
def apple_sync(db: Session = Depends(get_db)):
    """Uma passagem à mão, sem esperar pela hora certa."""
    if os.getenv("CLOUD") == "1":
        return _pede_ao_mac()
    try:
        conta = apple_reminders.sincroniza(db)
    except apple_reminders.SemAcesso as ex:
        raise HTTPException(
            status_code=403,
            detail=("O macOS não deu acesso aos Reminders. Autoriza em Definições do "
                    f"Sistema → Privacidade e Segurança → Lembretes. ({ex})"),
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))
    return {"ok": True, "resumo": apple_reminders.resumo(conta), **conta}


def _pede_ao_mac() -> dict:
    """Acorda o agente do Mac e espera pela passagem dele, até 20 segundos."""
    import time
    antes = apple_reminders.estado_do_agente()["quando"]
    apple_reminders.pede_passagem()
    for _ in range(40):
        time.sleep(0.5)
        ag = apple_reminders.estado_do_agente()
        if ag["quando"] != antes:
            if not ag["ok"]:
                raise HTTPException(status_code=502, detail=ag["detalhe"] or "o Mac não conseguiu")
            return {"ok": True, "resumo": ag["detalhe"]}
    raise HTTPException(status_code=504, detail="o Mac não respondeu — está desligado ou a dormir?")


# ── iCal Feed for Apple Calendar ─────────────────────────────────

@router.get("/calendar.ics")
def get_ical_feed(db: Session = Depends(get_db)):
    """Generate an iCal feed of all unchecked reminders with due dates."""
    from icalendar import Calendar, Event, Todo

    cal = Calendar()
    cal.add("prodid", "-//Cristopher//Reminders//PT")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", "Cristopher Reminders")

    items = (
        db.query(ListItem, UserList)
        .join(UserList, ListItem.list_id == UserList.id)
        .filter(ListItem.due_date.isnot(None), ListItem.checked == False)
        .all()
    )

    for item, lst in items:
        event = Event()
        event.add("uid", f"cristopher-reminder-{item.id}@localhost")
        event.add("summary", f"{lst.icon} {item.text}")
        if item.notes:
            event.add("description", item.notes)

        if item.due_time:
            try:
                h, m = map(int, item.due_time.split(":"))
                dt_start = datetime(item.due_date.year, item.due_date.month, item.due_date.day, h, m)
                event.add("dtstart", dt_start)
                event.add("dtend", dt_start + timedelta(minutes=30))
            except (ValueError, AttributeError):
                event.add("dtstart", item.due_date)
        else:
            event.add("dtstart", item.due_date)

        # Priority mapping: 0=none, 1=low(9), 2=medium(5), 3=high(1) in iCal spec
        ical_priority = {0: 0, 1: 9, 2: 5, 3: 1}.get(item.priority, 0)
        if ical_priority:
            event.add("priority", ical_priority)

        event.add("categories", [lst.name])
        event.add("dtstamp", datetime.now())
        cal.add_component(event)

    return Response(
        content=cal.to_ical(),
        media_type="text/calendar",
        headers={"Content-Disposition": "inline; filename=cristopher-reminders.ics"},
    )
