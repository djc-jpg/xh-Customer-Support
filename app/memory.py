import re
from collections import defaultdict, deque
from threading import Lock
from typing import Dict, List

from app.utils import extract_order_id


class SessionMemory:
    def __init__(self, max_turns: int = 6) -> None:
        self.max_messages = max_turns * 2
        self._store: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.max_messages))
        self._facts: Dict[str, deque] = defaultdict(lambda: deque(maxlen=12))
        self._summary: Dict[str, str] = defaultdict(str)
        self._lock = Lock()

    def append_user(self, session_id: str, content: str) -> None:
        with self._lock:
            self._store[session_id].append({"role": "user", "content": content})

    def append_assistant(self, session_id: str, content: str) -> None:
        with self._lock:
            self._store[session_id].append({"role": "assistant", "content": content})

    def get_history(self, session_id: str) -> List[dict]:
        with self._lock:
            return list(self._store[session_id])

    def remember_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        analysis: dict | None = None,
        tool_outputs: list[dict] | None = None,
    ) -> None:
        analysis = analysis or {}
        tool_outputs = tool_outputs or []

        with self._lock:
            facts = self._facts[session_id]
            order_id = extract_order_id(user_message) or extract_order_id(assistant_message)
            if order_id:
                self._push_fact(facts, f"最近提到的订单号：{order_id}")

            ticket_ids = self._extract_ticket_ids(assistant_message)
            for item in tool_outputs:
                result = item.get("result", {}) if isinstance(item, dict) else {}
                ticket_id = str(result.get("ticket_id", "")).strip()
                if ticket_id:
                    ticket_ids.add(ticket_id)

            for ticket_id in sorted(ticket_ids):
                self._push_fact(facts, f"最近创建的工单：{ticket_id}")

            intent = str(analysis.get("intent", "")).strip()
            urgency = str(analysis.get("urgency", "")).strip()
            sentiment = str(analysis.get("sentiment", "")).strip()
            if intent:
                self._push_fact(facts, f"用户主要诉求：{intent}")
            if urgency:
                self._push_fact(facts, f"问题紧急程度：{urgency}")
            if sentiment:
                self._push_fact(facts, f"用户情绪：{sentiment}")

            self._summary[session_id] = self._build_summary(session_id)

    def get_memory_snapshot(self, session_id: str) -> dict:
        with self._lock:
            return {
                "summary": self._summary.get(session_id, ""),
                "facts": list(self._facts[session_id]),
                "history_size": len(self._store[session_id]),
            }

    def _push_fact(self, facts: deque, fact: str) -> None:
        if fact in facts:
            facts.remove(fact)
        facts.appendleft(fact)

    def _build_summary(self, session_id: str) -> str:
        history = list(self._store[session_id])[-4:]
        if not history:
            return ""
        lines = []
        for item in history:
            role = "用户" if item.get("role") == "user" else "助手"
            content = re.sub(r"\s+", " ", str(item.get("content", ""))).strip()
            if len(content) > 48:
                content = content[:48].rstrip("，。；;,. ") + "..."
            lines.append(f"{role}: {content}")
        return " | ".join(lines)

    def _extract_ticket_ids(self, text: str) -> set[str]:
        return set(re.findall(r"\bT\d{5,}\b", str(text or "").upper()))
