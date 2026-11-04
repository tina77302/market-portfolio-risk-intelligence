"""Exercise Yahoo's silent partial failures without making network requests."""

from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from src.portfolio import data


def yahoo_frame(values):
    frame = pd.DataFrame(values, index=pd.date_range("2026-10-01", periods=3))
    return pd.concat({"Close": frame}, axis=1)


@pytest.fixture
def download(monkeypatch):
    mock = Mock()
    monkeypatch.setattr(data.yf, "download", mock)
    monkeypatch.setattr(data.time, "sleep", lambda _: None)
    return mock


def test_silent_failed_symbol_is_retried_without_redownloading_successes(download):
    download.side_effect = [
        yahoo_frame({"SPY": [100, 101, 102], "AAPL": [np.nan] * 3, "^VIX": [20, 21, 22]}),
        yahoo_frame({"AAPL": [200, 201, 202]}),
    ]
    actual = data.fetch_prices(["SPY", "AAPL"], "2018-01-01")
    assert download.call_args_list[1].args[0] == ["AAPL"]
    assert all(call.kwargs["threads"] is False for call in download.call_args_list)
    assert list(actual.columns) == ["SPY", "AAPL", "VIX"]
    assert actual.AAPL.tolist() == [200, 201, 202]
    assert actual.SPY.tolist() == [100, 101, 102]


def test_missing_column_and_empty_response_recover(download):
    download.side_effect = [
        yahoo_frame({"SPY": [100, 101, 102], "^VIX": [20, 21, 22]}),
        None,
        yahoo_frame({"AAPL": [200, 201, 202]}),
    ]
    assert data.fetch_prices(["SPY", "AAPL"], "2018-01-01").AAPL.notna().all()
    assert download.call_count == 3


def test_exception_can_recover_on_next_attempt(download):
    download.side_effect = [RuntimeError("database is locked"),
                            yahoo_frame({"SPY": [100, 101, 102], "^VIX": [20, 21, 22]})]
    assert len(data.fetch_prices(["SPY"], "2018-01-01")) == 3


def test_persistent_failure_names_symbol_and_stops(download):
    download.return_value = yahoo_frame({"SPY": [100, 101, 102], "^VIX": [20, 21, 22]})
    with pytest.raises(data.PriceCollectionError, match="after 3 attempts: AAPL"):
        data.fetch_prices(["SPY", "AAPL"], "2018-01-01")
    assert download.call_count == 3


def test_partial_history_is_not_forward_filled(download):
    download.return_value = yahoo_frame({"SPY": [100, 101, 102], "AAPL": [200, np.nan, 202],
                                         "^VIX": [20, 21, 22]})
    actual = data.fetch_prices(["SPY", "AAPL"], "2018-01-01")
    assert pd.isna(actual.AAPL.iloc[1])
    assert download.call_count == 1
