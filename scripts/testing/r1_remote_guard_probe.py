"""Minimal real FastAPI app used by the R1 remote-write guard harness."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import mutating_api_guard


def create_app() -> FastAPI:
    probe_app = FastAPI()
    probe_app.middleware("http")(mutating_api_guard)
    probe_app.state.mutation_count = 0

    @probe_app.get("/api/r1-remote-guard/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @probe_app.get("/api/r1-remote-guard/count")
    async def count() -> dict[str, int]:
        return {"count": int(probe_app.state.mutation_count)}

    @probe_app.post("/api/r1-remote-guard/probe")
    async def mutate() -> dict[str, int | bool]:
        probe_app.state.mutation_count += 1
        return {"ok": True, "count": int(probe_app.state.mutation_count)}

    return probe_app
