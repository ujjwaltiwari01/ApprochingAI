import asyncio
import re
import time
from typing import Any

import httpx
from loguru import logger

from src.core.config import Settings, get_settings

# Min seconds between calls per provider (free-tier RPM safety)
PROVIDER_MIN_INTERVAL: dict[str, float] = {
    "mistral": 0.55,
    "cerebras": 12.5,
    "gemini": 4.5,
    "groq": 2.5,
    "openrouter": 3.0,
}

# Cooldown after rate-limit / quota errors (seconds)
PROVIDER_COOLDOWN_DEFAULT: dict[str, float] = {
    "mistral": 90,
    "cerebras": 120,
    "gemini": 300,
    "groq": 3600,
    "openrouter": 120,
}


class MistralKeyPool:
    """Round-robin across multiple Mistral free-tier keys."""

    def __init__(self, keys: list[str]):
        self.keys = keys
        self._index = 0
        self._cooldown_until: dict[str, float] = {}

    def next_key(self) -> str | None:
        if not self.keys:
            return None
        now = time.monotonic()
        for _ in range(len(self.keys)):
            key = self.keys[self._index % len(self.keys)]
            self._index += 1
            if self._cooldown_until.get(key, 0) <= now:
                return key
        return None

    def cooldown_key(self, key: str, seconds: float) -> None:
        self._cooldown_until[key] = time.monotonic() + seconds
        logger.warning(f"Mistral key ...{key[-4:]} cooling down for {seconds:.0f}s")


