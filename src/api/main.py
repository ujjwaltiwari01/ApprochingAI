"""
API entry point (FastAPI) — HTTP gateway for the outreach system.

INTERVIEW ROLE:
  - Exposes job triggers that GitHub Actions calls every 5 minutes.
  - Mounts Brevo webhooks for open/click/reply tracking.
  - Protects destructive endpoints with JOB_SECRET (shared with GitHub + dashboard).

WHY FastAPI + async:
  - Workload is I/O-bound (DB, LLM HTTP, Brevo). Async avoids blocking the event loop
    while waiting on external APIs inside each 15-lead chunk.

KEY DESIGN:
  - `_job_lock`: only one chunk runs at a time → prevents duplicate sends if cron overlaps.
  - Each POST /jobs/daily-outreach processes ONE chunk (~15 leads) and returns quickly
    so Render free tier does not hit the ~30s request timeout.
"""
import asyncio
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from loguru import logger
from sqlalchemy import select

from src.api.routes.health import router as health_router
from src.api.routes.webhooks import router as webhooks_router
from src.core.config import get_settings
from src.core.logging import setup_logging
from src.db.models import Job, async_session
from src.services.job_runner import JobRunner

setup_logging()
settings = get_settings()
runner = JobRunner()  # Singleton orchestrator — reused across all HTTP requests
_job_lock = asyncio.Lock()  # Interview: mutex for single-flight chunk processing


def create_app() -> FastAPI:
    app = FastAPI(title="Job Outreach API", version="1.1.0")
    app.include_router(health_router)
    app.include_router(webhooks_router)
    _register_routes(app)
    return app


def verify_job_secret(authorization: str = Header(default="")) -> None:
    if not settings.job_secret or settings.job_secret == "change-me-to-random-secret":
        raise HTTPException(status_code=503, detail="JOB_SECRET not configured")
    expected = f"Bearer {settings.job_secret}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _register_routes(app: FastAPI) -> None:
    @app.get("/")
    async def root():
        return {
            "service": "Job Outreach API",
            "health": "/health",
            "docs": "/docs",
            "dashboard_note": "Use the outreach-dashboard service URL for the Streamlit UI.",
        }

    @app.post("/jobs/daily-outreach")
    async def trigger_daily_outreach(_: None = Depends(verify_job_secret)):
        """Process one outreach chunk synchronously (Render free-tier safe)."""
        # 409 if overlap — GitHub Actions concurrency queues runs; API still guards locally
        if _job_lock.locked():
            raise HTTPException(status_code=409, detail="Outreach chunk already running")

        async with _job_lock:
            try:
                result = await runner.run_daily_outreach_chunk()
                return result
            except Exception as exc:
                logger.exception("Outreach chunk failed")
                raise HTTPException(status_code=500, detail=str(exc)[:200]) from exc

    @app.post("/jobs/resume/{job_id}")
    async def resume_job(job_id: uuid.UUID, _: None = Depends(verify_job_secret)):
        if _job_lock.locked():
            raise HTTPException(status_code=409, detail="Outreach chunk already running")

        async with _job_lock:
            try:
                return await runner.resume_job(job_id)
            except Exception as exc:
                logger.exception(f"Resume job {job_id} failed")
                raise HTTPException(status_code=500, detail=str(exc)[:200]) from exc

    @app.get("/jobs/{job_id}/status")
    async def job_status(job_id: uuid.UUID, _: None = Depends(verify_job_secret)):
        async with async_session() as session:
            result = await session.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            return {
                "job_id": str(job.id),
                "status": job.status.value,
                "checkpoint": job.checkpoint,
                "error_log": job.error_log,
            }


app = create_app()
