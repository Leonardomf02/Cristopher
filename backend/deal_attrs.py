"""Lê o que o anúncio diz: ano, quilómetros, potência e cor.

O caça-deals só sabia o preço. Com isso, o "2000€ abaixo do costume" que a app
mostrava era a mediana de **tudo** o que já tinha aparecido na pesquisa — MT-09,
MT-10 e um suporte de alumínio de 20€ pelo meio, de 1€ a 8.990€. Comparar uma
mota de 2015 com essa mediana não diz nada.

Aqui tira-se do texto o que dá para tirar com regras (é português de anúncio,
não é prosa) e o resto fica `None`. **`None` não é um "não cumpre"**: um anúncio
que não diz os quilómetros não pode ser excluído por causa disso — pode ser
exactamente o que ele quer e o vendedor só não escreveu. Quem decide o que fazer
com o desconhecido é o `deal_criteria`.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

ANO_MIN, ANO_MAX = 1990, 2030


def _sem_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def normaliza(texto: str) -> str:
    return _sem_acentos(texto or "").lower()


# ── Quilómetros ─────────────────────────────────────────────────────────
# "13mil km", "30.000 km", "9.000km", "30 mil kms", "25000 quilómetros".
# O "mil" tem de ser tratado à parte: "13mil km" são 13.000, não 13.
_KM_MIL = re.compile(r"(\d{1,3})(?:[.,](\d{1,3}))?\s*mil\s*(?:km|kms|quilometros?)", re.I)
_KM_NUM = re.compile(r"(\d{1,3}(?:[.\s]\d{3})+|\d{3,6})\s*(?:km|kms|quilometros?)\b", re.I)
# "com 25 000 km" já entra no de cima; este apanha "km: 30.000"
_KM_DEPOIS = re.compile(r"(?:km|kms|quilometros?)\s*[:\-]?\s*(\d{1,3}(?:[.\s]\d{3})+|\d{3,6})", re.I)


# "Revisões feitas sempre de 5 em 5 mil km" não são os quilómetros da mota — e
# eram lidos como 5.000 numa mota que tinha 25.000. Estas expressões antes do
# número desqualificam-no.
_INTERVALO = re.compile(r"(?:revis|manuten|troca|mudan|servic|de\s+\d+\s+em|cada|"
                        r"a\s+cada|garantia|autonomia|raio\s+de)[^.]{0,24}$")


def _candidatos_km(t: str):
    """(posição, valor) de tudo o que parece uma quilometragem."""
    for m in _KM_MIL.finditer(t):
        inteiro, decimal = int(m.group(1)), m.group(2)
        yield m.start(), inteiro * 1000 + (int(decimal.ljust(3, "0")) if decimal else 0)
    for padrao in (_KM_NUM, _KM_DEPOIS):
        for m in padrao.finditer(t):
            try:
                yield m.start(), int(re.sub(r"[.\s]", "", m.group(1)))
            except ValueError:
                continue


def extrai_km(texto: str) -> Optional[int]:
    """Os quilómetros da mota. O primeiro que aparece no texto é o dela — os que
    vêm depois são quase sempre intervalos de revisão ou distâncias."""
    t = normaliza(texto)
    validos = []
    for pos, valor in _candidatos_km(t):
        # Abaixo de 100 km numa mota usada é quase sempre outra coisa
        # ("100 km de autonomia", "a 20 km de Lisboa").
        if not (100 <= valor <= 500_000):
            continue
        if _INTERVALO.search(t[max(0, pos - 40):pos]):
            continue
        validos.append((pos, valor))
    return min(validos)[1] if validos else None


# ── Ano ─────────────────────────────────────────────────────────────────
# Um ano solto no meio do texto é frágil: "5600€" não é ano, mas "2016" sozinho
# é. Aceita-se 1990-2030 e ignora-se o que esteja colado a € ou a km.
_ANO = re.compile(r"(?<![\d.,/])((?:19|20)\d{2})(?![\d]|\s*(?:€|eur|km|kms))", re.I)
_ANO_MES = re.compile(r"\b(?:0?[1-9]|1[0-2]|jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)"
                      r"\s*/\s*((?:19|20)\d{2})\b", re.I)


# Numa descrição o ano do modelo vem sempre com pista à frente. Sem exigir a
# pista, "Ano 2017 … Preço 5200" dava 2023 (apanhava outro ano qualquer do
# texto) e um anúncio "de 2015" dava 2024.
_PISTAS_ANO = (
    re.compile(r"\bano\s*(?:do\s*modelo)?\s*[:\-]?\s*((?:19|20)\d{2})\b"),
    re.compile(r"\b(?:de|do)\s+((?:19|20)\d{2})\b"),
    re.compile(r"\bmt[\s\-]?0?7\b[^\d\n]{0,20}((?:19|20)\d{2})\b"),
    re.compile(r"\b(?:0?[1-9]|1[0-2])\s*/\s*((?:19|20)\d{2})\b"),
)


def _ano_maximo_plausivel() -> int:
    """Os stands anunciam o modelo do ano seguinte; para cima disso é inspecção
    ou garantia, não é o ano da mota."""
    from datetime import date
    return date.today().year + 1


def _anos_do_texto(t: str) -> list[int]:
    tecto = _ano_maximo_plausivel()
    anos = [int(x) for x in _ANO.findall(t) if ANO_MIN <= int(x) <= ANO_MAX]
    return [a for a in anos if a <= tecto]


def extrai_ano(texto: str, *, exige_pista: bool = False) -> Optional[int]:
    """O ano do modelo.

    `exige_pista=True` para textos longos (descrições): só aceita um ano que
    venha atrás de "ano:", "de", do nome do modelo ou de um mês. Num título
    curto isso não é preciso — o que lá está é o ano da mota."""
    t = normaliza(texto)
    m = _ANO_MES.search(t)                       # "ago/2014" é o mais fiável
    if m:
        ano = int(m.group(1))
        if ANO_MIN <= ano <= _ano_maximo_plausivel():
            return ano
    if exige_pista:
        tecto = _ano_maximo_plausivel()
        for pista in _PISTAS_ANO:
            achado = pista.search(t)
            if achado:
                ano = int(achado.group(1))
                if ANO_MIN <= ano <= tecto:
                    return ano
        return None
    anos = _anos_do_texto(t)
    return max(anos) if anos else None


# ── Potência ────────────────────────────────────────────────────────────
# "55kw", "35 kW", "A2" (a carta A2 limita a 35 kW), "full power" (55 kW na MT-07).
# O número tem de começar em fronteira: sem isso, "MT-07 35kw" lia-se como 7 kW
# (apanhava o "07") e "2020 35 KW" como 20.
_KW = re.compile(r"(?<![\d.,])(\d{2,3})(?:[.,]\d+)?\s*k\s*w\b", re.I)
_CV = re.compile(r"(?<![\d.,])(\d{2,3})(?:[.,]\d+)?\s*(?:cv|hp|cavalos)\b", re.I)
# "(A2)", "carta A2", "versão A2" — mas não o "a 2" de "há 2 anos".
_A2 = re.compile(r"(?:\ba2\b|carta\s*a\s*2\b|\(\s*a\s*2\s*\))", re.I)


# As motas vendem-se por classe legal, não pelo número exacto: A2 são 35 kW e a
# versão livre da MT-07 são 55. Converter cavalos dá 33 ou 54 (o StandVirtual
# anuncia 45 cv e 73 cv), e com "exactamente 35 kW" isso rejeitava uma A2 a
# sério. Arredonda-se à classe quando está lá perto.
CLASSES_KW = (35, 55)
TOLERANCIA_KW = 3


def classe_de_potencia(kw: Optional[int]) -> Optional[int]:
    if kw is None:
        return None
    for classe in CLASSES_KW:
        if abs(kw - classe) <= TOLERANCIA_KW:
            return classe
    return kw


def extrai_potencia_kw(texto: str) -> Optional[int]:
    t = normaliza(texto)
    m = _KW.search(t)
    if m:
        kw = int(m.group(1))
        if 5 <= kw <= 250:
            return kw
    m = _CV.search(t)
    if m:
        kw = classe_de_potencia(round(int(m.group(1)) * 0.7355))
        if 5 <= kw <= 250:
            return kw
    if _A2.search(t):
        return 35
    if "full power" in t or "fullpower" in t:
        return 55
    return None


# ── Cor ─────────────────────────────────────────────────────────────────
CORES = {
    "preto": ("preta", "preto", "black", "negra", "negro"),
    "branco": ("branca", "branco", "white"),
    "azul": ("azul", "blue"),
    "vermelho": ("vermelha", "vermelho", "red"),
    "cinzento": ("cinzenta", "cinzento", "cinza", "grey", "gray", "prateada", "prateado"),
    "verde": ("verde", "green"),
    "amarelo": ("amarela", "amarelo", "yellow"),
    "laranja": ("laranja", "orange"),
}


# Uma cor no meio da descrição é quase sempre de uma peça, não da mota: "símbolos
# Yamaha em preto", "farol traseiro preto", "jantes pretas". Só conta a cor que
# venha agarrada ao artigo — no título, ou depois de "cor:" / "mota".
_PECAS = (r"simbolo|logo|farol|pisca|jante|pneu|banco|selim|escape|ponteira|carena\s+de|"
          r"protec|manete|espelho|matricula|capacete|mala|top\s*case|suporte|autocolante|"
          r"tampa|guarda|corrente|disco|pinca|risca|detalhe|fundo|interior")


def extrai_cor(texto: str, *, so_do_artigo: bool = False) -> Optional[str]:
    """A cor do artigo. `so_do_artigo` exige uma pista de que é mesmo a dele."""
    t = normaliza(texto)
    for cor, palavras in CORES.items():
        for p in palavras:
            for m in re.finditer(rf"\b{p}\b", t):
                antes = t[max(0, m.start() - 45):m.start()]
                if re.search(_PECAS, antes):
                    break                       # é a cor de uma peça
                if so_do_artigo and not re.search(
                        r"(?:cor\s*[:\-]?\s*|mota\s+|moto\s+|yamaha\s+|mt[\s\-]?0?7\s+)$",
                        antes[-24:]):
                    continue
                return cor
    return None


def extrai(titulo: str, descricao: str = "") -> dict:
    """Tudo o que se conseguiu ler do anúncio. `None` = o anúncio não diz.

    O título manda sobre a descrição. Numa descrição fala-se de outras motas, de
    peças e de anos de inspecção; no título está o que se está mesmo a vender —
    "espelho para FZ6 600" trazia um 2004 da descrição como se fosse o ano da
    mota."""
    titulo = titulo or ""
    descricao = descricao or ""
    saida = {}
    for chave, funcao in (("km", extrai_km), ("power_kw", extrai_potencia_kw)):
        saida[chave] = funcao(titulo)
        if saida[chave] is None and descricao:
            saida[chave] = funcao(descricao)
    saida["color"] = extrai_cor(titulo)
    if saida["color"] is None and descricao:
        saida["color"] = extrai_cor(descricao, so_do_artigo=True)
    saida["year"] = extrai_ano(titulo)
    if saida["year"] is None and descricao:
        saida["year"] = extrai_ano(descricao, exige_pista=True)
    return saida
