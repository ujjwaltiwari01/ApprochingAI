"""Tests: follow-up cadence (4/5/8/15 day rules) and engagement-aware delays."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from src.services.followup_engine import FollowupEngine


def test_next_followup_number():
    engine = FollowupEngine()
    lead = MagicMock()
    lead.followup_1_sent = None
    lead.followup_2_sent = None
    lead.followup_3_sent = None
    assert engine._next_followup_number(lead) == 1

    lead.followup_1_sent = datetime.now(timezone.utc)
    assert engine._next_followup_number(lead) == 2

    lead.followup_2_sent = datetime.now(timezone.utc)
    assert engine._next_followup_number(lead) == 3

    lead.followup_3_sent = datetime.now(timezone.utc)
    assert engine._next_followup_number(lead) is None


def test_engagement_type():
    engine = FollowupEngine()
    lead = MagicMock()
    lead.clicked_at = datetime.now(timezone.utc)
    lead.opened_at = datetime.now(timezone.utc)
    assert engine.get_engagement_type(lead) == "clicked"

    lead.clicked_at = None
    assert engine.get_engagement_type(lead) == "opened_no_reply"

    lead.opened_at = None
    assert engine.get_engagement_type(lead) == "never_opened"


def test_is_due():
    engine = FollowupEngine()
    lead = MagicMock()
    lead.sent_at = datetime.now(timezone.utc) - timedelta(days=5)
    lead.opened_at = None
    lead.clicked_at = None
    now = datetime.now(timezone.utc)
    assert engine._is_due(lead, 1, now) is True
