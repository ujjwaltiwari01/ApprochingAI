"""Async retry decorator with exponential backoff for flaky external APIs.

Design: decorator keeps call sites clean; ParamSpec/TypeVar preserve the wrapped
function's signature for type checkers. Backoff reduces thundering herd against
LLM/email providers after transient 429/5xx errors.
"""

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from loguru import logger

P = ParamSpec("P")
T = TypeVar("T")


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        # Exponential backoff: 1s, 2s, 4s, … capped by max_attempts.
                        delay = base_delay * (2 ** (attempt - 1))
                        logger.warning(
                            f"{func.__name__} attempt {attempt}/{max_attempts} failed: {exc}. "
                            f"Retrying in {delay}s"
                        )
                        await asyncio.sleep(delay)
            # Re-raise the last failure so callers see the real root cause.
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
