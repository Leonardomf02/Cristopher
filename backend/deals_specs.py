"""Lê ano, quilómetros, potência e cor do texto de um anúncio.

Sem isto, o "preço do costume" de um watch é a mediana de tudo o que a IA disse
que servia. No watch da MT-07 isso são 216 anúncios de 2014 a 2026, de 4.500€ a
8.990€, com 35 kW e 55 kW à mistura — e o resultado era dizer que uma de 2015
está "2.000€ abaixo do costume". Está: tem dez anos.

Com o ano e os quilómetros lidos do texto dá para duas coisas que mudam tudo:
comparar cada anúncio só com os **parecidos**, e deitar fora o que nem devia
chegar à IA (poupa quota e tira o lixo da lista).

Nada aqui adivinha: o que não estiver escrito fica `None`, e quem usa decide o
que fazer com a falta de informação.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Optional

ANO_MIN = 1990
ANO_MAX = date.today().year + 1

# Cores como aparecem nos anúncios portugueses. "Night Fluo", "Ice Fluo" e
# "Race Blu" são nomes de série da Yamaha e NÃO são pretas — é o erro fácil.
CORES = {
    "preto": ("preta", "preto", "black", "negra", "negro"),
    "azul": ("azul", "blue", "blu", "ice fluo", "iceflow", "ice flow"),
    "cinzento": ("cinza", "cinzenta", "cinzento", "grey", "gray", "prateada", "silver"),
    "vermelho": ("vermelha", "vermelho", "red"),
    "branco": ("branca", "branco", "white"),
    "verde": ("verde", "green"),
    "amarelo": ("amarela", "amarelo", "yellow", "night fluo", "nightfluo"),
}
# "Tech Black" e "Midnight Black" são pretos de catálogo — ganham a qualquer
# outra palavra que apareça no mesmo texto.
PRETO_DE_CATALOGO = ("tech black", "midnight black", "matt black", "preto mate")


def _limpa(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return t.lower()


def ano(texto: str) -> Optional[int]:
    """O ano do modelo. Aceita "2019", "12/2017" e "ano 2021"."""
    t = _limpa(texto)
    # Um ano colado a "km", "eur" ou "€" não é um ano.
    candidatos = []
    for m in re.finditer(r"(?<![\d.,])((?:19|20)\d{2})(?![\d])", t):
        valor = int(m.group(1))
        if not (ANO_MIN <= valor <= ANO_MAX):
            continue
        depois = t[m.end():m.end() + 6]
        if re.match(r"\s*(km|kms|eur|€|cc)", depois):
            continue
        candidatos.append(valor)
    if not candidatos:
        return None
    # Vários anos no texto (ex.: "2019" no título e "revisão 2024" na descrição):
    # o mais antigo é quase sempre o do modelo.
    return min(candidatos)


# "revisão feita há 1500 km", "pneus novos há 100 km" — números em km que não
# são a quilometragem da mota. Ignorar isto dava 20 km a uma mota com 53.000.
_KM_DE_MANUTENCAO = re.compile(
    r"(ha|desde|cada|apos|feita|feito|troca\w*|revis\w+|oleo|pneus?|correia|"
    r"kit|corrente|pastilhas|garantia|valid\w+)\W{0,12}$"
)


def quilometros(texto: str) -> Optional[int]:
    """Quilómetros da mota. Aceita "30.000 km", "15000km", "19 mil km", "Km 20 K".

    Fica com o **maior** valor plausível, não com o menor: os números pequenos
    num anúncio de mota são quase sempre manutenção ("óleo mudado há 1.500 km"),
    e o conta-quilómetros é o maior de todos."""
    t = _limpa(texto)

    for m in re.finditer(r"(\d{1,3})\s*mil\s*(?:km|kms|quilometros)", t):
        return int(m.group(1)) * 1000
    for m in re.finditer(r"km\s*(\d{1,3})\s*k\b", t):
        return int(m.group(1)) * 1000

    melhor = None
    for m in re.finditer(r"(\d[\d\s.,]{0,9})\s*(km|kms|quilometros)\b", t):
        cru = re.sub(r"[\s.,]", "", m.group(1))
        if not cru.isdigit():
            continue
        v = int(cru)
        # 689/700 é a cilindrada da MT-07, não a quilometragem.
        if v in (689, 700) or v > 400_000:
            continue
        if _KM_DE_MANUTENCAO.search(t[max(0, m.start() - 24):m.start()]):
            continue
        if melhor is None or v > melhor:
            melhor = v
    return melhor


def potencia_kw(texto: str) -> Optional[int]:
    """35 ou 55 kW. "Deslimitada" quer dizer que foi de 35 para 55 — continua a
    ser a versão A2 no livrete, e é isso que interessa a quem tem carta A2."""
    t = _limpa(texto)
    for m in re.finditer(r"(\d{2})\s*(?:kw|kilowatt)", t):
        v = int(m.group(1))
        if v in (35, 45, 55, 54):
            return 35 if v == 35 else 55
    if re.search(r"\ba2\b|carta a2|livrete", t):
        return 35
    if re.search(r"full\s*power|75\s*cv", t):
        return 55
    return None


def cor(titulo: str) -> Optional[str]:
    """A cor da mota, e **só a partir do título**.

    Na descrição a cor não é de fiar: "manetes pretas" numa Ice Fluo azul dava
    preta. E na maioria dos anúncios a cor nem sequer está escrita — vê-se na
    fotografia. Por isso isto nunca chega para excluir um anúncio sozinho; serve
    para dizer o que se sabe e o que não se sabe."""
    t = _limpa(titulo)
    for nome in PRETO_DE_CATALOGO:
        if nome in t:
            return "preto"
    for nome, palavras in CORES.items():
        for p in palavras:
            if re.search(rf"\b{re.escape(p)}\b", t):
                return nome
    return None


def le(titulo: str, descricao: str = "") -> dict:
    """Tudo o que se consegue ler de um anúncio. A cor sai só do título."""
    texto = f"{titulo}\n{descricao or ''}"
    return {
        "year": ano(texto),
        "km": quilometros(texto),
        "kw": potencia_kw(texto),
        "colour": cor(titulo),
    }
