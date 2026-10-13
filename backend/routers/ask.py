"""Perguntar à app em português sobre os próprios dados.

A IA escreve o SQL, a app executa-o numa ligação **só de leitura** e devolve a
tabela + uma frase com a resposta. Serve para as perguntas que nunca valeria a
pena transformar em ecrã ("quanto gastei em cafés em maio?").

Segurança: só SELECT/WITH, uma instrução, sem palavras de escrita, com LIMIT
imposto e ligação aberta em modo `ro`.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from ai_config import ask_agent_async, extract_json

router = APIRouter(prefix="/api/ask", tags=["Ask"])

from database import DB_PATH
LIMITE_LINHAS = 200

# Tabelas que valem para perguntas do dia-a-dia (o resto é ruído no prompt).
TABELAS = [
    "expenses", "monthly_income", "subscriptions", "budget_limits", "salary_buckets",
    "wishlist_items", "investment_positions", "investment_transactions",
    "sleep_entries", "mood_entries", "daily_journals", "habits", "habit_completions",
    "events", "user_lists", "list_items", "day_plans", "day_activities", "flow_sessions",
    "lol_games", "trips", "notes", "code_project_notes", "code_project_todos",
    "waka_project_days", "waka_day_metrics", "app_usage_sessions",
    "screen_time_daily_apps", "deal_results", "deal_watches", "spotify_playlists",
    "spotify_tracks", "stories", "day_types",
    "garmin_days", "garmin_activities", "garmin_snapshots", "night_outs",
]

PROIBIDO = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|"
    r"reindex|truncate|grant|begin|commit|rollback)\b", re.I
)


class Anterior(BaseModel):
    """Uma pergunta já respondida nesta conversa. O SQL vale mais que a resposta:
    é ele que diz de que tabelas e filtros se está a falar."""
    question: str
    sql: str = ""


class Pergunta(BaseModel):
    question: str
    explain: bool = True
    # Sem isto, "e no mês passado?" não queria dizer nada — cada pergunta chegava
    # à IA sozinha e ela tinha de adivinhar o assunto.
    context: list[Anterior] = []


def _schema_resumo() -> str:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        linhas = []
        for t in TABELAS:
            try:
                cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
            except sqlite3.Error:
                continue
            if cols:
                linhas.append(f"{t}({', '.join(cols)})")
        return "\n".join(linhas)
    finally:
        con.close()


def _valida_sql(sql: str) -> str:
    limpo = sql.strip().rstrip(";").strip()
    if not limpo:
        raise HTTPException(status_code=422, detail="A IA não devolveu SQL")
    if ";" in limpo:
        raise HTTPException(status_code=422, detail="Só é permitida uma instrução")
    if not re.match(r"^(select|with)\b", limpo, re.I):
        raise HTTPException(status_code=422, detail="Só são permitidas consultas SELECT")
    if PROIBIDO.search(limpo):
        raise HTTPException(status_code=422, detail="A consulta tem palavras de escrita")
    if not re.search(r"\blimit\b", limpo, re.I):
        limpo += f" LIMIT {LIMITE_LINHAS}"
    return limpo


def _executa(sql: str) -> tuple[list[str], list[list[Any]]]:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only = ON")
        cur = con.execute(sql)
        colunas = [d[0] for d in (cur.description or [])]
        linhas = [list(r) for r in cur.fetchmany(LIMITE_LINHAS)]
        return colunas, linhas
    except sqlite3.Error as ex:
        raise HTTPException(status_code=422, detail=f"SQL inválido: {ex}")
    finally:
        con.close()


# ── Perguntas fixadas ────────────────────────────────────────────
# Perguntar é a melhor parte da app e era usada uma vez e esquecida. Fixar uma
# pergunta guarda o SQL que a IA escreveu; a partir daí o número actualiza-se
# sozinho, sem gastar IA nenhuma.

class Fixar(BaseModel):
    question: str
    title: str = ""
    sql: str
    chart: str = "table"


def _valor_principal(colunas: list[str], linhas: list[list]) -> str:
    """O número que resume a resposta: numa tabela de 1x1 é a célula; numa lista
    é a soma da última coluna numérica; senão, o nº de linhas."""
    if not linhas:
        return "0"
    if len(linhas) == 1 and len(linhas[0]) == 1:
        v = linhas[0][0]
        if v is None:
            return "0"        # SUM() sem linhas dá NULL; mostrar "None" não diz nada
        return f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
    ultima = [linha[-1] for linha in linhas if linha and isinstance(linha[-1], (int, float))]
    if len(ultima) == len(linhas):
        total = sum(ultima)
        return f"{total:.2f}".rstrip("0").rstrip(".") if isinstance(total, float) else str(total)
    return str(len(linhas))


@router.get("/pinned")
def fixadas(db: Session = Depends(get_db)):
    """As perguntas fixadas, já com o valor de agora."""
    from models import SavedQuestion
    from datetime import datetime

    saida = []
    for p in db.query(SavedQuestion).order_by(SavedQuestion.position, SavedQuestion.id).all():
        item = {"id": p.id, "question": p.question, "title": p.title, "chart": p.chart,
                "sql": p.sql, "previous": p.last_value or None}
        try:
            colunas, linhas = _executa(p.sql)
            valor = _valor_principal(colunas, linhas)
            item.update({"columns": colunas, "rows": linhas[:12], "value": valor,
                         "row_count": len(linhas), "error": None})
            # `previous` é o valor de quando se olhou da última vez — é isso que
            # deixa ver que o número mexeu desde ontem.
            p.last_value = valor
            p.last_run_at = datetime.now()
        except HTTPException as ex:
            # Uma pergunta pode partir-se (tabela que mudou); não pode levar as outras.
            item.update({"columns": [], "rows": [], "value": None, "row_count": 0,
                         "error": str(ex.detail)})
        saida.append(item)
    db.commit()
    return saida


@router.post("/pinned")
def fixar(body: Fixar, db: Session = Depends(get_db)):
    from models import SavedQuestion

    sql = _valida_sql(body.sql)
    _executa(sql)                      # se não correr agora, não vale a pena fixar
    ja = db.query(SavedQuestion).filter(SavedQuestion.question == body.question.strip()).first()
    if ja:
        ja.sql, ja.title, ja.chart = sql, body.title[:120], body.chart
        db.commit()
        return {"id": ja.id, "updated": True}
    ultimo = db.query(SavedQuestion).order_by(SavedQuestion.position.desc()).first()
    p = SavedQuestion(
        question=body.question.strip()[:300],
        title=(body.title or body.question).strip()[:120],
        sql=sql, chart=body.chart if body.chart in ("table", "bar", "line") else "table",
        position=(ultimo.position + 1) if ultimo else 0,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "updated": False}


@router.delete("/pinned/{pinned_id}")
def desafixar(pinned_id: int, db: Session = Depends(get_db)):
    from models import SavedQuestion
    p = db.query(SavedQuestion).filter(SavedQuestion.id == pinned_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pergunta não encontrada")
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.get("/examples")
def exemplos():
    return {
        "examples": [
            "quanto gastei em comida em maio?",
            "quantas horas dormi em média nas semanas em que fui ao gym?",
            "em que dias joguei mais de 3 games?",
            "quais os 5 maiores gastos deste ano?",
            "quantas horas de código por mês este ano?",
            "que apps usei mais depois da meia-noite?",
        ]
    }


@router.post("/")
async def perguntar(body: Pergunta, db: Session = Depends(get_db)):
    pergunta = body.question.strip()
    if len(pergunta) < 4:
        raise HTTPException(status_code=400, detail="Pergunta demasiado curta")

    # Só as últimas: mais do que isto enche o prompt sem ajudar a perceber a
    # pergunta de agora.
    anteriores = ""
    if body.context:
        linhas = [
            f'- "{c.question.strip()[:200]}" → {c.sql.strip()[:400]}'
            for c in body.context[-3:] if c.question.strip()
        ]
        if linhas:
            anteriores = (
                "\nJá nesta conversa (da mais antiga para a mais recente):\n"
                + "\n".join(linhas)
                + "\n\nA pergunta de agora pode referir-se a estas — 'e no mês passado?', "
                  "'só de fim-de-semana', 'e em horas?'. Nesse caso parte do SQL anterior "
                  "e muda só o que ele pediu. Se for assunto novo, ignora o que está acima.\n"
            )

    prompt = f"""És o motor de consultas da app pessoal do Cristovão (SQLite).
