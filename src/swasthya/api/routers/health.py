"""`GET /healthz` -- no auth, per docs/api_contract.md."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
