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
runner = JobRunner()
_job_lock = asyncio.Lock()


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
    @app.post("/jobs/daily-outreach")
    async def trigger_daily_outreach(_: None = Depends(verify_job_secret)):
        """Process one outreach chunk synchronously (Render free-tier safe)."""
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