Transforma a pergunta dele em UMA consulta SELECT.

Esquema (tabela(colunas)):
{_schema_resumo()}
{anteriores}

Notas do domínio:
- expenses.amount > 0 é dinheiro que saiu; < 0 é entrada/reembolso. As categorias
  usadas são: food, groceries, travel, shopping, bills, subscriptions, health,
  entertainment, nightlife (sair à noite), transport, invest, other.
- sleep_entries.hours são horas dormidas nessa noite (date = dia em que acordou).
- lol_games.won é 1/0; game_hour é a hora do dia.
- waka_project_days.seconds é tempo de código (kind='project').
- app_usage_sessions.duration_seconds é uso de apps no Mac; screen_time_daily_apps.seconds
  é o Screen Time da Apple por app/categoria.
- habit_completions.date são os dias em que cumpriu um hábito.
- garmin_days é o que o relógio mediu por dia: sleep_score (0-100), fases em minutos,
  hrv_last_night (ms) com hrv_status, resting_hr, body battery (bb_start é com quanto
  acordou, bb_min o pior do dia), stress_avg, steps e training_readiness. Colunas a
  NULL são dias sem relógio ou métricas que ele ainda não calcula.
- garmin_activities são os treinos (type, duration_s, distance_m, avg_hr).
- garmin_snapshots são medições de 2 minutos que ele grava à mão no relógio, com
  hrv_rmssd (o HRV do costume, em ms), hr_avg, spo2_avg, resp_avg e stress_avg.
