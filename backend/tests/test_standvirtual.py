"""StandVirtual: os anúncios vêm do `__NEXT_DATA__` da página, já com campos."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import deal_attrs
import deals_sources as ds
from deals_sources import standvirtual as sv


def _pagina(anuncios: list[dict]) -> str:
    dados = {"props": {"pageProps": {"urqlState": {
        "chave": {"data": {"advertSearch": {"edges": [{"node": a} for a in anuncios]}}},
    }}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(dados)}</script></html>'


def _anuncio(**muda):
    base = {
        "id": "8097598048",
        "title": "Yamaha MT-07 35 KW",
        "url": "https://www.standvirtual.com/motos/anuncio/x.html",
        "location": {"city": {"name": "Rio Tinto"}, "region": {"name": "Porto"}},
        "price": {"amount": {"value": "6850", "currencyCode": "EUR"}},
        "thumbnail": {"x1": "https://exemplo/imagem.jpg"},
        "parameters": [
            {"key": "make", "value": "yamaha"},
            {"key": "model", "value": "mt-07"},
            {"key": "mileage", "value": "21500"},
            {"key": "first_registration_year", "value": "2021"},
            {"key": "engine_power", "value": "47"},
        ],
    }
    base.update(muda)
    return base


def test_a_fonte_esta_registada():
    assert "standvirtual" in ds.SOURCES
    assert "standvirtual" in ds.parse_sources("olx,facebook,standvirtual")


def test_le_os_anuncios_do_next_data():
    anuncios = sv._anuncios(_pagina([_anuncio()]))
    assert len(anuncios) == 1 and anuncios[0]["title"] == "Yamaha MT-07 35 KW"


def test_pagina_sem_next_data_nao_rebenta():
    assert sv._anuncios("<html>erro 502</html>") == []
    assert sv._anuncios("") == []


def test_atributos_vem_em_campos_e_nao_do_texto():
    """É a vantagem desta fonte: o ano e os km não são adivinhados."""
    a = sv._atributos({"title": "Yamaha MT-07"},
                      {"first_registration_year": "2021", "mileage": "21500",
                       "engine_power": "47"})
    assert a["year"] == 2021
    assert a["km"] == 21500


def test_a_potencia_e_arredondada_a_classe_legal():
    """45 cv dá 33 kW; com "exactamente 35" isso rejeitava uma A2 a sério."""
    assert sv._potencia_kw("Yamaha MT-07", {"engine_power": "45"}) == 35
    assert sv._potencia_kw("Yamaha MT-07", {"engine_power": "47"}) == 35
    assert sv._potencia_kw("Yamaha MT-07", {"engine_power": "73"}) == 55


def test_o_kw_escrito_ganha_aos_cavalos_do_motor():
    """Uma A2 traz o motor todo (75 cv) e "35 Kw" no título: é o título que vale.
    Sem isto, a mota que ele procurava era lida como 55 kW e deitada fora."""
    assert sv._potencia_kw("Yamaha MT-07 MT07 35 Kw",
                           {"version": "MT07 35 Kw", "engine_power": "75"}) == 35


def test_classe_de_potencia_nao_mexe_no_que_esta_longe():
    assert deal_attrs.classe_de_potencia(11) == 11
    assert deal_attrs.classe_de_potencia(125) == 125
    assert deal_attrs.classe_de_potencia(None) is None


def test_sem_potencia_fica_nao_diz():
    assert sv._atributos({"title": "Yamaha MT-07"}, {"mileage": "1000"})["power_kw"] is None


def test_slug_da_pesquisa():
    assert sv._slug("Yamaha MT-07") == "yamaha-mt-07"
    assert sv._slug("BMW  S1000RR!!") == "bmw-s1000rr"
    assert sv._slug("") == ""


def test_descricao_junta_o_que_ha_para_a_ia_ter_onde_procurar():
    d = sv._descricao({"shortDescription": "impecável"},
                      {"mileage": "21500", "first_registration_year": "2021"})
    assert "impecável" in d and "21500" in d and "2021" in d


def test_pesquisa_completa(monkeypatch):
    class Resposta:
        status_code = 200
        text = _pagina([_anuncio(), _anuncio(id="2", title="Yamaha MT-07 A2")])
        def raise_for_status(self): pass

    class Cliente:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, params=None): return Resposta()

    monkeypatch.setattr(sv.httpx, "Client", Cliente)
    r = sv.search("yamaha mt-07", max_price=8000, limit=10)
    assert len(r) == 2                       # sem duplicar entre motos e carros
    assert r[0].source == "standvirtual"
    assert r[0].price == 6850.0
    assert r[0].location == "Rio Tinto, Porto"
    assert r[0].attrs["year"] == 2021


def test_pesquisa_vazia_nao_pede_nada():
    assert sv.search("", limit=10) == []


# ── Facebook: 24 resultados por pesquisa, e nada mais ────────────

from deals_sources import facebook as fb        # noqa: E402
import deal_criteria as dc                      # noqa: E402


def test_varias_pesquisas_para_fugir_ao_tecto_de_24(monkeypatch):
    """Cada query dá uma janela diferente de 24 — um dos anúncios que ele queria
    só aparecia em "yamaha mt-07 35kw"."""
    por_query = {
        "yamaha mt 07": [("a", "MT-07 A"), ("b", "MT-07 B")],
        "yamaha mt-07 35kw": [("b", "MT-07 B"), ("c", "MT-07 C")],
    }

    def falso(q, **kw):
        from deals_sources.base import Listing
        return [Listing(source="facebook", external_id=i, title=t)
                for i, t in por_query.get(q, [])]

    monkeypatch.setattr(fb, "_search_uma", falso)
    r = fb.search("yamaha mt 07", extra_queries=["yamaha mt-07 35kw"], limit=40)
    assert [x.external_id for x in r] == ["a", "b", "c"]      # sem repetir o "b"


def test_pesquisas_alternativas_saem_dos_criterios():
    qs = dc.pesquisas_alternativas("Yamaha MT 07", {
        "power_kw_min": 35, "power_kw_max": 35, "colors": ["preto"],
        "year_min": 2021, "year_max": 2024})
    assert "yamaha mt-07" in qs                  # o hífen conta: é outra pesquisa
    assert any("35kw" in q for q in qs)
    assert any("preto" in q for q in qs)
    assert len(qs) <= 8                          # cada uma é um pedido


def test_sem_criterios_nao_inventa_pesquisas():
    assert dc.pesquisas_alternativas("iPhone 17", {}) == []
    assert dc.pesquisas_alternativas("", {"year_min": 2021}) == []


def _pagina_item(**kw):
    partes = []
    if kw.get("titulo", True):
        partes.append('"marketplace_listing_title":"Yamaha MT-07"')
    if kw.get("vendido"):
        partes.append('"is_sold":true')
    return "{" + ",".join(partes) + "}"


def test_anuncio_vivo_nao_e_dado_por_ido(monkeypatch):
    """Um anúncio some da pesquisa ao fim de dias sem estar vendido: a app dava
    19 anúncios vivos do Facebook como vendidos."""
    monkeypatch.setattr(fb, "_get", lambda *a, **k: _pagina_item())
    monkeypatch.setattr(fb.time, "sleep", lambda *_: None)
    assert fb.esta_vivo("123") is True




def test_vendido(monkeypatch):
    monkeypatch.setattr(fb, "_get", lambda *a, **k: _pagina_item(vendido=True))
    monkeypatch.setattr(fb.time, "sleep", lambda *_: None)
    assert fb.esta_vivo("123") is False


def test_apagado(monkeypatch):
    monkeypatch.setattr(fb, "_get", lambda *a, **k: _pagina_item(titulo=False))
    monkeypatch.setattr(fb.time, "sleep", lambda *_: None)
    assert fb.esta_vivo("123") is False


def test_facebook_em_baixo_nao_decide_nada(monkeypatch):
    """Sem resposta não se conclui que morreu — fica como está."""
    def rebenta(*a, **k):
        raise RuntimeError("timeout")
    monkeypatch.setattr(fb, "_get", rebenta)
    assert fb.esta_vivo("123") is None
