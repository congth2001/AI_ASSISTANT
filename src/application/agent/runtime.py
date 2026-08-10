import asyncio
import logging
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


class AgentOperationTimeout(TimeoutError):
    pass


async def run_with_policy(
    operation: Callable[[], Awaitable[T]],
    *,
    name: str,
    timeout_seconds: float,
    retries: int = 0,
) -> T:
    """Run an async dependency with a bounded timeout and retry budget."""
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(operation(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            if attempt >= retries:
                raise AgentOperationTimeout(f"{name} timed out") from exc
        except Exception:
            if attempt >= retries:
                raise
        delay = min(0.25 * (2**attempt), 1.0)
        logger.warning("Retrying agent operation", extra={"operation": name, "attempt": attempt + 1})
        await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


def node_metric(name: str, started_at: float, success: bool, error_type: str | None = None) -> dict:
    return {
        "node": name,
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        "success": success,
        "error_type": error_type,
    }

