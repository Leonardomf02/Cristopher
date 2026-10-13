"""Ler recibos: OCR + interpretação.

O OCR é o do próprio macOS (Vision, via `tools/ocr`), que lê português bem e não
precisa de instalar nada. Fora do macOS cai no tesseract, se existir. Depois é a
IA que transforma o texto em despesa; se a IA falhar, há regras locais que ainda
apanham o total e a data.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from datetime import date, datetime
from typing import Optional

from ai_config import ask_agent_async, extract_json

logger = logging.getLogger(__name__)

BIN_OCR = os.path.join(os.path.dirname(__file__), "tools", "ocr")
FONTE_OCR = BIN_OCR + ".swift"


def _compila_ocr() -> bool:
    """O binário não vai para o repositório: compila-se à primeira utilização."""
    if os.access(BIN_OCR, os.X_OK):
        return True
    if not os.path.exists(FONTE_OCR) or not shutil.which("swiftc"):
        return False
    try:
        r = subprocess.run(["swiftc", "-O", "-o", BIN_OCR, FONTE_OCR],
                           capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            logger.info("ocr nativo compilado")
            return True
        logger.warning("não consegui compilar o ocr nativo: %s", r.stderr[:300])
    except Exception as ex:
        logger.warning("swiftc rebentou: %s", ex)
    return False


CATEGORIAS = [
    "food", "groceries", "travel", "shopping", "bills", "subscriptions",
    "health", "entertainment", "nightlife", "transport", "invest", "other",
]


def ocr_disponivel() -> bool:
    return _compila_ocr() or shutil.which("tesseract") is not None


def ocr(path: str) -> str:
    if _compila_ocr():
        try:
            r = subprocess.run([BIN_OCR, path], capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            logger.warning("ocr nativo falhou (%s): %s", r.returncode, r.stderr[:200])
        except Exception as ex:
            logger.warning("ocr nativo rebentou: %s", ex)

    if shutil.which("tesseract"):
        try:
            r = subprocess.run(
                ["tesseract", path, "stdout", "-l", "por+eng"],
                capture_output=True, text=True, timeout=90,
            )
            if r.returncode != 0:      # sem o pacote de português, tenta só inglês
                r = subprocess.run(["tesseract", path, "stdout"], capture_output=True, text=True, timeout=90)
            if r.returncode == 0:
                return (r.stdout or "").strip()
        except Exception as ex:
            logger.warning("tesseract rebentou: %s", ex)
    return ""


# ── Regras locais (rede de segurança quando a IA não responde) ──

_TOTAL = re.compile(
    r"(total\s*(?:a\s*pagar|geral|liquido|líquido)?|valor\s*total|montante)\D{0,12}"
    r"(\d{1,4}[.,]\d{2})", re.I
)
_QUALQUER_VALOR = re.compile(r"(\d{1,4}[.,]\d{2})")
_DATA = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})")
_DATA_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

PALAVRAS_CATEGORIA = {
    "groceries": ["continente", "pingo doce", "lidl", "aldi", "mercadona", "auchan",
                  "minipreço", "minipreco", "intermarché", "supermercado", "żabka", "zabka", "biedronka"],
    "food": ["restaurante", "café", "cafe", "padaria", "pizzaria", "mcdonald", "kfc",
             "burger", "starbucks", "uber eats", "glovo", "bolt food"],
    "transport": ["uber", "bolt", "táxi", "taxi", "cp ", "carris", "metro", "gasolina",
                  "galp", "bp ", "repsol", "combustível", "combustivel"],
    "health": ["farmácia", "farmacia", "clínica", "clinica", "hospital", "dentista"],
    "shopping": ["decathlon", "zara", "h&m", "fnac", "worten", "media markt", "ikea", "primark"],
    "bills": ["meo", "nos", "vodafone", "edp", "galp energia", "águas", "aguas", "renda"],
    "entertainment": ["cinema", "nos cinemas", "teatro", "spotify", "netflix", "steam"],
}


def _categoria_local(texto: str) -> str:
    t = texto.lower()
    for cat, palavras in PALAVRAS_CATEGORIA.items():
        if any(p in t for p in palavras):
            return cat
    return "other"


def _valor_local(texto: str) -> Optional[float]:
    m = _TOTAL.search(texto)
    if m:
        return float(m.group(2).replace(",", "."))
    valores = [float(v.replace(",", ".")) for v in _QUALQUER_VALOR.findall(texto)]
    return max(valores) if valores else None


def _data_local(texto: str) -> Optional[date]:
    m = _DATA_ISO.search(texto)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    for m in _DATA.finditer(texto):
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if d > 31:                      # veio no formato ano-mês-dia
            d, y = y, d
        try:
            return date(y, mth, d)
        except ValueError:
            continue
    return None


def _comerciante_local(texto: str) -> str:
    for linha in texto.splitlines():
        limpa = linha.strip()
        if len(limpa) >= 3 and not _QUALQUER_VALOR.search(limpa) and "nif" not in limpa.lower():
            return limpa.title()[:60]
    return "Recibo"


def regras_locais(texto: str) -> dict:
    valor = _valor_local(texto)
    d = _data_local(texto)
    return {
        "merchant": _comerciante_local(texto),
        "amount": valor,
        "date": d.isoformat() if d else date.today().isoformat(),
        "category": _categoria_local(texto),
        "items": [],
        "city": None,
        "confidence": "baixa",
        "source": "regras",
    }


async def interpreta(texto: str) -> dict:
    """Texto do recibo → campos da despesa. Cai nas regras locais se a IA falhar."""
    if not texto.strip():
        return {**regras_locais(""), "amount": None, "confidence": "nenhuma"}

    prompt = f"""Este é o texto de um recibo lido por OCR (pode ter erros e colunas trocadas).
