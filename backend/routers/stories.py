"""Histórias — pesquisas explicadas pela IA.

O utilizador manda explicar um tema (ex: 'o que aconteceu em Chernobyl', 'quem foi
Alexandre o Grande') e escolhe o nível: simples / médio / grande. Cada nível é gerado
on-demand pelo agente iaedu.pt (com web search) e guardado, para alternar entre níveis
sem repetir a chamada à IA. As histórias ficam guardadas para rever depois."""

import json
import re
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Story, StoryVersion
from ai_config import ask_agent_async, extract_json

router = APIRouter(prefix="/api/stories", tags=["Stories"])
logger = logging.getLogger(__name__)

LEVELS = ("simple", "medium", "long")

_LEVEL_BRIEF = {
    "simple": (
        "SIMPLES — explica como se fosse a um miúdo curioso de 12 anos. 1 a 2 parágrafos "
        "curtos, linguagem do dia-a-dia, sem jargão. Vai direto ao essencial: o que é / o que "
        "aconteceu e porque é que importa."
    ),
    "medium": (
        "MÉDIO — explicação equilibrada em alguns parágrafos. Cobre contexto, o que aconteceu, "
        "causas e consequências principais. Usa subtítulos (##) só se ajudar a ler."
    ),
    "long": (
        "GRANDE — explicação aprofundada e bem estruturada. Usa subtítulos markdown (##), listas "
        "e, se fizer sentido, uma cronologia. Cobre antecedentes, desenvolvimento, figuras-chave, "
        "consequências e relevância. Detalhado mas sem encher chouriços."
    ),
}


# ── Schemas ──────────────────────────────────────────────────────

class CreateStoryIn(BaseModel):
    query: str
    level: str = "medium"


class LevelIn(BaseModel):
    level: str


class SourceOut(BaseModel):
    title: str
    url: str


class VersionOut(BaseModel):
    level: str
    body: str
    sources: list[SourceOut]
    created_at: datetime


class StoryOut(BaseModel):
    id: int
    query: str
    title: str
    last_level: str
    created_at: datetime
    versions: list[VersionOut]


class StoryListItem(BaseModel):
    id: int
    query: str
    title: str
    last_level: str
    created_at: datetime
    levels: list[str]
    snippet: str


# ── Helpers ──────────────────────────────────────────────────────

def _build_prompt(query: str, level: str) -> str:
    return f"""És um divulgador que explica temas (história, ciência, eventos, pessoas, lugares) de forma clara e rigorosa, em português de Portugal.

Tema pedido pelo utilizador:
\"\"\"
{query}
\"\"\"

Nível de profundidade: {_LEVEL_BRIEF[level]}

Regras:
- Responde em português de Portugal, em markdown (negrito, listas e subtítulos ## quando útil).
- Sê rigoroso: usa a web search para confirmar factos, datas e nomes. Não inventes.
- Se o tema for ambíguo, assume a interpretação mais provável e explica-a.
- NÃO ponhas um título # no topo (o título vai à parte).
- TERMINA a resposta com um bloco ```json EXACTAMENTE neste formato, como última coisa da resposta:
```json
{{"title": "<título curto e claro do tema, ex: 'Desastre de Chernobyl'>", "sources": [{{"title": "<nome da fonte>", "url": "<url>"}}]}}
```
Inclui 2 a 5 fontes web fiáveis que usaste."""


def _split_body_and_meta(text: str) -> tuple[str, str, list[dict]]:
    """Separa o markdown da explicação do bloco json final (title + sources)."""
    meta = extract_json(text)
    title = ""
    sources: list[dict] = []
    if isinstance(meta, dict):
        title = (meta.get("title") or "").strip()
        for s in meta.get("sources") or []:
            if not isinstance(s, dict):
                continue
            url = (s.get("url") or "").strip()
            if not url:
                continue
            name = (s.get("title") or s.get("name") or url).strip()
            sources.append({"title": name or url, "url": url})
    # tira o bloco json final do corpo (fenced ou não)
    body = re.sub(r"\n*```(?:json)?\s*[\[{].*?[\]}]\s*```\s*$", "", text.strip(), flags=re.DOTALL)
    body = re.sub(r"\n*\{[^{}]*\"sources\"[^{}]*\[.*?\]\s*\}\s*$", "", body.strip(), flags=re.DOTALL)
    return body.strip(), title, sources


async def _generate(query: str, level: str) -> tuple[str, str, list[dict]]:
    if level not in LEVELS:
        raise HTTPException(status_code=400, detail="Nível inválido")
    prompt = _build_prompt(query, level)
    text = await ask_agent_async(prompt, timeout=180.0)
    if not text:
        raise HTTPException(status_code=502, detail="IA indisponível")
    body, title, sources = _split_body_and_meta(text)
    if not body:
        logger.warning("Stories AI sem corpo: %s", text[:300])
        raise HTTPException(status_code=502, detail="Resposta da IA inválida")
    return body, title, sources


