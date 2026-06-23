"""Personalized cold-email generation with deterministic quality gates.

Role in pipeline: sits after website analysis and before Brevo send — turns
``agency_analysis`` JSON plus prompt templates into subject + body text that
passes length, tone, and personalization checks.

Why this design (interview angle): LLMs are great at tone but unreliable on
constraints (word count, banned phrases, required links). We split generation
into parallel body + subject calls for latency, then enforce rules in Python
rather than trusting the model. Retry loops feed validation failures back as
prompt context — cheaper than a second orchestration service and keeps quality
logic testable without API calls.

Key decisions:
- Manual ``{placeholder}`` substitution instead of ``str.format`` so example
  braces in prompt files cannot crash rendering.
- Heuristic subject picker over blind LLM choice — reduces generic/spammy lines.
- Separate validation for initial vs follow-up word counts.
- Buzzword/spam lists as code constants for fast iteration without redeploying prompts.
"""

import asyncio
import json
import re
from pathlib import Path

from loguru import logger

from src.core.config import get_settings
from src.services.llm_client import LLMClient
from src.utils.compact_analysis import compact_agency_analysis
from src.utils.lead_row_normalizer import recipient_greeting_instruction

BUZZWORDS = [
    "synergy", "leverage", "cutting-edge", "game-changer", "revolutionary",
    "best-in-class", "world-class", "passionate", "excited to connect",
    "hope this finds you well", "i came across your", "i was impressed",
    "touch base", "circle back", "deep dive", "move the needle",
    "i wanted to reach out", "i'd love to explore", "i would love to explore",
    "i'm passionate", "i am passionate", "innovative", "utilize",
    "looking for a job", "exciting opportunity",
]

SPAM_WORDS = ["free", "guarantee", "act now", "limited time", "click here", "buy now", "urgent"]


