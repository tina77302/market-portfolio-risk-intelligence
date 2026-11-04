import json

import pytest
from fastapi.testclient import TestClient

from src.portfolio import readiness
from src.portfolio.server import app


@pytest.mark.parametrize("fault", ["missing", "revision", "missing_manifest"])
def test_snapshot_failure_blocks_health_and_analysis(tmp_path, monkeypatch, fault):
    # Work on isolated files; never corrupt the research/demo snapshot itself.
    manifest = json.loads(readiness.MANIFEST.read_text())
    manifest = {name: digest for name, digest in manifest.items()}
    for name in manifest:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((readiness.ROOT / name).read_bytes())
    local_manifest = tmp_path / "manifest.json"
    local_manifest.write_text(json.dumps(manifest))
    target = tmp_path / "data/portfolio/prices.csv"
    if fault == "missing":
        target.unlink()
    elif fault == "revision":
        target.write_bytes(target.read_bytes().replace(b"2018", b"2017", 1))
    else:
        local_manifest.unlink()
    monkeypatch.setattr(readiness, "ROOT", tmp_path)
    monkeypatch.setattr(readiness, "MANIFEST", local_manifest)
    with TestClient(app) as client:
        for method, path, kwargs in [
            ("get", "/health", {}),
            ("post", "/api/portfolio/analyze", {"json": {"holdings": [{"ticker": "SPY", "weight": 100}], "value_usd": 100000}}),
            ("get", "/api/portfolio/scenarios", {}),
        ]:
            response = getattr(client, method)(path, **kwargs)
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "portfolio_snapshot_unavailable"


def test_current_snapshot_is_ready():
    assert TestClient(app).get("/health").status_code == 200
