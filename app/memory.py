from collections import defaultdict, deque
from threading import Lock
from typing import Dict, List


class SessionMemory:
    def __init__(self, max_turns: int = 6) -> None:
        self.max_messages = max_turns * 2
        self._store: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.max_messages))
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

