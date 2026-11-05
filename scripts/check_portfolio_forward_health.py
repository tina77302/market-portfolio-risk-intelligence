"""Stdlib checks for collection health and missing scheduled validation runs.

Reports GitHub error annotations and nonzero exit codes; delivery follows the
account's GitHub Actions notification settings. Never changes sealed study data.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

WORKFLOW = "portfolio-forward-validation.yml"
WORKFLOW_PATH = f".github/workflows/{WORKFLOW}"
COLLECTION_CRON = "37 23 * * 1,2,3,4,5"
GRACE = timedelta(minutes=90)
NY = ZoneInfo("America/New_York")
HEALTHY_STATES = {"WAITING_FOR_START_SESSION", "WAITING_FOR_OUTCOME", "EVALUATED"}
INPUT_STATES = {"WAITING_FOR_INPUT", "WAITING_FOR_FRESH_INPUT", "WAITING_FOR_ENDPOINT_RATE"}


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return result.astimezone(timezone.utc)


def report(ok, code, message, now, **details):
    return {"ok": ok, "code": code, "message": message,
            "checked_at": now.isoformat(), **details}


def check_status(status, now):
    at = timestamp(status["at"])
    state = status["status"]
    details = {"validation_status": state, "status_at": at.isoformat()}
    if at > now + timedelta(minutes=5) or now - at > timedelta(minutes=30):
        return report(False, "STALE_STATUS", "Collection did not produce a current status record.", now, **details)
    if state in INPUT_STATES:
        reason = status.get("reason") or status.get("fetch_error_type") or state
        return report(False, "INPUT_UNAVAILABLE", f"Validation input unavailable: {reason}", now, **details)
    if state not in HEALTHY_STATES:
        return report(False, "UNKNOWN_STATUS", "Unrecognized validation status; inspect the collector.", now, **details)
    as_of = date.fromisoformat(status["input_as_of"])
    age = (now.astimezone(NY).date() - as_of).days
    if age < 1 or age > 4:
        return report(False, "STALE_INPUT", "Input must be completed and no more than four calendar days old.",
                      now, input_as_of=as_of.isoformat(), **details)
    return report(True, "HEALTHY", "Inputs are current; validation is progressing or waiting normally.",
                  now, input_as_of=as_of.isoformat(), **details)


def latest_due(now):
    now = now.astimezone(timezone.utc)
    for offset in range(8):
        candidate = (now - timedelta(days=offset)).replace(hour=23, minute=37, second=0, microsecond=0)
        if candidate.weekday() < 5 and candidate <= now:
            return candidate
    raise ValueError("no scheduled slot found")


def check_schedule(workflow, runs, branch, now):
    due = latest_due(now)
    details = {"expected_schedule_at": due.isoformat(), "grace_minutes": 90}
    if workflow["path"] != WORKFLOW_PATH or workflow["state"] != "active":
        return report(False, "WORKFLOW_INACTIVE", "Collection workflow is missing, renamed or disabled.", now, **details)
    if timestamp(workflow["created_at"]) > due:
        return report(True, "WAITING_FOR_FIRST_SCHEDULE", "No schedule was due since the workflow was created.", now, **details)
    if now < due + GRACE:
        return report(True, "SCHEDULE_GRACE_PERIOD", "The latest schedule is still within its delay allowance.", now, **details)
    eligible = [r for r in runs if r["event"] == "schedule" and r["head_branch"] == branch
                and r["path"] == WORKFLOW_PATH and due <= timestamp(r["created_at"]) <= now]
    if not eligible:
        return report(False, "MISSING_SCHEDULE", "No scheduled collection run appeared within 90 minutes.", now, **details)
    run = max(eligible, key=lambda r: (timestamp(r["created_at"]), r["id"]))
    details.update(run_id=run["id"], run_url=run["html_url"])
    if run["status"] != "completed":
        return report(False, "SCHEDULE_NOT_COMPLETED", "Scheduled collection has not completed after the delay allowance.", now, **details)
    if run["conclusion"] != "success":
        return report(False, "SCHEDULE_FAILED", f"Scheduled collection concluded: {run['conclusion']}", now, **details)
    return report(True, "SCHEDULE_HEALTHY", "The latest scheduled collection completed successfully.", now, **details)


def github_get(path):
    # Fixed API origin; do not send the workflow token to configurable hosts.
    request = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def scheduled_health(repository, now, get=github_get):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository identity")
    root = f"/repos/{repository}"
    branch = get(root)["default_branch"]
    workflow = get(f"{root}/actions/workflows/{WORKFLOW}")
    # Read every matching page; a burst of runs must not hide the schedule.
    query = urllib.parse.urlencode({"event": "schedule", "branch": branch,
                                   "created": ">=" + latest_due(now).isoformat(), "per_page": 100})
    runs = []
    for page in range(1, 11):
        batch = get(f"{root}/actions/workflows/{WORKFLOW}/runs?{query}&page={page}")["workflow_runs"]
        runs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError("run history pagination limit reached; cannot confirm schedule")
    return check_schedule(workflow, runs, branch, now)


def emit(result, output=None):
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(payload, end="")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(f"### Portfolio validation health: {result['code']}\n\n{result['message']}\n\n")
            summary.write(f"Checked at: `{result['checked_at']}`\n\n")
            for key in ("validation_status", "input_as_of", "expected_schedule_at", "run_url"):
                if key in result:
                    summary.write(f"- {key}: {result[key]}\n")
    if not result["ok"]:
        message = (result["code"] + ": " + result["message"]).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title=Portfolio validation health::{message}")
    return 0 if result["ok"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "schedule"))
    parser.add_argument("--status-file", type=Path, default=Path("data/portfolio_forward_validation/status.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    try:
        if args.command == "status":
            result = check_status(json.loads(args.status_file.read_text()), now)
        else:
            result = scheduled_health(os.environ["GITHUB_REPOSITORY"], now)
    except Exception as exc:
        # No request headers, tokens or raw HTTP responses in public artifacts.
        result = report(False, "MONITOR_ERROR", f"Health check could not complete: {type(exc).__name__}", now)
    return emit(result, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
