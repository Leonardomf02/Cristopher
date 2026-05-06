"""Ideas → Todos: take a brain-dump (text or transcribed audio) and use the
iaedu.pt agent to extract a structured list of actionable to-dos."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date as date_type
import httpx
import json
import re
import uuid
import logging

from ai_config import AI_API_URL, AI_API_KEY, AI_CHANNEL_ID

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

    thread_id = uuid.uuid4().hex[:20]
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                AI_API_URL,
                headers={"x-api-key": AI_API_KEY},
                data={
                    "channel_id": AI_CHANNEL_ID,
                    "thread_id": thread_id,
                    "user_info": "{}",
                    "message": prompt,
                },
            )
            if response.status_code != 200:
                logger.warning(f"Ideas AI failed: HTTP {response.status_code}")
                raise HTTPException(status_code=502, detail="AI indisponível")

            full_text = ""
            token_text = ""
            for line in response.text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("type") == "message":
                        content = event.get("content", {})
                        if isinstance(content, dict):
                            full_text = content.get("content", "")
                        else:
                            full_text = str(content)
                        break
                    elif event.get("type") == "token":
                        token_text += event.get("content", "")
                except json.JSONDecodeError:
                    continue
            if not full_text:
                full_text = token_text
    except httpx.HTTPError as e:
        logger.warning(f"Ideas AI HTTPError: {e}")
        raise HTTPException(status_code=502, detail="AI indisponível")

    code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', full_text, re.DOTALL)
    json_str = code_match.group(1) if code_match else None
    if not json_str:
        json_match = re.search(r'\{.*\}', full_text, re.DOTALL)
        if not json_match:
            logger.warning(f"Ideas AI no JSON: {full_text[:300]}")
            raise HTTPException(status_code=502, detail="Resposta da IA inválida")
        json_str = json_match.group()

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="JSON da IA inválido")

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
