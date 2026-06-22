from fastapi import APIRouter
from sqlalchemy import text

from src.db.models import async_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    db_ok = False
    db_error = None
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception as exc:
        db_error = str(exc)[:200]

    status = "healthy" if db_ok else "degraded"
    payload = {"status": status, "service": "job-outreach-api", "database": db_ok}
    if db_error:
        payload["database_error"] = db_error
    return payload
