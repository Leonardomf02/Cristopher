"""Planeador de dia: encaixa atividades reutilizáveis a partir da hora de acordar.

Dois motores:
  • local — algoritmo determinístico (âncoras fixas → janelas por prioridade → flex encolhe).
  • ai    — manda as regras ao agente iaedu.pt e faz parse do horário devolvido.
"""
import json
from datetime import date as _date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import DayActivity, DayPlanRecord, Event
from schemas import (
    DayActivityCreate, DayActivityUpdate, DayActivityOut,
    DayPlanRequest, DayPlanResponse, DayPlanSummary, PlanBlock, PlanBlockCreate, PlanBlockUpdate,
    EnsureTodayResponse,
)
from ai_config import ask_agent_async, extract_json

router = APIRouter(prefix="/api/day-planner", tags=["Day Planner"])

WINDOWS = {"any", "morning", "afternoon", "evening", "before_lunch", "after_lunch", "produtivo"}

# Atividades semeadas no 1º acesso (as que o utilizador descreveu).
_SEED = [
    dict(name="Pequeno-almoço", icon="🥐", color="#F59E0B", duration_min=30, window="morning", priority=3, position=0),
    dict(name="Gym", icon="🏋️", color="#EF4444", duration_min=120, window="before_lunch", priority=2, position=1),
    dict(name="Almoço", icon="🍽️", color="#F59E0B", duration_min=60, window="afternoon", fixed_time="13:00", priority=3, position=2),
    dict(name="Trabalho", icon="💼", color="#3B82F6", duration_min=240, duration_max=360, window="any", priority=2, splittable=True, chunk_max=120, position=3),
    dict(name="League of Legends", icon="🎮", color="#8B5CF6", duration_min=120, window="any", priority=1, position=4),
    dict(name="Jantar", icon="🍝", color="#F59E0B", duration_min=60, window="evening", fixed_time="20:00", priority=3, position=5),
    dict(name="Série", icon="📺", color="#EC4899", duration_min=60, window="evening", priority=0, position=6),
]


# ── helpers de tempo (minutos desde meia-noite; podem passar de 24h) ──

def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _fmt(mins: int) -> str:
    mins %= 24 * 60
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _seed_if_empty(db: Session):
    if db.query(func.count(DayActivity.id)).scalar() == 0:
        for s in _SEED:
            db.add(DayActivity(**s))
        db.commit()


# ── As horas em que ele produz mesmo ──────────────────────────────
#
# As janelas eram do relógio ("de manhã", "à tarde") e o Trabalho estava em
# "qualquer hora", por isso caía onde calhasse. Mas a app sabe há meses quando é
# que ele escreve código: às 15h e das 22h à 1h. A janela `produtivo` põe o
# trabalho onde ele historicamente trabalha, em vez de onde parece bem.

MIN_DIAS_PARA_CONFIAR = 10


def horas_produtivas(db: Session, dias: int = 120) -> dict:
    """As horas do dia em que ele costuma programar, por peso.

    Fonte: WakaTime por hora (o que é mesmo código escrito). Devolve as horas
    que valem a maior parte do tempo, para o planeador as poder usar como
    janela. `enough` a False quando ainda não há histórico que chegue."""
    from datetime import timedelta
    from models import WakaHourDay

    desde = _date.today() - timedelta(days=dias)
    linhas = (
        db.query(WakaHourDay.hour, func.sum(WakaHourDay.seconds), func.count(func.distinct(WakaHourDay.day)))
        .filter(WakaHourDay.day >= desde, WakaHourDay.seconds > 0)
        .group_by(WakaHourDay.hour)
        .all()
    )
    dias_com_dados = (
        db.query(func.count(func.distinct(WakaHourDay.day)))
        .filter(WakaHourDay.day >= desde, WakaHourDay.seconds > 0)
        .scalar() or 0
    )
    por_hora = {int(h): int(s or 0) for h, s, _ in linhas}
    total = sum(por_hora.values())
    if dias_com_dados < MIN_DIAS_PARA_CONFIAR or total <= 0:
        return {"enough": False, "days": int(dias_com_dados), "hours": [], "top": []}

    # As horas que juntas valem 70% do código feito — o resto é ruído de dias soltos.
    ordenadas = sorted(por_hora.items(), key=lambda kv: -kv[1])
    acumulado, melhores = 0, []
    for hora, seg in ordenadas:
        melhores.append(hora)
        acumulado += seg
        if acumulado >= total * 0.70:
            break

    return {
        "enough": True,
        "days": int(dias_com_dados),
        "total_seconds": total,
        "hours": [
            {"hour": h, "seconds": por_hora.get(h, 0),
             "share": round(por_hora.get(h, 0) / total * 100, 1),
             "top": h in melhores}
            for h in range(24)
        ],
        "top": sorted(melhores),
    }


# Duas horas boas separadas por uma pausa curta são o mesmo período de trabalho;
# separadas por meia tarde já são dois períodos diferentes.
_JUNTA_ATE_H = 2


def _janela_produtiva(db: Session, wake: int, day_end: int) -> Optional[tuple[int, int]]:
    """O melhor período contínuo para trabalhar, em minutos do dia dele.

    Os picos dele são dois (a tarde e a noite) e apanhar do primeiro ao último
    dava "12:00 às 01:00" — o dia inteiro, que não é janela nenhuma. Aqui
    agrupam-se as horas boas em períodos e escolhe-se o que pesa mais.
    None quando ainda não há histórico para confiar."""
    dados = horas_produtivas(db)
    if not dados["enough"] or not dados["top"]:
        return None
    peso = {h["hour"]: h["seconds"] for h in dados["hours"]}

    # As horas dele passam da meia-noite (programa às 22h-1h). Cada hora do
    # relógio é trazida para dentro do dia acordado antes de se olhar ao alcance,
    # senão a 1h da manhã parecia estar antes de ele acordar.
    momentos: list[tuple[int, int]] = []
    for h in dados["top"]:
        for cand in (h * 60, h * 60 + 24 * 60):
            if wake <= cand < day_end:
                momentos.append((cand, peso.get(h, 0)))
                break
    if not momentos:
        return None
    momentos.sort()

    periodos: list[tuple[int, int, int]] = []       # (início, fim, peso)
    ini, fim, total = momentos[0][0], momentos[0][0] + 60, momentos[0][1]
    for minuto, seg in momentos[1:]:
        if minuto - fim <= _JUNTA_ATE_H * 60:
            fim, total = minuto + 60, total + seg
        else:
            periodos.append((ini, fim, total))
            ini, fim, total = minuto, minuto + 60, seg
    periodos.append((ini, fim, total))

    melhor = max(periodos, key=lambda p: p[2])
    return max(wake, melhor[0]), min(day_end, melhor[1])


