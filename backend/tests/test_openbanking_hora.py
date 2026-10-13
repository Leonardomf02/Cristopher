"""A hora de um movimento vive num campo diferente em cada banco.

O Revolut (via Enable Banking) não a dá de todo — confirmado contra a conta
real: `transaction_date` vem a null e as datas são todas YYYY-MM-DD. Outros
bancos dão-na, e antes só se olhava para o `booking_date`. Estes testes fixam o
comportamento para os dois casos.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openbanking import _hora_do_movimento  # noqa: E402


def test_revolut_nao_da_hora():
    """Payload real de um movimento do Revolut, encurtado."""
    assert _hora_do_movimento({
        "booking_date": "2026-07-30",
        "value_date": "2026-07-30",
        "transaction_date": None,
        "transaction_amount": {"currency": "EUR", "amount": "446.92"},
    }) == ""


def test_transaction_date_ganha_ao_booking_date():
    """A hora da compra vale mais do que a hora a que o banco a processou."""
    assert _hora_do_movimento({
        "booking_date": "2026-07-31T09:00:00Z",
        "transaction_date": "2026-07-30T14:35:00Z",
    }) == "14:35"


def test_meia_noite_nao_conta_como_hora():
    """00:00 é uma data sem hora disfarçada de instante."""
    assert _hora_do_movimento({"booking_date": "2026-07-30T00:00:00"}) == ""


def test_encontra_hora_encaixada_no_payload():
    assert _hora_do_movimento({
        "booking_date": "2026-07-30",
        "bank_transaction_code": {"code": "CARD"},
        "note": None,
        "creditor": {"contact_details": {"processed_at": "2026-07-30 21:07:44"}},
    }) == "21:07"


def test_espaco_em_vez_de_T():
    assert _hora_do_movimento({"transaction_date": "2026-07-30 08:05:00"}) == "08:05"


def test_payload_vazio_nao_rebenta():
    assert _hora_do_movimento({}) == ""
    assert _hora_do_movimento({"booking_date": None, "value_date": ""}) == ""
