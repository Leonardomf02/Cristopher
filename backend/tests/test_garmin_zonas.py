"""Zonas de frequência cardíaca: os limiares do relógio e o tempo em cada uma.

O tempo por zona sai das próprias leituras (uma de 2 em 2 minutos), e a única
parte que não é óbvia é o que fazer quando o relógio sai do pulso: sem tecto, um
buraco de seis horas contava como seis horas em zona 1 — a zona da última leitura
antes de ele o tirar.

Corre sozinho:  python tests/test_garmin_zonas.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cache
import garmin_sync
from routers.garmin import _zonas_fc

ZONAS = {"floors": [98, 118, 137, 157, 176], "max": 196, "resting": 87,
         "method": "HR_MAX"}
MINUTO = 60_000


def _com_zonas(guardadas=ZONAS):
    cache.cache_invalidate(garmin_sync.CHAVE_ZONAS_FC)
    if guardadas is not None:
        cache.cache_set(garmin_sync.CHAVE_ZONAS_FC, guardadas, 3600)


def _serie(bpms, passo_min=2, inicio=1_786_489_200_000):
    return {"hr": [[inicio + i * passo_min * MINUTO, bpm] for i, bpm in enumerate(bpms)]}


def test_sem_zonas_guardadas_nao_inventa():
    _com_zonas(None)
    assert _zonas_fc(_serie([60, 62, 64])) is None


def test_cada_leitura_cai_na_sua_zona():
    _com_zonas()
    # 60 é repouso (abaixo da zona 1), 100 é zona 1, 120 zona 2, 140 zona 3,
    # 160 zona 4 e 180 zona 5. A última leitura vale zero: não há seguinte, e
    # por isso não se sabe quanto tempo ela durou.
    z = _zonas_fc(_serie([60, 100, 120, 140, 160, 180, 180]))
    assert z["minutes"] == [2, 2, 2, 2, 2, 2]
    assert z["floors"] == ZONAS["floors"]


def test_o_piso_da_zona_conta_para_a_zona():
    _com_zonas()
    z = _zonas_fc(_serie([98, 98]))
    assert z["minutes"][1] == 2          # 98 é o piso da zona 1, não repouso


def test_buraco_de_horas_nao_vira_horas_na_ultima_zona():
    """Relógio fora do pulso: entre as duas leituras passaram 6 horas."""
    _com_zonas()
    serie = {"hr": [[0, 120], [6 * 60 * MINUTO, 60], [6 * 60 * MINUTO + 2 * MINUTO, 60]]}
    z = _zonas_fc(serie)
    assert z["minutes"][2] == 5          # tecto de 5 min, não 360
    assert sum(z["minutes"]) == 7


def test_dia_sem_leituras_da_zeros():
    _com_zonas()
    z = _zonas_fc({"hr": []})
    assert z["minutes"] == [0, 0, 0, 0, 0, 0]


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
