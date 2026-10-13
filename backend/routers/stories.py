"""Histórias — pesquisas explicadas pela IA.

O utilizador manda explicar um tema (ex: 'o que aconteceu em Chernobyl', 'quem foi
Alexandre o Grande') e escolhe o nível: simples / médio / grande. Cada nível é gerado
on-demand pelo agente iaedu.pt (com web search) e guardado, para alternar entre níveis
sem repetir a chamada à IA. As histórias ficam guardadas para rever depois.

A IA também recomenda temas para explorar a seguir: relacionados com uma história que
acabou de ler (ex: leu Alexandre o Grande → Batalha de Gaugamela, Aristóteles) ou gerais,
com base em tudo o que já pesquisou."""

import asyncio
import json
import re
import logging
import unicodedata
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Story, StoryVersion, StorySuggestion
from ai_config import ask_agent_async, extract_json

router = APIRouter(prefix="/api/stories", tags=["Stories"])
logger = logging.getLogger(__name__)

LEVELS = ("simple", "medium", "long")
SUGGESTIONS_N = 6

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
    suggestion_id: int | None = None  # veio de uma recomendação → descarta-a ao criar


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


class SuggestionOut(BaseModel):
    id: int
    story_id: int | None
    query: str
    title: str
    reason: str
    category: str


class RefreshSuggestionsIn(BaseModel):
    story_id: int | None = None


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
    text = await ask_agent_async(prompt, timeout=180.0, feature="stories")
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


# ── Sugestões ────────────────────────────────────────────────────

def _norm(text: str) -> str:
    """Chave de comparação: sem acentos, sem pontuação, minúsculas."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _suggestions_prompt(seed: Story | None, read: list[str], avoid: list[str], n: int) -> str:
    if seed:
        context = f"""O utilizador acabou de ler uma explicação sobre:
\"\"\"
{seed.title or seed.query}
\"\"\"

Sugere {n} temas para ele CONTINUAR A EXPLORAR a partir daqui: figuras ligadas ao tema,
acontecimentos que vieram antes ou depois, lugares, rivais, consequências, curiosidades
pouco conhecidas. Devem ser vizinhos naturais do tema, não repetições dele."""
    elif read:
        context = f"""Temas que o utilizador já mandou explicar (do mais recente para o mais antigo):
{chr(10).join('- ' + t for t in read[:20])}

Sugere {n} temas novos que ele provavelmente vai gostar, a partir dos interesses acima.
OBRIGATÓRIO misturar: cerca de metade próximos do que já leu (aprofundar a mesma área) e
pelo menos 2 de áreas COMPLETAMENTE diferentes (outra época, outro campo do saber), para
lhe abrir horizontes. Não faças as 6 à volta do mesmo assunto."""
    else:
        context = f"""O utilizador ainda não pesquisou nada.

Sugere {n} temas fascinantes e variados para arrancar — mistura história, ciência,
pessoas extraordinárias, acontecimentos marcantes e mistérios por resolver."""

    avoid_block = ""
    if avoid:
        avoid_block = f"""
NÃO sugiras nenhum destes (já lidos ou já sugeridos):
{chr(10).join('- ' + a for a in avoid[:40])}
"""

    return f"""És um curador de temas para uma app onde o utilizador manda a IA explicar-lhe assuntos (história, ciência, pessoas, eventos, lugares).

{context}
{avoid_block}
Regras:
- Português de Portugal.
- Cada sugestão é um tema concreto e pesquisável, NÃO uma categoria vaga.
- `query`: a pergunta/tema tal como se escreve na pesquisa (ex: "quem foi Aristóteles", "a batalha de Gaugamela").
- `title`: título curto e claro (máx 6 palavras).
- `reason`: UMA frase curta (máx 15 palavras) a dizer porque é que vale a pena, ligada ao que ele já leu.
- `category`: uma palavra (ex: História, Ciência, Pessoas, Mistério, Tecnologia, Arte).
- Nada de repetir temas entre si.

