"""Ideas → Todos: take a brain-dump (text or transcribed audio) and use the
iaedu.pt agent to extract a structured list of actionable to-dos."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date as date_type
import logging

from ai_config import ask_agent_async, extract_json

router = APIRouter(prefix="/api/ideas", tags=["Ideas"])
logger = logging.getLogger(__name__)


class ProcessIdeasIn(BaseModel):
    text: str


class ExtractedTodo(BaseModel):
    text: str
    priority: int = 0           # 0=none, 1=low, 2=medium, 3=high
    due_date: Optional[date_type] = None
    notes: str = ""


class ProcessIdeasOut(BaseModel):
    todos: list[ExtractedTodo]


@router.post("/process", response_model=ProcessIdeasOut)
async def process_ideas(data: ProcessIdeasIn):
    text = (data.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Texto vazio")

    today = date_type.today().isoformat()
    prompt = f"""És um assistente que organiza brain-dumps em tarefas concretas.

Recebes um texto cru (português, pode ser transcrição de áudio com pontuação fraca) com ideias soltas, tarefas, lembretes e pensamentos. O teu trabalho:

1. Extrair APENAS itens accionáveis (coisas a fazer / decidir / comprar / contactar / verificar). Ignora opiniões, descrições, divagações.
2. Reescrever cada item num imperativo curto e claro. Máximo ~10 palavras.
3. Atribuir prioridade: 0=normal, 1=baixa, 2=média, 3=alta. Só usa 2 ou 3 quando o texto sinalizar urgência ("hoje", "amanhã", "urgente", "antes de"). Caso contrário usa 0.
4. Se o texto mencionar uma data ou prazo concreto, devolve em ISO YYYY-MM-DD. Hoje é {today}. Senão, omite.
5. Junta detalhes complementares em "notes" se forem úteis (contexto, sub-passos). Senão deixa "".
6. Sem duplicados. Sem itens vagos tipo "pensar nisso".

Responde APENAS com JSON válido neste formato:
{{"todos": [
  {{"text": "...", "priority": 0, "due_date": "YYYY-MM-DD"|null, "notes": ""}}
]}}

Sem texto extra, sem markdown, sem explicações.

Texto:
\"\"\"
{text}
\"\"\""""

    full_text = await ask_agent_async(prompt)
    if not full_text:
        raise HTTPException(status_code=502, detail="AI indisponível")

    parsed = extract_json(full_text)
    if not isinstance(parsed, dict):
        logger.warning(f"Ideas AI no JSON: {full_text[:300]}")
        raise HTTPException(status_code=502, detail="Resposta da IA inválida")

    raw_todos = parsed.get("todos") or []
    out: list[ExtractedTodo] = []
    for t in raw_todos:
        if not isinstance(t, dict):
            continue
        txt = (t.get("text") or "").strip()
        if not txt:
            continue
        prio = t.get("priority")
        prio = int(prio) if isinstance(prio, (int, float, str)) and str(prio).strip().lstrip("-").isdigit() else 0
        prio = max(0, min(3, prio))
        due = t.get("due_date")
        due_parsed: Optional[date_type] = None
        if isinstance(due, str) and due:
            try:
                due_parsed = date_type.fromisoformat(due[:10])
            except ValueError:
                due_parsed = None
        notes = (t.get("notes") or "").strip()
        out.append(ExtractedTodo(text=txt, priority=prio, due_date=due_parsed, notes=notes))

    return ProcessIdeasOut(todos=out)
