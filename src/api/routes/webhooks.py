import uuid

from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from loguru import logger
from sqlalchemy import select

from src.core.config import get_settings
from src.db.models import EmailEvent, Lead, LeadStatus, async_session

router = APIRouter(prefix="/webhooks/brevo", tags=["webhooks"])
settings = get_settings()

EVENT_PRIORITY = {
    "replied": 5,
    "click": 4,
    "clicked": 4,
    "open": 3,
    "opened": 3,
    "delivered": 2,
    "hard_bounce": 1,
    "soft_bounce": 1,
    "spam": 1,
    "blocked": 1,
}

STATUS_MAP = {
    "delivered": LeadStatus.EMAIL_SENT,
    "opened": LeadStatus.OPENED,
    "unique_opened": LeadStatus.OPENED,
    "click": LeadStatus.CLICKED,
    "clicked": LeadStatus.CLICKED,
    "hard_bounce": LeadStatus.BOUNCED,
    "soft_bounce": LeadStatus.BOUNCED,
    "spam": LeadStatus.SPAM,
    "blocked": LeadStatus.BOUNCED,
}


def _extract_lead_id(payload: dict) -> str | None:
    custom = payload.get("X-Mailin-custom", "") or payload.get("tags", "")
    if isinstance(custom, str) and "lead_id:" in custom:
        for part in custom.split("|"):
            if part.startswith("lead_id:"):
                return part.split(":", 1)[1]
    tags = payload.get("tags", [])
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("lead_"):
                return tag.replace("lead_", "")
    return None


async def _find_lead_by_message(message_id: str | None, email: str | None) -> Lead | None:
    async with async_session() as session:
        if message_id:
            result = await session.execute(
                select(Lead).where(Lead.message_id == message_id)
            )
            lead = result.scalar_one_or_none()
            if lead:
                return lead

        if email:
            result = await session.execute(
                select(Lead).where(Lead.email.ilike(email.strip()))
            )
            return result.scalar_one_or_none()
    return None


def _verify_webhook_secret(request: Request, x_webhook_secret: str = Header(default="")) -> None:
    if not settings.webhook_secret or settings.webhook_secret == "change-me-to-random-secret":
        return
    provided = x_webhook_secret or request.query_params.get("secret", "")
    if provided != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@router.post("/transactional")
async def handle_transactional_webhook(request: Request):
    _verify_webhook_secret(request)
    payload = await request.json()
    event_type = payload.get("event", "").lower()
    message_id = payload.get("message-id") or payload.get("messageId")
    email = payload.get("email")
    lead_id_str = _extract_lead_id(payload)
    brevo_event_id = f"{message_id}_{event_type}_{payload.get('ts', payload.get('date', ''))}"

    logger.info(f"Brevo event: {event_type} for {email}")

    async with async_session() as session:
        existing = await session.execute(
            select(EmailEvent).where(EmailEvent.brevo_event_id == brevo_event_id)
        )
        if existing.scalar_one_or_none():
            return {"status": "duplicate"}

        lead = None
        if lead_id_str:
            try:
                lead_uuid = uuid.UUID(lead_id_str)
                result = await session.execute(select(Lead).where(Lead.id == lead_uuid))
                lead = result.scalar_one_or_none()
            except ValueError:
                pass
        if not lead:
            lead = await _find_lead_by_message(message_id, email)

        event = EmailEvent(
            lead_id=lead.id if lead else None,
            message_id=message_id,
            event_type=event_type,
            event_time=datetime.now(timezone.utc),
            metadata_=payload,
            brevo_event_id=brevo_event_id,
        )
        session.add(event)

        if lead and event_type in STATUS_MAP:
            new_status = STATUS_MAP[event_type]
            current_priority = EVENT_PRIORITY.get(lead.status.value.lower(), 0)
            new_priority = EVENT_PRIORITY.get(event_type, 0)

            if new_priority >= current_priority:
                lead.status = new_status

            if event_type in ("opened", "unique_opened") and not lead.opened_at:
                lead.opened_at = datetime.now(timezone.utc)
            elif event_type in ("click", "clicked") and not lead.clicked_at:
                lead.clicked_at = datetime.now(timezone.utc)

            if lead.replied_at:
                lead.status = LeadStatus.REPLIED

        await session.commit()

    return {"status": "ok"}


@router.post("/inbound")
async def handle_inbound_webhook(request: Request):
    _verify_webhook_secret(request)
    payload = await request.json()
    in_reply_to = payload.get("InReplyTo") or payload.get("inReplyTo")
    from_email = payload.get("From", {}).get("Address") if isinstance(payload.get("From"), dict) else payload.get("from")

    logger.info(f"Inbound reply from {from_email}")

    async with async_session() as session:
        lead = await _find_lead_by_message(in_reply_to, from_email)
        if not lead and from_email:
            result = await session.execute(
                select(Lead).where(Lead.email.ilike(from_email.strip()))
            )
            lead = result.scalar_one_or_none()

        if lead:
            lead.replied_at = datetime.now(timezone.utc)
            lead.status = LeadStatus.REPLIED
            lead.do_not_contact = False

            event = EmailEvent(
                lead_id=lead.id,
                message_id=in_reply_to,
                event_type="replied",
                event_time=datetime.now(timezone.utc),
                metadata_=payload,
                brevo_event_id=f"reply_{in_reply_to}_{from_email}",
            )
            session.add(event)
            await session.commit()
            logger.info(f"Lead {lead.id} marked as REPLIED — follow-ups stopped")

    return {"status": "ok"}