# ── CRUD ─────────────────────────────────────────────────────────

@router.get("/activities", response_model=list[DayActivityOut])
def list_activities(db: Session = Depends(get_db)):
    _seed_if_empty(db)
    return db.query(DayActivity).order_by(DayActivity.position, DayActivity.id).all()


@router.post("/activities", response_model=DayActivityOut)
def create_activity(data: DayActivityCreate, db: Session = Depends(get_db)):
    if data.window not in WINDOWS:
        raise HTTPException(422, f"window inválida: {data.window}")
    a = DayActivity(**data.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.put("/activities/{activity_id}", response_model=DayActivityOut)
def update_activity(activity_id: int, data: DayActivityUpdate, db: Session = Depends(get_db)):
    a = db.query(DayActivity).filter(DayActivity.id == activity_id).first()
    if not a:
        raise HTTPException(404, "Atividade não encontrada")
    fields = data.model_dump(exclude_unset=True)
    if "window" in fields and fields["window"] not in WINDOWS:
        raise HTTPException(422, f"window inválida: {fields['window']}")
    for k, v in fields.items():
        setattr(a, k, v)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int, db: Session = Depends(get_db)):
    a = db.query(DayActivity).filter(DayActivity.id == activity_id).first()
    if not a:
        raise HTTPException(404, "Atividade não encontrada")
    db.delete(a)
    db.commit()
    return {"ok": True}


# ── Motor local ──────────────────────────────────────────────────

def _hora_do_dia(relogio: int, wake: int, day_end: int, offset_tipico: int) -> int:
    """Uma hora do relógio (almoço às 13h, jantar às 20h) trazida para o dia acordado.

    Quem acorda às 8h almoça às 13h; quem acorda às 21h não vai almoçar 16h depois
    — nesse caso a refeição passa a contar-se a partir do acordar."""
    for cand in (relogio, relogio + 24 * 60, relogio + 48 * 60):
        if wake <= cand < day_end:
            return cand
    return wake + offset_tipico


def _refeicoes(activities: list[DayActivity], wake: int, day_end: int) -> tuple[int, int]:
    """Referências de almoço e jantar. Se o que está marcado para antes do almoço
    não cabe (acordar tarde + gym de 2h), o almoço cede — mais vale almoçar às
    13h45 do que ficar sem gym, que era o que acontecia."""
    dia = max(60, day_end - wake)
    almoco = _hora_do_dia(13 * 60, wake, day_end, offset_tipico=180)
    almoco = min(max(almoco, wake + 120), wake + max(180, int(dia * 0.35)))

    precisa_antes = sum(
        (a.duration_min or 0) for a in activities
        if not a.fixed_time and a.window in ("morning", "before_lunch")
    )
    if precisa_antes:
        almoco = max(almoco, wake + precisa_antes + 15)

    jantar = _hora_do_dia(20 * 60, wake, day_end, offset_tipico=9 * 60)
    jantar = max(jantar, almoco + 150)
    return min(almoco, day_end - 60), min(jantar, day_end - 60)


def _window_bounds(window: str, wake: int, day_end: int, lunch: int, dinner: int,
                   produtiva: Optional[tuple[int, int]] = None) -> tuple[int, int]:
    """Intervalo [início, fim] em minutos onde a janela permite começar.

    As janelas são do DIA DELE, não do relógio: quem acorda às 11h tem "manhã"
    das 11h às 14h. Com horas de relógio fixas (manhã = até às 12h), acordar tarde
    deixava o pequeno-almoço, o gym e o almoço sem sítio nenhum."""
    dia = max(60, day_end - wake)
    if window == "morning":
        return wake, min(wake + min(180, int(dia * 0.30)), day_end)
    if window == "afternoon":
        return min(lunch, day_end), min(max(lunch + 180, dinner), day_end)
    if window == "evening":
        return min(dinner, day_end), day_end
    if window == "before_lunch":
        return wake, max(wake + 30, lunch)
    if window == "after_lunch":
        return min(lunch, day_end), day_end
    if window == "produtivo":
        # Sem histórico que chegue vale mais o dia todo do que uma janela inventada.
        return produtiva if produtiva else (wake, day_end)
    return wake, day_end  # any


