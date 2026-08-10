from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class ToolResult:
    """Normalized result returned by every agent tool."""

    success: bool
    has_data: bool
    content: str = ""
    error_code: str | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

