"""
Daily job orchestrator — coordinates one CHUNK of outreach per API call.

INTERVIEW ROLE:
  - Brain of the scheduler loop: follow-ups first, then new leads, then save checkpoint.
  - Makes the pipeline resumable across GitHub Actions iterations and server restarts.

WHY checkpoint JSON in `jobs` table (not Redis):
  - Free-tier stack: Postgres already exists, durable, no extra infra.
  - Stores followups_sent_count, new_sent_count, *_done flags between chunks.

WHY follow-ups before new leads:
  - Warm contacts convert better; don't waste quota on cold mail while follow-ups age out.
"""
import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import case, or_, select

from src.core.config import get_settings
from src.db.models import Job, JobStatus, JobType, Lead, LeadStatus, async_session
from src.services.batch_processor import BatchProcessor
from src.services.followup_engine import FollowupEngine
from src.utils.lead_row_normalizer import LEAD_SOURCE_USA_OWNERS


def _new_lead_send_order():
    """USA owners always before agency_list; then score and hiring probability."""
    return (
        case((Lead.lead_source == LEAD_SOURCE_USA_OWNERS, 0), else_=1),
        Lead.match_score.desc(),
        Lead.hiring_probability.desc().nulls_last(),
    )


class JobRunner:
    """One chunk = up to JOB_CHUNK_SIZE leads, split between follow-ups and new outreach."""

    def __init__(self):
        self.settings = get_settings()
        self.processor = BatchProcessor()
        self.followup_engine = FollowupEngine()

    async def run_daily_outreach_chunk(self, job_id: uuid.UUID | None = None) -> dict:
        """Process one chunk of follow-ups then new leads. Safe for Render free tier."""
        job = await self._resolve_job(job_id)
        if job.status == JobStatus.COMPLETED:
            return self._chunk_response(job, completed=True, message="Already completed today")

        checkpoint = dict(job.checkpoint or {})
        # Legacy field from older deploys — causes stuck pagination if left in JSON
        legacy_offset = int(checkpoint.pop("new_offset", 0) or 0)
        processed_lead_ids: set[str] = set(checkpoint.get("processed_lead_ids") or [])
        if legacy_offset and not processed_lead_ids:
            # In-flight job from pre-fix deploy: seed skip list so chunk 2+ moves forward
            async with async_session() as session:
                result = await session.execute(
                    select(Lead.id)
                    .where(
                        Lead.status == LeadStatus.NEW,
                        Lead.do_not_contact.is_(False),
                    )
                    .order_by(*_new_lead_send_order())
                    .limit(legacy_offset)
                )
                for lead_id in result.scalars().all():
                    processed_lead_ids.add(str(lead_id))
            checkpoint["processed_lead_ids"] = sorted(processed_lead_ids)
            logger.info(
                f"Migrated legacy new_offset={legacy_offset} → {len(processed_lead_ids)} processed_lead_ids"
            )
        followup_stats = dict(checkpoint.get("followup_stats", {}))
        new_stats = dict(checkpoint.get("new_stats", {}))
        chunk = self.settings.job_chunk_size  # Default 15 — tuned for Render timeout + LLM latency
        chunk_budget = chunk  # Shared budget: follow-ups consume first, remainder goes to new

        try:
            await self._update_job(job.id, JobStatus.RUNNING, started_at=job.started_at or datetime.now(timezone.utc))

            daily_fu_cap = self.settings.daily_followup_per_account * 3  # 150 × 3 Brevo accounts
            fu_sent_today = int(checkpoint.get("followups_sent_count", 0))

            if not checkpoint.get("followups_done") and chunk_budget > 0 and fu_sent_today < daily_fu_cap:
                remaining = min(chunk_budget, daily_fu_cap - fu_sent_today)
                followup_leads = await self.followup_engine.get_eligible_followups(remaining)
                if followup_leads:
                    batch_stats = await self.processor.process_followups(followup_leads)
                    for key, val in batch_stats.items():
                        followup_stats[key] = followup_stats.get(key, 0) + val
                    sent_now = batch_stats.get("sent", 0)
                    fu_sent_today += sent_now
                    checkpoint["followups_sent_count"] = fu_sent_today
                    if sent_now > 0:
                        chunk_budget -= len(followup_leads)
                    else:
                        # A full batch of eligible follow-ups sent nothing (e.g. all
                        # failed validation). Stop retrying them for the rest of today
                        # so they can't monopolize every chunk and starve new leads.
                        checkpoint["followups_done"] = True
                else:
                    # No eligible follow-ups left — let new leads use the budget.
                    checkpoint["followups_done"] = True

                if fu_sent_today >= daily_fu_cap:
                    checkpoint["followups_done"] = True

            daily_new_cap = self.settings.daily_new_per_account * 3
            new_sent_today = int(checkpoint.get("new_sent_count", 0))

            if not checkpoint.get("new_done") and chunk_budget > 0 and new_sent_today < daily_new_cap:
                remaining = min(chunk_budget, daily_new_cap - new_sent_today)

                async with async_session() as session:
                    query = (
                        select(Lead)
                        .where(
                            Lead.status == LeadStatus.NEW,
                            Lead.do_not_contact.is_(False),
                            Lead.sent_at.is_(None),
                            Lead.message_id.is_(None),
                        )
                        .order_by(*_new_lead_send_order())
                        .limit(remaining)
                    )
                    if processed_lead_ids:
                        query = query.where(Lead.id.not_in([uuid.UUID(x) for x in processed_lead_ids]))
                    result = await session.execute(query)
                    new_leads = list(result.scalars().all())

                if new_leads:
                    batch_stats = await self.processor.process_new_leads(new_leads)
                    for key, val in batch_stats.items():
                        new_stats[key] = new_stats.get(key, 0) + val
                    new_sent_today += batch_stats.get("sent", 0)
                    checkpoint["new_sent_count"] = new_sent_today
                    # Never retry same lead in this daily job — even if send/DB partially failed
                    for lead in new_leads:
                        processed_lead_ids.add(str(lead.id))
                    checkpoint["processed_lead_ids"] = sorted(processed_lead_ids)
                else:
                    checkpoint["new_done"] = True

                if new_sent_today >= daily_new_cap:
                    checkpoint["new_done"] = True

            checkpoint["followup_stats"] = followup_stats
            checkpoint["new_stats"] = new_stats
            completed = bool(checkpoint.get("followups_done") and checkpoint.get("new_done"))

            status = JobStatus.COMPLETED if completed else JobStatus.RUNNING
            await self._update_job(
                job.id,
                status,
                completed_at=datetime.now(timezone.utc) if completed else job.completed_at,
                checkpoint=checkpoint,
            )

            logger.info(f"Job {job.id} chunk done — completed={completed} fu={fu_sent_today}/{daily_fu_cap} new={new_sent_today}/{daily_new_cap}")
            return self._chunk_response(job, completed=completed, checkpoint=checkpoint)

        except Exception as exc:
            logger.error(f"Daily outreach chunk failed for job {job.id}: {exc}")
            await self._log_error(job.id, str(exc))
            await self._update_job(job.id, JobStatus.FAILED, checkpoint=checkpoint)
            raise

    async def run_daily_outreach(self, job_id: uuid.UUID | None = None) -> uuid.UUID:
        """Legacy full run — loops chunks until complete."""
        job = await self._resolve_job(job_id)
        while True:
            result = await self.run_daily_outreach_chunk(job.id)
            if result["completed"]:
                return job.id

    async def resume_job(self, job_id: uuid.UUID) -> dict:
        return await self.run_daily_outreach_chunk(job_id)

    async def _resolve_job(self, job_id: uuid.UUID | None) -> Job:
        if job_id:
            job = await self._get_job(job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            return job
        return await self._get_or_create_todays_job()

    async def _get_or_create_todays_job(self) -> Job:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with async_session() as session:
            result = await session.execute(
                select(Job)
                .where(
                    Job.job_type == JobType.DAILY_OUTREACH,
                    or_(
                        Job.started_at >= today_start,
                        Job.completed_at >= today_start,
                    ),
                )
                .order_by(Job.started_at.desc().nulls_last(), Job.completed_at.desc().nulls_last())
                .limit(1)
            )
            job = result.scalar_one_or_none()
            if job and job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
                cp = job.checkpoint or {}
                stats = cp.get("new_stats") or {}
                errors = int(stats.get("errors", 0))
                sent = int(cp.get("new_sent_count", 0))
                processed = len(cp.get("processed_lead_ids") or [])
                # Stuck job: many failures, no sends since early chunks — start a fresh job today
                if errors >= 30 and processed >= 15 and sent < self.settings.daily_new_per_account * 3:
                    logger.warning(
                        f"Abandoning stuck job {job.id} (sent={sent}, errors={errors}, processed={processed})"
                    )
                    job.status = JobStatus.FAILED
                    job.completed_at = datetime.now(timezone.utc)
                    await session.commit()
                    job = None
            if job:
                return job

            job = Job(job_type=JobType.DAILY_OUTREACH, status=JobStatus.PENDING, checkpoint={})
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    def _chunk_response(self, job: Job, *, completed: bool, checkpoint: dict | None = None, message: str = "") -> dict:
        cp = checkpoint or job.checkpoint or {}
        return {
            "status": "completed" if completed else "running",
            "completed": completed,
            "job_id": str(job.id),
            "message": message,
            "followups_sent_today": cp.get("followups_sent_count", 0),
            "new_sent_today": cp.get("new_sent_count", 0),
            "followups_done": cp.get("followups_done", False),
            "new_done": cp.get("new_done", False),
            "checkpoint": cp,
        }

    async def _get_job(self, job_id: uuid.UUID) -> Job | None:
        async with async_session() as session:
            result = await session.execute(select(Job).where(Job.id == job_id))
            return result.scalar_one_or_none()

    async def _update_job(self, job_id: uuid.UUID, status: JobStatus, **kwargs) -> None:
        async with async_session() as session:
            result = await session.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job:
                job.status = status
                for key, value in kwargs.items():
                    setattr(job, key, value)
                await session.commit()

    async def _log_error(self, job_id: uuid.UUID, error: str) -> None:
        async with async_session() as session:
            result = await session.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job:
                errors = job.error_log or []
                errors.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": error,
                })
                job.error_log = errors
                await session.commit()
