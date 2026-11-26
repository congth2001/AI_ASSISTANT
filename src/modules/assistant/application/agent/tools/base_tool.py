from abc import ABC, abstractmethod
from src.modules.assistant.application.agent.tools.tool_result import ToolResult


class BaseTool(ABC):
    name: str
    description: str
    requires_approval: bool = False

    @abstractmethod
    async def run(self, **kwargs) -> ToolResult:
        pass
