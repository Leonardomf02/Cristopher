"""Tests for the Finst screenshot OCR parser (_parse_finst_ocr).

Runs standalone:  python tests/test_finst_parser.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.investments import _parse_finst_ocr


def _by_symbol(parsed):
    return {p["instrument"]: p for p in parsed}


def test_vertical_layout_two_cryptos():
    """Real Tesseract output for the Finst portfolio table: each cell on its own
    line, with the name many lines away from the numbers. Regression for the case
    that extracted 0 cryptos (anchor was the distant name, and '1.698, 53€' lost
    the price to a stray space)."""
    text = "\n".join([
        "Name >", "", "Q Bb Bitcoin", "", "iv)", "", "4", "", "Vv", "", "Ethereum", "",
        "\\ Value", "", "161,26€", "0,00270406 BTC", "", "74,93€", "0,04411863 ETH", "",
        ") Price, BEP", "", "59.639,15€", "66.466,7226 €", "", "1.698, 53€", "2.036,78207 €", "",
        "| Daily P/L", "", "-4,A7€", "-2,70%", "", "-1,05€", "-1,38%", "",
        "/ Unrealized P/L", "", "-18,46€", "-10,27%", "", "-14,92€", "-16,61%",
    ])
    got = _by_symbol(_parse_finst_ocr(text))
    assert set(got) == {"BTC", "ETH"}, f"expected BTC+ETH, got {set(got)}"
    assert abs(got["BTC"]["quantity"] - 0.00270406) < 1e-9
    assert abs(got["BTC"]["value_eur"] - 161.26) < 0.01
    assert abs(got["BTC"]["current_price"] - 59639.15) < 0.1
    assert abs(got["ETH"]["quantity"] - 0.04411863) < 1e-9
    assert abs(got["ETH"]["value_eur"] - 74.93) < 0.01
    assert abs(got["ETH"]["current_price"] - 1698.53) < 0.1
    # BEP must be picked up so the return matches Finst (-18,46€ / -14,92€).
    assert abs(got["BTC"]["bep_price"] - 66466.7226) < 0.1
    assert abs(got["ETH"]["bep_price"] - 2036.78207) < 0.1
    btc_ret = got["BTC"]["value_eur"] - got["BTC"]["quantity"] * got["BTC"]["bep_price"]
    eth_ret = got["ETH"]["value_eur"] - got["ETH"]["quantity"] * got["ETH"]["bep_price"]
    assert abs(btc_ret - (-18.46)) < 0.05, btc_ret
    assert abs(eth_ret - (-14.92)) < 0.05, eth_ret


def test_implausible_bep_dropped():
    """A BEP that's nowhere near the current price (a stray column value) is dropped."""
    text = """Bitcoin
Value 161,26€ 0,00270406 BTC 74,93€ 0,04411863 ETH
Price 59.639,15€ 66.466,72€ 1.698,53€ 2.036,78€"""
    got = _by_symbol(_parse_finst_ocr(text))
    # BTC's bep must not be the ETH value (74.93) — it's implausible vs price 59639
    if "BTC" in got and got["BTC"].get("bep_price") is not None:
        bep = got["BTC"]["bep_price"]
        price = got["BTC"]["current_price"]
        assert price * 0.2 <= bep <= price * 5, f"implausible bep {bep} vs price {price}"


def test_list_layout_single_crypto():
    """Classic list layout where value/price sit on the qty line."""
    text = """Bitcoin
0,00184052 BTC 65.101,16€ 119,82€ +2,49%"""
    got = _by_symbol(_parse_finst_ocr(text))
    assert "BTC" in got
    assert abs(got["BTC"]["quantity"] - 0.00184052) < 1e-9


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
