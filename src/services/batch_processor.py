"""
Per-lead pipeline: analyze → generate → validate → send → persist.

INTERVIEW ROLE:
  - Called by JobRunner for each lead in a chunk.
  - Encodes the core business loop recruiters would do manually.

PIPELINE ORDER (why this sequence):
  1. WebsiteAnalyzer — gather context before LLM (garbage in = generic email out).
  2. EmailGenerator — LLM + validation gate (quality control before reputation risk).
  3. BrevoClient — send only if validation passed (unless ALLOW_INVALID_SEND=true).
  4. DB update — audit trail in generated_content + lead status funnel.

CRITICAL BUG FIX PATTERN:
  - Brevo send success does NOT roll back if DB update fails (email already delivered).
"""
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from src.core.config import get_settings
from src.db.models import GeneratedContent, Lead, LeadStatus, async_session
from src.services.brevo_client import BrevoClient
from src.services.email_generator import EmailGenerator
from src.services.followup_engine import FollowupEngine
from src.services.website_analyzer import WebsiteAnalyzer
from src.utils.lead_row_normalizer import recipient_first_name_from_lead


class BatchProcessor:
    """Stateless service object — safe to instantiate once per JobRunner."""

    def __init__(self):
        self.settings = get_settings()
        self.analyzer = WebsiteAnalyzer()
        self.generator = EmailGenerator()
        self.brevo = BrevoClient()
        self.followup = FollowupEngine()

    async def process_new_leads(self, leads: list[Lead]) -> dict:
        stats = {"analyzed": 0, "generated": 0, "sent": 0, "skipped_validation": 0, "errors": 0}

        for lead in leads:
            try:
                # Re-load row so we never act on stale status from a prior chunk/session
                async with async_session() as session:
                    result = await session.execute(select(Lead).where(Lead.id == lead.id))
                    db_lead = result.scalar_one_or_none()
                if not db_lead:
                    stats["errors"] += 1
                    continue
                if db_lead.status != LeadStatus.NEW or db_lead.message_id or db_lead.sent_at:
                    logger.info(f"Skipping lead {db_lead.id} — already processed (status={db_lead.status})")
                    continue
                lead = db_lead

                analysis = await self.analyzer.analyze_for_lead(lead)
                await self.analyzer.update_lead_status(lead.id, analysis)
                stats["analyzed"] += 1

                subject, body, provider, valid, _ = await self.generator.generate_initial_email(
                    lead.company_name or lead.name or "your agency",
                    analysis,
                    recipient_first_name=recipient_first_name_from_lead(lead),
                )
                stats["generated"] += 1

                # Validation gate — interview: prevents LLM slop from hurting domain reputation
                if not valid and not self.settings.allow_invalid_send:
                    logger.warning(f"Skipping send for {lead.id} — validation failed")
                    stats["skipped_validation"] += 1
                    continue

                await self._save_generated(lead.id, subject, body, provider, valid, followup_number=0)
                await self._send_and_mark(
                    lead, subject, body, followup_number=0, is_followup=False, stats=stats
                )

            except Exception as exc:
                logger.error(f"Failed processing lead {lead.id}: {exc}")
                stats["errors"] += 1

        return stats

    async def process_followups(self, leads: list[Lead]) -> dict:
        stats = {"generated": 0, "sent": 0, "skipped_validation": 0, "errors": 0}

        for lead in leads:
            if await self.followup.should_stop(lead.id):
                continue

            try:
                followup_num = self.followup._next_followup_number(lead)
                if not followup_num:
                    continue

                engagement = self.followup.get_engagement_type(lead)
                analysis = await self.analyzer.get_cached_analysis(lead)
                if not analysis:
                    analysis = await self.analyzer.analyze_for_lead(lead)

                subject, body, provider, valid = await self.generator.generate_followup_email(
                    company_name=lead.company_name or lead.name or "your agency",
                    agency_analysis=analysis,
                    followup_number=followup_num,
                    previous_subject=lead.last_subject or "",
                    engagement_type=engagement,
                    recipient_first_name=recipient_first_name_from_lead(lead),
                )
                stats["generated"] += 1

                if not valid and not self.settings.allow_invalid_send:
                    logger.warning(f"Skipping followup send for {lead.id} — validation failed")
                    stats["skipped_validation"] += 1
                    continue

                await self._save_generated(lead.id, subject, body, provider, valid, followup_number=followup_num)
                await self._send_and_mark(
                    lead, subject, body, followup_number=followup_num, is_followup=True, stats=stats
                )
                await self.followup.mark_followup_sent(lead.id, followup_num)

            except Exception as exc:
                logger.error(f"Failed followup for lead {lead.id}: {exc}")
                stats["errors"] += 1

        return stats

    async def _save_generated(
        self,
        lead_id,
        subject: str,
        body: str,
        provider: str,
        valid: bool,
        followup_number: int,
    ) -> None:
        async with async_session() as session:
            content = GeneratedContent(
                lead_id=lead_id,
                subject=subject,
                email_body=body,
                llm_provider=provider,
                validation_passed=valid,
                followup_number=followup_number,
            )
            session.add(content)

            result = await session.execute(select(Lead).where(Lead.id == lead_id))
            db_lead = result.scalar_one()
            db_lead.last_subject = subject
            db_lead.last_email_body = body
            if followup_number == 0:
                db_lead.status = LeadStatus.EMAIL_GENERATED
            await session.commit()

    async def _send_and_mark(
        self,
        lead: Lead,
        subject: str,
        body: str,
        *,
        followup_number: int,
        is_followup: bool,
        stats: dict,
    ) -> None:
        html = self.brevo.text_to_html(body)
        message_id, account_id = await self.brevo.send_email(
            to_email=lead.email,
            to_name=lead.name or lead.company_name or "",
            subject=subject,
            html_body=html,
            lead_id=str(lead.id),
            followup_number=followup_number,
            is_followup=is_followup,
        )
        stats["sent"] += 1  # Count send after Brevo accepts — source of truth is Brevo API

        try:
            # Separate try: DB failure after deliver must not re-raise (no double-send on retry)
            async with async_session() as session:
                result = await session.execute(select(Lead).where(Lead.id == lead.id))
                db_lead = result.scalar_one_or_none()
                if not db_lead:
                    logger.error(f"Lead {lead.id} not found after send to {lead.email}")
                    return
                if not is_followup:
                    db_lead.status = LeadStatus.EMAIL_SENT
                    db_lead.sent_at = datetime.now(timezone.utc)
                db_lead.message_id = message_id
                db_lead.brevo_account = account_id
                await session.commit()
        except Exception as exc:
            logger.error(
                f"Email delivered to {lead.email} but DB update failed for lead {lead.id}: {exc}"
            )
