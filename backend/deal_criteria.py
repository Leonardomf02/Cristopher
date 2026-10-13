"""O que ele quer, verificado anúncio a anúncio — e o preço justo do que quer.

Antes só havia um campo de texto solto (`ai_context`) que ia no prompt e mais
nada. Se a IA não lesse bem, o anúncio passava; e não havia forma de dizer
"potência exactamente 35 kW" sem esperar que ela percebesse. Agora os critérios
são campos, verificam-se com regras, e a IA recebe-os já verificados em vez de
ter de os descobrir.

Três respostas por critério, e a terceira é a que importa:

  cumpre · não cumpre · **o anúncio não diz**

Um anúncio sem quilómetros escritos não é um anúncio que falha os quilómetros.
Deitá-lo fora seria perder a mota certa por causa de um vendedor preguiçoso; por
isso o que não se sabe fica marcado como não sabido e o anúncio continua na
lista, mais abaixo.
"""
from __future__ import annotations

import re
from typing import Optional

import deal_attrs

CUMPRE, FALHA, NAO_DIZ = "ok", "fail", "unknown"

# Rótulos em português para a app não ter de os inventar em dois sítios.
ETIQUETAS = {
    "year": "Ano",
    "km": "Quilómetros",
    "power_kw": "Potência",
    "color": "Cor",
    "price": "Preço",
    "must_include": "Tem de dizer",
    "must_exclude": "Não pode dizer",
}


def _intervalo(valor: Optional[float], minimo, maximo) -> str:
    if minimo is None and maximo is None:
        return ""
    if valor is None:
        return NAO_DIZ
    if minimo is not None and valor < minimo:
        return FALHA
    if maximo is not None and valor > maximo:
        return FALHA
    return CUMPRE


def _texto_criterio(chave: str, criterios: dict, attrs: dict) -> str:
    """A frase que a app mostra ao lado do resultado."""
    if chave == "year":
        lo, hi = criterios.get("year_min"), criterios.get("year_max")
        pedido = f"{lo}-{hi}" if lo and hi else (f"desde {lo}" if lo else f"até {hi}")
        return f"{pedido} · anúncio: {attrs.get('year') or 'não diz'}"
    if chave == "km":
        return (f"até {criterios['km_max']:,} km".replace(",", ".") +
                f" · anúncio: {f'{attrs['km']:,}'.replace(',', '.') + ' km' if attrs.get('km') else 'não diz'}")
    if chave == "power_kw":
        lo, hi = criterios.get("power_kw_min"), criterios.get("power_kw_max")
        pedido = f"{lo} kW" if lo == hi else (f"{lo}-{hi} kW" if lo and hi else f"{lo or hi} kW")
        return f"{pedido} · anúncio: {str(attrs.get('power_kw') or 'não diz')}"
    if chave == "color":
        cores = ", ".join(criterios.get("colors") or [])
        lida = attrs.get("color")
        if not lida:
            return f"{cores} · o anúncio não diz e a foto não deu"
        origem = " (visto na foto)" if attrs.get("color_src") == "foto" else ""
        return f"{cores} · anúncio: {lida}{origem}"
    if chave == "price":
        return f"até {criterios['price_max']:.0f}€"
    return ""


