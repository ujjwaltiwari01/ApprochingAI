import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.core.config import get_settings


class Base(DeclarativeBase):
    pass


class LeadStatus(str, enum.Enum):
    NEW = "NEW"
    WEBSITE_ANALYZED = "WEBSITE_ANALYZED"
    EMAIL_GENERATED = "EMAIL_GENERATED"
    EMAIL_SENT = "EMAIL_SENT"
    OPENED = "OPENED"
    CLICKED = "CLICKED"
    REPLIED = "REPLIED"
    INTERESTED = "INTERESTED"
    INTERVIEW = "INTERVIEW"
    HIRED = "HIRED"
    BOUNCED = "BOUNCED"
    SPAM = "SPAM"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


class JobType(str, enum.Enum):
    DAILY_OUTREACH = "daily_outreach"
    FOLLOWUP = "followup"
    IMPORT = "import"
    SCRAPE = "scrape"
    GENERATE = "generate"
    SEND = "send"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class ScrapeStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    CACHED = "cached"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]

class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, name="lead_status", create_type=False, values_callable=_enum_values),
        default=LeadStatus.NEW,
    )
    current_stage: Mapped[str | None] = mapped_column(Text, default="initial")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    followup_1_sent: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    followup_2_sent: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    followup_3_sent: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    portfolio_clicked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_subject: Mapped[str | None] = mapped_column(Text)
    last_email_body: Mapped[str | None] = mapped_column(Text)
    match_score: Mapped[int] = mapped_column(Integer, default=50)
    hiring_probability: Mapped[int] = mapped_column(Integer, default=0)
    csv_raw: Mapped[dict | None] = mapped_column(JSONB)
    brevo_account: Mapped[int | None] = mapped_column(Integer)
    message_id: Mapped[str | None] = mapped_column(Text)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    generated_content: Mapped[list["GeneratedContent"]] = relationship(back_populates="lead")
    email_events: Mapped[list["EmailEvent"]] = relationship(back_populates="lead")


class WebsiteCache(Base):
    __tablename__ = "website_cache"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    website: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    homepage_content: Mapped[str | None] = mapped_column(Text)
    services_content: Mapped[str | None] = mapped_column(Text)
    about_content: Mapped[str | None] = mapped_column(Text)
    team_content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    specialization: Mapped[str | None] = mapped_column(Text)
    last_scraped: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    scrape_status: Mapped[ScrapeStatus] = mapped_column(
        Enum(ScrapeStatus, name="scrape_status", create_type=False, values_callable=_enum_values),
        default=ScrapeStatus.PENDING,
    )
    error_log: Mapped[str | None] = mapped_column(Text)
    analysis_json: Mapped[dict | None] = mapped_column(JSONB)


class GeneratedContent(Base):
    __tablename__ = "generated_content"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"))
    personalized_hook: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    email_body: Mapped[str | None] = mapped_column(Text)
    llm_provider: Mapped[str | None] = mapped_column(Text)
    followup_number: Mapped[int] = mapped_column(Integer, default=0)
    validation_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="generated_content")


class EmailEvent(Base):
    __tablename__ = "email_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"))
    message_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    brevo_event_id: Mapped[str | None] = mapped_column(Text)

    lead: Mapped["Lead | None"] = relationship(back_populates="email_events")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, name="job_type", create_type=False, values_callable=_enum_values),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", create_type=False, values_callable=_enum_values),
        default=JobStatus.PENDING,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_log: Mapped[list | None] = mapped_column(JSONB, default=list)
    checkpoint: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    batch_offset: Mapped[int] = mapped_column(Integer, default=0)


class DailySendCounter(Base):
    __tablename__ = "daily_send_counters"
    __table_args__ = (UniqueConstraint("send_date", "brevo_account"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    send_date: Mapped[datetime] = mapped_column(Date, server_default=func.current_date())
    brevo_account: Mapped[int] = mapped_column(Integer, nullable=False)
    new_sent: Mapped[int] = mapped_column(Integer, default=0)
    followup_sent: Mapped[int] = mapped_column(Integer, default=0)


settings = get_settings()
_engine = None
_async_session = None


def get_engine():
    global _engine
    if _engine is None:
        connect_args = {}
        if "supabase" in settings.database_url:
            connect_args["ssl"] = "require"
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    return _engine


def get_async_session_factory():
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _async_session


class _SessionProxy:
    def __call__(self, *args, **kwargs):
        return get_async_session_factory()(*args, **kwargs)


async_session = _SessionProxy()


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
