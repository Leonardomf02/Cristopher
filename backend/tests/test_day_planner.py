"""O planeador punha o trabalho onde calhasse e às vezes deixava o jantar de fora.

A janela `produtivo` sai do histórico de código (waka_hour_days), não do relógio:
ele programa às 15h e das 22h à 1h, e as janelas genéricas ("de manhã", "à tarde")
não sabiam disso.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routers.day_planner import _plan_local, _to_min, _fmt, _window_bounds  # noqa: E402


def act(name, **kw):
    base = dict(id=abs(hash(name)) % 10000, name=name, icon="", color="", duration_min=60,
                duration_max=None, window="any", fixed_time=None, priority=1,
                splittable=False, chunk_max=None, enabled=True)
    base.update(kw)
    return SimpleNamespace(**base)


def blocos_de(blocks, nome):
    return [(b["start"], b["end"]) for b in blocks if b["name"] == nome]


def test_janela_produtiva_puxa_o_trabalho_para_as_horas_boas():
    trabalho = act("Trabalho", duration_min=120, duration_max=240, window="produtivo",
                   splittable=True, chunk_max=120, priority=2)
    wake, fim = _to_min("09:00"), _to_min("09:00") + 14 * 60
    produtiva = (_to_min("15:00"), _to_min("19:00"))

    blocks, unplaced = _plan_local([trabalho], wake, fim, produtiva)
    assert not unplaced
    for inicio, fimb in blocos_de(blocks, "Trabalho"):
        assert produtiva[0] <= inicio and fimb <= produtiva[1]


def test_sem_historico_a_janela_nao_restringe():
    """Sem dados que cheguem, `produtiva` vem a None e o dia todo serve —
    mais vale planear a uma hora qualquer do que não planear."""
    trabalho = act("Trabalho", duration_min=120, window="produtivo", priority=2)
    wake, fim = _to_min("09:00"), _to_min("09:00") + 14 * 60

    blocks, unplaced = _plan_local([trabalho], wake, fim, None)
    assert not unplaced
    assert blocos_de(blocks, "Trabalho")


def test_fora_da_janela_so_completa_o_minimo():
    """Se a janela boa não chega, trabalha-se a horas piores — mas só até ao
    mínimo. Esticar até ao máximo enchia a noite e deixava o jantar de fora."""
    trabalho = act("Trabalho", duration_min=120, duration_max=360, window="produtivo",
                   splittable=True, chunk_max=120, priority=2)
    gym = act("Gym", duration_min=120, window="any", priority=3)
    wake, fim = _to_min("09:00"), _to_min("09:00") + 14 * 60
    produtiva = (_to_min("09:00"), _to_min("11:00"))     # ocupada pelo gym

    blocks, unplaced = _plan_local([gym, trabalho], wake, fim, produtiva)
    assert not unplaced
    total = sum(f - i for i, f in blocos_de(blocks, "Trabalho"))
    assert 120 <= total < 360


def test_jantar_nao_fica_por_colocar_quando_a_tarde_acaba_cedo():
    """Bug antigo: sem nada ocupado à frente o cursor saltava para o fim do dia
    e passava por cima de uma janela que só abria mais tarde."""
    jantar = act("Jantar", duration_min=60, window="evening", priority=3)
    lol = act("LoL", duration_min=120, window="any", priority=1)
    wake, fim = _to_min("08:00"), _to_min("08:00") + 16 * 60

    blocks, unplaced = _plan_local([lol, jantar], wake, fim, None)
    assert "Jantar" not in unplaced
    assert blocos_de(blocks, "Jantar")


def test_nao_cria_blocos_de_15_minutos():
    trabalho = act("Trabalho", duration_min=60, duration_max=310, window="any",
                   splittable=True, chunk_max=120, priority=2)
    wake, fim = _to_min("09:00"), _to_min("09:00") + 5 * 60

    blocks, _ = _plan_local([trabalho], wake, fim, None)
    for inicio, fimb in blocos_de(blocks, "Trabalho"):
        assert fimb - inicio >= 30


def test_flexivel_que_cumpriu_o_minimo_nao_conta_como_por_colocar():
    trabalho = act("Trabalho", duration_min=60, duration_max=600, window="any",
                   splittable=True, chunk_max=120, priority=2)
    wake, fim = _to_min("09:00"), _to_min("09:00") + 3 * 60

    _, unplaced = _plan_local([trabalho], wake, fim, None)
    assert unplaced == []


def test_window_bounds_produtivo_cai_no_dia_todo_sem_dados():
    wake, fim = _to_min("09:00"), _to_min("23:00")
    assert _window_bounds("produtivo", wake, fim, 780, 1200, None) == (wake, fim)
    assert _window_bounds("produtivo", wake, fim, 780, 1200, (600, 900)) == (600, 900)
