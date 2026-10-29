"""
A1. 자산별 팩터 베타 분석

스냅샷(data/portfolio)으로 28개 지원 자산의 Market·Rate·Volatility 베타를 추정하고,
각 Stress 시나리오 충격을 곱한 자산별 추정 수익률을 표와 차트로 남깁니다.

    python -m analysis.portfolio_factor_betas
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from src.portfolio.factors import build_factor_moves, estimate_betas  # noqa: E402
from src.portfolio.scenarios import SCENARIOS_PATH  # noqa: E402
from src.portfolio.snapshot import (  # noqa: E402
    SNAPSHOT_FACTORS_PATH,
    SNAPSHOT_META_PATH,
    SNAPSHOT_PRICES_PATH,
)
from src.portfolio.universe import load_universe  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "portfolio"
TABLE_PATH = REPORT_DIR / "asset_factor_betas.csv"
CHART_PATH = REPORT_DIR / "asset_scenario_returns.png"

# 차트 색: 참조 팔레트(dataviz)의 diverging 양 끝. 손실 = red, 이익 = blue
LOSS, GAIN = "#e34948", "#2a78d6"
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
# |t| < 2인 베타는 0과 구분되지 않으므로 흐리게 표시
FADED_ALPHA = 0.3
T_THRESHOLD = 2

PANEL_TITLES = {
    "equity_selloff": "Equity sell-off: SPY {shock:+.1%}",
    "rate_shock": "Rate shock: 10Y yield {shock:+.0f} bp",
    "volatility_shock": "Volatility shock: VIX {shock:+.1f} pt",
}


def build_table(betas, universe, scenarios):
    """베타(원 단위)와 읽기 쉬운 환산값, 시나리오별 추정 수익률(%)을 한 표로 만듭니다."""
    table = universe[["name", "sector"]].join(betas)
    table["rate_pct_per_100bp"] = table["rate"] * 100 * 100
    table["vol_pct_per_10pt"] = table["volatility"] * 10 * 100
    for s in scenarios:
        table[f"{s['id']}_return_pct"] = table[s["factor"]] * s["shock"] * 100
    return table


def plot_scenario_returns(table, scenarios, meta):
    fig, axes = plt.subplots(1, 3, figsize=(13, 9), sharex=True, facecolor=SURFACE)

    for ax, s in zip(axes, scenarios):
        col = f"{s['id']}_return_pct"
        data = table[col].sort_values(ascending=False)  # 손실이 큰 자산이 위로
        t_values = table.loc[data.index, f"{s['factor']}_t"].abs()
        colors = [
            to_rgba(LOSS if v < 0 else GAIN, 1 if t >= T_THRESHOLD else FADED_ALPHA)
            for v, t in zip(data, t_values)
        ]

        ax.set_facecolor(SURFACE)
        ax.barh(data.index, data.values, height=0.7, color=colors)
        ax.axvline(0, color=INK_2, linewidth=1)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK_2, labelsize=9, length=0)
        ax.set_title(
            PANEL_TITLES[s["id"]].format(shock=s["shock"]),
            loc="left", fontsize=11, color=INK, fontweight="bold",
        )
        ax.set_xlabel("Estimated 10-day return (%)", color=INK_2, fontsize=9)

        # 손실이 가장 큰 3개 자산만 값 표시
        for ticker in data.index[-3:]:
            v = data[ticker]
            ax.text(v - 0.8, ticker, f"{v:.1f}%", va="center", ha="right",
                    fontsize=8.5, color=INK)

    lo = min(table[f"{s['id']}_return_pct"].min() for s in scenarios)
    axes[0].set_xlim(lo * 1.25, 12)

    fig.suptitle(
        "Estimated asset returns under each stress scenario (daily beta x historical 10-day shock)",
        x=0.01, ha="left", fontsize=13, color=INK, fontweight="bold",
    )
    fig.text(
        0.01, 0.948,
        f"Betas: separate univariate daily regressions, {meta['window_start']} to "
        f"{meta['window_end']} ({meta['window_days']} days). "
        "Scenarios are compared separately and never summed.",
        fontsize=9.5, color=INK_2,
    )
    fig.legend(
        handles=[
            Patch(color=LOSS, label="Loss"),
            Patch(color=GAIN, label="Gain"),
            Patch(color=to_rgba(LOSS, FADED_ALPHA),
                  label=f"Faded: |t| < {T_THRESHOLD}, not distinguishable from zero"),
        ],
        loc="upper left", bbox_to_anchor=(0.005, 0.94), ncol=3,
        frameon=False, fontsize=9, labelcolor=INK_2,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(CHART_PATH, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main():
    prices = pd.read_csv(SNAPSHOT_PRICES_PATH, index_col="Date", parse_dates=True)
    factors = pd.read_csv(SNAPSHOT_FACTORS_PATH, index_col="Date", parse_dates=True)
    meta = json.loads(SNAPSHOT_META_PATH.read_text())
    scenarios = json.loads(SCENARIOS_PATH.read_text())["scenarios"]
    universe = load_universe()

    asset_returns, factor_moves = build_factor_moves(prices, factors)
    betas = estimate_betas(asset_returns, factor_moves)
    table = build_table(betas, universe, scenarios)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    table.round(6).to_csv(TABLE_PATH)
    plot_scenario_returns(table, scenarios, meta)

    view = table[[
        "sector", "market", "market_r2", "rate_pct_per_100bp", "rate_t",
        "vol_pct_per_10pt", "volatility_r2",
    ] + [f"{s['id']}_return_pct" for s in scenarios]]
    print(view.round(3).to_string())
    print("corr(market, volatility) =",
          round(factor_moves["market"].corr(factor_moves["volatility"]), 3))
    print("corr(market, rate) =",
          round(factor_moves["market"].corr(factor_moves["rate"]), 3))


if __name__ == "__main__":
    main()
