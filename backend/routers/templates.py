from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import DayTemplate
from schemas import DayTemplateCreate, DayTemplateUpdate, DayTemplateOut

router = APIRouter(prefix="/api/templates", tags=["Day Templates"])


@router.get("/", response_model=list[DayTemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return db.query(DayTemplate).order_by(DayTemplate.name).all()


@router.post("/", response_model=DayTemplateOut)
def create_template(data: DayTemplateCreate, db: Session = Depends(get_db)):
    t = DayTemplate(**data.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.put("/{template_id}", response_model=DayTemplateOut)
def update_template(template_id: int, data: DayTemplateUpdate, db: Session = Depends(get_db)):
    t = db.query(DayTemplate).filter(DayTemplate.id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(DayTemplate).filter(DayTemplate.id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    db.delete(t)
    db.commit()
    return {"ok": True}