class EmailGenerator:
    """Orchestrates LLM calls, parsing, subject selection, and validation for outreach copy."""

    def __init__(self):
        self.settings = get_settings()
        self.llm = LLMClient(self.settings)
        self.prompts_dir = Path(__file__).parent.parent.parent / "prompts"
        self.sender_profile = self._load_sender_profile()

    def _load_sender_profile(self) -> str:
        profile_path = Path(__file__).parent.parent.parent / "config" / "sender_profile.json"
        if profile_path.exists():
            return json.dumps(json.loads(profile_path.read_text()), indent=2)
        return "Ujjwal Tiwari - AI Engineer"

    def _load_prompt(self, name: str) -> str:
        return (self.prompts_dir / name).read_text(encoding="utf-8")

    def _analysis_for_prompt(self, agency_analysis: dict) -> str:
        data = (
            compact_agency_analysis(agency_analysis)
            if self.settings.llm_compact_analysis
            else agency_analysis
        )
        return json.dumps(data, indent=2)

    def _format_prompt(self, template: str, **kwargs) -> str:
        """Substitute known placeholders only — stray {braces} in examples won't crash."""
        result = template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", str(value))
        leftover = re.findall(r"\{([a-z_][a-z0-9_]*)\}", result, re.I)
        if leftover:
            logger.warning(f"Prompt has unreplaced placeholders (ignored): {leftover}")
        return result

    async def generate_initial_email(
        self,
        company_name: str,
        agency_analysis: dict,
        recipient_first_name: str | None = None,
    ) -> tuple[str, str, str, bool, list[str]]:
        """Returns (subject, body, provider, validation_passed, subject_candidates)."""
        analysis_json = self._analysis_for_prompt(agency_analysis)
        greeting_instruction = recipient_greeting_instruction(recipient_first_name)
        prompt = self._format_prompt(
            self._load_prompt("master_email.txt"),
            portfolio_url=self.settings.sender_portfolio_url,
            linkedin_url=self.settings.sender_linkedin_url,
            sender_profile=self.sender_profile,
            agency_analysis=analysis_json,
            company_name=company_name,
            recipient_greeting_instruction=greeting_instruction,
        )
        subject_prompt = self._format_prompt(
            self._load_prompt("subject_lines.txt"),
            company_name=company_name,
            agency_analysis=analysis_json,
        )
        email_system = (
            "You are Ujjwal Tiwari writing your own cold outreach as a job candidate. "
            "You are not pitching freelance services or selling a product. "
            "Follow the 5-sentence structure in the prompt. "
            "The email body must be 75 to 110 words before the Portfolio and LinkedIn lines."
        )

        # Parallel LLM calls: body and subject are independent — saves ~1 round-trip vs sequential.
        (text, provider), (subject_text, _) = await asyncio.gather(
            self.llm.generate(prompt, system=email_system, max_tokens=600, task="initial_email"),
            self.llm.generate(subject_prompt, max_tokens=300, task="subject_lines"),
        )
        subject, body = self._parse_email_output(text)
        subject_candidates = self._parse_subject_lines(subject_text)
        if subject_candidates:
            subject = self._pick_best_subject(subject, subject_candidates, company_name)
        elif subject:
            subject_candidates = [subject]

        valid = self._validate_email(subject, body, agency_analysis)
        attempts = 0
        max_retries = self.settings.llm_email_max_retries
        # Validation-driven retry: append failure reasons to the same prompt instead of a separate repair step.
        while not valid and attempts < max_retries:
            attempts += 1
            details = self.validate_email_details(subject, body, agency_analysis)
            logger.warning(f"Email validation failed for {company_name}, regenerating (attempt {attempts})")
            retry_text, provider = await self.llm.generate(
                prompt
                + f"\n\nIMPORTANT: Previous attempt failed validation.\n"
                f"Issues: {', '.join(details['reasons'])}.\n"
                f"Current word count: {details['word_count']}. Required: 75 to 110 words.\n"
                "Rewrite completely using the 5-sentence structure from the prompt. "
                "Sentence 1: specific agency observation. Sentences 2-3: relevant credential as a candidate. "
                "Sentence 4: role type you are open to. Sentence 5: easy CTA. "
                "75 to 110 words before links. No dashes. End with Ujjwal, then Portfolio and LinkedIn.",
                system=(
                    "You are Ujjwal Tiwari, a candidate reaching out about a role or contract engagement. "
                    "The email body MUST be at least 75 words and at most 110 words."
                ),
                max_tokens=600,
                task="email_retry",
            )
            subject, body = self._parse_email_output(retry_text)
            if subject_candidates:
                subject = self._pick_best_subject(subject, subject_candidates, company_name)
            valid = self._validate_email(subject, body, agency_analysis)
        return subject, body, provider, valid, subject_candidates

    async def generate_followup_email(
        self,
        company_name: str,
        agency_analysis: dict,
        followup_number: int,
        previous_subject: str,
        engagement_type: str,
        recipient_first_name: str | None = None,
    ) -> tuple[str, str, str, bool]:
        resume_line = ""
        if followup_number >= 2 and self.settings.sender_resume_url:
            resume_line = f"- Include resume link: {self.settings.sender_resume_url}"

        prompt = self._format_prompt(
            self._load_prompt("followup_templates.txt"),
            company_name=company_name,
            followup_number=followup_number,
            previous_subject=previous_subject,
            engagement_type=engagement_type,
            portfolio_url=self.settings.sender_portfolio_url,
            linkedin_url=self.settings.sender_linkedin_url,
            resume_line=resume_line,
            agency_analysis=self._analysis_for_prompt(agency_analysis),
            recipient_greeting_instruction=recipient_greeting_instruction(recipient_first_name),
        )
        text, provider = await self.llm.generate(prompt, max_tokens=400, task="followup")
        subject, body = self._parse_email_output(text)
        valid = self._validate_email(subject, body, agency_analysis, is_followup=True)
        return subject, body, provider, valid

    async def generate_subject_lines(self, company_name: str, agency_analysis: dict) -> list[str]:
        prompt = self._format_prompt(
            self._load_prompt("subject_lines.txt"),
            company_name=company_name,
            agency_analysis=self._analysis_for_prompt(agency_analysis),
        )
        text, _ = await self.llm.generate(prompt, max_tokens=300, task="subject_lines")
        return self._parse_subject_lines(text)

    def _parse_subject_lines(self, text: str) -> list[str]:
        lines = []
        for line in text.strip().split("\n"):
            cleaned = re.sub(r"^\d+[\.\)]\s*", "", line.strip())
            if not cleaned or cleaned.isdigit():
                continue
            word_count = len(cleaned.split())
            if 3 <= word_count <= 10 and len(cleaned) > 2:
                lines.append(cleaned)
        return lines[:5]

    _GENERIC_SUBJECT_PATTERNS = (
        "something i noticed",
        "noticed something",
        "on your site",
        "ai engineer open",
        "open to contract",
        "exciting opportunity",
        "partnership opportunity",
        "following up",
        "quick question about your",
    )

    def _pick_best_subject(self, generated: str, candidates: list[str], company_name: str) -> str:
        """Prefer agency-specific, non-generic subject from candidates."""
        company_tokens = {t.lower() for t in re.findall(r"[a-zA-Z]{3,}", company_name)}
        # Lightweight scoring beats a second LLM call — predictable, free, and unit-testable.
        scored = []
        for subj in candidates:
            words = subj.split()
            if len(words) > 10 or len(words) < 3 or len(subj) <= 2 or subj.isdigit():
                continue
            score = 0
            lower = subj.lower()
            if any(tok in lower for tok in company_tokens):
                score += 5
            if any(pat in lower for pat in self._GENERIC_SUBJECT_PATTERNS):
                score -= 4
            if "opportunity" in lower or "exciting" in lower or "free" in lower:
                score -= 3
            if "?" in subj or " — " in subj or " - " in subj:
                score += 1
            if subj.endswith("."):
                score -= 2
            scored.append((score, subj))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0][1]
        return generated or (candidates[0] if candidates else "")

    def _parse_email_output(self, text: str) -> tuple[str, str]:
        subject = ""
        body_lines: list[str] = []
        body_started = False

        for line in text.strip().split("\n"):
            lower = line.lower().strip()
            if lower.startswith("subject:"):
                subject = line.split(":", 1)[1].strip()
            elif lower.startswith("email:"):
                body_started = True
                rest = line.split(":", 1)[1].strip()
                if rest:
                    body_lines.append(rest)
            elif body_started:
                body_lines.append(line)

        body = "\n".join(body_lines).strip()
        # Models sometimes omit "Email:" label — treat full output as body to avoid empty sends.
        if not body and not body_started:
            body = text.strip()

        body = self._normalize_body(body)
        return subject, body

    def _normalize_body(self, body: str) -> str:
        """Strip stray Subject lines and enforce Ujjwal before link lines."""
        lines = [ln for ln in body.split("\n") if not ln.strip().lower().startswith("subject:")]
        content: list[str] = []
        links: list[str] = []
        signoff = ""
        for ln in lines:
            stripped = ln.strip()
            if stripped.startswith("Portfolio:") or stripped.startswith("LinkedIn:"):
                links.append(stripped)
            elif stripped == "Ujjwal":
                signoff = stripped
            else:
                content.append(ln)
        ordered: list[str] = []
        if content:
            ordered.extend(content)
        if signoff:
            ordered.append(signoff)
        ordered.extend(links)
        return "\n".join(ordered).strip()

    def _body_content_lines(self, body: str) -> list[str]:
        """Email prose lines only (exclude sign-off and link lines)."""
        content = []
        for ln in body.split("\n"):
            stripped = ln.strip()
            if not stripped:
                continue
            if stripped == "Ujjwal":
                continue
            if stripped.startswith("Portfolio:") or stripped.startswith("LinkedIn:"):
                continue
            content.append(stripped)
        return content

    def _has_ujjwal_signoff(self, body: str) -> bool:
        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            if ln.startswith("Portfolio:") or ln.startswith("LinkedIn:"):
                return i > 0 and lines[i - 1] == "Ujjwal"
        return lines[-1] == "Ujjwal" if lines else False

    def _validate_email(
        self, subject: str, body: str, agency_analysis: dict, is_followup: bool = False
    ) -> bool:
        return self.validate_email_details(subject, body, agency_analysis, is_followup)["passed"]

    def validate_email_details(
        self, subject: str, body: str, agency_analysis: dict, is_followup: bool = False
    ) -> dict:
        reasons: list[str] = []
        if not subject:
            reasons.append("Missing subject")
        if not body:
            reasons.append("Missing body")

        # Word count excludes sign-off and link lines — matches prompt "75–110 words before Portfolio/LinkedIn".
        word_count = len(" ".join(self._body_content_lines(body)).split())

        if is_followup:
            if word_count < 25:
                reasons.append(f"Too short ({word_count} words, min 25)")
            elif word_count > 120:
                reasons.append(f"Too long ({word_count} words, max 120)")
        else:
            if word_count < 75:
                reasons.append(f"Too short ({word_count} words, min 75)")
            elif word_count > 110:
                reasons.append(f"Too long ({word_count} words, max 110)")

        if len(subject.split()) > 10:
            reasons.append(f"Subject too long ({len(subject.split())} words, max 10)")
        elif len(subject.split()) < 3:
            reasons.append(f"Subject too short ({len(subject.split())} words, min 3)")

        if "—" in body or " - " in body:
            reasons.append("Contains dash (banned by prompt)")

        paragraphs = [p for p in "\n".join(self._body_content_lines(body)).split("\n\n") if p.strip()]
        max_paragraphs = 6 if not is_followup else 4
        if len(paragraphs) > max_paragraphs:
            reasons.append(f"Too many paragraphs ({len(paragraphs)}, max {max_paragraphs})")

        combined = f"{subject} {body}".lower()
        for buzz in BUZZWORDS:
            if buzz in combined:
                reasons.append(f"Buzzword: {buzz}")
                break

        for spam in SPAM_WORDS:
            if spam in combined:
                reasons.append(f"Spam word: {spam}")
                break

        if self.settings.sender_portfolio_url not in body:
            reasons.append("Missing portfolio link")
        if self.settings.sender_linkedin_url not in body:
            reasons.append("Missing LinkedIn link")
        if not self._has_ujjwal_signoff(body):
            reasons.append("Sign-off should end with Ujjwal")

        summary = agency_analysis.get("summary", "") or agency_analysis.get("positioning", "")
        if summary and not is_followup:
            tokens: set[str] = set()
            for field in ("summary", "positioning", "specialization", "industry"):
                text = str(agency_analysis.get(field) or "")
                tokens.update(w.lower().strip(".,\"'") for w in text.split() if len(w) > 4)
            services = agency_analysis.get("services") or []
            if isinstance(services, list):
                for svc in services:
                    tokens.update(w.lower() for w in str(svc).split() if len(w) > 4)
            body_lower = " ".join(self._body_content_lines(body)).lower()
            # Token overlap check is a cheap proxy for "mentioned something from their site" — not semantic similarity.
            if tokens and not any(tok in body_lower for tok in list(tokens)[:20]):
                reasons.append("No website-specific insight detected")

        return {"passed": len(reasons) == 0, "reasons": reasons, "word_count": word_count}
