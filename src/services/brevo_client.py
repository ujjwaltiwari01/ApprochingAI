import asyncio
from datetime import date

import httpx
from loguru import logger
from sqlalchemy import select

from src.core.config import get_settings
from src.core.retry import async_retry
from src.db.models import DailySendCounter, async_session


class BrevoClient:
    BASE_URL = "https://api.brevo.com/v3"

    def __init__(self):
        self.settings = get_settings()
        self._account_index = 0

    async def send_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
        lead_id: str,
        followup_number: int = 0,
        is_followup: bool = False,
    ) -> tuple[str, int]:
        """Returns (message_id, brevo_account_id)."""
        account = await self._get_available_account(is_followup)
        if not account:
            raise RuntimeError("All Brevo accounts at daily quota")

        message_id = await self._send_with_account(
            account, to_email, to_name, subject, html_body, lead_id, followup_number
        )
        await self._increment_counter(account["id"], is_followup)
        return message_id, account["id"]

    @async_retry(max_attempts=5, base_delay=2.0)
    async def _send_with_account(
        self,
        account: dict,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
        lead_id: str,
        followup_number: int,
    ) -> str:
        payload = {
            "sender": {"name": account["sender_name"], "email": account["sender_email"]},
            "to": [{"email": to_email, "name": to_name or to_email}],
            "subject": subject,
            "htmlContent": html_body,
            "replyTo": {"email": self.settings.sender_email},
            "tags": [f"lead_{lead_id}", f"followup_{followup_number}"],
            "headers": {"X-Mailin-custom": f"lead_id:{lead_id}|followup:{followup_number}"},
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.BASE_URL}/smtp/email",
                headers={
                    "api-key": account["api_key"],
                    "Content-Type": "application/json",
                    "accept": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("messageId", data.get("messageIds", [""])[0] if data.get("messageIds") else "")

    async def _get_available_account(self, is_followup: bool) -> dict | None:
        today = date.today()
        accounts = [a for a in self.settings.brevo_accounts if a["api_key"]]
        if not accounts:
            return None

        n = len(accounts)
        async with async_session() as session:
            for step in range(n):
                account = accounts[(self._account_index + step) % n]
                result = await session.execute(
                    select(DailySendCounter).where(
                        DailySendCounter.send_date == today,
                        DailySendCounter.brevo_account == account["id"],
                    )
                )
                counter = result.scalar_one_or_none()
                limit = account["daily_followup"] if is_followup else account["daily_new"]
                current = 0
                if counter:
                    current = counter.followup_sent if is_followup else counter.new_sent

                if current < limit:
                    self._account_index = (self._account_index + step + 1) % n
                    return account

        return None

    async def _increment_counter(self, account_id: int, is_followup: bool) -> None:
        today = date.today()
        async with async_session() as session:
            result = await session.execute(
                select(DailySendCounter).where(
                    DailySendCounter.send_date == today,
                    DailySendCounter.brevo_account == account_id,
                )
            )
            counter = result.scalar_one_or_none()
            if not counter:
                counter = DailySendCounter(send_date=today, brevo_account=account_id)
                session.add(counter)

            if is_followup:
                counter.followup_sent += 1
            else:
                counter.new_sent += 1
            await session.commit()

    def text_to_html(self, text: str) -> str:
        paragraphs = text.strip().split("\n\n")
        html_parts = []
        for p in paragraphs:
            lines = p.strip().split("\n")
            html_parts.append(f"<p>{'<br>'.join(lines)}</p>")
        return "\n".join(html_parts)
