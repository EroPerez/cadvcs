import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from ..config import HISTORY_FILE, MAX_HISTORY


class ConversationHistory:
    def __init__(self):
        self._messages: List[Dict] = []
        self._load()

    def add(self, role: str, content: str):
        self._messages.append(
            {"role": role, "content": content, "ts": datetime.now().isoformat()}
        )
        # Keep only the last MAX_HISTORY turns (each turn = 1 user + 1 assistant)
        if len(self._messages) > MAX_HISTORY * 2:
            self._messages = self._messages[-(MAX_HISTORY * 2):]
        self._save()

    def get_messages(self) -> List[Dict]:
        """Return messages in the format Claude API expects."""
        return [{"role": m["role"], "content": m["content"]} for m in self._messages]

    def clear(self):
        self._messages = []
        self._save()

    def _save(self):
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.write_text(
                json.dumps(self._messages, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _load(self):
        try:
            if HISTORY_FILE.exists():
                self._messages = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            self._messages = []