def _version_out(v: StoryVersion) -> dict:
    try:
        raw = json.loads(v.sources or "[]")
    except (json.JSONDecodeError, TypeError):
        raw = []
    return {"level": v.level, "body": v.body, "sources": raw, "created_at": v.created_at}


def _snippet(body: str, n: int = 180) -> str:
    plain = re.sub(r"[#*_`>\-]", "", body or "")
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:n] + ("…" if len(plain) > n else "")


# ── Endpoints ────────────────────────────────────────────────────

@router.get("", response_model=list[StoryListItem])
def list_stories():
    db: Session = SessionLocal()
    try:
        stories = db.query(Story).order_by(Story.created_at.desc()).all()
        out = []
        for s in stories:
            versions = db.query(StoryVersion).filter(StoryVersion.story_id == s.id).all()
            by_level = {v.level: v for v in versions}
            pick = by_level.get(s.last_level) or (versions[0] if versions else None)
            out.append({
                "id": s.id,
                "query": s.query,
                "title": s.title or s.query,
                "last_level": s.last_level,
                "created_at": s.created_at,
                "levels": [lv for lv in LEVELS if lv in by_level],
                "snippet": _snippet(pick.body) if pick else "",
            })
        return out
    finally:
        db.close()


@router.get("/{story_id}", response_model=StoryOut)
def get_story(story_id: int):
    db: Session = SessionLocal()
    try:
        s = db.query(Story).filter(Story.id == story_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="História não encontrada")
        versions = db.query(StoryVersion).filter(StoryVersion.story_id == s.id).all()
        order = {lv: i for i, lv in enumerate(LEVELS)}
        versions.sort(key=lambda v: order.get(v.level, 99))
        return {
            "id": s.id,
            "query": s.query,
            "title": s.title or s.query,
            "last_level": s.last_level,
            "created_at": s.created_at,
            "versions": [_version_out(v) for v in versions],
        }
    finally:
        db.close()


@router.post("", response_model=StoryOut)
async def create_story(data: CreateStoryIn):
    query = (data.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Tema vazio")
    level = data.level if data.level in LEVELS else "medium"

    body, title, sources = await _generate(query, level)

    db: Session = SessionLocal()
    try:
        s = Story(query=query, title=title or query, last_level=level)
        db.add(s)
        db.flush()
        v = StoryVersion(story_id=s.id, level=level, body=body, sources=json.dumps(sources, ensure_ascii=False))
        db.add(v)
        db.commit()
        db.refresh(s)
        return {
            "id": s.id,
            "query": s.query,
            "title": s.title,
            "last_level": s.last_level,
            "created_at": s.created_at,
            "versions": [_version_out(v)],
        }
    finally:
        db.close()


@router.post("/{story_id}/level", response_model=VersionOut)
async def set_level(story_id: int, data: LevelIn):
    """Garante que um nível está gerado (gera se faltar) e marca-o como o último visto."""
    level = data.level
    if level not in LEVELS:
        raise HTTPException(status_code=400, detail="Nível inválido")

    db: Session = SessionLocal()
    try:
        s = db.query(Story).filter(Story.id == story_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="História não encontrada")
        existing = db.query(StoryVersion).filter(
            StoryVersion.story_id == story_id, StoryVersion.level == level
        ).first()
        if existing:
            s.last_level = level
            db.commit()
            return _version_out(existing)
        query = s.query
    finally:
        db.close()

    body, title, sources = await _generate(query, level)

    db = SessionLocal()
    try:
        s = db.query(Story).filter(Story.id == story_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="História não encontrada")
        # corrida: outro pedido pode ter gerado entretanto
        existing = db.query(StoryVersion).filter(
            StoryVersion.story_id == story_id, StoryVersion.level == level
        ).first()
        if not existing:
            existing = StoryVersion(
                story_id=story_id, level=level, body=body,
                sources=json.dumps(sources, ensure_ascii=False),
            )
            db.add(existing)
        if not s.title and title:
            s.title = title
        s.last_level = level
        db.commit()
        db.refresh(existing)
        return _version_out(existing)
    finally:
        db.close()


@router.delete("/{story_id}")
def delete_story(story_id: int):
    db: Session = SessionLocal()
    try:
        s = db.query(Story).filter(Story.id == story_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="História não encontrada")
        db.query(StoryVersion).filter(StoryVersion.story_id == story_id).delete()
        db.delete(s)
        db.commit()
        return {"ok": True}
    finally:
        db.close()
