"""Structured logging setup for CLI jobs and long-running outreach batches.

Design: dual sinks — INFO on stderr for operator visibility in CI/Render logs,
DEBUG to rotating files for post-mortems without flooding production consoles.
"""

import sys

from loguru import logger


def setup_logging() -> None:
    # Reset default handler so we control format/levels exactly once at startup.
    logger.remove()
    # Human-readable stderr for live tailing during daily outreach runs.
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level="INFO",
    )
    # File sink: full DEBUG trail; enqueue=True avoids blocking the event loop on I/O.
    logger.add(
        "logs/outreach_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
        enqueue=True,
    )
