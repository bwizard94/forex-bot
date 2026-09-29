from src.data.fetcher import mids_from_usd_rates, usd_base_legs


def test_usd_base_legs() -> None:
    assert usd_base_legs(["EUR/USD", "GBP/USD", "USD/JPY"]) == ["EUR", "GBP", "JPY"]


def test_invert_usd_quote_pairs() -> None:
    rates = {"EUR": 0.866739, "GBP": 0.74239, "JPY": 155.27}
    mids = mids_from_usd_rates(rates, ["EUR/USD", "GBP/USD", "USD/JPY"])
    assert abs(mids["EUR/USD"] - (1 / 0.866739)) < 1e-9
    assert abs(mids["GBP/USD"] - (1 / 0.74239)) < 1e-9
    assert abs(mids["USD/JPY"] - 155.27) < 1e-9


def test_cross_from_usd_base() -> None:
    rates = {"EUR": 0.5, "GBP": 0.4}
    mids = mids_from_usd_rates(rates, ["EUR/GBP"])
    # EUR/GBP = GBP_per_USD / EUR_per_USD = 0.4 / 0.5
    assert abs(mids["EUR/GBP"] - 0.8) < 1e-9
