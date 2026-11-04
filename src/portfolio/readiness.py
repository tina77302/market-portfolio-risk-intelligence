"""HTTP boundary integrity gate; never repairs or imputes the team's frozen snapshot."""
import hashlib
import json
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/portfolio-snapshot.sha256.json"


def require_snapshot():
    try:
        expected = json.loads(MANIFEST.read_text())
        if not expected or any(
            hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest
            for name, digest in expected.items()
        ):
            raise ValueError("snapshot integrity mismatch")
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail={"code": "portfolio_snapshot_unavailable"}) from None
