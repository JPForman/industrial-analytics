from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text

from app.deps import DbSession
from app.routers import auth

app = FastAPI(title="Industrial Analytics API", version="0.1.0")
app.include_router(auth.router)


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
