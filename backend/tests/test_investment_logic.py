"""Tests for the pure investment helpers: capital-gains-tax netting, monthly
snapshot source coercion, and the market-pulse DCA nudge levels.

Runs standalone:  python tests/test_investment_logic.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.investments import _after_tax_return, _coerce_snapshot_source, CG_TAX_RATE
from routers.investment_signals import _pulse_level


def test_after_tax_taxes_only_gains():
    # ganho positivo → 28% de imposto
    assert _after_tax_return(100.0) == 72.0
    assert _after_tax_return(40.59) == round(40.59 * 0.72, 2)


def test_after_tax_no_tax_on_loss():
    # perda agregada → sem imposto, devolve o próprio valor
    assert _after_tax_return(-50.0) == -50.0
    assert _after_tax_return(0.0) == 0.0


def test_after_tax_rate_is_28():
    assert CG_TAX_RATE == 0.28


def test_snapshot_source_coercion():
    assert _coerce_snapshot_source("plano") == "plano"
    assert _coerce_snapshot_source("ia") == "ia"
    assert _coerce_snapshot_source("extra") == "extra"
    # qualquer coisa inválida cai em 'extra' (nunca rebenta)
    assert _coerce_snapshot_source("lixo") == "extra"
    assert _coerce_snapshot_source("") == "extra"


def test_pulse_levels():
    # drawdown negativo = % abaixo do topo
    assert _pulse_level(-1.0)[0] == "normal"
    assert _pulse_level(-4.9)[0] == "normal"
    assert _pulse_level(-5.0)[0] == "dip"
    assert _pulse_level(-9.9)[0] == "dip"
    assert _pulse_level(-10.0)[0] == "deep"
    assert _pulse_level(-30.0)[0] == "deep"


def test_pulse_hint_nonempty():
    for dd in (-1.0, -7.0, -20.0):
        level, hint = _pulse_level(dd)
        assert isinstance(hint, str) and len(hint) > 10
        assert level in ("normal", "dip", "deep")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