Responde APENAS com um bloco ```json, sem mais texto:
```json
[{{"query": "...", "title": "...", "reason": "...", "category": "..."}}]
```"""


async def _generate_suggestions(story_id: int | None) -> list[dict]:
    db: Session = SessionLocal()
    try:
        seed = db.query(Story).filter(Story.id == story_id).first() if story_id else None
        if story_id and not seed:
            raise HTTPException(status_code=404, detail="História não encontrada")
        stories = db.query(Story).order_by(Story.created_at.desc()).all()
        read = [s.title or s.query for s in stories]
        # blacklist: tudo o que já leu + sugestões já em cima da mesa ou descartadas
        avoid = [s.title or s.query for s in stories]
        avoid += [s.title or s.query for s in db.query(StorySuggestion).all()]
        prompt = _suggestions_prompt(seed, read, avoid, SUGGESTIONS_N)
    finally:
        db.close()

    text = await ask_agent_async(prompt, timeout=120.0, feature="stories")
    data = extract_json(text or "")
    if isinstance(data, dict):
        data = data.get("suggestions") or data.get("items") or []
    if not isinstance(data, list) or not data:
        logger.warning("Stories: sugestões inválidas: %s", (text or "")[:300])
        raise HTTPException(status_code=502, detail="IA não devolveu sugestões")

    taken = {_norm(a) for a in avoid}
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        query = (item.get("query") or item.get("title") or "").strip()
        title = (item.get("title") or query).strip()
        if not query or _norm(title) in taken or _norm(query) in taken:
            continue
        taken.add(_norm(title))
        taken.add(_norm(query))
        out.append({
            "query": query,
            "title": title,
            "reason": (item.get("reason") or "").strip(),
            "category": (item.get("category") or "").strip(),
        })
        if len(out) >= SUGGESTIONS_N:
            break

    db = SessionLocal()
    try:
        # substitui as sugestões vivas deste âmbito; as descartadas ficam como blacklist
        db.query(StorySuggestion).filter(
            StorySuggestion.story_id == story_id,
            StorySuggestion.dismissed.is_(False),
        ).delete()
        rows = [
            StorySuggestion(story_id=story_id, query=s["query"], title=s["title"],
                            reason=s["reason"], category=s["category"])
            for s in out
        ]
        db.add_all(rows)
        db.commit()
        return [_suggestion_out(r) for r in rows]
    finally:
        db.close()


def _suggestion_out(s: StorySuggestion) -> dict:
    return {
        "id": s.id, "story_id": s.story_id, "query": s.query,
        "title": s.title, "reason": s.reason, "category": s.category,
    }


async def _autofill_suggestions(story_id: int) -> None:
    """Depois de criar uma história, prepara em segundo plano os temas relacionados e
    refresca os gerais, para já estarem lá quando o utilizador acabar de ler."""
    for target in (story_id, None):
        try:
            await _generate_suggestions(target)
        except Exception as e:  # noqa: BLE001 — best-effort, nunca parte o fluxo
            logger.warning("Stories: autofill de sugestões falhou (%s): %s", target, e)


@router.get("/suggestions", response_model=list[SuggestionOut])
def list_suggestions(story_id: int | None = None):
    db: Session = SessionLocal()
    try:
        rows = (
            db.query(StorySuggestion)
            .filter(StorySuggestion.story_id == story_id, StorySuggestion.dismissed.is_(False))
            .order_by(StorySuggestion.created_at.desc(), StorySuggestion.id.desc())
            .limit(SUGGESTIONS_N)
            .all()
        )
        return [_suggestion_out(s) for s in rows]
    finally:
        db.close()


@router.post("/suggestions/refresh", response_model=list[SuggestionOut])
async def refresh_suggestions(data: RefreshSuggestionsIn):
    return await _generate_suggestions(data.story_id)


@router.post("/suggestions/{suggestion_id}/dismiss")
def dismiss_suggestion(suggestion_id: int):
    db: Session = SessionLocal()
    try:
        s = db.query(StorySuggestion).filter(StorySuggestion.id == suggestion_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="Sugestão não encontrada")
        s.dismissed = True
        db.commit()
        return {"ok": True}
    finally:
        db.close()


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
        if data.suggestion_id:
            sug = db.query(StorySuggestion).filter(StorySuggestion.id == data.suggestion_id).first()
            if sug:
                sug.dismissed = True
        db.commit()
        db.refresh(s)
        out = {
            "id": s.id,
            "query": s.query,
            "title": s.title,
            "last_level": s.last_level,
            "created_at": s.created_at,
            "versions": [_version_out(v)],
        }
    finally:
        db.close()

    asyncio.create_task(_autofill_suggestions(out["id"]))
    return out


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
        db.query(StorySuggestion).filter(StorySuggestion.story_id == story_id).delete()
        db.delete(s)
        db.commit()
        return {"ok": True}
    finally:
        db.close()
