"""Ingestão dos dados locais do Mac (modo híbrido).

O backend corre na cloud (sempre online), mas o Screen Time e o tracker de apps
só existem no Mac. Um agente local (agent/push_local.py) lê esses dados e faz
POST para aqui. Protegido por um token partilhado (env INGEST_TOKEN), não pela
sessão de login — para o agente poder correr sem interação.
"""
import os
from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import ScreenTimeDailyApp, AppUsageSession, Expense, ListItem, UserList, MoodEntry

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

_TOKEN = os.getenv("INGEST_TOKEN", "")


def _check_token(token: str | None):
    if not _TOKEN:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Ingestão desativada (INGEST_TOKEN não definido)")
    if token != _TOKEN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de ingestão inválido")


# ── Screen Time (snapshot diário por app) ────────────────────────

class ScreenTimeRow(BaseModel):
    date: date_cls
    device_id: str = "__local__"
    bundle_id: str
    category: str = ""
    seconds: int = 0


class ScreenTimePayload(BaseModel):
    rows: list[ScreenTimeRow]


@router.post("/screen-time")
def ingest_screen_time(
    payload: ScreenTimePayload,
    db: Session = Depends(get_db),
    x_ingest_token: str | None = Header(default=None),
):
    _check_token(x_ingest_token)
    upserted = 0
    for r in payload.rows:
        row = (
            db.query(ScreenTimeDailyApp)
            .filter_by(date=r.date, device_id=r.device_id, bundle_id=r.bundle_id)
            .first()
        )
        if row:
            row.seconds = r.seconds
            row.category = r.category
        else:
            db.add(ScreenTimeDailyApp(
                date=r.date, device_id=r.device_id, bundle_id=r.bundle_id,
                category=r.category, seconds=r.seconds,
            ))
        upserted += 1
    db.commit()
    return {"upserted": upserted}


# ── App usage (sessões de janela ativa) ──────────────────────────

class AppUsageRow(BaseModel):
    app_name: str
    window_title: str = ""
    bundle_id: str | None = None
    date: date_cls
    start_time: datetime
    end_time: datetime
    duration_seconds: int


class AppUsagePayload(BaseModel):
    sessions: list[AppUsageRow]


@router.post("/app-usage")
def ingest_app_usage(
    payload: AppUsagePayload,
    db: Session = Depends(get_db),
    x_ingest_token: str | None = Header(default=None),
):
    _check_token(x_ingest_token)
    upserted = 0
    for s in payload.sessions:
        # Dedup pela chave natural de uma sessão: (app_name, start_time).
        row = (
            db.query(AppUsageSession)
            .filter_by(app_name=s.app_name, start_time=s.start_time)
            .first()
        )
        if row:
            row.window_title = s.window_title
            row.end_time = s.end_time
            row.duration_seconds = s.duration_seconds
            row.bundle_id = s.bundle_id
        else:
            db.add(AppUsageSession(
                app_name=s.app_name, window_title=s.window_title, bundle_id=s.bundle_id,
                date=s.date, start_time=s.start_time, end_time=s.end_time,
                duration_seconds=s.duration_seconds,
            ))
        upserted += 1
    db.commit()
    return {"upserted": upserted}


# ── Captura rápida (Atalhos do iOS / voz) ────────────────────────
#
# Uma frase ditada ao telemóvel entra na app sem abrir nada:
#   "gastei 12 no lidl"        → despesa
#   "lembra-me de pagar a luz" → reminder
#   "dia 8"                    → humor
# A IA interpreta; se não estiver disponível, há um interpretador local por regras.

class CapturePayload(BaseModel):
    text: str
    kind: str | None = None    # expense | reminder | mood | note (None = adivinha)


def _lista_por_omissao(db: Session) -> UserList:
    lst = db.query(UserList).order_by(UserList.id).first()
    if not lst:
        lst = UserList(name="Reminders", icon="🗒️", color="#3B82F6")
        db.add(lst)
        db.commit()
        db.refresh(lst)
    return lst


