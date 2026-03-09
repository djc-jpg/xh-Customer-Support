from typing import Any

ORDER_DB: dict[str, dict[str, Any]] = {
    "O1001": {"status": "已发货", "eta": "2026-03-07", "carrier": "顺丰", "last_update": "包裹已到达上海转运中心"},
    "O1002": {"status": "待发货", "eta": "2026-03-09", "carrier": "中通", "last_update": "仓库正在打包"},
    "O1003": {"status": "已签收", "eta": "2026-03-03", "carrier": "京东物流", "last_update": "前台代收"},
}


def query_order(order_id: str) -> dict[str, Any]:
    order_id = (order_id or "").upper().strip()
    record = ORDER_DB.get(order_id)
    if not record:
        return {"found": False, "order_id": order_id, "message": "未查询到该订单号"}
    return {"found": True, "order_id": order_id, **record}


QUERY_ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "query_order",
        "description": "查询订单状态和物流信息",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "订单号，例如 O1001",
                }
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
}

