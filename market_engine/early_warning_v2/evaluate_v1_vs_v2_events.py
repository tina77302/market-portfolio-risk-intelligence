from pathlib import Path
import numpy as np
import pandas as pd

THRESHOLD = 0.50
LOOKBACK_DAYS = 10

ROOT = Path.cwd()

V1_PATH = ROOT / "data/processed/early_warning_v2/korea_oos_predictions_v1_reproduction_10d.csv"
V2_PATH = ROOT / "data/processed/early_warning_v2/korea_oos_predictions_exp_a_downside_10d.csv"
TARGET_PATH = Path.home() / "market-stress-early-warning/data/processed/korea/korea_targets.csv"

OUT_DIR = ROOT / "data/processed/early_warning_v2/event_validation"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_predictions(path, name):
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df[["Date", "Prob_XGBoost"]].copy()
    df = df.rename(columns={"Prob_XGBoost": name})
    return df


v1 = load_predictions(V1_PATH, "V1_Prob")
v2 = load_predictions(V2_PATH, "V2_Prob")

targets = pd.read_csv(
    TARGET_PATH,
    parse_dates=["Date"],
)[["Date", "Is_Stress_Event"]]

df = (
    v1.merge(v2, on="Date", how="inner")
      .merge(targets, on="Date", how="left")
      .sort_values("Date")
      .reset_index(drop=True)
)

if df["Is_Stress_Event"].isna().any():
    raise ValueError("Missing Is_Stress_Event labels on OOS dates.")

df["Is_Stress_Event"] = df["Is_Stress_Event"].astype(int)

# Stress episode onset/end:
# contiguous Is_Stress_Event == 1 observations form one episode.
previous = df["Is_Stress_Event"].shift(1).fillna(0)
next_value = df["Is_Stress_Event"].shift(-1).fillna(0)

onsets = df.index[
    (df["Is_Stress_Event"] == 1) & (previous == 0)
].tolist()

ends = df.index[
    (df["Is_Stress_Event"] == 1) & (next_value == 0)
].tolist()

events = []
end_pointer = 0

for event_id, onset_pos in enumerate(onsets, start=1):
    while end_pointer < len(ends) and ends[end_pointer] < onset_pos:
        end_pointer += 1

    if end_pointer >= len(ends):
        end_pos = len(df) - 1
    else:
        end_pos = ends[end_pointer]
        end_pointer += 1

    events.append((event_id, onset_pos, end_pos))


def evaluate_model(prob_col, model_name):
    rows = []

    for event_id, onset_pos, end_pos in events:
        lookback_start = max(0, onset_pos - LOOKBACK_DAYS)
        pre_event = df.iloc[lookback_start:onset_pos]

        alerts = pre_event[
            pre_event[prob_col] >= THRESHOLD
        ]

        detected = len(alerts) > 0

        first_warning = pd.NaT
        first_lead = np.nan
        last_warning = pd.NaT
        last_lead = np.nan

        if detected:
            first_pos = alerts.index[0]
            last_pos = alerts.index[-1]

            first_warning = df.loc[first_pos, "Date"]
            last_warning = df.loc[last_pos, "Date"]

            first_lead = onset_pos - first_pos
            last_lead = onset_pos - last_pos

        rows.append({
            "Model": model_name,
            "Event_ID": event_id,
            "Stress_Onset": df.loc[onset_pos, "Date"],
            "Stress_End": df.loc[end_pos, "Date"],
            "Event_Length": end_pos - onset_pos + 1,
            "Detected_Pre_Event": detected,
            "First_Warning": first_warning,
            "First_Warning_Lead_Days": first_lead,
            "Last_Warning": last_warning,
            "Last_Warning_Lead_Days": last_lead,
            "Max_Pre_Event_Prob": (
                pre_event[prob_col].max()
                if len(pre_event) else np.nan
            ),
        })

    return pd.DataFrame(rows)


v1_events = evaluate_model("V1_Prob", "V1_17F")
v2_events = evaluate_model("V2_Prob", "V2_A_21F")

results = pd.concat(
    [v1_events, v2_events],
    ignore_index=True,
)

summary_rows = []

for model, sub in results.groupby("Model", sort=False):
    detected = sub[sub["Detected_Pre_Event"]]

    summary_rows.append({
        "Model": model,
        "Stress_Episodes": len(sub),
        "Detected_Episodes": int(sub["Detected_Pre_Event"].sum()),
        "Missed_Episodes": int((~sub["Detected_Pre_Event"]).sum()),
        "Event_Coverage": sub["Detected_Pre_Event"].mean(),
        "Median_First_Lead": (
            detected["First_Warning_Lead_Days"].median()
            if len(detected) else np.nan
        ),
        "Mean_First_Lead": (
            detected["First_Warning_Lead_Days"].mean()
            if len(detected) else np.nan
        ),
    })

summary = pd.DataFrame(summary_rows)

comparison = v1_events[
    ["Event_ID", "Stress_Onset", "Detected_Pre_Event"]
].merge(
    v2_events[
        ["Event_ID", "Detected_Pre_Event"]
    ],
    on="Event_ID",
    suffixes=("_V1", "_V2"),
)

comparison["V2_Newly_Detected"] = (
    (~comparison["Detected_Pre_Event_V1"])
    & comparison["Detected_Pre_Event_V2"]
)

comparison["V2_Newly_Missed"] = (
    comparison["Detected_Pre_Event_V1"]
    & (~comparison["Detected_Pre_Event_V2"])
)

results.to_csv(
    OUT_DIR / "v1_v2_event_details.csv",
    index=False,
)

summary.to_csv(
    OUT_DIR / "v1_v2_event_summary.csv",
    index=False,
)

comparison.to_csv(
    OUT_DIR / "v1_v2_event_comparison.csv",
    index=False,
)

print("\n=== EVENT-LEVEL EARLY WARNING VALIDATION ===")
print(f"Threshold       : {THRESHOLD:.2f}")
print(f"Lookback        : {LOOKBACK_DAYS} trading days")
print(f"OOS rows        : {len(df)}")
print(f"OOS period      : {df['Date'].min().date()} -> {df['Date'].max().date()}")
print(f"Stress episodes : {len(events)}")

print("\n=== SUMMARY ===")
print(summary.round(4).to_string(index=False))

print("\n=== V2 CHANGES VS V1 ===")
print(
    "Newly detected episodes:",
    int(comparison["V2_Newly_Detected"].sum())
)
print(
    "Newly missed episodes:",
    int(comparison["V2_Newly_Missed"].sum())
)

print("\nNewly detected:")
print(
    comparison.loc[
        comparison["V2_Newly_Detected"],
        ["Event_ID", "Stress_Onset"]
    ].to_string(index=False)
)

print("\nNewly missed:")
print(
    comparison.loc[
        comparison["V2_Newly_Missed"],
        ["Event_ID", "Stress_Onset"]
    ].to_string(index=False)
)

print("\nSaved to:", OUT_DIR)