class LLMClient:
    DEFAULT_PROVIDERS = ["mistral", "cerebras", "openrouter", "gemini", "groq"]

    _provider_locks: dict[str, asyncio.Lock] = {}
    _last_call_at: dict[str, float] = {}
    _provider_cooldown_until: dict[str, float] = {}
    _semaphore: asyncio.Semaphore | None = None
    _mistral_pool: MistralKeyPool | None = None

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.timeout = self.settings.llm_timeout_seconds
        raw = self.settings.llm_providers.strip()
        self.providers = (
            [p.strip().lower() for p in raw.split(",") if p.strip()]
            if raw
            else self.DEFAULT_PROVIDERS
        )
        if LLMClient._semaphore is None:
            LLMClient._semaphore = asyncio.Semaphore(max(1, self.settings.llm_max_concurrent))
        if self.settings.mistral_api_keys:
            LLMClient._mistral_pool = MistralKeyPool(self.settings.mistral_api_keys)

    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        max_tokens: int = 1024,
        task: str = "general",
    ) -> tuple[str, str]:
        """Returns (response_text, provider_name). Tries providers in configured order."""
        assert LLMClient._semaphore is not None
        errors: list[str] = []
        async with LLMClient._semaphore:
            for provider in self.providers:
                if self._is_provider_cooling(provider):
                    errors.append(f"{provider}: cooling down")
                    continue
                try:
                    await self._throttle(provider)
                    result = await asyncio.wait_for(
                        self._call_provider(provider, prompt, system, max_tokens=max_tokens),
                        timeout=self.timeout,
                    )
                    if result:
                        logger.info(f"LLM response from {provider} ({task})")
                        await self._post_call_delay()
                        return result, provider
                except asyncio.TimeoutError:
                    errors.append(f"{provider}: timed out after {self.timeout}s")
                    logger.warning(f"{provider} timed out after {self.timeout}s ({task})")
                except Exception as exc:
                    if self._is_rate_limited(exc):
                        cooldown = self._parse_cooldown(exc, provider)
                        self._cooldown_provider(provider, cooldown)
                        errors.append(f"{provider}: rate limited")
                        logger.warning(f"{provider} rate limited ({task}), cooldown {cooldown:.0f}s")
                    else:
                        errors.append(f"{provider}: {exc}")
                        logger.warning(f"{provider} failed ({task}): {exc}")
            detail = "; ".join(errors) if errors else "no providers configured"
            raise RuntimeError(f"All LLM providers failed ({detail})")

    def _is_provider_cooling(self, provider: str) -> bool:
        return self._provider_cooldown_until.get(provider, 0) > time.monotonic()

    def _cooldown_provider(self, provider: str, seconds: float) -> None:
        self._provider_cooldown_until[provider] = time.monotonic() + seconds

    async def _throttle(self, provider: str) -> None:
        lock = self._provider_locks.setdefault(provider, asyncio.Lock())
        async with lock:
            min_gap = PROVIDER_MIN_INTERVAL.get(provider, 1.0)
            last = self._last_call_at.get(provider, 0.0)
            wait = min_gap - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_at[provider] = time.monotonic()

    async def _post_call_delay(self) -> None:
        delay = self.settings.llm_request_delay_ms / 1000.0
        if delay > 0:
            await asyncio.sleep(delay)

    @staticmethod
    def _is_rate_limited(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(
            token in msg
            for token in ("429", "rate limit", "rate_limit", "quota", "too many requests", "exceeded")
        )

    @staticmethod
    def _parse_cooldown(exc: Exception, provider: str) -> float:
        msg = str(exc)
        match = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", msg, re.I)
        if match:
            return float(match.group(1)) + 2
        if "tokens per day" in msg.lower() or "tpd" in msg.lower():
            return 3600
        return PROVIDER_COOLDOWN_DEFAULT.get(provider, 120)

    async def _call_provider(
        self, provider: str, prompt: str, system: str, *, max_tokens: int
    ) -> str | None:
        for attempt in range(2):
            try:
                if provider == "gemini":
                    return await self._call_gemini(prompt, system, max_tokens)
                if provider == "groq":
                    return await self._call_groq(prompt, system, max_tokens)
                if provider == "openrouter":
                    return await self._call_openrouter(prompt, system, max_tokens)
                if provider == "cerebras":
                    return await self._call_cerebras(prompt, system, max_tokens)
                if provider == "mistral":
                    return await self._call_mistral(prompt, system, max_tokens)
            except Exception as exc:
                if attempt == 1 or not self._is_rate_limited(exc):
                    raise
                await asyncio.sleep(2)
        return None

    async def _call_gemini(self, prompt: str, system: str, max_tokens: int) -> str:
        import google.generativeai as genai

        genai.configure(api_key=self.settings.gemini_api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        response = await asyncio.to_thread(
            model.generate_content,
            full_prompt,
            generation_config={"max_output_tokens": max_tokens},
        )
        return response.text

    async def _call_groq(self, prompt: str, system: str, max_tokens: int) -> str:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=self.settings.groq_api_key)
        messages = self._messages(system, prompt)
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def _call_openrouter(self, prompt: str, system: str, max_tokens: int) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        messages = self._messages(system, prompt)
        for model in (
            "meta-llama/llama-3.3-70b-instruct:free",
            "meta-llama/llama-3.3-70b-instruct",
        ):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                if self._is_rate_limited(exc) or "402" in str(exc):
                    continue
                raise
        raise RuntimeError("OpenRouter models unavailable")

    async def _call_cerebras(self, prompt: str, system: str, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.cerebras_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-oss-120b",
                    "messages": self._messages(system, prompt),
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            msg = response.json()["choices"][0]["message"]
            return msg.get("content") or msg.get("reasoning") or ""

    async def _call_mistral(self, prompt: str, system: str, max_tokens: int) -> str:
        pool = LLMClient._mistral_pool
        keys = pool.keys if pool else self.settings.mistral_api_keys
        if not keys:
            raise RuntimeError("No Mistral API keys configured")

        last_exc: Exception | None = None
        tries = len(keys) * 2
        for _ in range(tries):
            api_key = pool.next_key() if pool else keys[0]
            if not api_key:
                break
            try:
                return await self._mistral_request(api_key, system, prompt, max_tokens)
            except Exception as exc:
                last_exc = exc
                if self._is_rate_limited(exc) and pool:
                    pool.cooldown_key(api_key, self._parse_cooldown(exc, "mistral"))
                    continue
                raise
        raise last_exc or RuntimeError("All Mistral keys exhausted")

    async def _mistral_request(
        self, api_key: str, system: str, prompt: str, max_tokens: int
    ) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mistral-small-latest",
                    "messages": self._messages(system, prompt),
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""

    @staticmethod
    def _messages(system: str, prompt: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def summarize_website(self, page_contents: dict[str, str]) -> dict[str, Any]:
        combined = "\n\n".join(
            f"=== {page} ===\n{content[:2500]}"
            for page, content in page_contents.items()
            if content
        )
        prompt = f"""Analyze this agency website and return JSON only:
{{
  "industry": "",
  "positioning": "",
  "services": [],
  "specialization": "",
  "hiring_probability": 0,
  "summary": ""
}}

Website content:
{combined[:10000]}"""
        text, _ = await self.generate(prompt, max_tokens=512, task="website_summary")
        import json

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group())
        return {
            "industry": "",
            "positioning": "",
            "services": [],
            "specialization": "",
            "hiring_probability": 0,
            "summary": text[:500],
        }