def avalia(titulo: str, descricao: str, preco: Optional[float],
           criterios: Optional[dict], attrs: Optional[dict] = None) -> dict:
    """Confronta um anúncio com os critérios. Devolve o veredicto e o porquê.

    `attrs` para quando a fonte já os deu em campos (StandVirtual) — nesse caso
    não se adivinha nada do texto."""
    criterios = criterios or {}
    attrs = attrs if attrs else deal_attrs.extrai(titulo, descricao)
    texto = deal_attrs.normaliza(f"{titulo}\n{descricao}")
    verificacoes = []

    def junta(chave: str, estado: str) -> None:
        if not estado:
            return
        verificacoes.append({
            "key": chave,
            "label": ETIQUETAS.get(chave, chave),
            "status": estado,
            "detail": _texto_criterio(chave, criterios, attrs),
        })

    junta("year", _intervalo(attrs["year"], criterios.get("year_min"), criterios.get("year_max")))
    junta("km", _intervalo(attrs["km"], None, criterios.get("km_max")))
    junta("power_kw", _intervalo(attrs["power_kw"], criterios.get("power_kw_min"),
                                 criterios.get("power_kw_max")))

    cores = [deal_attrs.normaliza(c) for c in (criterios.get("colors") or [])]
    if cores:
        junta("color", NAO_DIZ if attrs["color"] is None
              else (CUMPRE if attrs["color"] in cores else FALHA))

    if criterios.get("price_max") is not None:
        junta("price", NAO_DIZ if preco is None
              else (CUMPRE if preco <= criterios["price_max"] else FALHA))

    for chave, obrigatorio in (("must_include", True), ("must_exclude", False)):
        palavras = [deal_attrs.normaliza(p) for p in (criterios.get(chave) or []) if p.strip()]
        if not palavras:
            continue
        presentes = [p for p in palavras if p in texto]
        if obrigatorio:
            em_falta = [p for p in palavras if p not in presentes]
            verificacoes.append({
                "key": chave, "label": ETIQUETAS[chave],
                "status": CUMPRE if not em_falta else FALHA,
                "detail": ", ".join(palavras) + (f" · falta: {', '.join(em_falta)}" if em_falta else ""),
            })
        else:
            verificacoes.append({
                "key": chave, "label": ETIQUETAS[chave],
                "status": FALHA if presentes else CUMPRE,
                "detail": ", ".join(palavras) + (f" · encontrado: {', '.join(presentes)}" if presentes else ""),
            })

    falhas = [v for v in verificacoes if v["status"] == FALHA]
    duvidas = [v for v in verificacoes if v["status"] == NAO_DIZ]
    return {
        "attrs": attrs,
        "checks": verificacoes,
        "verdict": FALHA if falhas else (NAO_DIZ if duvidas else CUMPRE),
        "failed": [v["label"] for v in falhas],
        "unknown": [v["label"] for v in duvidas],
        "score": len([v for v in verificacoes if v["status"] == CUMPRE]),
        "total": len(verificacoes),
    }


def resumo_para_prompt(criterios: Optional[dict]) -> str:
    """Os critérios em texto, para irem no pedido à IA já mastigados."""
    c = criterios or {}
    linhas = []
    if c.get("year_min") or c.get("year_max"):
        linhas.append(f"- Ano: {c.get('year_min') or '?'} a {c.get('year_max') or '?'} (obrigatório)")
    if c.get("km_max"):
        linhas.append(f"- Quilómetros: no máximo {c['km_max']:,}".replace(",", ".") + " km")
    if c.get("power_kw_min") or c.get("power_kw_max"):
        lo, hi = c.get("power_kw_min"), c.get("power_kw_max")
        linhas.append(f"- Potência: {lo} kW" if lo == hi else f"- Potência: {lo or '?'} a {hi or '?'} kW")
    if c.get("colors"):
        linhas.append(f"- Cor: {' ou '.join(c['colors'])} (a mota toda, não só detalhes)")
    if c.get("price_max"):
        linhas.append(f"- Preço: até {c['price_max']:.0f}€")
    if c.get("must_include"):
        linhas.append(f"- Tem de dizer na descrição: {', '.join(c['must_include'])}")
    if c.get("must_exclude"):
        linhas.append(f"- Não serve se disser: {', '.join(c['must_exclude'])}")
    return "\n".join(linhas)


# ── Preço justo ─────────────────────────────────────────────────────────

MINIMO_COMPARAVEIS = 6


