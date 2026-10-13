"""OLX: o ano, os km e a cor vêm em campos — e estavam a ser deitados fora.

O anúncio real "YAMAHA MT-07 (Akrapovic)" traz `Ano: 2018`, `Quilómetros:
22.000 km` e `Cor: azul` nos `params` da API, e no texto livre não diz nada
disso ("como nova, pronta a usar, pneu traseiro novo"). A app mostrava-o com
quatro pontos de interrogação, comparava-o com motas de todos os anos e ainda
ia gastar o modelo de visão a adivinhar-lhe a cor pela fotografia.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deals_sources import olx


def _param(chave, valor_chave, etiqueta=None):
    return {"key": chave, "value": {"key": valor_chave, "label": etiqueta or valor_chave}}


def _anuncio(**muda):
    base = {
        "id": "1013799231",
        "title": "YAMAHA MT-07 (Akrapovic)",
        "description": "YAMAHA MT-07 como nova, pronta a usar. <br />Pneu traseiro novo.",
        "url": "https://www.olx.pt/d/anuncio/yamaha-mt-07-akrapovic-IDJuObG.html",
        "params": [
            _param("condicao", "usado", "Usado"),
            _param("modelo", "mt-07", "MT-07"),
            {"key": "price", "value": {"value": 7000, "currency": "EUR", "label": "7.000 €"}},
            _param("year", "2018", "2018 "),
            _param("quilometros", "22000", "22.000 km"),
            _param("cor", "azul", "azul"),
        ],
    }
    base.update(muda)
    return base


def test_o_anuncio_da_o_ano_os_km_e_a_cor():
    a = olx._atributos(_anuncio())
    assert a["year"] == 2018
    assert a["km"] == 22000
    assert a["color"] == "azul"


def test_o_texto_deste_anuncio_nao_dizia_nada_disto():
    """A prova de que os campos são precisos: sem eles fica tudo em branco."""
    import deal_attrs
    a = _anuncio()
    lidos = deal_attrs.extrai(a["title"], a["description"])
    assert lidos["year"] is None and lidos["km"] is None and lidos["color"] is None


def test_a_etiqueta_serve_quando_a_chave_falta():
    a = olx._atributos(_anuncio(params=[
        {"key": "quilometros", "value": {"label": "22.000 km"}},
        {"key": "year", "value": {"label": "2018 "}},
    ]))
    assert a["km"] == 22000 and a["year"] == 2018


def test_cores_do_olx_viram_cores_da_app():
    def cor(v):
        return olx._atributos(_anuncio(params=[_param("cor", v)]))["color"]
    assert cor("prateado") == "cinzento"
    assert cor("preto") == "preto"
    assert cor("outra") is None          # não é cor nenhuma: fica "o anúncio não diz"


def test_sem_campos_nao_inventa():
    a = olx._atributos({"params": []})
    assert a == {"year": None, "km": None, "power_kw": None, "color": None}


def test_a_potencia_em_cavalos_e_arredondada_a_classe_legal():
    """Como no StandVirtual: 45 cv são uma A2 de 35 kW, não 33."""
    assert olx._atributos(_anuncio(params=[_param("potencia", "45")]))["power_kw"] == 35
    assert olx._atributos(_anuncio(params=[_param("potencia", "35 kW")]))["power_kw"] == 35


def test_a_condicao_vem_de_condicao_e_nao_so_de_state():
    """Nos veículos a chave chama-se `condicao`: as motos vinham todas sem condição."""
    assert olx._state(_anuncio()) == "Usado"
    assert olx._state({"params": [_param("state", "new", "Novo")]}) == "Novo"
    assert olx._state({"params": []}) == ""


def test_a_pesquisa_leva_os_campos_ate_ao_listing(monkeypatch):
    class Resposta:
        status_code = 200
        def json(self): return {"data": [_anuncio()]}
        def raise_for_status(self): pass

    class Cliente:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, params=None): return Resposta()

    monkeypatch.setattr(olx.curl, "Session", Cliente)
    r = olx.search("yamaha mt 07", limit=10)
    assert len(r) == 1
    assert r[0].price == 7000 and r[0].condition == "Usado"
    assert r[0].attrs == {"year": 2018, "km": 22000, "power_kw": None, "color": "azul"}


def test_o_texto_preenche_o_que_o_campo_nao_deu():
    """A fusão do router: o OLX raramente dá a potência, mas o título dá-a.

    Com o `attrs or extrai(...)` tudo-ou-nada de antes, um anúncio com três dos
    quatro campos ficava sem o quarto."""
    from routers.deals import _attrs_do_anuncio
    from deals_sources.base import Listing

    lst = Listing(source="olx", external_id="1", title="Yamaha MT-07 35 kW",
                  description="", attrs={"year": 2018, "km": 22000,
                                         "power_kw": None, "color": "azul"})
    a = _attrs_do_anuncio(lst)
    assert a == {"year": 2018, "km": 22000, "power_kw": 35, "color": "azul"}


def test_o_campo_ganha_ao_texto():
    from routers.deals import _attrs_do_anuncio
    from deals_sources.base import Listing

    lst = Listing(source="olx", external_id="1", title="Yamaha MT-07 de 2016",
                  description="Ano: 2016, 90.000 km",
                  attrs={"year": 2018, "km": 22000, "power_kw": None, "color": None})
    a = _attrs_do_anuncio(lst)
    assert a["year"] == 2018 and a["km"] == 22000
