"""Liveness probe, matching the dashboard service's own contract."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Report that the process is serving."""
    return {"status": "ok"}
