"""Tests for the pure investment helpers: capital-gains-tax netting, monthly
snapshot source coercion, and the market-pulse DCA nudge levels.

Runs standalone:  python tests/test_investment_logic.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from routers.investments import (
    _after_tax_return, _coerce_snapshot_source, CG_TAX_RATE,
    _tax_class, _effective_cg_rate, _holding_days_from_month,
)
from routers.investment_signals import _pulse_level, _entry_cost_pct, _net_after_cost_tax


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


def test_tax_class():
    assert _tax_class("BTC", "finst") == "crypto"
    assert _tax_class("ETH", "trading212") == "crypto"   # ticker conhecido
    assert _tax_class("VUAA", "trading212") == "security"
    assert _tax_class("NVDA", "trading212") == "security"


def test_crypto_one_year_exemption():
    # cripto < 1 ano paga 28%; ≥ 1 ano fica isenta
    assert _effective_cg_rate("crypto", 364) == 0.28
    assert _effective_cg_rate("crypto", 365) == 0.0
    assert _effective_cg_rate("crypto", 800) == 0.0


def test_security_holding_exclusions():
    assert _effective_cg_rate("security", 100) == 0.28        # < 2 anos
    assert _effective_cg_rate("security", 2 * 365) == 0.252   # 2-5 anos
    assert _effective_cg_rate("security", 5 * 365) == 0.224   # 5-8 anos
    assert _effective_cg_rate("security", 8 * 365) == 0.196   # 8+ anos


def test_holding_days_from_month():
    today = date(2026, 6, 4)
    assert _holding_days_from_month("2026-04", today) == (today - date(2026, 4, 1)).days
    assert _holding_days_from_month("2026-06", today) == 3
    assert _holding_days_from_month("lixo", today) == 0   # nunca rebenta


def test_entry_cost_ordering():
    # cripto custa mais que ação, que custa mais (ou igual) que ETF
    assert _entry_cost_pct("crypto") > _entry_cost_pct("stock") > _entry_cost_pct("etf")
    assert _entry_cost_pct("etf") == 0.15


def test_net_after_cost_tax():
    # ganho de 10% numa ETF (custo 0.15%): (10-0.15)*0.72 ≈ 7.09
    assert abs(_net_after_cost_tax(10.0, "etf") - (9.85 * 0.72)) < 1e-6
    # cripto +10% (custo 1%): (10-1)*0.72 = 6.48
    assert abs(_net_after_cost_tax(10.0, "crypto") - (9.0 * 0.72)) < 1e-6
    # perda não paga imposto, só leva o custo
    assert _net_after_cost_tax(-5.0, "stock") == round(-5.0 - 0.30, 3)


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
