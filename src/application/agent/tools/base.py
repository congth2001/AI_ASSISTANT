from abc import ABC, abstractmethod
from src.application.agent.tools.result import ToolResult


class BaseTool(ABC):
    name: str
    description: str
    requires_approval: bool = False

    @abstractmethod
    async def run(self, **kwargs) -> ToolResult:
        pass
