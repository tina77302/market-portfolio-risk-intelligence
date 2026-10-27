import pytest

from src.portfolio.universe import load_universe


def test_universe_loads_with_unique_tickers():
    universe = load_universe()

    assert len(universe) >= 10
    assert universe.index.is_unique
    assert "SPY" in universe.index


def test_every_asset_has_sector_and_class():
    universe = load_universe()

    assert universe["sector"].str.len().gt(0).all()
    assert set(universe["type"]) <= {"stock", "etf"}
    assert set(universe["asset_class"]) <= {"equity", "bond", "commodity"}


def test_duplicate_ticker_is_rejected(tmp_path):
    path = tmp_path / "universe.csv"
    path.write_text(
        "ticker,name,type,sector,asset_class\n"
        "SPY,SPDR S&P 500 ETF Trust,etf,Broad Equity,equity\n"
        "SPY,SPDR S&P 500 ETF Trust,etf,Broad Equity,equity\n"
    )

    with pytest.raises(ValueError, match="중복"):
        load_universe(path)