def _regras_locais(texto: str) -> dict:
    """Interpretação sem IA: apanha valores e palavras-chave."""
    import re
    low = texto.lower().strip()

    m = re.search(r"(\d+[.,]?\d*)\s*(?:€|eur|euros)?", low)
    valor = float(m.group(1).replace(",", ".")) if m else None
    gasto = any(p in low for p in ("gastei", "paguei", "comprei", "custou", "gasto de"))
    if gasto and valor:
        desc = re.sub(r"\b(gastei|paguei|comprei|custou|euros?|eur|€|no|na|em|de|do|da)\b", " ", low)
        desc = re.sub(r"\d+[.,]?\d*", " ", desc)
        return {"kind": "expense", "amount": valor, "description": " ".join(desc.split()).title() or "Despesa"}

    if any(p in low for p in ("lembra-me", "lembrar", "não te esqueças", "tenho de", "preciso de")):
        limpo = re.sub(r"^(lembra-me de|lembra-me|lembrar de|tenho de|preciso de)\s*", "", low)
        return {"kind": "reminder", "text": limpo.capitalize() or texto}

    m2 = re.search(r"\b(dia|humor|mood)\s*(\d{1,2})\b", low)
    if m2:
        return {"kind": "mood", "mood": min(10, int(m2.group(2)))}

    return {"kind": "reminder", "text": texto.strip()}


async def _interpreta(texto: str, kind: str | None) -> dict:
    from ai_config import ask_agent_async, extract_json
    if kind:
        base = _regras_locais(texto)
        base["kind"] = kind
        return base
    prompt = f"""Interpreta esta frase ditada para a minha app pessoal e diz o que fazer com ela.

Frase: "{texto}"

Devolve SÓ um JSON, um destes formatos:
{{"kind":"expense","amount":12.5,"description":"Lidl","category":"groceries"}}
{{"kind":"reminder","text":"pagar a luz","due":"hoje|amanha|null"}}
{{"kind":"mood","mood":8,"note":""}}
{{"kind":"note","text":"..."}}

Categorias válidas: food, groceries, travel, shopping, bills, subscriptions, health,
entertainment, nightlife, transport, invest, other. Se for uma compra usa expense; se for algo
a fazer usa reminder; se for como te sentes usa mood; caso contrário note."""
    try:
        resposta = await ask_agent_async(prompt, timeout=60.0, feature="captura")
        data = extract_json(resposta) or {}
        if data.get("kind") in ("expense", "reminder", "mood", "note"):
            return data
    except Exception:
        pass
    return _regras_locais(texto)


@router.post("/capture")
async def quick_capture(
    payload: CapturePayload,
    db: Session = Depends(get_db),
    x_ingest_token: str | None = Header(default=None),
):
    """Cria despesa/reminder/humor/nota a partir de uma frase. Para Atalhos do iOS."""
    _check_token(x_ingest_token)
    return await executa_captura(payload, db)


async def executa_captura(payload: CapturePayload, db: Session) -> dict:
    """A captura em si, sem verificação de token — para a app poder usá-la
    autenticada pela sessão (a paleta ⌘K) e o Atalho do iOS pelo token."""
    texto = payload.text.strip()
    if not texto:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Texto vazio")

    data = await _interpreta(texto, payload.kind)
    tipo = data.get("kind")
    hoje = date_cls.today()

    if tipo == "expense":
        valor = float(data.get("amount") or 0)
        if valor <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Não percebi o valor")
        despesa = Expense(
            description=str(data.get("description") or texto)[:120],
            amount=valor,
            category=str(data.get("category") or "other"),
            date=hoje,
            notes="via captura rápida",
            kind="spend",
        )
        db.add(despesa)
        db.commit()
        db.refresh(despesa)
        return {"ok": True, "kind": "expense", "id": despesa.id,
                "summary": f"{despesa.description} · {valor:.2f}€ ({despesa.category})"}

    if tipo == "mood":
        valor = int(data.get("mood") or 0)
        if not 0 <= valor <= 10:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Humor fora da escala")
        entrada = db.query(MoodEntry).filter(MoodEntry.date == hoje).first()
        if not entrada:
            entrada = MoodEntry(date=hoje)
            db.add(entrada)
        entrada.mood = valor
        entrada.quality = "great" if valor >= 9 else "good" if valor >= 7 else "meh" if valor >= 5 else "bad"
        if data.get("note"):
            entrada.note = str(data["note"])[:300]
        db.commit()
        return {"ok": True, "kind": "mood", "summary": f"dia registado a {valor}/10"}

    # reminder e note caem no mesmo sítio: uma lista de itens
    lst = _lista_por_omissao(db)
    devido = None
    quando = str(data.get("due") or "").lower()
    if quando in ("hoje", "today"):
        devido = hoje
    elif quando in ("amanha", "amanhã", "tomorrow"):
        devido = hoje + timedelta(days=1)
    item = ListItem(
        list_id=lst.id,
        text=str(data.get("text") or texto)[:200],
        checked=False,
        due_date=devido,
        notes="via captura rápida",
        position=0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"ok": True, "kind": tipo or "reminder", "id": item.id,
            "summary": f"{item.text}" + (f" · para {devido.isoformat()}" if devido else " · sem data")}


