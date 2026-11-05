from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import urllib.error

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatch = load("portfolio_aws_dispatch", "infra/aws/portfolio_dispatch.py")
builder = load("portfolio_aws_template", "infra/aws/build_portfolio_scheduler.py")
NOW = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)
EVENT = {"kind": "collect", "scheduled_for": "2026-11-05T00:59:00Z"}


class ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class Table:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, **kwargs):
        key = Item["dispatch_key"]
        if key in self.items:
            raise ConditionalFailure()
        self.items[key] = Item.copy()

    def get_item(self, Key, **kwargs):
        return {"Item": self.items.get(Key["dispatch_key"], {})}

    def update_item(self, Key, **kwargs):
        self.items[Key["dispatch_key"]]["status"] = kwargs["ExpressionAttributeValues"][":status"]

    def delete_item(self, Key):
        self.items.pop(Key["dispatch_key"], None)


class API:
    def __init__(self, failure=None, runs=None, state="active"):
        self.posts = []
        self.failure = failure
        self.runs = runs or []
        self.state = state

    def __call__(self, token, method, path, body=None):
        if method == "POST":
            self.posts.append((path, body))
            if self.failure:
                raise self.failure
            return None
        if "/runs?" in path:
            return {"workflow_runs": self.runs}
        return {"state": self.state}


def test_retries_send_only_one_dispatch_and_keep_source_receipt():
    table, api = Table(), API()
    first = dispatch.deliver(EVENT, NOW, "example/repo", "private-test-token", table, api)
    second = dispatch.deliver(EVENT, NOW, "example/repo", "private-test-token", table, api)
    assert first["status"] == "DISPATCHED"
    assert second["status"] == "DUPLICATE_SUPPRESSED"
    assert len(api.posts) == 1
    assert api.posts[0][1] == {"ref": "main", "inputs": {"scheduler_source": "aws-eventbridge", "scheduled_for": EVENT["scheduled_for"]}}


def test_existing_run_is_found_even_after_ambiguous_response():
    table = Table()
    spec = dispatch.dispatch_spec(EVENT, NOW)
    table.put_item(Item={"dispatch_key": spec["key"], "status": "CLAIMED"})
    api = API(runs=[{"id": 55, "head_branch": "main", "display_title": spec["title"]}])
    assert dispatch.deliver(EVENT, NOW, "example/repo", "private-test-token", table, api)["run_id"] == 55
    assert not api.posts


def test_unconfirmed_dispatch_is_not_blindly_repeated():
    table, api = Table(), API(failure=dispatch.DispatchUncertain("Response lost"))
    with pytest.raises(dispatch.DispatchUncertain):
        dispatch.deliver(EVENT, NOW, "example/repo", "private-test-token", table, api)
    api.failure = None
    with pytest.raises(dispatch.DispatchUncertain):
        dispatch.deliver(EVENT, NOW, "example/repo", "private-test-token", table, api)
    assert len(api.posts) == 1


def test_explicit_rejection_releases_claim_for_authorized_retry():
    table, api = Table(), API(failure=dispatch.GitHubRejected(429))
    with pytest.raises(dispatch.GitHubRejected):
        dispatch.deliver(EVENT, NOW, "example/repo", "private-test-token", table, api)
    assert not table.items
    api.failure = None
    assert dispatch.deliver(EVENT, NOW, "example/repo", "private-test-token", table, api)["status"] == "DISPATCHED"


def test_disabled_workflow_is_respected():
    table, api = Table(), API(state="disabled_manually")
    with pytest.raises(dispatch.ConfigurationRequired):
        dispatch.deliver(EVENT, NOW, "example/repo", "private-test-token", table, api)
    assert not api.posts and not table.items


@pytest.mark.parametrize("event", [
    {"kind": "../unknown", "scheduled_for": EVENT["scheduled_for"]},
    {"kind": "collect", "scheduled_for": "2026-11-05T03:00:00Z"},
    {"kind": "collect", "scheduled_for": "2026-11-04T00:00:00Z"},
    {"kind": "collect", "scheduled_for": "2026-11-05T00:59:00"},
])
def test_untrusted_or_expired_inputs_do_not_dispatch(event):
    api = API()
    with pytest.raises(ValueError):
        dispatch.deliver(event, NOW, "example/repo", "private-test-token", Table(), api)
    assert not api.posts


def test_verification_is_not_labelled_as_routine_collection():
    spec = dispatch.dispatch_spec({**EVENT, "kind": "verify"}, NOW)
    assert spec["source"] == "aws-verification"
    assert "aws-eventbridge" not in spec["title"]
    assert spec["key"] != dispatch.dispatch_spec(EVENT, NOW)["key"]


@pytest.mark.parametrize("value", ['{"token":""}', '{}', 'not json', '{"token":"x\\ny"}'])
def test_unconfigured_secret_does_not_become_a_fake_connection(value):
    with pytest.raises(dispatch.ConfigurationRequired):
        dispatch.token_from_secret(value)


def test_http_error_bodies_and_tokens_are_not_exposed(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "forbidden", {}, io.BytesIO(b"private-test-token"))
    monkeypatch.setattr(dispatch.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(dispatch.GitHubRejected) as exc:
        dispatch.github("private-test-token", "GET", "/repos/example/repo")
    assert "private-test-token" not in str(exc.value)


def test_authentication_is_not_forwarded_on_redirect():
    with pytest.raises(dispatch.GitHubRejected):
        dispatch.NoRedirect().redirect_request(None, None, 302, "Moved", {}, "https://other.example")


def test_infrastructure_starts_disabled_without_real_credentials_or_public_endpoints():
    plan = builder.template()
    assert plan["Parameters"]["EnableSchedules"]["Default"] == "false"
    assert json.loads(plan["Resources"]["GitHubSecret"]["Properties"]["SecretString"])["token"] == ""
    types = {r["Type"] for r in plan["Resources"].values()}
    assert "AWS::Lambda::Url" not in types and "AWS::EC2::Instance" not in types
    for name in ("LambdaRole", "SchedulerRole"):
        statements = plan["Resources"][name]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        assert all(s["Resource"] != "*" and "*" not in s["Action"] for s in statements)
