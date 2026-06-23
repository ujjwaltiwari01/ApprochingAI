"""Follow-up scheduling and eligibility for multi-touch outreach sequences.

Role in pipeline: runs after initial sends and webhook events — decides which
leads are due for follow-up 1/2/3 and what engagement context to pass into
email generation (opened vs never opened).

Why this design (interview angle): cadence rules belong in code, not prompts or
cron magic numbers scattered in YAML. Centralizing delays here makes the
sequence auditable ("why did this lead get FU2 on day X?") and lets us bias
toward high ``match_score`` leads when daily follow-up quota is tight.

Key decisions:
- Shorter delay for never-opened FU1 — re-engage before giving up on cold leads.
- Longer gaps for FU2/FU3 — avoid harassment; engagement-aware FU1 for openers.
- In-Python filtering after a wide DB fetch — simpler than encoding schedule logic in SQL.
- ``should_stop`` guard — reply or DNC immediately halts the sequence.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from src.db.models import Lead, LeadStatus, async_session


class FollowupEngine:
    """Encodes follow-up timing, eligibility queries, and engagement classification."""

    MAX_FOLLOWUPS = 3

    FOLLOWUP_SCHEDULE = {
        1: timedelta(days=4),
        2: timedelta(days=8),
        3: timedelta(days=15),
    }

    NEVER_OPENED_DELAY = timedelta(days=5)

    async def get_eligible_followups(self, limit: int = 450) -> list[Lead]:
        now = datetime.now(timezone.utc)
        eligible = []

        async with async_session() as session:
            # Over-fetch then filter in Python — schedule rules are easier to change than complex SQL.
            result = await session.execute(
                select(Lead).where(
                    Lead.status.in_([
                        LeadStatus.EMAIL_SENT,
                        LeadStatus.OPENED,
                        LeadStatus.CLICKED,
                    ]),
                    Lead.replied_at.is_(None),
                    Lead.do_not_contact.is_(False),
                ).order_by(Lead.match_score.desc()).limit(max(limit * 25, 100))
            )
            leads = result.scalars().all()

            for lead in leads:
                followup_num = self._next_followup_number(lead)
                if followup_num is None or followup_num > self.MAX_FOLLOWUPS:
                    continue

                if not self._is_due(lead, followup_num, now):
                    continue

                eligible.append(lead)
                if len(eligible) >= limit:
                    break

        return eligible

    def _next_followup_number(self, lead: Lead) -> int | None:
        if not lead.followup_1_sent:
            return 1
        if not lead.followup_2_sent:
            return 2
        if not lead.followup_3_sent:
            return 3
        return None

    def _is_due(self, lead: Lead, followup_num: int, now: datetime) -> bool:
        base_time = self._base_time_for_followup(lead, followup_num)
        if not base_time:
            return False

        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)

        if followup_num == 1:
            # Opened/clicked leads get the standard cadence; never-opened get a faster nudge.
            if lead.opened_at or lead.clicked_at:
                delay = self.FOLLOWUP_SCHEDULE[1]
            else:
                delay = self.NEVER_OPENED_DELAY
        else:
            delay = self.FOLLOWUP_SCHEDULE[followup_num]

        return now >= base_time + delay

    def _base_time_for_followup(self, lead: Lead, followup_num: int) -> datetime | None:
        # FU1 anchor is initial send; later follow-ups chain off prior send timestamps.
        if followup_num == 1:
            return lead.sent_at
        if followup_num == 2:
            return lead.followup_1_sent or lead.sent_at
        if followup_num == 3:
            return lead.followup_2_sent or lead.followup_1_sent or lead.sent_at
        return None

    def get_engagement_type(self, lead: Lead) -> str:
        # Engagement label drives follow-up prompt tone — clicked > opened > silent.
        if lead.clicked_at:
            return "clicked"
        if lead.opened_at:
            return "opened_no_reply"
        return "never_opened"

    async def mark_followup_sent(self, lead_id, followup_num: int) -> None:
        now = datetime.now(timezone.utc)
        async with async_session() as session:
            result = await session.execute(select(Lead).where(Lead.id == lead_id))
            lead = result.scalar_one_or_none()
            if lead:
                if followup_num == 1:
                    lead.followup_1_sent = now
                elif followup_num == 2:
                    lead.followup_2_sent = now
                elif followup_num == 3:
                    lead.followup_3_sent = now
                await session.commit()

    async def should_stop(self, lead_id) -> bool:
        async with async_session() as session:
            result = await session.execute(select(Lead).where(Lead.id == lead_id))
            lead = result.scalar_one_or_none()
            if not lead:
                return True
            return (
                lead.replied_at is not None
                or lead.status == LeadStatus.REPLIED
                or lead.do_not_contact
            )
