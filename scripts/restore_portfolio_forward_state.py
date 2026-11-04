"""Restore the latest trusted workflow artifact; never silently reset lost state.

Only stdlib imports: runs before installing the restored dependency lock.
"""
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import urllib.parse
import urllib.request
import zipfile

WORKFLOW = "portfolio-forward-validation.yml"
ARTIFACT = "portfolio-forward-state"
ALLOWED_EVENTS = ("schedule", "workflow_dispatch", "push")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urllib.parse.urlparse(req.full_url).netloc != urllib.parse.urlparse(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


def extract_state(data, target):
    target = Path(target)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            if name.is_absolute() or ".." in name.parts or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("unsafe state artifact member")
        archive.extractall(target)
    if not (target / "policy.json").is_file():
        raise ValueError("restored artifact has no sealed policy")


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository identity")
    token = os.environ["GH_TOKEN"]
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    current = int(os.environ["GITHUB_RUN_ID"])
    target = Path("data/portfolio_forward_validation")

    def request(path, binary=False):
        req = urllib.request.Request(api + path, headers={"Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.build_opener(SafeRedirect()).open(req, timeout=30) as response:
            payload = response.read()
        return payload if binary else json.loads(payload)

    branch = request(f"/repos/{repository}")["default_branch"]
    listing = request(f"/repos/{repository}/actions/artifacts?name={ARTIFACT}&per_page=100")
    restored = False
    for artifact in sorted(listing["artifacts"], key=lambda a: a["created_at"], reverse=True):
        run_id = artifact["workflow_run"]["id"]
        if run_id == current:
            continue
        run = request(f"/repos/{repository}/actions/runs/{run_id}")
        if run["path"] != f".github/workflows/{WORKFLOW}" or run["event"] not in ALLOWED_EVENTS or run["head_branch"] != branch:
            continue
        if artifact["expired"]:
            raise RuntimeError("latest forward state expired; restore an archive, do not bootstrap")
        extract_state(request(f"/repos/{repository}/actions/artifacts/{artifact['id']}/zip", binary=True), target)
        restored = True
        break
    if not restored:
        runs = request(f"/repos/{repository}/actions/workflows/{WORKFLOW}/runs?per_page=100")
        prior = [r for r in runs["workflow_runs"] if r["id"] != current and r["head_branch"] == branch
                 and r["event"] in ALLOWED_EVENTS]
        if prior:
            raise RuntimeError("previous run exists but no restorable state; refusing silent reset")
    version = json.loads((target / "policy.json").read_text())["payload"]["runtime"]["python"] if restored else "3.12"
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version):
        raise ValueError("invalid restored Python version")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"python-version={version}\n")
    print("Restored sealed forward state." if restored else "First run: initialize a new forward study.")


if __name__ == "__main__":
    main()
