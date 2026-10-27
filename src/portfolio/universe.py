from pathlib import Path

import pandas as pd

UNIVERSE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data" / "portfolio" / "universe.csv"
)

REQUIRED_COLUMNS = ["ticker", "name", "type", "sector", "asset_class"]
VALID_TYPES = {"stock", "etf"}
VALID_ASSET_CLASSES = {"equity", "bond", "commodity"}


def load_universe(path=UNIVERSE_PATH):
    """
    지원 자산 목록(티커·이름·유형·섹터·자산군)을 읽고 형식을 검증합니다.

    섹터는 yfinance info 대신 직접 작성한 CSV 값을 사용합니다.
    ETF는 내부 종목을 보지 않고 하나의 자산으로 취급합니다.
    """
    df = pd.read_csv(path)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"universe.csv에 필요한 컬럼이 없습니다: {missing}")

    if df[REQUIRED_COLUMNS].isna().any().any():
        raise ValueError("universe.csv에 빈 값이 있습니다.")

    duplicated = df.loc[df["ticker"].duplicated(), "ticker"].tolist()
    if duplicated:
        raise ValueError(f"중복된 티커가 있습니다: {duplicated}")

    bad_types = set(df["type"]) - VALID_TYPES
    if bad_types:
        raise ValueError(f"알 수 없는 type: {sorted(bad_types)}")

    bad_classes = set(df["asset_class"]) - VALID_ASSET_CLASSES
    if bad_classes:
        raise ValueError(f"알 수 없는 asset_class: {sorted(bad_classes)}")

    return df.set_index("ticker")
