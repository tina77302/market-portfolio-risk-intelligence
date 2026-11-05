"""EventBridge -> GitHub dispatcher. No portfolio data or credentials in logs."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

WORKFLOWS = {"collect": "portfolio-forward-validation.yml", "watch": "portfolio-forward-watchdog.yml",
             "verify": "portfolio-forward-validation.yml"}


class ConfigurationRequired(RuntimeError):
    pass


class DispatchUncertain(RuntimeError):
    pass


class GitHubRejected(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"GitHub rejected request: HTTP {status}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GitHubRejected(code)


def github(token, method, path, body=None):
    request = urllib.request.Request("https://api.github.com" + path,
        data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=12) as response:
            content = response.read()
            return json.loads(content) if content else None
    except urllib.error.HTTPError as exc:
        # Do not include server bodies or headers in a public workflow or log.
        raise GitHubRejected(exc.code) from None
    except urllib.error.URLError:
        raise DispatchUncertain("GitHub response unavailable; inspect run history before retrying.") from None


def token_from_secret(secret):
    try:
        token = json.loads(secret)["token"].strip()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ConfigurationRequired("GitHub secret must contain a nonempty token field.") from None
    if not token or "\n" in token or "\r" in token:
        raise ConfigurationRequired("GitHub execution credential is not configured.")
    return token


def dispatch_spec(event, now):
    kind = event.get("kind")
    if kind not in WORKFLOWS:
        raise ValueError("Unsupported dispatch kind.")
    when = datetime.fromisoformat(event["scheduled_for"].replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("Scheduled time must have a timezone.")
    when = when.astimezone(timezone.utc)
    if when > now + timedelta(minutes=5) or now - when > timedelta(hours=2):
        raise ValueError("Scheduled event is outside its two-hour delivery window.")
    scheduled_for = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    source = "aws-verification" if kind == "verify" else "aws-eventbridge"
    name = "Portfolio forward watchdog" if kind == "watch" else "Portfolio forward validation"
    return {"workflow": WORKFLOWS[kind], "source": source, "scheduled_for": scheduled_for,
            "title": f"{name} | {source} | {scheduled_for}",
            "key": hashlib.sha256(f"{kind}:{scheduled_for}".encode()).hexdigest()}


def find_existing(token, repository, spec, api=github):
    query = urllib.parse.urlencode({"event": "workflow_dispatch", "branch": "main", "per_page": 100,
                                   "created": ">=" + spec["scheduled_for"]})
    for page in range(1, 11):
        payload = api(token, "GET", f"/repos/{repository}/actions/workflows/{spec['workflow']}/runs?{query}&page={page}")
        for run in payload["workflow_runs"]:
            if run.get("display_title") == spec["title"] and run.get("head_branch") == "main":
                return run["id"]
        if len(payload["workflow_runs"]) < 100:
            return None
    raise DispatchUncertain("GitHub run history exceeded the verification page limit.")


def deliver(event, now, repository, token, table, api=github):
    spec = dispatch_spec(event, now)
    root = f"/repos/{repository}/actions/workflows/{spec['workflow']}"
    workflow = api(token, "GET", root)
    if workflow["state"] != "active":
        raise ConfigurationRequired("Target workflow is disabled; it will not be re-enabled automatically.")
    existing = find_existing(token, repository, spec, api)
    if existing:
        return {"status": "ALREADY_DISPATCHED", "run_id": existing, "scheduled_for": spec["scheduled_for"]}
    try:
        table.put_item(Item={"dispatch_key": spec["key"], "status": "CLAIMED",
            "scheduled_for": spec["scheduled_for"], "expires_at": int(now.timestamp()) + 7*86400},
            ConditionExpression="attribute_not_exists(dispatch_key)")
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        saved = table.get_item(Key={"dispatch_key": spec["key"]}, ConsistentRead=True).get("Item", {})
        if saved.get("status") == "DISPATCHED":
            return {"status": "DUPLICATE_SUPPRESSED", "scheduled_for": spec["scheduled_for"]}
        # A previous call may have been accepted without returning a response.
        # Leave it visible in the failure queue rather than blindly dispatching twice.
        raise DispatchUncertain("An earlier dispatch has an unconfirmed outcome; inspect GitHub run history.") from None
    try:
        api(token, "POST", root + "/dispatches", {"ref": "main", "inputs": {
            "scheduler_source": spec["source"], "scheduled_for": spec["scheduled_for"]}})
    except GitHubRejected as exc:
        if 400 <= exc.status < 500:
            table.delete_item(Key={"dispatch_key": spec["key"]})
        raise
    table.update_item(Key={"dispatch_key": spec["key"]},
        UpdateExpression="SET #status = :status", ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": "DISPATCHED"})
    return {"status": "DISPATCHED", "workflow": spec["workflow"], "source": spec["source"],
            "scheduled_for": spec["scheduled_for"]}


def handler(event, context):
    import boto3
    secret = boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["GITHUB_SECRET_ARN"])
    token = token_from_secret(secret["SecretString"])
    repository = os.environ["GITHUB_REPOSITORY"]
    if event.get("kind") == "preflight":
        for workflow in set(WORKFLOWS.values()):
            data = github(token, "GET", f"/repos/{repository}/actions/workflows/{workflow}")
            if data["state"] != "active":
                raise ConfigurationRequired("A target workflow is disabled.")
        return {"status": "CREDENTIAL_READ_OK", "dispatch_write_permission_verified": False}
    table = boto3.resource("dynamodb").Table(os.environ["DISPATCH_TABLE"])
    result = deliver(event, datetime.now(timezone.utc), repository, token, table)
    print(json.dumps(result))
    return result
