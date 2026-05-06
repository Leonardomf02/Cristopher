from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from database import get_db
from models import Note, NoteFolder
from schemas import (
    NoteCreate, NoteUpdate, NoteOut,
    NoteFolderCreate, NoteFolderUpdate, NoteFolderOut,
)

router = APIRouter(prefix="/api/notes", tags=["Notes"])


# ── Folders ──────────────────────────────────────────────────────

@router.get("/folders", response_model=list[NoteFolderOut])
def list_folders(db: Session = Depends(get_db)):
    folders = db.query(NoteFolder).order_by(NoteFolder.position, NoteFolder.id).all()
    result = []
    for f in folders:
        out = NoteFolderOut.model_validate(f)
        out.note_count = db.query(func.count(Note.id)).filter(Note.folder_id == f.id).scalar() or 0
        result.append(out)
    return result


@router.post("/folders", response_model=NoteFolderOut)
def create_folder(data: NoteFolderCreate, db: Session = Depends(get_db)):
    max_pos = db.query(func.max(NoteFolder.position)).scalar() or 0
    folder = NoteFolder(**data.model_dump(), position=max_pos + 1)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    out = NoteFolderOut.model_validate(folder)
    out.note_count = 0
    return out


@router.put("/folders/{folder_id}", response_model=NoteFolderOut)
def update_folder(folder_id: int, data: NoteFolderUpdate, db: Session = Depends(get_db)):
    folder = db.query(NoteFolder).filter(NoteFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(folder, key, value)
    db.commit()
    db.refresh(folder)
    out = NoteFolderOut.model_validate(folder)
    out.note_count = db.query(func.count(Note.id)).filter(Note.folder_id == folder.id).scalar() or 0
    return out


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int, db: Session = Depends(get_db)):
    folder = db.query(NoteFolder).filter(NoteFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    # Move notes in this folder to unfiled
    db.query(Note).filter(Note.folder_id == folder_id).update({"folder_id": None})
    db.delete(folder)
    db.commit()
    return {"ok": True}


# ── Notes ────────────────────────────────────────────────────────

@router.get("/", response_model=list[NoteOut])
def list_notes(
    folder_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Note)
    if folder_id is not None:
        q = q.filter(Note.folder_id == folder_id)
    if search:
        term = f"%{search}%"
        q = q.filter((Note.title.ilike(term)) | (Note.content.ilike(term)))
    return q.order_by(Note.pinned.desc(), Note.updated_at.desc()).all()


@router.get("/{note_id}", response_model=NoteOut)
def get_note(note_id: int, db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.post("/", response_model=NoteOut)
def create_note(data: NoteCreate, db: Session = Depends(get_db)):
    note = Note(**data.model_dump())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.put("/{note_id}", response_model=NoteOut)
def update_note(note_id: int, data: NoteUpdate, db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(note, key, value)
    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(note)
    db.commit()
    return {"ok": True}