def _plan_local(activities: list[DayActivity], wake: int, day_end: int,
                produtiva: Optional[tuple[int, int]] = None) -> tuple[list[dict], list[str]]:
    """Layout cronológico: coloca âncoras fixas e depois avança um cursor pelo dia,
    escolhendo em cada buraco a atividade elegível de maior prioridade. Atividades
    splittable ocupam vários blocos (≤ chunk_max) espalhados pelos buracos."""
    def ancora(hhmm: str, fallback_frac: float) -> int:
        """Hora fixa trazida para dentro do dia acordado. Se o dia dele começa às
        21h, um almoço marcado para as 13h só faz sentido no dia seguinte; e se
        nem assim couber, cai numa fracção do dia (senão a âncora desaparecia)."""
        base = _to_min(hhmm)
        for cand in (base, base + 24 * 60, base - 24 * 60):
            if wake <= cand < day_end:
                return cand
        return wake + int((day_end - wake) * fallback_frac)

    # Hora de almoço de referência: fixed_time de uma refeição "almoço", senão a meio.
    lunch, dinner = _refeicoes(activities, wake, day_end)
    for a in activities:
        if a.fixed_time and "almoç" in a.name.lower():
            lunch = ancora(a.fixed_time, 0.30)
        if a.fixed_time and "jantar" in a.name.lower():
            dinner = ancora(a.fixed_time, 0.70)

    busy: list[tuple[int, int]] = []
    blocks: list[dict] = []

    def place(a: DayActivity, s: int, e: int, note: str = ""):
        busy.append((s, e))
        blocks.append({"activity_id": a.id, "name": a.name, "icon": a.icon,
                       "color": a.color, "start": s, "end": e, "note": note})

    # 1) âncoras (hora fixa) reservam o slot
    for a in (x for x in activities if x.fixed_time):
        frac = 0.30 if "almoç" in a.name.lower() else 0.75
        s = ancora(a.fixed_time, frac)
        fora = _fmt(s) != a.fixed_time
        place(a, s, min(s + a.duration_min, day_end),
              "fora da hora habitual (acordaste tarde)" if fora else "")

    # 2) tarefas restantes: cada uma com o que falta colocar (`rem`)
    tasks = []
    for a in (x for x in activities if not x.fixed_time):
        lo, hi = _window_bounds(a.window, wake, day_end, lunch, dinner, produtiva)
        # Uma janela mais curta do que a própria actividade deixava-a por
        # colocar: vale mais alargar as pontas do que não a planear de todo.
        if hi - lo < a.duration_min:
            falta = a.duration_min - (hi - lo)
            lo, hi = max(wake, lo - falta // 2), min(day_end, hi + falta - falta // 2)
        tasks.append({"a": a, "lo": lo, "hi": hi, "rem": (a.duration_max or a.duration_min), "feito": 0})
    split_count: dict[int, int] = {}

    def covering_end(t: int):
        for bs, be in busy:
            if bs <= t < be:
                return be
        return None

    def next_busy_start(t: int) -> int:
        after = [bs for bs, be in busy if bs >= t]
        return min(after) if after else day_end

    def passo(cursor: int) -> int:
        """Avança o cursor uma vez: coloca a melhor tarefa aqui, ou salta o buraco."""
        cov = covering_end(cursor)
        if cov is not None:               # dentro de uma âncora → saltar
            return cov
        free_end = next_busy_start(cursor)
        avail = free_end - cursor
        if avail <= 0:
            return free_end

        def room(t):
            return min(avail, t["hi"] - cursor)

        def fits(t):
            r = room(t)
            if r <= 0 or t["lo"] > cursor or cursor >= t["hi"]:
                return False
            if t["a"].splittable:
                # Um bloco de 15min de trabalho não serve a ninguém; só se aceita
                # um pedaço curto quando ainda falta chegar ao mínimo do dia.
                minimo = 30 if t["feito"] >= t["a"].duration_min else min(30, t["rem"])
                return r >= min(minimo, t["rem"]) and r >= 15
            return r >= t["a"].duration_min            # inteira (flex pode encolher)

        cand = [t for t in tasks if t["rem"] > 0 and fits(t)]
        if not cand:
            # Buraco inútil → salta. Mas se houver uma tarefa cuja janela abre
            # ainda dentro deste buraco, salta só até lá: com `free_end` a valer
            # o fim do dia, o cursor saltava por cima do jantar e ele ficava por
            # colocar sempre que a tarde acabava antes das 20h.
            abrem = [t["lo"] for t in tasks if t["rem"] > 0 and cursor < t["lo"] < free_end]
            return min(abrem) if abrem else free_end

        # Se uma refeição (ou outra coisa mais prioritária) abre a janela já a
        # seguir, não vale a pena meter aqui trabalho e empurrá-la para mais tarde.
        melhor = max(t["a"].priority for t in cand)
        proximas = [t["lo"] for t in tasks
                    if t["rem"] > 0 and t["a"].priority > melhor and cursor < t["lo"] <= cursor + 30]
        if proximas:
            return min(proximas)
        # maior prioridade; janela que fecha mais cedo (mais urgente); mais por fazer
        cand.sort(key=lambda t: (-t["a"].priority, t["hi"], -t["rem"]))
        t = cand[0]
        a = t["a"]
        r = room(t)
        if a.splittable:
            dur = min(a.chunk_max or 120, t["rem"], r)
            split_count[a.id] = split_count.get(a.id, 0) + 1
            place(a, cursor, cursor + dur, f"bloco {split_count[a.id]}")
            t["rem"] -= dur
        else:
            dur = min(t["rem"], r)                      # flex encolhe até caber
            note = "duração reduzida" if (a.duration_max and dur < a.duration_max) else ""
            place(a, cursor, cursor + dur, note)
            t["rem"] = 0                                # não-splittable → 1 bloco só
        t["feito"] += dur
        return cursor + dur

    def varre() -> None:
        cursor, guard = wake, 0
        while cursor < day_end and any(t["rem"] > 0 for t in tasks) and guard < 2000:
            guard += 1
            cursor = passo(cursor)

    varre()

    # Se o dia não deu para a janela boa (acordou tarde, o gym comeu a tarde), mais
    # vale trabalhar a uma hora pior do que não trabalhar. Mas só até ao mínimo do
    # dia: esticar até ao máximo fora da janela enchia a noite de trabalho e
    # deixava o jantar por colocar.
    sobrou = [t for t in tasks
              if t["a"].window == "produtivo" and t["feito"] < t["a"].duration_min]
    if sobrou:
        for t in sobrou:
            t["lo"], t["hi"] = wake, day_end
            t["rem"] = t["a"].duration_min - t["feito"]
        varre()

    # Uma actividade flexível que já cumpriu o mínimo do dia não está "por
    # colocar" — só não esticou até ao máximo, que é o que "flexível" quer dizer.
    unplaced = [t["a"].name for t in tasks if t["rem"] > 0 and t["feito"] < t["a"].duration_min]
    blocks.sort(key=lambda b: b["start"])
    return blocks, unplaced


def _fill_free_time(blocks: list[dict], wake: int, day_end: int, min_gap: int = 15) -> list[dict]:
    """Preenche os buracos entre atividades (e o resto do dia até `day_end`) com blocos
    de 'Tempo livre', para o plano cobrir as ~16h do dia sem espaços vazios."""
    def free(s: int, e: int) -> dict:
        return {"activity_id": None, "name": "Tempo livre", "icon": "🌿",
                "color": "#6B7280", "start": s, "end": e, "note": ""}

    busy = sorted((b["start"], b["end"]) for b in blocks)
    out = list(blocks)
    cursor = wake
    for s, e in busy:
        if s - cursor >= min_gap:
            out.append(free(cursor, s))
        cursor = max(cursor, e)
    if day_end - cursor >= min_gap:
        out.append(free(cursor, day_end))
    out.sort(key=lambda b: b["start"])
    return out


# ── Motor IA ─────────────────────────────────────────────────────

_WIN_PT = {"any": "qualquer hora", "morning": "de manhã", "afternoon": "à tarde",
           "evening": "à noite", "before_lunch": "antes do almoço", "after_lunch": "depois do almoço",
           "produtivo": "nas horas em que rendo mais"}


async def _plan_ai(activities: list[DayActivity], wake: int, day_end: int, preferences: str = "",
                   produtiva: Optional[tuple[int, int]] = None):
    linhas = []
    for a in activities:
        dur = f"{a.duration_min}min" if not a.duration_max else f"{a.duration_min}–{a.duration_max}min (flexível)"
        extra = f", hora fixa {a.fixed_time}" if a.fixed_time else ""
        if a.splittable:
            extra += f", pode ser dividida em vários blocos (máx {a.chunk_max or 120}min cada)"
        linhas.append(f"- {a.name}: {dur}, {_WIN_PT.get(a.window, a.window)}, prioridade {a.priority}{extra}")
    pref_block = f"\nPreferências minhas (respeita-as):\n{preferences.strip()}\n" if preferences.strip() else ""
    # A IA não tem como adivinhar as horas dele; o histórico de código tem.
    janela_block = (
        f"\nPelo meu histórico, rendo mais entre as {_fmt(produtiva[0])} e as {_fmt(produtiva[1])} — "
        "põe aí o que exige cabeça.\n" if produtiva else ""
    )
    prompt = (
        f"Planeia-me o dia. Acordo às {_fmt(wake)} e quero deitar-me por volta das {_fmt(day_end)}.\n"
        f"Atividades a encaixar:\n" + "\n".join(linhas) + pref_block + janela_block + "\n"
        "Regras: respeita as horas fixas e as janelas; encaixa primeiro as de maior prioridade; "
        "atividades divisíveis podem aparecer em vários blocos ao longo do dia; "
        "não sobreponhas atividades; deixa transições realistas.\n"
        "Responde APENAS com JSON no formato:\n"
        '{"blocks":[{"name":"...","start":"HH:MM","end":"HH:MM","note":"..."}],'
        '"unplaced":["..."],"advice":"1-2 frases de conselho"}'
    )
    text = await ask_agent_async(prompt, feature="planeador")
    data = extract_json(text) if text else None
    by_name = {a.name.lower(): a for a in activities}
    blocks: list[dict] = []
    if isinstance(data, dict):
        for b in data.get("blocks", []):
            if not isinstance(b, dict) or "start" not in b or "end" not in b:
                continue
            a = by_name.get(str(b.get("name", "")).lower())
            blocks.append({
                "activity_id": a.id if a else None,
                "name": b.get("name", ""),
                "icon": a.icon if a else "⏱️",
                "color": a.color if a else "#3B82F6",
                "start": _to_min(b["start"]),
                "end": _to_min(b["end"]),
                "note": b.get("note", ""),
            })
        blocks.sort(key=lambda x: x["start"])
        return blocks, [str(u) for u in data.get("unplaced", [])], str(data.get("advice", ""))
    return None, [], ""


# ── Endpoint de planeamento ──────────────────────────────────────

@router.post("/plan", response_model=DayPlanResponse)
async def make_plan(req: DayPlanRequest, db: Session = Depends(get_db)):
    plan_date = req.plan_date or _date.today()
    # As horas do dia dele já são medidas pelo relógio — pedir-lhas outra vez era
    # pedir que confirmasse à mão o que a app sabe melhor do que ele.
    wake_time = req.wake_time or _guess_wake_time(db, plan_date)
    day_end_time = req.day_end or _guess_bedtime(db, plan_date)
    try:
        wake = _to_min(wake_time)
    except (ValueError, AttributeError):
        raise HTTPException(422, "wake_time inválido (usa HH:MM)")

    q = db.query(DayActivity).filter(DayActivity.enabled == True)
    if req.activity_ids:
        q = q.filter(DayActivity.id.in_(req.activity_ids))
    activities = q.order_by(DayActivity.position, DayActivity.id).all()
    if not activities:
        raise HTTPException(400, "Sem atividades ativas para planear")

    # Sem hora de deitar → dia de 16h a partir do acordar (com tempo livre no fim).
    day_end = _to_min(day_end_time) if day_end_time else wake + 16 * 60
    if day_end <= wake:
        day_end += 24 * 60  # deitar depois da meia-noite

    produtiva = _janela_produtiva(db, wake, day_end)

    advice = ""
    if req.mode == "ai":
        result = await _plan_ai(activities, wake, day_end, req.preferences or "", produtiva)
        if result[0] is None:
            # IA indisponível/parse falhou → cai no local para não devolver vazio
            blocks, unplaced = _plan_local(activities, wake, day_end, produtiva)
            advice = "IA indisponível — usei o planeador local."
        else:
            blocks, unplaced, advice = result
    else:
        blocks, unplaced = _plan_local(activities, wake, day_end, produtiva)

    if produtiva and any(a.window == "produtivo" for a in activities):
        nota = f"As horas em que costumas render vão das {_fmt(produtiva[0])} às {_fmt(produtiva[1])}."
        advice = f"{advice} {nota}".strip() if advice else nota

    blocks = _fill_free_time(blocks, wake, day_end)

    out_blocks = [PlanBlock(activity_id=b["activity_id"], name=b["name"], icon=b["icon"],
                            color=b["color"], start=_fmt(b["start"]), end=_fmt(b["end"]),
                            note=b["note"]) for b in blocks]

    if req.save:
        rec = db.query(DayPlanRecord).filter(DayPlanRecord.plan_date == plan_date).first()
        if not rec:
            rec = DayPlanRecord(plan_date=plan_date)
            db.add(rec)
        else:
            for old in json.loads(rec.blocks_json or "[]"):   # o plano vai ser substituído
                _drop_event(db, old)
        rec.wake_time = wake_time
        rec.day_end = day_end_time
        rec.mode = req.mode
        rec.preferences = req.preferences or ""
        rec.advice = advice
        rec.blocks_json = json.dumps([b.model_dump() for b in out_blocks])
        rec.unplaced_json = json.dumps(unplaced)
        db.commit()

    return DayPlanResponse(mode=req.mode, wake_time=wake_time, blocks=out_blocks,
                           unplaced=unplaced, advice=advice, plan_date=plan_date,
                           day_end=day_end_time, preferences=req.preferences or "")


# ── Plano automático da manhã ────────────────────────────────────

# Um plano feito logo depois da meia-noite ainda não sabe a que horas ele vai
# acordar. Antes herdava a hora do plano anterior — e um valor mau (21:07) passava
# de dia para dia, deixando o pequeno-almoço, o gym e o almoço sem sítio.
WAKE_MIN, WAKE_MAX = 4 * 60, 15 * 60


def _plausivel(hhmm: Optional[str]) -> bool:
    try:
        return hhmm is not None and WAKE_MIN <= _to_min(str(hhmm)[:5]) <= WAKE_MAX
    except (ValueError, AttributeError):
        return False


def _guess_wake_time(db: Session, plan_date: _date) -> str:
    """Hora de acordar: a real do dia; senão a mediana das últimas semanas."""
    from datetime import timedelta
    from models import SleepEntry

    entry = (
        db.query(SleepEntry)
        .filter(SleepEntry.date == plan_date)
        .order_by(SleepEntry.id.desc())
        .first()
    )
    if entry and entry.wake_time:
        return str(entry.wake_time)[:5]

    recentes = [
        _to_min(str(e.wake_time)[:5])
        for e in db.query(SleepEntry)
        .filter(SleepEntry.date >= plan_date - timedelta(days=30), SleepEntry.date < plan_date)
        .order_by(SleepEntry.date.desc()).limit(21).all()
        if _plausivel(e.wake_time)
    ]
    if len(recentes) >= 3:
        recentes.sort()
        return _fmt(recentes[len(recentes) // 2])

    last = (
        db.query(DayPlanRecord)
        .filter(DayPlanRecord.plan_date < plan_date)
        .order_by(DayPlanRecord.plan_date.desc())
        .first()
    )
    if last and _plausivel(last.wake_time):
        return last.wake_time
    return "09:00"


def _guess_bedtime(db: Session, plan_date: _date) -> Optional[str]:
    """A que horas ele se costuma deitar, pelas noites medidas.

    A hora de deitar é do outro lado da meia-noite quase sempre, por isso a
    mediana faz-se na escala contínua (01:30 conta como 25:30) — senão a mediana
    de quem se deita às 23h e à 01h dava meio-dia."""
    from datetime import timedelta
    from models import SleepEntry

    minutos = []
    for e in (db.query(SleepEntry)
              .filter(SleepEntry.date >= plan_date - timedelta(days=30),
                      SleepEntry.date <= plan_date, SleepEntry.bedtime.isnot(None))
              .order_by(SleepEntry.date.desc()).limit(21).all()):
        try:
            m = _to_min(str(e.bedtime)[:5])
        except (ValueError, AttributeError):
            continue
        minutos.append(m + 24 * 60 if m < 12 * 60 else m)
    if len(minutos) < 3:
        return None
    minutos.sort()
    return _fmt(minutos[len(minutos) // 2] % (24 * 60))


@router.get("/day-bounds")
def day_bounds(db: Session = Depends(get_db)):
    """As horas do dia dele, medidas em vez de perguntadas: a que horas acordou
    hoje e a que horas se costuma deitar."""
    from models import SleepEntry

    hoje = _date.today()
    noite = (db.query(SleepEntry).filter(SleepEntry.date == hoje)
             .order_by(SleepEntry.id.desc()).first())
    deitar = _guess_bedtime(db, hoje)
    return {
        "wake_time": _guess_wake_time(db, hoje),
        "day_end": deitar,
        # Vale a pena separar o que foi medido esta noite do que é o costume dele:
        # numa manhã sem sincronização a hora vem da mediana, e isso deve ver-se.
        "wake_source": (noite.source if noite and noite.wake_time else None) or "estimativa",
        "measured_today": bool(noite and noite.wake_time),
    }


@router.post("/ensure-today", response_model=EnsureTodayResponse)
async def ensure_today(force: bool = False, db: Session = Depends(get_db)):
    """Garante que o dia de hoje já tem plano. Chamado uma vez por dia pela app:
    quem nunca carrega em "Planear" passa a ter o dia montado à mesma."""
    today = _date.today()
    existing = db.query(DayPlanRecord).filter(DayPlanRecord.plan_date == today).first()
    if existing and not force:
        return EnsureTodayResponse(created=False, reason="já existe", plan_date=today)

    _seed_if_empty(db)
    if not db.query(DayActivity).filter(DayActivity.enabled == True).count():
        return EnsureTodayResponse(created=False, reason="sem atividades activas", plan_date=today)

    last = (
        db.query(DayPlanRecord)
        .filter(DayPlanRecord.plan_date < today)
        .order_by(DayPlanRecord.plan_date.desc())
        .first()
    )
    req = DayPlanRequest(
        mode="local",                       # sem custo de IA: isto corre sozinho todos os dias
        # As horas vêm do relógio (ver `make_plan`); a do plano anterior só serve
        # de rede se ele nunca tiver medido uma noite.
        day_end=None,
        preferences=last.preferences if last else "",
        plan_date=today,
        save=True,
    )
    plan = await make_plan(req, db)
    return EnsureTodayResponse(created=True, reason="plano criado", plan_date=today, plan=plan)


@router.get("/productive-hours")
def productive_hours(days: int = 120, db: Session = Depends(get_db)):
    """As horas em que ele costuma programar — o que alimenta a janela `produtivo`."""
    dados = horas_produtivas(db, days)
    if dados["enough"]:
        wake = _to_min(_guess_wake_time(db, _date.today()))
        janela = _janela_produtiva(db, wake, wake + 16 * 60)
        dados["window"] = {"start": _fmt(janela[0]), "end": _fmt(janela[1])} if janela else None
    else:
        dados["window"] = None
        dados["needed_days"] = MIN_DIAS_PARA_CONFIAR
    return dados


# ── Histórico ────────────────────────────────────────────────────

@router.get("/plans", response_model=list[DayPlanSummary])
def list_plans(db: Session = Depends(get_db)):
    recs = db.query(DayPlanRecord).order_by(DayPlanRecord.plan_date.desc()).all()
    return [DayPlanSummary(plan_date=r.plan_date, wake_time=r.wake_time, mode=r.mode,
                           block_count=len(json.loads(r.blocks_json or "[]"))) for r in recs]


def _record_to_response(r: DayPlanRecord) -> DayPlanResponse:
    return DayPlanResponse(
        mode=r.mode, wake_time=r.wake_time,
        blocks=[PlanBlock(**b) for b in json.loads(r.blocks_json or "[]")],
        unplaced=json.loads(r.unplaced_json or "[]"), advice=r.advice or "",
        plan_date=r.plan_date, day_end=r.day_end, preferences=r.preferences or "")


@router.get("/plans/{plan_date}", response_model=DayPlanResponse)
async def get_plan(plan_date: _date, db: Session = Depends(get_db)):
    r = db.query(DayPlanRecord).filter(DayPlanRecord.plan_date == plan_date).first()
    if not r:
        raise HTTPException(404, "Sem plano para essa data")

    # O plano automático é feito de madrugada, antes de se saber a que horas ele
    # acorda. Quando o sono fica registado, refaz-se sozinho — desde que ele ainda
    # não lhe tenha mexido.
    if plan_date == _date.today() and r.mode == "local":
        real = _guess_wake_time(db, plan_date)
        blocos = json.loads(r.blocks_json or "[]")
        intocado = not any(b.get("done") or b.get("event_id") for b in blocos)
        try:
            desvio = abs(_to_min(real) - _to_min(r.wake_time))
        except (ValueError, AttributeError):
            desvio = 0
        if intocado and desvio >= 45:
            plano = await make_plan(DayPlanRequest(
                wake_time=real, mode="local", day_end=r.day_end,
                preferences=r.preferences or "", plan_date=plan_date, save=True,
            ), db)
            return plano

    return _record_to_response(r)


def _load_blocks(db: Session, plan_date: _date, index: int | None = None):
    r = db.query(DayPlanRecord).filter(DayPlanRecord.plan_date == plan_date).first()
    if not r:
        raise HTTPException(404, "Sem plano para essa data")
    blocks = json.loads(r.blocks_json or "[]")
    if index is not None and not 0 <= index < len(blocks):
        raise HTTPException(404, "Bloco inexistente")
    return r, blocks


def _save_blocks(db: Session, r: DayPlanRecord, blocks: list) -> DayPlanResponse:
    """Reordena cronologicamente (blocos depois da meia-noite vão para o fim) e grava.
    Mantém os eventos do calendário alinhados com os blocos já feitos."""
    wake = _to_min(r.wake_time)
    blocks.sort(key=lambda b: _to_min(b["start"]) + (24 * 60 if _to_min(b["start"]) < wake else 0))
    for b in blocks:
        if b.get("done") and b.get("event_id"):
            ev = db.query(Event).filter(Event.id == b["event_id"]).first()
            if ev:
                ev.title = f"{b.get('icon', '')} {b['name']}".strip()
                ev.start_time, ev.end_time = b["start"], b["end"]
                ev.color = b.get("color", ev.color)
    r.blocks_json = json.dumps(blocks)
    db.commit()
    db.refresh(r)
    return _record_to_response(r)


def _add_event(db: Session, plan_date: _date, b: dict) -> int:
    """Cria o evento no calendário para um bloco dado como feito."""
    ev = Event(
        title=f"{b.get('icon', '')} {b['name']}".strip(),
        description="Planeador do dia",
        date=plan_date,
        start_time=b["start"],
        end_time=b["end"],
        event_type="fixed",
        category="general",
        color=b.get("color", "#3B82F6"),
        completed=True,
    )
    db.add(ev)
    db.flush()          # precisamos do id antes do commit
    return ev.id


def _drop_event(db: Session, b: dict) -> None:
    """Remove o evento associado ao bloco (se existir) e limpa a referência."""
    ev_id = b.pop("event_id", None)
    if ev_id:
        ev = db.query(Event).filter(Event.id == ev_id).first()
        if ev:
            db.delete(ev)


def _check_time(value: str, field: str) -> None:
    try:
        _to_min(value)
    except (ValueError, AttributeError):
        raise HTTPException(422, f"{field} inválido (usa HH:MM)")


@router.post("/plans/{plan_date}/blocks", response_model=DayPlanResponse)
def add_block(plan_date: _date, data: PlanBlockCreate, db: Session = Depends(get_db)):
    """Acrescenta um bloco solto ao horário, sem passar por uma atividade guardada."""
    _check_time(data.start, "start")
    _check_time(data.end, "end")
    if data.start == data.end:
        raise HTTPException(422, "O bloco tem de ter duração")

    r = db.query(DayPlanRecord).filter(DayPlanRecord.plan_date == plan_date).first()
    if not r:                                  # ainda não há plano nesse dia → nasce deste bloco
        r = DayPlanRecord(plan_date=plan_date, wake_time=data.start, mode="manual",
                          blocks_json="[]", unplaced_json="[]")
        db.add(r)
        db.flush()

    blocks = json.loads(r.blocks_json or "[]")
    blocks.append({"activity_id": None, "name": data.name, "icon": data.icon, "color": data.color,
                   "start": data.start, "end": data.end, "note": data.note, "done": False})
    return _save_blocks(db, r, blocks)


@router.post("/plans/{plan_date}/blocks/{index}/toggle", response_model=DayPlanResponse)
def toggle_block(plan_date: _date, index: int, db: Session = Depends(get_db)):
    """Marca/desmarca um bloco como feito. Marcar cria o evento no calendário;
    desmarcar apaga-o."""
    r, blocks = _load_blocks(db, plan_date, index)
    b = blocks[index]
    b["done"] = not b.get("done", False)
    if b["done"]:
        b["event_id"] = _add_event(db, plan_date, b)
    else:
        _drop_event(db, b)
    return _save_blocks(db, r, blocks)


@router.put("/plans/{plan_date}/blocks/{index}", response_model=DayPlanResponse)
def update_block(plan_date: _date, index: int, data: PlanBlockUpdate, db: Session = Depends(get_db)):
    """Edita um bloco do plano (horas, nome ou nota)."""
    r, blocks = _load_blocks(db, plan_date, index)
    fields = data.model_dump(exclude_unset=True)
    for key in ("start", "end"):
        if fields.get(key) is not None:
            try:
                _to_min(fields[key])
            except (ValueError, AttributeError):
                raise HTTPException(422, f"{key} inválido (usa HH:MM)")
    blocks[index].update({k: v for k, v in fields.items() if v is not None})
    if blocks[index]["start"] == blocks[index]["end"]:
        raise HTTPException(422, "O bloco tem de ter duração")
    return _save_blocks(db, r, blocks)


@router.delete("/plans/{plan_date}/blocks/{index}", response_model=DayPlanResponse)
def delete_block(plan_date: _date, index: int, db: Session = Depends(get_db)):
    r, blocks = _load_blocks(db, plan_date, index)
    _drop_event(db, blocks[index])       # não deixar o evento órfão no calendário
    blocks.pop(index)
    return _save_blocks(db, r, blocks)


@router.post("/plans/{plan_date}/blocks/{index}/reorder/{new_index}", response_model=DayPlanResponse)
def reorder_block(plan_date: _date, index: int, new_index: int, db: Session = Depends(get_db)):
    """Recoloca um bloco noutra posição da lista. As durações de cada bloco e as folgas
    de cada posição mantêm-se, por isso o dia ocupa exatamente o mesmo intervalo."""
    r, blocks = _load_blocks(db, plan_date, index)
    if not 0 <= new_index < len(blocks):
        raise HTTPException(400, "Posição inválida")
    if new_index == index:
        return _record_to_response(r)

    wake = _to_min(r.wake_time)

    def absm(t: str) -> int:                        # minutos desde a meia-noite do dia do acordar
        m = _to_min(t)
        return m + 24 * 60 if m < wake else m

    durs = [absm(b["end"]) - absm(b["start"]) for b in blocks]
    starts = [absm(b["start"]) for b in blocks]
    # folga que precede cada posição (a da 1ª posição é o próprio início do dia)
    gaps = [0] + [starts[i] - (starts[i - 1] + durs[i - 1]) for i in range(1, len(blocks))]

    items = list(zip(blocks, durs))
    items.insert(new_index, items.pop(index))

    cur = starts[0]
    for pos, (b, d) in enumerate(items):
        cur += gaps[pos]
        b["start"], b["end"] = _fmt(cur), _fmt(cur + d)
        cur += d

    return _save_blocks(db, r, [b for b, _ in items])


@router.delete("/plans/{plan_date}")
def delete_plan(plan_date: _date, db: Session = Depends(get_db)):
    r = db.query(DayPlanRecord).filter(DayPlanRecord.plan_date == plan_date).first()
    if not r:
        raise HTTPException(404, "Sem plano para essa data")
    db.delete(r)
    db.commit()
    return {"ok": True}


# ── Helpers para os avisos automáticos ───────────────────────────

def today_blocks(db: Session) -> list[dict]:
    """Blocos do plano de hoje (lista vazia se não houver plano)."""
    rec = db.query(DayPlanRecord).filter(DayPlanRecord.plan_date == _date.today()).first()
    if not rec:
        return []
    try:
        return json.loads(rec.blocks_json or "[]")
    except json.JSONDecodeError:
        return []


def ensure_today_sync(db: Session) -> list[dict]:
    """Garante plano para hoje sem async: usa o motor local directamente."""
    blocos = today_blocks(db)
    if blocos:
        return blocos
    _seed_if_empty(db)
    activities = (
        db.query(DayActivity)
        .filter(DayActivity.enabled == True)
        .order_by(DayActivity.position, DayActivity.id)
        .all()
    )
    if not activities:
        return []
    hoje = _date.today()
    wake = _to_min(_guess_wake_time(db, hoje))
    ultimo = (
        db.query(DayPlanRecord)
        .filter(DayPlanRecord.plan_date < hoje)
        .order_by(DayPlanRecord.plan_date.desc())
        .first()
    )
    day_end = _to_min(ultimo.day_end) if (ultimo and ultimo.day_end) else wake + 16 * 60
    if day_end <= wake:
        day_end += 24 * 60
    crus, unplaced = _plan_local(activities, wake, day_end)
    crus = _fill_free_time(crus, wake, day_end)
    saida = [
        {"activity_id": b["activity_id"], "name": b["name"], "icon": b["icon"], "color": b["color"],
         "start": _fmt(b["start"]), "end": _fmt(b["end"]), "note": b["note"], "done": False, "event_id": None}
        for b in crus
    ]
    rec = DayPlanRecord(
        plan_date=hoje, wake_time=_fmt(wake), day_end=_fmt(day_end) if ultimo and ultimo.day_end else None,
        mode="local", preferences=(ultimo.preferences if ultimo else "") or "",
        advice="", blocks_json=json.dumps(saida), unplaced_json=json.dumps(unplaced),
    )
    db.add(rec)
    db.commit()
    return saida


# ── Plano vs realidade ────────────────────────────────────────────
# Ninguém pica os blocos como feitos — e não precisa. O tracker de apps já sabe o
# que esteve à frente do ecrã a cada minuto; basta cruzar com o horário planeado.
# Blocos fora do computador (gym, refeições) confirmam-se ao contrário: se o Mac
# esteve parado àquela hora, é sinal de que ele saiu mesmo.

_CATEGORIAS_POR_ACTIVIDADE = {
    "trabalho": {"development", "productivity", "communication"},
    "league of legends": {"gaming"},
    "lol": {"gaming"},
    "série": {"entertainment", "media"},
    "serie": {"entertainment", "media"},
    "estudo": {"development", "productivity"},
}

# Actividades que acontecem longe do computador: aqui "cumprir" é não haver ecrã.
_LONGE_DO_PC = {"gym", "ginásio", "ginasio", "almoço", "almoco", "jantar",
                "pequeno-almoço", "pequeno-almoco", "dormir", "sono", "passear"}


def _esperado(nome: str) -> tuple[Optional[set[str]], bool]:
    n = (nome or "").strip().lower()
    if n in _LONGE_DO_PC:
        return (None, True)
    for chave, cats in _CATEGORIAS_POR_ACTIVIDADE.items():
        if chave in n:
            return (cats, False)
    return (None, False)


@router.get("/plans/{plan_date}/reality")
def plan_reality(plan_date: str, db: Session = Depends(get_db)):
    from datetime import datetime, timedelta
    from models import AppUsageSession, AppCategoryOverride, BrowserTitleRule, LolGame
    from app_categories import categorize, categorize_browser_title, is_browser

    d = _date.fromisoformat(plan_date)
    rec = db.query(DayPlanRecord).filter(DayPlanRecord.plan_date == d).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Sem plano nesse dia")
    blocos = json.loads(rec.blocks_json or "[]")

    sessoes = db.query(AppUsageSession).filter(AppUsageSession.date == d).all()
    # o dia pode esticar para lá da meia-noite: apanha também as do dia seguinte
    sessoes += db.query(AppUsageSession).filter(AppUsageSession.date == d + timedelta(days=1)).all()
    if not sessoes:
        return {"date": plan_date, "tracked": False, "blocks": [], "summary": None}

    overrides = {
        o.bundle_id or o.app_name: o.category
        for o in db.query(AppCategoryOverride).all()
    }
    try:
        regras = {r.pattern: r.category for r in db.query(BrowserTitleRule).all()}
    except Exception:
        regras = {}

    def categoria(s) -> str:
        if s.bundle_id and s.bundle_id in overrides:
            return overrides[s.bundle_id]
        if s.app_name and s.app_name in overrides:
            return overrides[s.app_name]
        if is_browser(s.bundle_id, s.app_name):
            pelo_titulo = categorize_browser_title(getattr(s, "window_title", None), regras, getattr(s, "domain", None))
            if pelo_titulo:
                return pelo_titulo
        return categorize(s.bundle_id, s.app_name)

    def limites(hhmm: str, base: _date) -> datetime:
        return datetime.combine(base, datetime.strptime(hhmm, "%H:%M").time())

    # Fora da janela em que o tracker esteve a correr não se sabe nada — isso é
    # diferente de "não cumpriu". Blocos assim ficam por saber e não contam.
    janelas = sorted((s.start_time, s.end_time) for s in sessoes if s.start_time and s.end_time)

    def ha_tracker(desde: datetime, ate: datetime) -> bool:
        return any(a < ate and b > desde for a, b in janelas)

    jogos = db.query(LolGame).filter(LolGame.date == d).all()

    saida = []
    minutos_planeados = minutos_cumpridos = 0
    for i, b in enumerate(blocos):
        if b.get("name") == "Tempo livre":
            continue
        ini = limites(b["start"], d)
        fim = limites(b["end"], d)
        if fim <= ini:
            fim += timedelta(days=1)      # bloco que atravessa a meia-noite
        planeado = (fim - ini).total_seconds() / 60
        if planeado <= 0:
            continue

        segundos: dict[str, float] = {}
        for s in sessoes:
            if not s.start_time or not s.end_time:
                continue
            sobreposicao = (min(s.end_time, fim) - max(s.start_time, ini)).total_seconds()
            if sobreposicao > 0:
                c = categoria(s)
                segundos[c] = segundos.get(c, 0) + sobreposicao

        cats_esperadas, fora_do_pc = _esperado(b["name"])
        total_ecra = sum(segundos.values()) / 60
        top = sorted(segundos.items(), key=lambda kv: -kv[1])[:3]

        # Sem ecrã pode ser "saiu de casa" ou "o Mac estava desligado". Só se sabe
        # que ele estava por perto se o tracker apanhou coisas antes E depois.
        margem = timedelta(hours=3)
        sem_dados = bool(
            total_ecra == 0
            and not (ha_tracker(ini - margem, ini) and ha_tracker(fim, fim + margem))
        )
        if sem_dados:
            saida.append({
                "index": i, "name": b["name"], "icon": b.get("icon", ""),
                "color": b.get("color", "#6B7280"), "start": b["start"], "end": b["end"],
                "planned_min": round(planeado), "actual_min": None, "pct": None,
                "away_from_pc": fora_do_pc, "screen_min": 0, "top": [], "unknown": True,
            })
            continue

        # O cliente de LoL nem sempre é apanhado pelo tracker; as games registadas
        # servem de prova para os blocos de jogo.
        if cats_esperadas and "gaming" in cats_esperadas and jogos:
            dentro = [g for g in jogos if g.game_hour is not None
                      and ini.hour <= g.game_hour < (fim.hour if fim.hour > ini.hour else 24)]
            if dentro:
                por_games = sum((g.game_duration or 1800) for g in dentro) / 60
                segundos["gaming"] = max(segundos.get("gaming", 0), por_games * 60)
                total_ecra = max(total_ecra, por_games)

        if fora_do_pc:
            # sem ecrã = provavelmente esteve mesmo fora
            cumprido = max(0.0, planeado - total_ecra)
        elif cats_esperadas:
            cumprido = sum(v for c, v in segundos.items() if c in cats_esperadas) / 60
        else:
            cumprido = total_ecra

        cumprido = min(cumprido, planeado)
        minutos_planeados += planeado
        minutos_cumpridos += cumprido

        saida.append({
            "index": i,
            "name": b["name"],
            "icon": b.get("icon", ""),
            "color": b.get("color", "#6B7280"),
            "start": b["start"],
            "end": b["end"],
            "planned_min": round(planeado),
            "actual_min": round(cumprido),
            "pct": round(min(100, cumprido / planeado * 100)) if planeado else 0,
            "away_from_pc": fora_do_pc,
            "screen_min": round(total_ecra),
            "top": [{"category": c, "minutes": round(v / 60)} for c, v in top],
            "unknown": False,
        })

    avaliados = [b for b in saida if not b["unknown"]]
    cumpridos = [b for b in avaliados if b["pct"] >= 60]
    falhados = sorted([b for b in avaliados if b["pct"] < 40], key=lambda b: b["planned_min"], reverse=True)
    por_saber = [b for b in saida if b["unknown"]]
    return {
        "date": plan_date,
        "tracked": True,
        "blocks": saida,
        "summary": {
            "planned_min": round(minutos_planeados),
            "actual_min": round(minutos_cumpridos),
            "pct": round(minutos_cumpridos / minutos_planeados * 100) if minutos_planeados else 0,
            "kept": len(cumpridos),
            "total": len(avaliados),
            "unknown": len(por_saber),
            "unknown_min": round(sum(b["planned_min"] for b in por_saber)),
            "worst": falhados[:3],
        },
    }


# ── Fechar o plano com o que aconteceu mesmo ─────────────────────
# Em nove planos, zero blocos marcados: pedir para carimbar o dia não funciona.
# O tracker já sabe o que ele fez — é a app que fecha o plano.

# A partir de quanto do bloco cumprido se considera feito.
CUMPRIDO_PCT = 60


@router.post("/plans/{plan_date}/close")
def fecha_plano(plan_date: str, db: Session = Depends(get_db)):
    """Marca como feitos os blocos que a realidade confirma."""
    rec = db.query(DayPlanRecord).filter(DayPlanRecord.plan_date == _date.fromisoformat(plan_date)).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Sem plano nesse dia")

    realidade = plan_reality(plan_date, db)
    if not realidade.get("tracked"):
        return {"date": plan_date, "closed": 0, "tracked": False}

    blocos = json.loads(rec.blocks_json or "[]")
    fechados = 0
    for r in realidade["blocks"]:
        i = r["index"]
        if i >= len(blocos) or r["unknown"]:
            continue
        feito = (r["pct"] or 0) >= CUMPRIDO_PCT
        # Nunca desmarca o que ele carimbou à mão.
        if blocos[i].get("done") and blocos[i].get("done_by") != "realidade":
            continue
        if blocos[i].get("done") != feito:
            blocos[i]["done"] = feito
            blocos[i]["done_by"] = "realidade" if feito else None
            fechados += 1
        blocos[i]["actual_min"] = r["actual_min"]

    rec.blocks_json = json.dumps(blocos, ensure_ascii=False)
    db.commit()
    return {"date": plan_date, "closed": fechados, "tracked": True,
            "pct": realidade["summary"]["pct"]}


@router.get("/recurring")
def blocos_repetidos(days: int = Query(30, ge=7, le=180), db: Session = Depends(get_db)):
    """Por cada coisa que ele põe no plano: quantas vezes planeou e quantas fez.

    É a pergunta que o plano diário não respondia — o "Gym" esteve no plano quatro
    dias seguidos e não aconteceu nenhum."""
    desde = _date.today() - timedelta(days=days - 1)
    planos = (
        db.query(DayPlanRecord)
        .filter(DayPlanRecord.plan_date >= desde, DayPlanRecord.plan_date < _date.today())
        .order_by(DayPlanRecord.plan_date)
        .all()
    )
    contagem: dict[str, dict] = {}
    for p in planos:
        try:
            realidade = plan_reality(p.plan_date.isoformat(), db)
        except HTTPException:
            continue
        if not realidade.get("tracked"):
            continue
        for r in realidade["blocks"]:
            nome = r["name"]
            if nome in ("Tempo livre", "Dormir"):
                continue
            linha = contagem.setdefault(nome, {
                "name": nome, "icon": r.get("icon", ""), "planned": 0, "done": 0,
                "unknown": 0, "planned_min": 0, "actual_min": 0,
            })
            linha["planned"] += 1
            linha["planned_min"] += r["planned_min"]
            if r["unknown"]:
                linha["unknown"] += 1
            else:
                linha["actual_min"] += r["actual_min"] or 0
                if (r["pct"] or 0) >= CUMPRIDO_PCT:
                    linha["done"] += 1

    linhas = []
    for l in contagem.values():
        avaliados = l["planned"] - l["unknown"]
        l["rate"] = round(l["done"] / avaliados * 100) if avaliados else None
        linhas.append(l)
    # O que mais falha primeiro, e entre iguais o que ocupa mais tempo planeado.
    linhas.sort(key=lambda l: (l["rate"] if l["rate"] is not None else 999, -l["planned_min"]))
    return {"days": days, "plans": len(planos), "blocks": linhas}
