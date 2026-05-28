"""Session management — JSONL format compatible with pi agent."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

SESSIONS_DIR = Path.home() / ".pi" / "agent" / "sessions"


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    parent_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Session:
    id: str
    name: str
    path: Path
    created_at: datetime
    messages: list[ChatMessage] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.name or self.id[:8]

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def preview(self) -> str:
        user_msgs = [m for m in self.messages if m.role == "user"]
        if user_msgs:
            c = user_msgs[-1].content
            return (c[:38] + "…") if len(c) > 38 else c
        return "Nouvelle session"

    def add_message(self, role: str, content: str) -> ChatMessage:
        parent_id = self.messages[-1].id if self.messages else None
        msg = ChatMessage(role=role, content=content, parent_id=parent_id)
        self.messages.append(msg)
        self._save()
        return msg

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "session_header",
                "id": self.id,
                "name": self.name,
                "created_at": self.created_at.isoformat(),
            }, ensure_ascii=False) + "\n")
            for msg in self.messages:
                f.write(json.dumps({
                    "type": "message",
                    "id": msg.id,
                    "parent_id": msg.parent_id,
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp,
                }, ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> Optional["Session"]:
        try:
            name = session_id = ""
            created_at = datetime.now()
            messages: list[ChatMessage] = []

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if entry.get("type") == "session_header":
                        name = entry.get("name", "")
                        session_id = entry.get("id", "")
                        try:
                            created_at = datetime.fromisoformat(entry["created_at"])
                        except Exception:
                            pass
                    elif entry.get("type") == "message":
                        messages.append(ChatMessage(
                            role=entry.get("role", "user"),
                            content=entry.get("content", ""),
                            id=entry.get("id", str(uuid.uuid4())[:8]),
                            parent_id=entry.get("parent_id"),
                            timestamp=entry.get("timestamp", datetime.now().isoformat()),
                        ))

            return cls(
                id=session_id or path.stem,
                name=name or path.stem[:20],
                path=path,
                created_at=created_at,
                messages=messages,
            )
        except Exception:
            return None


class SessionManager:
    def __init__(self, directory: Optional[Path] = None):
        self.directory = directory or SESSIONS_DIR
        self.directory.mkdir(parents=True, exist_ok=True)

    def list_sessions(self) -> list[Session]:
        sessions = []
        for p in sorted(
            self.directory.glob("*.jsonl"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            s = Session.load(p)
            if s:
                sessions.append(s)
        return sessions

    def create(self, name: str = "") -> Session:
        sid = str(uuid.uuid4())
        display = name or f"Session {datetime.now().strftime('%d/%m %H:%M')}"
        path = self.directory / f"{sid}.jsonl"
        s = Session(id=sid, name=display, path=path, created_at=datetime.now())
        s._save()
        return s

    def delete(self, session_id: str) -> bool:
        for p in self.directory.glob("*.jsonl"):
            if p.stem == session_id:
                p.unlink()
                return True
        return False
