"""Ler o anúncio, confrontar com o que ele quer, e dizer quanto vale.

Os casos vieram todos dos anúncios reais que estão na base — incluindo os que
partiram a primeira versão das regras.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import deal_attrs as da
import deal_criteria as dc


# ── Ler o anúncio ───────────────────────────────────────────────

def test_potencia_nao_apanha_digitos_do_modelo():
    """"MT-07 35kw" lia-se como 7 kW: a regex agarrava o "07"."""
    assert da.extrai_potencia_kw("Yamaha MT-07 35kw 2014 – 30.000 km") == 35


def test_potencia_nao_apanha_digitos_do_ano():
    """"2020 35 KW" dava 20 kW pela mesma razão."""
    assert da.extrai_potencia_kw("Yamaha MT-07 2020 35 KW (A2) - Deslimitada") == 35


def test_potencia_pela_carta_a2_e_pelo_full_power():
    assert da.extrai_potencia_kw("MT-07 versão A2") == 35
    assert da.extrai_potencia_kw("Yamaha MT-07 2024 – Full Power") == 55


def test_potencia_ignora_o_a2_de_ha_2_anos():
    assert da.extrai_potencia_kw("comprada há 2 anos, impecável") is None


def test_potencia_em_cavalos_convertida():
    assert da.extrai_potencia_kw("MT-07 com 75 cv") == 55


def test_quilometros_nos_formatos_todos():
    assert da.extrai_km("13mil km") == 13000
    assert da.extrai_km("30.000 km") == 30000
    assert da.extrai_km("Yamaha MT-07 2019 - 30 599 km") == 30599
    assert da.extrai_km("apenas 9.500 km") == 9500
    assert da.extrai_km("cerca de 18000kms") == 18000


def test_quilometros_nao_confunde_distancia_nem_autonomia():
    assert da.extrai_km("a 20 km de Lisboa") is None


def test_ano_do_titulo():
    assert da.extrai_ano("Yamaha MT 07 2016 ABS") == 2016
    assert da.extrai_ano("Yamaha MT-07 (ago/2014)") == 2014


def test_ano_ignora_precos_e_quilometros():
    assert da.extrai_ano("Yamaha MT-07 por 5600€") is None
    assert da.extrai_ano("MT-07 com 2000 km") is None


def test_na_descricao_o_ano_precisa_de_pista():
    """Sem exigir pista, "Ano 2017 … Preço 5200" dava 2023, e "de 2015" dava 2024."""
    assert da.extrai_ano("Ano 2017\nkm: 26.400km\nPreço 5200", exige_pista=True) == 2017
    assert da.extrai_ano("YAMAHA MT-07 ABS de 2015 sem acidentes", exige_pista=True) == 2015
    assert da.extrai_ano("Aceitamos retomas. Financiamento 2026 disponível",
                         exige_pista=True) is None


def test_o_titulo_manda_sobre_a_descricao():
    """"espelho para FZ6" trazia um ano da descrição como se fosse o da mota."""
    a = da.extrai("Yamaha MT-07 2022", "Tive uma de 2015 antes desta")
    assert a["year"] == 2022


def test_cor():
    assert da.extrai_cor("Yamaha MT-07 preta") == "preto"
    assert da.extrai_cor("MT-07 Azul – Como Nova") == "azul"
    assert da.extrai_cor("Yamaha MT-07") is None


# ── Confrontar com o que ele quer ───────────────────────────────

CRITERIOS = {
    "year_min": 2021, "year_max": 2024,
    "km_max": 10000,
    "power_kw_min": 35, "power_kw_max": 35,
    "colors": ["preto"],
    "must_include": ["akrapovic"],
}


def test_a_que_cumpre_tudo():
    r = dc.avalia("Yamaha MT-07 2022 35kw preta", "Akrapovic, 8.000 km", 6500, CRITERIOS)
    assert r["verdict"] == dc.CUMPRE
    assert r["failed"] == []


def test_ano_fora_do_intervalo_falha():
    r = dc.avalia("Yamaha MT-07 2019 35kw preta", "Akrapovic, 8.000 km", 6500, CRITERIOS)
    assert r["verdict"] == dc.FALHA
    assert "Ano" in r["failed"]


def test_potencia_errada_falha():
    r = dc.avalia("Yamaha MT-07 2022 55kw preta", "Akrapovic, 8.000 km", 6500, CRITERIOS)
    assert "Potência" in r["failed"]


def test_o_que_o_anuncio_nao_diz_nao_e_um_nao():
    """O vendedor não escrever os km não pode deitar a mota certa fora."""
    r = dc.avalia("Yamaha MT-07 2022", "Com Akrapovic", 6500, CRITERIOS)
    assert r["verdict"] == dc.NAO_DIZ
    assert r["failed"] == []
    assert "Quilómetros" in r["unknown"] and "Cor" in r["unknown"]


def test_palavra_obrigatoria_em_falta_falha():
    r = dc.avalia("Yamaha MT-07 2022 35kw preta", "8.000 km, impecável", 6500, CRITERIOS)
    assert "Tem de dizer" in r["failed"]


def test_palavra_proibida_falha():
    r = dc.avalia("Yamaha MT-07 2022", "", 6500, {"must_exclude": ["acidentada"]})
    assert r["verdict"] == dc.CUMPRE
    r2 = dc.avalia("Yamaha MT-07 2022 acidentada", "", 6500, {"must_exclude": ["acidentada"]})
    assert r2["verdict"] == dc.FALHA


def test_sem_criterios_passa_tudo():
    assert dc.avalia("Seja o que for", "", 10, {})["verdict"] == dc.CUMPRE
    assert dc.avalia("Seja o que for", "", 10, None)["verdict"] == dc.CUMPRE


def test_acentos_e_maiusculas_nao_interessam():
    """O Akrapovič vem escrito com e sem caron; tem de dar no mesmo."""
    r = dc.avalia("YAMAHA MT-07 2022 35KW PRETA", "AKRAPOVIČ montado, 8.000 KM",
                  6500, CRITERIOS)
    assert r["verdict"] == dc.CUMPRE


# ── Quanto vale ─────────────────────────────────────────────────

def _mercado(por_ano: int = 8):
    """Um mercado onde o ano pesa: cada ano mais novo, mais caro."""
    return [{"price": 4000 + (ano - 2014) * 400, "year": ano, "km": 20000}
            for ano in range(2014, 2025) for _ in range(por_ano)]


def test_compara_com_as_do_mesmo_ano():
    r = dc.preco_justo(_mercado(), {"year": 2016})
    assert r["fair"] == 4800                     # 4000 + 2*400
    assert r["basis"] == "de 2016"


def test_com_poucas_do_mesmo_ano_alarga_e_diz_que_alargou():
    """Melhor comparar com anos vizinhos do que com nada — mas tem de se ver."""
    r = dc.preco_justo(_mercado(por_ano=2), {"year": 2016})
    assert r["basis"] == "de 2015 a 2017"
    assert r["n"] == 6


def test_sem_ano_no_anuncio_usa_tudo():
    r = dc.preco_justo(_mercado(), {"year": None})
    assert r["basis"] == "de todos os anos"


def test_amostra_pequena_nao_da_preco():
    assert dc.preco_justo([{"price": 5000, "year": 2019}], {"year": 2019}) is None


def test_a_mediana_de_tudo_mentia():
    """O caso real: a app dizia "900€ abaixo do costume" numa que está acima."""
    mercado = _mercado()
    tudo = sorted(c["price"] for c in mercado)
    mediana_de_tudo = tudo[len(tudo) // 2]
    justo_2016 = dc.preco_justo(mercado, {"year": 2016})["fair"]
    assert justo_2016 < mediana_de_tudo          # uma de 2016 vale menos que "o costume"


def test_quilometros_separam_quando_ha_amostra():
    mercado = ([{"price": 7000, "year": 2020, "km": 5000} for _ in range(8)] +
               [{"price": 5000, "year": 2020, "km": 60000} for _ in range(8)])
    poucos = dc.preco_justo(mercado, {"year": 2020, "km": 6000})
    muitos = dc.preco_justo(mercado, {"year": 2020, "km": 55000})
    assert poucos["fair"] == 7000 and muitos["fair"] == 5000
    assert "km" in poucos["basis"]


def test_resumo_para_prompt_diz_o_essencial():
    texto = dc.resumo_para_prompt(CRITERIOS)
    assert "2021" in texto and "10.000 km" in texto and "35 kW" in texto
    assert "preto" in texto and "akrapovic" in texto


# ── Falsos positivos que quase lhe custavam uma viagem ───────────

def test_intervalo_de_revisao_nao_e_a_quilometragem():
    """"Revisões de 5 em 5 mil km" numa mota com 25.000 dava 5.000 — e ela
    passava a cumprir um limite de 10.000 km que não cumpre."""
    desc = ("MT 07 35kw 2022. A mota conta com 25.000km. Pneus em bom estado. "
            "Revisões feitas sempre de 5 em 5 mil km.")
    assert da.extrai_km(desc) == 25000


def test_o_primeiro_numero_de_km_e_o_da_mota():
    assert da.extrai_km("Tem 42.000 km. Troca de óleo cada 5000 km") == 42000


def test_cor_de_uma_peca_nao_e_a_cor_da_mota():
    """"Símbolos Yamaha em preto" e "farol traseiro preto" não fazem a mota preta."""
    a = da.extrai("MT 07 35kw 2022.",
                  "Símbolos Yamaha em preto. Farol traseiro preto com piscas embutidos.")
    assert a["color"] is None


def test_cor_no_titulo_conta():
    assert da.extrai("Yamaha MT-07 preta", "")["color"] == "preto"


def test_cor_com_pista_na_descricao_conta():
    assert da.extrai("Yamaha MT-07", "Cor: azul metalizado")["color"] == "azul"
    assert da.extrai("Yamaha MT-07", "Vendo mota azul, impecável")["color"] == "azul"


def test_jantes_pretas_nao_fazem_a_mota_preta():
    assert da.extrai("Yamaha MT-07", "jantes pretas e pneus novos")["color"] is None
