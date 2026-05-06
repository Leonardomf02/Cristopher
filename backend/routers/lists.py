from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from database import get_db
from models import UserList, ListItem
from schemas import (
    UserListCreate, UserListUpdate, UserListOut,
    ListItemCreate, ListItemUpdate, ListItemOut,
)

router = APIRouter(prefix="/api/lists", tags=["Lists"])


# ── Lists CRUD ───────────────────────────────────────────────────

@router.get("/", response_model=list[UserListOut])
def get_lists(db: Session = Depends(get_db)):
    lists = db.query(UserList).order_by(UserList.created_at).all()
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


@router.post("/", response_model=UserListOut)
def create_list(data: UserListCreate, db: Session = Depends(get_db)):
    lst = UserList(**data.model_dump())
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
    db.query(ListItem).filter(ListItem.list_id == list_id).delete()
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
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(ListItem).filter(ListItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


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