def _mediana(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def preco_justo(comparaveis: list[dict], alvo: dict) -> Optional[dict]:
    """Quanto vale uma como esta.

    `comparaveis`: [{"price": float, "year": int|None, "km": int|None}, …].
    Compara com as do mesmo ano (alargando a janela até haver amostra) em vez de
    com tudo o que apareceu na pesquisa — a mediana de "tudo" misturava MT-09,
    MT-10 e um suporte de 20€, e dizia que uma de 2015 estava "2000€ abaixo do
    costume" quando estava no preço."""
    com_preco = [c for c in comparaveis if c.get("price")]
    if len(com_preco) < MINIMO_COMPARAVEIS:
        return None

    ano = alvo.get("year")
    base, descricao = None, ""
    if ano:
        # O ano exacto primeiro; só se não houver amostra que chegue é que se
        # alarga, e diz-se sempre com que amostra se ficou.
        for janela in (0, 1, 2, 3):
            iguais = [c for c in com_preco
                      if c.get("year") and abs(c["year"] - ano) <= janela]
            if len(iguais) >= MINIMO_COMPARAVEIS:
                base = iguais
                descricao = f"de {ano}" if janela == 0 else f"de {ano - janela} a {ano + janela}"
                break
    if base is None:
        base = [c for c in com_preco if c.get("year")] or com_preco
        descricao = "de todos os anos"

    # Havendo quilómetros que cheguem, compara-se com a metade parecida: uma de
    # 2019 com 9 mil km não vale o mesmo que uma de 2019 com 60 mil.
    km = alvo.get("km")
    com_km = [c for c in base if c.get("km")]
    if km and len(com_km) >= 2 * MINIMO_COMPARAVEIS:
        corte = _mediana([c["km"] for c in com_km])
        metade = [c for c in com_km if (c["km"] <= corte) == (km <= corte)]
        if len(metade) >= MINIMO_COMPARAVEIS:
            base = metade
            # O separador de milhares tem de ser trocado só no número: aplicar o
            # replace à frase toda comia a vírgula e dava "de 2019. com mais de".
            quantos = f"{corte:,.0f}".replace(",", ".")
            descricao += f", com {'menos' if km <= corte else 'mais'} de {quantos} km"

    precos = [c["price"] for c in base]
    return {
        "fair": round(_mediana(precos), 2),
        "n": len(precos),
        "basis": descricao,
        "p25": round(sorted(precos)[len(precos) // 4], 2),
        "p75": round(sorted(precos)[3 * len(precos) // 4], 2),
    }


def pesquisas_alternativas(query: str, criterios: Optional[dict]) -> list[str]:
    """Outras maneiras de perguntar a mesma coisa.

    O Facebook devolve 24 resultados por pesquisa e não pagina; cada forma de
    escrever traz uma janela diferente. Um anúncio que não aparecia em "Yamaha
    MT 07" aparecia em "yamaha mt-07 35kw" — e era uma das que ele queria."""
    c = criterios or {}
    base = (query or "").strip().lower()
    if not base:
        return []
    saida: list[str] = []

    compacto = base.replace("-", " ").replace("  ", " ")
    if compacto != base:
        saida.append(compacto)
    # O Facebook trata "mt 07" e "mt-07" como pesquisas diferentes e devolve 24
    # de cada — um dos anúncios que ele queria só aparecia com o hífen.
    hifenado = re.sub(r"(\b[a-z]{2})\s+(\d{2}\b)", r"\1-\2", base)
    if hifenado != base:
        saida.append(hifenado)
    sem_espaco = re.sub(r"(\b[a-z]{2})\s+(\d{2}\b)", r"\1\2", base)   # "mt 07" → "mt07"
    if sem_espaco != base:
        saida.append(sem_espaco)

    kw = c.get("power_kw_min") or c.get("power_kw_max")
    if kw:
        saida.append(f"{base} {int(kw)}kw")
    for cor in (c.get("colors") or [])[:1]:
        saida.append(f"{base} {cor}")
    anos = [a for a in (c.get("year_max"), c.get("year_min")) if a]
    saida.extend(f"{base} {ano}" for ano in anos)
    for palavra in (c.get("must_include") or [])[:1]:
        saida.append(f"{base} {palavra}")

    vistas, unicas = {base}, []
    for q in saida:
        if q not in vistas:
            vistas.add(q)
            unicas.append(q)
    return unicas[:8]          # cada uma é um pedido ao Facebook
