"""Onde ele estava, a partir de onde gastou o dinheiro.

As viagens estavam paradas em Abril — 11, todas do mesmo mês — enquanto os
extractos de Maio a Julho mostravam Roma, Atenas, Tallinn, Riga, Helsínquia,
Veneza, Dublin, Amesterdão, Budva, Kotor, Tirana, Bruxelas, Malta, Vilnius e
Estocolmo. O detector existia, mas era um botão que ninguém carregava.

Agendá-lo tal como estava não chegava: o critério era "país diferente de
Portugal" e ele vive na Polónia, por isso sairia uma viagem "Polónia" por mês e
o Erasmus inteiro seria uma viagem. Faltava a noção de **casa**: o país onde ele
passa a maior parte dos dias de cada mês. As viagens são as saídas de casa.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Iterable, Optional

import cities

# Moeda → país, quando o extracto não traz o país nem uma cidade conhecida.
MOEDA_PAIS = {
    "PLN": "POL", "SEK": "SWE", "RON": "ROU", "CZK": "CZE", "HUF": "HUN",
    "GBP": "GBR", "DKK": "DNK", "NOK": "NOR", "CHF": "CHE", "BGN": "BGR",
    "TRY": "TUR", "ALL": "ALB", "MKD": "MKD", "RSD": "SRB", "ISK": "ISL",
    "UAH": "UKR", "MDL": "MDA", "GEL": "GEO",
}

# ISO2 (e abreviaturas do Revolut) → ISO3.
NORMALIZA = {
    "PL": "POL", "PT": "PRT", "SE": "SWE", "RO": "ROU", "ROM": "ROU",
    "LT": "LTU", "LV": "LVA", "EE": "EST", "DE": "DEU", "FR": "FRA",
    "ES": "ESP", "IT": "ITA", "GB": "GBR", "UK": "GBR", "NL": "NLD",
    "BE": "BEL", "CZ": "CZE", "AT": "AUT", "HU": "HUN", "GR": "GRC",
    "HR": "HRV", "BG": "BGR", "IE": "IRL", "LU": "LUX", "MT": "MLT",
    "ME": "MNE", "AL": "ALB", "FI": "FIN", "DK": "DNK", "NO": "NOR",
    "CH": "CHE", "TR": "TUR", "IS": "ISL", "US": "USA",
}

# Quantos dias de intervalo ainda contam como a mesma ida.
INTERVALO_MESMA_VIAGEM = 2
# Abaixo disto não se cria viagem: uma compra online num site estrangeiro não é
# uma viagem.
MINIMO_DESPESAS = 2


# Sítios que não provam que ele lá esteve. A morada destes é a da empresa: a
# Vinted é lituana, a Apple factura de Cork e a Ryanair de Dublin — sem isto,
# comprar 702€ na Vinted virava uma viagem a Vilnius e pagar o iCloud virava
# uma ida à Irlanda.
SEM_LOCALIZACAO = (
    "vinted", "klarna", "youget", "shein", "temu", "aliexpress", "amazon",
    "github", "apple", "icloud", "google", "openai", "chatgpt", "anthropic",
    "claude", "spotify", "netflix", "crunchyroll", "hbo", "disney", "steam",
    "paypal", "revolut", "trading 212", "trading212", "finst", "stichting",
    "booking", "airbnb", "ryanair", "wizz", "easyjet", "vueling", "trip.com",
    "omio", "flixbus", "blablacar", "kiwi.com", "edreams", "transfer to",
    "transfer from", "vodafone", "meo", "nos ",
)


def _iso3(codigo: Optional[str]) -> Optional[str]:
    if not codigo:
        return None
    c = codigo.strip().upper()
    if len(c) == 1:
        return None                      # o Revolut manda letras soltas ("I", "B")
    c = NORMALIZA.get(c, c)
    # Só códigos que a app sabe nomear: "0TL" e "BAR" chegavam aqui como país.
    return c if c in cities.PAISES else None


def e_online(descricao: Optional[str]) -> bool:
    d = (descricao or "").lower()
    return any(p in d for p in SEM_LOCALIZACAO)


def pais_da_despesa(e) -> Optional[str]:
    """O país de uma despesa: pela cidade, pelo código do país ou pela moeda.

    A cidade manda: o código do país que o Revolut manda vem muitas vezes com a
    província ("MI" por Milão, "BG" por Bergamo, que é a Bulgária no ISO)."""
    if e_online(getattr(e, "description", None)):
        return None
    achado = cities.resolve(getattr(e, "merchant_city", None))
    if achado:
        return achado[1]
    pais = _iso3(getattr(e, "merchant_country", None))
    if pais:
        return pais
    moeda = (getattr(e, "original_currency", None) or "").strip().upper()
    return MOEDA_PAIS.get(moeda)


def _mes(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def dias_por_pais(despesas: Iterable) -> dict[str, dict[str, set]]:
    """{mês: {país: {dias com despesas lá}}}. Conta dias e não despesas: um dia
    de compras numa cidade não faz dela a casa dele."""
    fora: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for e in despesas:
        p = pais_da_despesa(e)
        if p:
            fora[_mes(e.date)][p].add(e.date)
    return fora


# A casa de um mês olha também para as semanas à volta: em Fevereiro ele passou
# por Londres a caminho de Cracóvia e, mês a mês, Londres ganhava — com a janela,
# o mês de chegada já sabe onde ele foi viver.
JANELA_CASA_DIAS = 25


def base_por_mes(despesas: Iterable) -> dict[str, str]:
    """O país onde ele viveu em cada mês."""
    com_pais = [(e.date, pais_da_despesa(e)) for e in despesas]
    com_pais = [(d, p) for d, p in com_pais if p]
    if not com_pais:
        return {}

    meses = sorted({_mes(d) for d, _ in com_pais})
    casas: dict[str, str] = {}
    for m in meses:
        ano, mes = int(m[:4]), int(m[5:7])
        inicio = date(ano, mes, 1) - timedelta(days=JANELA_CASA_DIAS)
        fim = (date(ano + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1)
               + timedelta(days=JANELA_CASA_DIAS))
        dias: dict[str, set] = defaultdict(set)
        for d, p in com_pais:
            if inicio <= d <= fim:
                dias[p].add(d)
        candidato = max(dias, key=lambda p: len(dias[p]), default=None)
        casas[m] = candidato or ""
    return casas


def viagens(despesas: Iterable) -> list[dict]:
    """As idas fora de casa: um segmento por país e por período contínuo."""
    lista = sorted([e for e in despesas if pais_da_despesa(e)], key=lambda e: (e.date, e.id))
    if not lista:
        return []
    casas = base_por_mes(lista)

    fora_de_casa = [e for e in lista if pais_da_despesa(e) != casas.get(_mes(e.date))]
    if not fora_de_casa:
        return []

    segmentos: list[dict] = []
    for e in fora_de_casa:
        p = pais_da_despesa(e)
        aberto = next(
            (s for s in segmentos
             if s["country"] == p and (e.date - s["end"]).days <= INTERVALO_MESMA_VIAGEM),
            None,
        )
        if aberto:
            aberto["end"] = max(aberto["end"], e.date)
            aberto["expenses"].append(e)
        else:
            segmentos.append({"country": p, "start": e.date, "end": e.date, "expenses": [e]})

    saida = []
    for s in segmentos:
        if len(s["expenses"]) < MINIMO_DESPESAS:
            continue
        nomes = {
            (cities.resolve(x.merchant_city) or ("", "", 0, 0))[0]
            for x in s["expenses"] if getattr(x, "merchant_city", None)
        }
        saida.append({
            **s,
            "cities": sorted(n for n in nomes if n),
            "home": casas.get(_mes(s["start"]), ""),
            "total": round(sum(x.amount for x in s["expenses"] if (x.amount or 0) > 0), 2),
        })
    saida.sort(key=lambda s: s["start"])
    return saida


def nome_do_pais(iso3: str) -> str:
    return cities.pais(iso3)[0]
