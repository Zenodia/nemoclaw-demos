"""
Debug output utilities for AgenticTA.

Controls whether debug-level print statements produce output.
In production, debug output is silenced. In development/testing,
it can be enabled via environment variable.

Environment Variables:
    AGENTICTA_DEBUG:  Set to "1", "true", or "yes" to enable debug prints.
                      Default: disabled (no debug output).

    LOG_LEVEL:        Controls Python logging level for logger-based output.
                      Values: DEBUG, INFO, WARNING, ERROR, CRITICAL
                      Default: INFO

Usage (quick migration from raw print):
    # Before (always prints, even in production):
    print(f"[DEBUG] user_id={user_id}, chapters={len(chapters)}")

    # After (only prints when AGENTICTA_DEBUG=true):
    from common.debug import debug_print
    debug_print(f"[DEBUG] user_id={user_id}, chapters={len(chapters)}")

Usage (proper logging - preferred for new code):
    from common.debug import get_debug_logger
    logger = get_debug_logger(__name__)
    logger.debug("user_id=%s, chapters=%d", user_id, len(chapters))
    logger.info("Curriculum generated successfully")  # Always shows at INFO+

Quick reference - what to use when:
    debug_print(...)           → Drop-in replacement for debug prints (migration path)
    logger.debug(...)          → Detailed diagnostics (only shown at DEBUG level)
    logger.info(...)           → Operational milestones ("chapter built", "user created")
    logger.warning(...)        → Something unexpected but recoverable
    logger.error(...)          → Something failed
    print(...)                 → Interactive CLI output only (not for server code)
"""

import os
import logging

# ── Debug flag ────────────────────────────────────────────────────────
# Read once at import time. Changing the env var requires a restart.

DEBUG: bool = os.environ.get("AGENTICTA_DEBUG", "").lower() in ("1", "true", "yes")

# ── Log level ─────────────────────────────────────────────────────────
# Aligns with logging_config.py. Falls back to INFO if not set.

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()


def debug_print(*args, **kwargs):
    """Drop-in replacement for ``print()`` that only outputs when debug is enabled.

    Use this as a quick migration path for existing ``print(f"[DEBUG] ...")``
    statements. For new code, prefer ``logger.debug(...)`` instead.

    Examples::

        # Replaces: print(f"[DEBUG] value={x}")
        debug_print(f"[DEBUG] value={x}")

        # Replaces: print(Fore.CYAN + f"[DEBUG] query={q}" + Fore.RESET)
        debug_print(Fore.CYAN + f"[DEBUG] query={q}" + Fore.RESET)
    """
    if DEBUG:
        print(*args, **kwargs)


def is_debug() -> bool:
    """Return whether debug mode is enabled.

    Useful for guarding expensive debug computations::

        if is_debug():
            debug_print(f"Full state dump: {json.dumps(state, indent=2)}")
    """
    return DEBUG


def get_debug_logger(name: str) -> logging.Logger:
    """Get a logger configured to respect the ``LOG_LEVEL`` environment variable.

    This is a convenience wrapper around Python's standard ``logging.getLogger``
    that ensures the logger's effective level matches the app-wide configuration.

    Args:
        name: Logger name (typically ``__name__``).

    Returns:
        A configured ``logging.Logger`` instance.

    Example::

        from common.debug import get_debug_logger
        logger = get_debug_logger(__name__)

        logger.debug("Detailed trace info - only shown when LOG_LEVEL=DEBUG")
        logger.info("Operational info - shown at INFO level and above")
        logger.warning("Something unexpected happened")
    """
    logger = logging.getLogger(name)

    # Ensure the logger respects the app-wide level.
    # If logging hasn't been configured yet (e.g., during imports),
    # set a basic handler so messages aren't silently dropped.
    if not logging.root.handlers:
        logging.basicConfig(
            level=getattr(logging, LOG_LEVEL, logging.INFO),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    return logger