- night_outs são as noites em que saiu (date = dia em que a noite começou; sem linha =
  ficou em casa), com drank 1/0 se bebeu e drink_level 1 pouco / 2 médio / 3 muito
  (NULL nas antigas, marcadas antes de haver nível). A noite de sono a seguir é garmin_days de date+1.
- Datas estão em texto ISO (YYYY-MM-DD). Usa date('now') para hoje.

Pergunta: "{pergunta}"

Devolve SÓ um JSON:
{{"sql": "SELECT ...", "title": "título curto do resultado", "chart": "table|bar|line"}}

Regras: só SELECT (podes usar WITH), sem ponto e vírgula, no máximo {LIMITE_LINHAS} linhas,
nomes de colunas legíveis em português com AS, e arredonda valores monetários a 2 casas."""

    try:
        resposta = await ask_agent_async(prompt, timeout=120.0, feature="ask")
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"IA indisponível: {ex}")

    data = extract_json(resposta) or {}
    sql = _valida_sql(str(data.get("sql", "")))
    titulo = str(data.get("title") or pergunta)[:120]
    chart = str(data.get("chart") or "table")
    if chart not in ("table", "bar", "line"):
        chart = "table"

    colunas, linhas = _executa(sql)

    frase = ""
    if body.explain and linhas:
        amostra = [colunas] + linhas[:15]
        try:
            frase_raw = await ask_agent_async(
                f"""Responde à pergunta numa frase curta em português de Portugal, com os números do resultado.

Pergunta: "{pergunta}"
Resultado (primeira linha = nomes das colunas):
{amostra}

Responde só com a frase, sem introduções.""",
                timeout=60.0, feature="ask",
            )
            frase = (frase_raw or "").strip().split("\n")[0][:300]
        except Exception:
            frase = ""

    return {
        "question": pergunta,
        "title": titulo,
        "sql": sql,
        "chart": chart,
        "columns": colunas,
        "rows": linhas,
        "row_count": len(linhas),
        "answer": frase,
    }
