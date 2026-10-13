"""Cidades dos extractos: limpar, juntar variantes e dar coordenadas.

Os extractos escrevem a mesma cidade de várias maneiras (Warsaw/Warszawa,
Koebenhavn/Kobenhavn) e às vezes metem lá IBANs ou códigos de terminal. Isto
normaliza o nome, deita fora o que não é cidade e devolve lat/lon para o mapa.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

# nome normalizado → (nome bonito, país ISO3, lat, lon)
CIDADES: dict[str, tuple[str, str, float, float]] = {
    "krakow": ("Cracóvia", "POL", 50.06, 19.94),
    "kaszow": ("Cracóvia", "POL", 50.06, 19.94),
    "trabki": ("Cracóvia", "POL", 50.06, 19.94),
    "zielonki": ("Cracóvia", "POL", 50.12, 19.90),
    "wola batorska": ("Cracóvia", "POL", 50.06, 19.94),
    "warsaw": ("Varsóvia", "POL", 52.23, 21.01),
    "warszawa": ("Varsóvia", "POL", 52.23, 21.01),
    "katowice": ("Katowice", "POL", 50.26, 19.02),
    "gdansk": ("Gdansk", "POL", 54.35, 18.65),
    "sopot": ("Sopot", "POL", 54.44, 18.56),
    "poznan": ("Poznan", "POL", 52.41, 16.93),
    "wroclaw": ("Wroclaw", "POL", 51.11, 17.03),
    "ustron": ("Ustron", "POL", 49.72, 18.82),
    "lisboa": ("Lisboa", "PRT", 38.72, -9.14),
    "lisbon": ("Lisboa", "PRT", 38.72, -9.14),
    "coimbra": ("Coimbra", "PRT", 40.21, -8.43),
    "figueira da f": ("Figueira da Foz", "PRT", 40.15, -8.86),
    "london": ("Londres", "GBR", 51.51, -0.13),
    "london ec2m": ("Londres", "GBR", 51.52, -0.08),
    "edgware": ("Londres", "GBR", 51.61, -0.27),
    "southall": ("Londres", "GBR", 51.51, -0.38),
    "whitechapel": ("Londres", "GBR", 51.52, -0.06),
    "dublin": ("Dublin", "IRL", 53.35, -6.26),
    "dublin 2": ("Dublin", "IRL", 53.34, -6.26),
    "cork": ("Cork", "IRL", 51.90, -8.47),
    "amsterdam": ("Amesterdão", "NLD", 52.37, 4.90),
    "rotterdam": ("Roterdão", "NLD", 51.92, 4.48),
    "sneek": ("Sneek", "NLD", 53.03, 5.66),
    "woudsend": ("Woudsend", "NLD", 52.93, 5.63),
    "brussel": ("Bruxelas", "BEL", 50.85, 4.35),
    "luxembourg": ("Luxemburgo", "LUX", 49.61, 6.13),
    "berlin": ("Berlim", "DEU", 52.52, 13.40),
    "roma": ("Roma", "ITA", 41.90, 12.50),
    "fiumicino": ("Roma", "ITA", 41.80, 12.25),
    "milano": ("Milão", "ITA", 45.46, 9.19),
    "bergamo": ("Bergamo", "ITA", 45.70, 9.67),
    "venezia": ("Veneza", "ITA", 45.44, 12.32),
    "stockholm": ("Estocolmo", "SWE", 59.33, 18.07),
    "solna": ("Estocolmo", "SWE", 59.36, 18.00),
    "goteborg": ("Gotemburgo", "SWE", 57.71, 11.97),
    "malmoe": ("Malmö", "SWE", 55.60, 13.00),
    "kobenhavn": ("Copenhaga", "DNK", 55.68, 12.57),
    "koebenhavn": ("Copenhaga", "DNK", 55.68, 12.57),
    "koebenhavn k": ("Copenhaga", "DNK", 55.68, 12.57),
    "kastrup": ("Copenhaga", "DNK", 55.63, 12.65),
    "helsinki": ("Helsínquia", "FIN", 60.17, 24.94),
    "tallinn": ("Tallinn", "EST", 59.44, 24.75),
    "riga": ("Riga", "LVA", 56.95, 24.11),
    "rigalatvia": ("Riga", "LVA", 56.95, 24.11),
    "vilnius": ("Vilnius", "LTU", 54.69, 25.28),
    "kaunas": ("Kaunas", "LTU", 54.90, 23.90),
    "athens": ("Atenas", "GRC", 37.98, 23.73),
    "athina": ("Atenas", "GRC", 37.98, 23.73),
    "athina syntag": ("Atenas", "GRC", 37.98, 23.73),
    "moschato": ("Atenas", "GRC", 37.95, 23.68),
    "menemeni": ("Salónica", "GRC", 40.66, 22.90),
    "thessaloniki": ("Salónica", "GRC", 40.64, 22.94),
    "pireas": ("Pireu", "GRC", 37.94, 23.65),
    "aigina": ("Egina", "GRC", 37.75, 23.43),
    "anoliosia": ("Atenas", "GRC", 38.06, 23.72),
    "sofia": ("Sófia", "BGR", 42.70, 23.32),
    "sofiya": ("Sófia", "BGR", 42.70, 23.32),
    "bucuresti": ("Bucareste", "ROU", 44.43, 26.10),
    "bucuresti sec": ("Bucareste", "ROU", 44.43, 26.10),
    "sector 1": ("Bucareste", "ROU", 44.47, 26.08),
    "brasov": ("Brasov", "ROU", 45.66, 25.61),
    "bran": ("Bran", "ROU", 45.51, 25.37),
    "tirane": ("Tirana", "ALB", 41.33, 19.82),
    "budva": ("Budva", "MNE", 42.29, 18.84),
    "kotor": ("Kotor", "MNE", 42.42, 18.77),
    "ulcinj": ("Ulcinj", "MNE", 41.93, 19.20),
    "luqa": ("Luqa", "MLT", 35.86, 14.49),
    "qormi": ("Qormi", "MLT", 35.88, 14.47),
    "paceville": ("Paceville", "MLT", 35.92, 14.49),
    "st julians": ("St. Julian's", "MLT", 35.92, 14.49),
    "san francisco": ("São Francisco", "USA", 37.77, -122.42),
    "paris": ("Paris", "FRA", 48.86, 2.35),
    "madrid": ("Madrid", "ESP", 40.42, -3.70),
    "barcelona": ("Barcelona", "ESP", 41.39, 2.17),
    "porto": ("Porto", "PRT", 41.15, -8.61),
    "praha": ("Praga", "CZE", 50.08, 14.44),
    "prague": ("Praga", "CZE", 50.08, 14.44),
    "budapest": ("Budapeste", "HUN", 47.50, 19.04),
    "wien": ("Viena", "AUT", 48.21, 16.37),
    "vienna": ("Viena", "AUT", 48.21, 16.37),
    "zurich": ("Zurique", "CHE", 47.38, 8.54),
    "oslo": ("Oslo", "NOR", 59.91, 10.75),
    "reykjavik": ("Reiquiavique", "ISL", 64.15, -21.94),
    "istanbul": ("Istambul", "TUR", 41.01, 28.98),
}

# Não são cidades: IBANs, códigos de terminal, moradas cortadas.
_LIXO = re.compile(r"(\d{4,}|^[a-z]{1,2}$|^kasa|^ta$|^dl |\.(com|nl|uk)|^www\.)", re.I)


def _normaliza(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome.strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def resolve(nome: Optional[str]) -> Optional[tuple[str, str, float, float]]:
    """Nome do extracto → (cidade, país, lat, lon). None se não for cidade utilizável."""
    if not nome or not nome.strip():
        return None
    n = _normaliza(nome)
    if n in CIDADES:
        return CIDADES[n]
    if _LIXO.search(n) or len(n) < 3:
        return None
    # Nomes com sufixos de morada ("London Ec2m", "Bucuresti Sec"): tenta o 1º pedaço.
    primeiro = n.split(" ")[0]
    if primeiro in CIDADES:
        return CIDADES[primeiro]
    return None


# ISO3 → (nome em português, ISO2 para a bandeira)
PAISES: dict[str, tuple[str, str]] = {
    "POL": ("Polónia", "PL"), "PRT": ("Portugal", "PT"), "GBR": ("Reino Unido", "GB"),
    "IRL": ("Irlanda", "IE"), "NLD": ("Países Baixos", "NL"), "BEL": ("Bélgica", "BE"),
    "LUX": ("Luxemburgo", "LU"), "DEU": ("Alemanha", "DE"), "ITA": ("Itália", "IT"),
    "SWE": ("Suécia", "SE"), "DNK": ("Dinamarca", "DK"), "FIN": ("Finlândia", "FI"),
    "EST": ("Estónia", "EE"), "LVA": ("Letónia", "LV"), "LTU": ("Lituânia", "LT"),
    "GRC": ("Grécia", "GR"), "BGR": ("Bulgária", "BG"), "ROU": ("Roménia", "RO"),
    "ALB": ("Albânia", "AL"), "MNE": ("Montenegro", "ME"), "MLT": ("Malta", "MT"),
    "USA": ("Estados Unidos", "US"), "FRA": ("França", "FR"), "ESP": ("Espanha", "ES"),
    "CZE": ("Chéquia", "CZ"), "HUN": ("Hungria", "HU"), "AUT": ("Áustria", "AT"),
    "CHE": ("Suíça", "CH"), "NOR": ("Noruega", "NO"), "ISL": ("Islândia", "IS"),
    "TUR": ("Turquia", "TR"),
}


def pais(iso3: str) -> tuple[str, str]:
    return PAISES.get(iso3, (iso3, ""))