# ── Champ select do LoL (o cliente só existe no Mac) ─────────────

class ChampSelectIn(BaseModel):
    client_running: bool = False
    phase: str | None = None
    session: dict | None = None


@router.post("/lol-champ-select")
def ingest_champ_select(
    payload: ChampSelectIn,
    x_ingest_token: str | None = Header(default=None),
):
    """O agente do Mac empurra o estado do cliente do LoL. Fica em memória e
    caduca em segundos — ver `lol_live`."""
    _check_token(x_ingest_token)
    import lol_live
    lol_live.guarda(payload.model_dump())
    return {"ok": True}


# ── Reminders da Apple, pelo agente do Mac ───────────────────────
# A NAS não fala com a Apple. O agente lê os Reminders no Mac (EventKit), manda-os
# para aqui, a NAS decide o que muda de cada lado (`apple_reminders.planeia`, a
# mesma regra de sempre) e devolve o que o Mac tem de escrever. Para ser
# imediato, o agente fica pendurado em `/reminders/wait` e acorda assim que
# alguma coisa muda nas Listas.

class RemindersPlanoIn(BaseModel):
    dump: dict


class RemindersAplicadoIn(BaseModel):
    ops: dict
    result: dict
    conta: dict = {}


class RemindersErroIn(BaseModel):
    error: str


def _impressao_atual() -> str:
    import apple_reminders
    from database import SessionLocal
    db = SessionLocal()
    try:
        return f"{apple_reminders.impressao(db)}:{apple_reminders.pedidos()}"
    finally:
        db.close()


@router.post("/reminders/plan")
def reminders_plano(payload: RemindersPlanoIn, db: Session = Depends(get_db),
                    x_ingest_token: str | None = Header(default=None)):
    _check_token(x_ingest_token)
    import apple_reminders
    with apple_reminders._lock:
        ops, conta = apple_reminders.planeia(db, payload.dump)
    if not any(ops.values()):
        apple_reminders.regista_passagem_do_agente(True, apple_reminders.resumo(conta))
    return {"ops": ops, "conta": conta, "fp": _impressao_atual()}


@router.post("/reminders/applied")
def reminders_aplicado(payload: RemindersAplicadoIn, db: Session = Depends(get_db),
                       x_ingest_token: str | None = Header(default=None)):
    _check_token(x_ingest_token)
    import apple_reminders
    with apple_reminders._lock:
        extra = apple_reminders.regista_aplicado(db, payload.ops, payload.result)
    conta = {**payload.conta, **extra}
    apple_reminders.regista_passagem_do_agente(not extra.get("erros"), apple_reminders.resumo(conta))
    return {"ok": True, "fp": _impressao_atual()}


@router.post("/reminders/error")
def reminders_erro(payload: RemindersErroIn, x_ingest_token: str | None = Header(default=None)):
    """O Mac não conseguiu ler os Reminders (quase sempre: sem autorização)."""
    _check_token(x_ingest_token)
    import apple_reminders
    apple_reminders.regista_passagem_do_agente(False, payload.error[:300])
    return {"ok": True}


@router.get("/reminders/wait")
async def reminders_espera(since: str = "", timeout: float = 25.0,
                           x_ingest_token: str | None = Header(default=None)):
    """Responde assim que as Listas mudarem em relação a `since`, ou ao fim de
    `timeout` segundos. Abaixo dos 60s do reverse proxy da NAS."""
    import asyncio
    from starlette.concurrency import run_in_threadpool
    _check_token(x_ingest_token)
    fim = asyncio.get_event_loop().time() + max(1.0, min(timeout, 50.0))
    while True:
        fp = await run_in_threadpool(_impressao_atual)
        if fp != since:
            return {"changed": True, "fp": fp}
        if asyncio.get_event_loop().time() >= fim:
            return {"changed": False, "fp": fp}
        await asyncio.sleep(1.0)
