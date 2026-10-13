from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Listing:
    """Anúncio normalizado, comum a todas as fontes."""
    source: str
    external_id: str
    title: str
    description: str = ""
    price: Optional[float] = None
    currency: str = "EUR"
    condition: str = ""        # texto da fonte (Novo/Usado/Muito bom…)
    url: str = ""
    image_url: str = ""
    location: str = ""
    seller: str = ""
    # Ano, km, potência e cor quando a fonte os dá em campos (StandVirtual dá).
    # Vale mais do que o `deal_attrs`, que os tem de adivinhar a partir do texto.
    attrs: Optional[dict] = None


def matches_condition(listing_condition: str, wanted: str) -> bool:
    """Filtro suave de condição. wanted: any|new|used. Usa heurística sobre o texto da fonte."""
    if wanted not in ("new", "used"):
        return True
    text = (listing_condition or "").lower()
    is_new = any(k in text for k in ("novo", "new", "selado", "nunca usado", "etiqueta"))
    return is_new if wanted == "new" else not is_new
