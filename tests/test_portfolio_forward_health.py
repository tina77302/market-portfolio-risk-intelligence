"""Operational failures must be visible without changing sealed study records."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_portfolio_forward_health.py"
spec = importlib.util.spec_from_file_location("forward_health", SCRIPT)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)
NOW = datetime(2026, 11, 4, 2, 17, tzinfo=timezone.utc)


def workflow(**changes):
    return {"path": health.WORKFLOW_PATH, "state": "active", "created_at": "2026-11-01T00:00:00Z", **changes}


def run(**changes):
    return {"id": 123, "event": "schedule", "head_branch": "main", "path": health.WORKFLOW_PATH,
            "created_at": "2026-11-03T23:40:00Z", "status": "completed", "conclusion": "success",
            "html_url": "https://github.com/example/repo/actions/runs/123", **changes}


@pytest.mark.parametrize("state", sorted(health.HEALTHY_STATES))
def test_normal_waiting_and_evaluated_states_do_not_alert(state):
    status = {"at": NOW.isoformat(), "status": state, "input_as_of": "2026-11-02"}
    assert health.check_status(status, NOW)["ok"]


@pytest.mark.parametrize("state", sorted(health.INPUT_STATES))
def test_input_and_rate_problems_alert_even_when_collector_exits_zero(state):
    status = {"at": NOW.isoformat(), "status": state, "fetch_error_type": "PriceCollectionError"}
    result = health.check_status(status, NOW)
    assert not result["ok"]
    assert result["code"] == "INPUT_UNAVAILABLE"


@pytest.mark.parametrize("at", [NOW - timedelta(hours=1), NOW + timedelta(minutes=6)])
def test_old_or_future_status_cannot_masquerade_as_current(at):
    result = health.check_status({"at": at.isoformat(), "status": "WAITING_FOR_OUTCOME"}, NOW)
    assert result["code"] == "STALE_STATUS"


@pytest.mark.parametrize("as_of", ["2026-10-20", "2026-11-03", "2026-11-04"])
def test_completed_price_freshness_is_checked_while_waiting_for_outcome(as_of):
    # At NOW the New York date is Nov 3, so its own bar is not completed input.
    result = health.check_status({"at": NOW.isoformat(), "status": "WAITING_FOR_OUTCOME",
                                  "input_as_of": as_of}, NOW)
    assert result["code"] == "STALE_INPUT"


def test_manual_or_push_success_does_not_hide_missing_schedule():
    runs = [run(event="push"), run(event="workflow_dispatch"), run(head_branch="feature"),
            run(path=".github/workflows/other.yml"), run(created_at="2026-11-02T23:40:00Z")]
    result = health.check_schedule(workflow(), runs, "main", NOW)
    assert result["code"] == "MISSING_SCHEDULE"


def test_schedule_succeeds_and_latest_attempt_failure_is_reported():
    assert health.check_schedule(workflow(), [run()], "main", NOW)["ok"]
    failed = run(id=124, created_at="2026-11-03T23:45:00Z", conclusion="failure")
    result = health.check_schedule(workflow(), [run(), failed], "main", NOW)
    assert result["code"] == "SCHEDULE_FAILED"
    assert result["run_id"] == 124


@pytest.mark.parametrize("changes,code", [
    ({"status": "queued", "conclusion": None}, "SCHEDULE_NOT_COMPLETED"),
    ({"status": "in_progress", "conclusion": None}, "SCHEDULE_NOT_COMPLETED"),
    ({"conclusion": "cancelled"}, "SCHEDULE_FAILED"),
    ({"conclusion": "skipped"}, "SCHEDULE_FAILED"),
])
def test_stuck_cancelled_and_skipped_runs_alert(changes, code):
    assert health.check_schedule(workflow(), [run(**changes)], "main", NOW)["code"] == code


def test_grace_period_and_first_deployment_do_not_raise_false_alarm():
    soon = datetime(2026, 11, 4, 0, 30, tzinfo=timezone.utc)
    assert health.check_schedule(workflow(), [], "main", soon)["code"] == "SCHEDULE_GRACE_PERIOD"
    assert health.check_schedule(workflow(created_at="2026-11-04T00:00:00Z"), [], "main", NOW)["code"] == "WAITING_FOR_FIRST_SCHEDULE"
    boundary = health.latest_due(NOW) + health.GRACE
    assert health.check_schedule(workflow(), [], "main", boundary)["code"] == "MISSING_SCHEDULE"


@pytest.mark.parametrize("state", ["disabled_manually", "disabled_inactivity"])
def test_disabled_workflow_alerts(state):
    assert health.check_schedule(workflow(state=state), [run()], "main", NOW)["code"] == "WORKFLOW_INACTIVE"


@pytest.mark.parametrize("day", [7, 8, 9])
def test_weekend_and_monday_morning_expect_friday_not_nonexistent_weekend_runs(day):
    now = datetime(2026, 11, day, 2, 17, tzinfo=timezone.utc)
    assert health.latest_due(now).isoformat() == "2026-11-06T23:37:00+00:00"


def test_timezone_offsets_are_converted_to_utc():
    local = datetime.fromisoformat("2026-11-04T11:17:00+09:00")
    assert health.latest_due(local) == health.latest_due(NOW)


def test_api_pagination_and_non_main_default_branch():
    requests = []

    def get(path):
        requests.append(path)
        if path == "/repos/example/repo":
            return {"default_branch": "production"}
        if "/runs?" not in path:
            return workflow()
        if path.endswith("&page=1"):
            return {"workflow_runs": [run(head_branch="feature")] * 100}
        return {"workflow_runs": [run(head_branch="production")]}

    assert health.scheduled_health("example/repo", NOW, get, policy={"mode": "github"})["ok"]
    assert len(requests) == 4
    assert "branch=production" in requests[-1]
    assert "event=schedule" in requests[-1]


def test_status_cli_fails_closed_on_missing_or_malformed_file(tmp_path):
    status = tmp_path / "status.json"
    output = tmp_path / "health.json"
    for payload in (None, "not json", '{"at":"bad","status":"WAITING_FOR_OUTCOME"}'):
        if payload is not None:
            status.write_text(payload)
        result = subprocess.run([sys.executable, str(SCRIPT), "status", "--status-file", str(status),
                                 "--output", str(output)], capture_output=True, text=True)
        assert result.returncode == 1
        assert json.loads(output.read_text())["code"] == "MONITOR_ERROR"
        assert "::error title=Portfolio validation health::" in result.stdout


def test_error_annotation_escapes_newlines_and_percent(tmp_path, capsys, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    result = health.report(False, "TEST", "line1\nline2 50%", NOW)
    assert health.emit(result) == 1
    assert "line1%0Aline2 50%25" in capsys.readouterr().out
    assert "Portfolio validation health: TEST" in summary.read_text()


def test_watchdog_and_collection_schedule_contract_stays_in_sync():
    collection = (ROOT / health.WORKFLOW_PATH).read_text()
    policy = json.loads(health.POLICY_PATH.read_text())
    if policy["mode"] == "github":
        assert f"cron: '{health.COLLECTION_CRON}'" in collection
    else:
        assert "  schedule:" not in collection
    assert "id: collect" in collection
    assert "steps.collect.outcome == 'success'" in collection
    assert collection.index("check_portfolio_forward_health.py status") < collection.index("uses: actions/upload-artifact")


def test_external_schedule_requires_exact_provider_slot_and_success():
    policy = {"mode": "aws-eventbridge", "activated_at": "2026-11-01T00:00:00Z"}
    expected_title = "Portfolio forward validation | aws-eventbridge | 2026-11-03T23:37:00Z"
    correct = run(event="workflow_dispatch", display_title=expected_title)
    assert health.check_schedule(workflow(), [correct], "main", NOW, policy)["ok"]
    impostors = [run(), run(event="workflow_dispatch"),
                 run(event="workflow_dispatch", display_title=expected_title.replace("eventbridge", "verification")),
                 run(event="workflow_dispatch", display_title=expected_title.replace("11-03", "11-02"))]
    assert health.check_schedule(workflow(), impostors, "main", NOW, policy)["code"] == "MISSING_SCHEDULE"
    assert health.check_schedule(workflow(), [{**correct, "conclusion": "failure"}], "main", NOW, policy)["code"] == "SCHEDULE_FAILED"


def test_external_activation_does_not_require_predeployment_runs():
    policy = {"mode": "aws-eventbridge", "activated_at": "2026-11-04T01:00:00Z"}
    assert health.check_schedule(workflow(), [], "main", NOW, policy)["code"] == "WAITING_FOR_FIRST_SCHEDULE"
    with pytest.raises(ValueError):
        health.check_schedule(workflow(), [], "main", NOW, {"mode": "aws-eventbridge", "activated_at": None})
