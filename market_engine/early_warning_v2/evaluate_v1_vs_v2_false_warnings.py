from pathlib import Path
import numpy as np
import pandas as pd

THRESHOLD = 0.50
FOLLOW_WINDOW = 10
WARNING_GAP = 0

ROOT = Path.cwd()

V1_PATH = ROOT / "data/processed/early_warning_v2/korea_oos_predictions_v1_reproduction_10d.csv"
V2_PATH = ROOT / "data/processed/early_warning_v2/korea_oos_predictions_exp_a_downside_10d.csv"
TARGET_PATH = Path.home() / "market-stress-early-warning/data/processed/korea/korea_targets.csv"

OUT_DIR = ROOT / "data/processed/early_warning_v2/event_validation"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_predictions(path):
    df = pd.read_csv(path, parse_dates=["Date"])
    return (
        df[["Date", "Prob_XGBoost"]]
        .sort_values("Date")
        .reset_index(drop=True)
    )


targets = (
    pd.read_csv(TARGET_PATH, parse_dates=["Date"])
    [["Date", "Is_Stress_Event"]]
    .sort_values("Date")
)

v1 = load_predictions(V1_PATH)
v2 = load_predictions(V2_PATH)


def identify_warning_episodes(scores):
    warning = (scores >= THRESHOLD).astype(int)

    positions = np.flatnonzero(
        warning.values == 1
    )

    if len(positions) == 0:
        return []

    episodes = []
    start = positions[0]
    previous = positions[0]

    for pos in positions[1:]:
        gap = pos - previous - 1

        if gap > WARNING_GAP:
            episodes.append({
                "start_pos": start,
                "end_pos": previous,
            })
            start = pos

        previous = pos

    episodes.append({
        "start_pos": start,
        "end_pos": previous,
    })

    return episodes


def evaluate_model(pred, model_name):
    df = (
        pred.merge(targets, on="Date", how="left")
        .sort_values("Date")
        .reset_index(drop=True)
    )

    if df["Is_Stress_Event"].isna().any():
        raise ValueError(
            f"{model_name}: missing stress labels."
        )

    df["Is_Stress_Event"] = (
        df["Is_Stress_Event"]
        .fillna(0)
        .astype(int)
    )

    scores = df["Prob_XGBoost"]
    stress = df["Is_Stress_Event"]

    episodes = identify_warning_episodes(scores)

    rows = []

    for episode_id, episode in enumerate(
        episodes,
        start=1,
    ):
        start_pos = episode["start_pos"]
        end_pos = episode["end_pos"]

        start_date = df.loc[start_pos, "Date"]
        end_date = df.loc[end_pos, "Date"]

        episode_scores = scores.iloc[
            start_pos:end_pos + 1
        ]

        full_window = (
            start_pos + FOLLOW_WINDOW < len(df)
        )

        hit = np.nan
        lead = np.nan

        if full_window:
            forward = stress.iloc[
                start_pos + 1:
                start_pos + FOLLOW_WINDOW + 1
            ]

            stress_positions = np.flatnonzero(
                forward.values == 1
            )

            hit = int(len(stress_positions) > 0)

            if hit:
                lead = int(stress_positions[0] + 1)

        rows.append({
            "Model": model_name,
            "Warning_Episode_ID": episode_id,
            "Warning_Start": start_date,
            "Warning_End": end_date,
            "Warning_Days": len(episode_scores),
            "Max_Risk_Score": episode_scores.max(),
            "Mean_Risk_Score": episode_scores.mean(),
            "Full_10D_Window": int(full_window),
            "Stress_Within_10D": hit,
            "Lead_To_Stress_10D": lead,
        })

    return pd.DataFrame(rows)


v1_results = evaluate_model(v1, "V1_17F")
v2_results = evaluate_model(v2, "V2_A_21F")

results = pd.concat(
    [v1_results, v2_results],
    ignore_index=True,
)

summary_rows = []

for model, group in results.groupby(
    "Model",
    sort=False,
):
    valid = group[
        group["Full_10D_Window"] == 1
    ].copy()

    total = len(valid)
    hits = int(valid["Stress_Within_10D"].sum())
    false_warnings = total - hits

    summary_rows.append({
        "Model": model,
        "Warning_Episodes": total,
        "Followed_By_Stress": hits,
        "False_Warning_Episodes": false_warnings,
        "Warning_Precision": (
            hits / total if total else np.nan
        ),
        "False_Warning_Rate": (
            false_warnings / total
            if total else np.nan
        ),
        "Median_Days_To_Stress": (
            valid.loc[
                valid["Stress_Within_10D"] == 1,
                "Lead_To_Stress_10D",
            ].median()
        ),
        "Median_Warning_Duration": (
            valid["Warning_Days"].median()
        ),
    })

summary = pd.DataFrame(summary_rows)

oos_start = max(v1["Date"].min(), v2["Date"].min())
oos_end = min(v1["Date"].max(), v2["Date"].max())
years = (oos_end - oos_start).days / 365.25

summary["False_Warning_Episodes_Per_Year"] = (
    summary["False_Warning_Episodes"] / years
)

results.to_csv(
    OUT_DIR / "v1_v2_false_warning_details.csv",
    index=False,
)

summary.to_csv(
    OUT_DIR / "v1_v2_false_warning_summary.csv",
    index=False,
)

print("\n=== FALSE WARNING VALIDATION ===")
print(f"Threshold     : {THRESHOLD:.2f}")
print(f"Follow window : {FOLLOW_WINDOW} trading days")
print(f"Warning gap   : {WARNING_GAP}")
print(
    f"OOS period    : "
    f"{oos_start.date()} -> {oos_end.date()}"
)
print(f"Approx years  : {years:.2f}")

print("\n=== SUMMARY ===")
print(summary.round(4).to_string(index=False))

print("\nSaved to:", OUT_DIR)
