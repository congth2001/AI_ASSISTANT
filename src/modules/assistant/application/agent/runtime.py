import asyncio
import logging
import time
from typing import Awaitable, Callable, TypeVar

from src.common.errors import ExternalServiceError
from src.modules.assistant.domain.errors import (
    AgentOperationTimeout,
    AgentPolicyStateError,
)

T = TypeVar("T")
logger = logging.getLogger(__name__)


# Only transient failures are worth another attempt. Domain/validation errors
# (bad SQL plan, forbidden table, malformed input) and programming errors fail
# the same way every time, so retrying would only add latency.
_RETRYABLE_ERRORS = (ExternalServiceError, ConnectionError)


async def run_with_policy(
    operation: Callable[[], Awaitable[T]],
    *,
    name: str,
    timeout_seconds: float,
    retries: int = 0,
) -> T:
    """Run an async dependency with a bounded timeout and retry budget.

    Retries happen only for timeouts and transient infrastructure errors
    (``ExternalServiceError``, ``ConnectionError``); every other exception is
    re-raised immediately.

    Limitation: ``asyncio.wait_for`` cancels the awaiting task on timeout, but
    work delegated with ``asyncio.to_thread`` cannot be cancelled. The worker
    thread keeps running to completion in the background, so a retry may run
    concurrently with the abandoned attempt. Operations that use
    ``to_thread`` must therefore be idempotent/read-only.
    """
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(operation(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            if attempt >= retries:
                raise AgentOperationTimeout(operation=name) from exc
        except _RETRYABLE_ERRORS:
            if attempt >= retries:
                raise
        delay = min(0.25 * (2**attempt), 1.0)
        logger.warning("Retrying agent operation", extra={"operation": name, "attempt": attempt + 1})
        await asyncio.sleep(delay)
    raise AgentPolicyStateError()


def node_metric(name: str, started_at: float, success: bool, error_type: str | None = None) -> dict:
    return {
        "node": name,
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        "success": success,
        "error_type": error_type,
    }