Extrai os dados da compra.

Texto do recibo:
---
{texto[:4000]}
---

Devolve SÓ um JSON:
{{"merchant": "nome da loja", "amount": 16.55, "date": "AAAA-MM-DD",
  "category": "uma de: {', '.join(CATEGORIAS)}",
  "items": ["artigo 1", "artigo 2"], "city": "cidade ou null",
  "currency": "EUR", "confidence": "alta|media|baixa"}}

Regras:
- `amount` é o TOTAL PAGO (não o subtotal nem o IVA), em número com ponto decimal.
- Datas europeias: 28/07/2026 é 28 de Julho. Se não houver data, usa null.
- `items` no máximo 6, nomes curtos e legíveis.
- Se algo não estiver no recibo, mete null. Não inventes."""

    try:
        resposta = await ask_agent_async(prompt, timeout=120.0, feature="recibos")
    except Exception as ex:
        logger.warning("IA indisponível na leitura do recibo: %s", ex)
        return regras_locais(texto)

    data = extract_json(resposta) or {}
    if not isinstance(data, dict) or data.get("amount") in (None, ""):
        local = regras_locais(texto)
        if data.get("merchant"):
            local["merchant"] = str(data["merchant"])[:60]
        return local

    try:
        valor = round(abs(float(str(data["amount"]).replace(",", "."))), 2)
    except (TypeError, ValueError):
        return regras_locais(texto)

    d = str(data.get("date") or "")
    try:
        dia = datetime.strptime(d[:10], "%Y-%m-%d").date()
    except ValueError:
        dia = _data_local(texto) or date.today()

    cat = str(data.get("category") or "").strip().lower()
    if cat not in CATEGORIAS:
        cat = _categoria_local(texto)

    itens = data.get("items")
    itens = [str(i)[:60] for i in itens][:6] if isinstance(itens, list) else []

    return {
        "merchant": (str(data.get("merchant") or "").strip() or _comerciante_local(texto))[:60],
        "amount": valor,
        "date": dia.isoformat(),
        "category": cat,
        "items": itens,
        "city": (str(data["city"]).strip()[:60] if data.get("city") else None),
        "currency": (str(data.get("currency") or "EUR").upper()[:3]),
        "confidence": str(data.get("confidence") or "media"),
        "source": "ia",
    }
