from fastapi import APIRouter
from sqlalchemy import text

from src.db.models import async_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    db_ok = False
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False

    status = "healthy" if db_ok else "degraded"
    return {"status": status, "service": "job-outreach-api", "database": db_ok}
