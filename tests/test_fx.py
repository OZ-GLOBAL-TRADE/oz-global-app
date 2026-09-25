from unittest.mock import Mock, patch

import pytest

from jarvis import fx


@pytest.fixture(autouse=True)
def _reset_cache():
    fx._cache["rates"], fx._cache["fetched_at"] = None, 0.0
    yield
    fx._cache["rates"], fx._cache["fetched_at"] = None, 0.0


def _fake_response(rates):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json.return_value = {"rates": rates}
    return resp


def test_get_rates_success_includes_base_at_1():
    with patch("jarvis.fx.requests.get", return_value=_fake_response({"EUR": 0.9, "TRY": 30.0})) as get:
        rates = fx.get_rates("USD")
    assert rates == {"USD": 1.0, "EUR": 0.9, "TRY": 30.0}
    get.assert_called_once()


def test_get_rates_is_cached_within_ttl():
    with patch("jarvis.fx.requests.get", return_value=_fake_response({"EUR": 0.9, "TRY": 30.0})) as get:
        fx.get_rates("USD")
        fx.get_rates("USD")
    get.assert_called_once()


def test_get_rates_network_failure_returns_none_when_no_cache():
    with patch("jarvis.fx.requests.get", side_effect=ConnectionError("no network")):
        assert fx.get_rates("USD") is None


def test_get_rates_network_failure_falls_back_to_stale_cache():
    with patch("jarvis.fx.requests.get", return_value=_fake_response({"EUR": 0.9, "TRY": 30.0})):
        fx.get_rates("USD")
    fx._cache["fetched_at"] = 0.0  # süresi dolmuş gibi davran
    with patch("jarvis.fx.requests.get", side_effect=ConnectionError("no network")):
        assert fx.get_rates("USD") == {"USD": 1.0, "EUR": 0.9, "TRY": 30.0}


def test_to_usd_same_currency_returns_amount_unchanged():
    assert fx.to_usd(100.0, "USD", {"USD": 1.0}) == 100.0


def test_to_usd_converts_using_rate():
    rates = {"USD": 1.0, "EUR": 0.9, "TRY": 30.0}
    assert fx.to_usd(90.0, "EUR", rates) == pytest.approx(100.0)
    assert fx.to_usd(300.0, "TRY", rates) == pytest.approx(10.0)


def test_to_usd_missing_rate_returns_none():
    assert fx.to_usd(100.0, "GBP", {"USD": 1.0, "EUR": 0.9}) is None


def test_convert_between_any_two_currencies():
    rates = {"USD": 1.0, "EUR": 0.9, "TRY": 30.0}
    assert fx.convert(100.0, "USD", "USD", rates) == 100.0
    assert fx.convert(90.0, "EUR", "USD", rates) == pytest.approx(100.0)
    assert fx.convert(100.0, "USD", "TRY", rates) == pytest.approx(3000.0)
    assert fx.convert(90.0, "EUR", "TRY", rates) == pytest.approx(3000.0)
    assert fx.convert(10.0, "GBP", "USD", rates) is None
