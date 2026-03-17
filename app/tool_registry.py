import logging
from dataclasses import dataclass
from typing import Any, Callable

from tools.order_api import QUERY_ORDER_TOOL, query_order
from tools.ticket_api import CREATE_TICKET_TOOL, create_ticket

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class RegisteredTool:
    name: str
    definition: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, definition: dict[str, Any], handler: ToolHandler) -> None:
        function = definition.get("function", {})
        name = str(function.get("name", "")).strip()
        if not name:
            raise ValueError("tool definition missing function.name")
        self._tools[name] = RegisteredTool(name=name, definition=definition, handler=handler)

    def list_definitions(self) -> list[dict[str, Any]]:
        return [tool.definition for tool in self._tools.values()]

    def describe(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for tool in self._tools.values():
            function = tool.definition.get("function", {})
            rows.append(
                {
                    "name": tool.name,
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters", {}),
                }
            )
        return rows

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"unknown tool: {name}")

        logger.info("tool call name=%s args=%s", name, arguments)
        return tool.handler(arguments)


def create_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        QUERY_ORDER_TOOL,
        lambda arguments: query_order(str(arguments.get("order_id", ""))),
    )
    registry.register(
        CREATE_TICKET_TOOL,
        lambda arguments: create_ticket(
            user_issue=str(arguments.get("user_issue", "")),
            priority=str(arguments.get("priority", "normal")),
        ),
    )
    return registry
