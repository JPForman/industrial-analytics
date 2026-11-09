import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text

from app.core.config import get_settings
from app.deps import DbSession
from app.live import broadcaster
from app.mqtt_bridge import run_bridge
from app.routers import assets, auth, batches, live, readings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Start the MQTT bridge with the app and cancel it on shutdown."""
    settings = get_settings()
    task = None
    if settings.live_bridge_enabled:
        task = asyncio.create_task(run_bridge(broadcaster, settings.mqtt_host, settings.mqtt_port))
    yield
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Industrial Analytics API", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(assets.router)
app.include_router(batches.router)
app.include_router(readings.router)
app.include_router(live.router)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies."""
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready(db: DbSession) -> dict[str, str]:
    """Readiness: dependencies (the DB) are reachable. Orchestrators gate traffic on this."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    return {"status": "ready"}
