from datetime import datetime
from itertools import count
from typing import Any

_counter = count(10001)
TICKETS: dict[str, dict[str, Any]] = {}


def create_ticket(user_issue: str, priority: str = "normal") -> dict[str, Any]:
    ticket_id = f"T{next(_counter)}"
    ticket = {
        "ticket_id": ticket_id,
        "priority": priority,
        "status": "open",
        "issue": user_issue,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    TICKETS[ticket_id] = ticket
    return ticket


CREATE_TICKET_TOOL = {
    "type": "function",
    "function": {
        "name": "create_ticket",
        "description": "创建客服工单并返回工单号",
        "parameters": {
            "type": "object",
            "properties": {
                "user_issue": {
                    "type": "string",
                    "description": "用户问题描述",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "工单优先级",
                },
            },
            "required": ["user_issue"],
            "additionalProperties": False,
        },
    },
}

