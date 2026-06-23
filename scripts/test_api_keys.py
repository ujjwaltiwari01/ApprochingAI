#!/usr/bin/env python3
"""Test all Brevo and LLM API keys from .env — never prints full keys.

Pre-flight health check before enabling daily outreach or deploying to Render.
Each provider gets a minimal "Reply with OK" call; LLMClient chain test mirrors
production fallback order (mistral → cerebras → openrouter → gemini → groq).
Exit code 1 if any check fails — suitable for CI or manual `python scripts/test_api_keys.py`.
"""

import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

RESULTS: list[tuple[str, bool, str]] = []  # Collected for summary + exit code


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def test_brevo(account_num: int) -> None:
    key = os.getenv(f"BREVO_API_KEY_{account_num}", "")
    sender = os.getenv(f"BREVO_SENDER_EMAIL_{account_num}", "")
    name = f"Brevo Account {account_num}"
    if not key:
        record(name, False, "API key missing")
        return
    try:
        r = httpx.get(
            "https://api.brevo.com/v3/account",
            headers={"api-key": key, "accept": "application/json"},
            timeout=20,
        )
        if r.status_code == 200:
            data = r.json()
            email_credits = data.get("plan", [{}])
            plan_type = data.get("plan", [{}])[0].get("type", "unknown") if data.get("plan") else "unknown"
            record(name, True, f"plan={plan_type}, sender={sender}")
        else:
            record(name, False, f"HTTP {r.status_code}: {r.text[:120]}")
    except Exception as exc:
        record(name, False, str(exc)[:120])


def test_gemini() -> None:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        record("Gemini", False, "API key missing")
        return
    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        # Try models in order — first success wins (matches production resilience)
        for model_name in ("gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.0-flash-lite"):
            try:
                model = genai.GenerativeModel(model_name)
                resp = model.generate_content("Reply with exactly: OK")
                text = (resp.text or "").strip()[:50]
                record("Gemini", True, f"model={model_name}, response={text!r}")
                return
            except Exception as inner:
                last_err = str(inner)[:100]
                continue
        record("Gemini", False, last_err)
    except Exception as exc:
        record("Gemini", False, str(exc)[:120])


def test_groq() -> None:
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        record("Groq", False, "API key missing")
        return
    try:
        from groq import Groq

        client = Groq(api_key=key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=10,
        )
        text = (resp.choices[0].message.content or "").strip()[:50]
        record("Groq", True, f"response={text!r}")
    except Exception as exc:
        record("Groq", False, str(exc)[:120])


def test_openrouter() -> None:
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        record("OpenRouter", False, "API key missing")
        return
    try:
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "meta-llama/llama-3.3-70b-instruct",
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                "max_tokens": 10,
            },
            timeout=30,
        )
        if r.status_code == 200:
            text = r.json()["choices"][0]["message"]["content"].strip()[:50]
            record("OpenRouter", True, f"response={text!r}")
        else:
            record("OpenRouter", False, f"HTTP {r.status_code}: {r.text[:120]}")
    except Exception as exc:
        record("OpenRouter", False, str(exc)[:120])


def test_cerebras() -> None:
    key = os.getenv("CEREBRAS_API_KEY", "")
    if not key:
        record("Cerebras", False, "API key missing")
        return
    try:
        r = httpx.post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-oss-120b",
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                "max_tokens": 20,
            },
            timeout=30,
        )
        if r.status_code == 200:
            msg = r.json()["choices"][0]["message"]
            text = (msg.get("content") or msg.get("reasoning") or "").strip()[:50]
            record("Cerebras", True, f"model=gpt-oss-120b, response={text!r}")
        else:
            record("Cerebras", False, f"HTTP {r.status_code}: {r.text[:120]}")
    except Exception as exc:
        record("Cerebras", False, str(exc)[:120])


def test_mistral_key(key: str, label: str) -> None:
    if not key:
        record(label, False, "API key missing")
        return
    try:
        r = httpx.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                "max_tokens": 10,
            },
            timeout=30,
        )
        if r.status_code == 200:
            text = r.json()["choices"][0]["message"]["content"].strip()[:50]
            record(label, True, f"response={text!r}")
        else:
            record(label, False, f"HTTP {r.status_code}: {r.text[:120]}")
    except Exception as exc:
        record(label, False, str(exc)[:120])


def test_mistral() -> None:
    test_mistral_key(os.getenv("MISTRAL_API_KEY", ""), "Mistral Account 1")
    test_mistral_key(os.getenv("MISTRAL_API_KEY_2", ""), "Mistral Account 2")


async def test_llm_client_chain() -> None:
    """End-to-end test of the same LLMClient used by EmailGenerator."""
    try:
        from src.core.config import get_settings
        from src.services.llm_client import LLMClient

        get_settings.cache_clear()
        client = LLMClient()
        text, provider = await client.generate("Reply with exactly: OK", max_tokens=10, task="healthcheck")
        record("LLM Fallback Chain", True, f"providers={client.providers}, used={provider}, response={text.strip()[:50]!r}")
    except Exception as exc:
        record("LLM Fallback Chain", False, str(exc)[:150])


def test_supabase() -> None:
    try:
        from streamlit_app.db_utils import test_connection

        data = test_connection()
        record("Supabase", True, f"{data['leads']:,} leads, {data['cache']:,} cache")
    except Exception as exc:
        record("Supabase", False, str(exc)[:120])


def main() -> None:
    print("=" * 60)
    print("API KEY TEST SUITE")
    print("=" * 60)

    test_supabase()  # DB reachability first — downstream tests assume data layer works
    for i in range(1, 4):  # Three Brevo sender accounts (150/day each)
        test_brevo(i)
    test_gemini()
    test_groq()
    test_openrouter()
    test_cerebras()
    test_mistral()
    asyncio.run(test_llm_client_chain())

    print("=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"RESULT: {passed}/{total} passed")
    if passed < total:
        print("\nFailed:")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  - {name}: {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
