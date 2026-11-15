"""ASTRA-Med FastAPI Application Entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import db_session, init_db
from app.routers import dashboard, ground, metrics, mission, routine, vision
from app.services.seed_service import ensure_seeded


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize SQLite WAL schema, seed baseline telemetry, and clear stale vision alerts."""
    init_db()
    with db_session() as conn:
        ensure_seeded(conn)
        conn.execute("DELETE FROM vision_assessments;")
    yield


app = FastAPI(
    title="ASTRA-Med API",
    description=(
        "Autonomous Space Telemetry & Risk Assessment — Core Backend, Mission Simulator, "
        "and Hybrid Vision Engine for NASA Space Apps Challenge (Team xterra)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(metrics.router)
app.include_router(mission.router)
app.include_router(routine.router)
app.include_router(ground.router)
app.include_router(vision.router)


@app.get("/", tags=["Root"])
def root() -> dict[str, str]:
    """Root discovery endpoint pointing to Swagger UI and health check."""
    return {
        "service": "ASTRA-Med Backend",
        "team": "xterra",
        "docs": "/docs",
        "health": "/api/health",
    }
