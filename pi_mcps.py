"""MCP server configuration — stored in ~/.pi/agent/mcps.json.

'Pour tous les users': user-level MCPs go to ~/.pi/agent/mcps.json ;
system-level (read-only) MCPs are read from /etc/pi/agent/mcps.json when
present and displayed with a [sys] badge.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

USER_MCPS_FILE   = Path.home() / ".pi" / "agent" / "mcps.json"
SYSTEM_MCPS_FILE = Path("/etc/pi/agent/mcps.json")


@dataclass
class MCPServer:
    id:      str
    name:    str
    command: str
    args:    list[str]         = field(default_factory=list)
    env:     dict[str, str]    = field(default_factory=dict)
    enabled: bool              = True
    system:  bool              = False   # read-only system entry

    @property
    def summary(self) -> str:
        parts = [self.command] + self.args[:2]
        line = " ".join(parts)
        return (line[:36] + "…") if len(line) > 36 else line

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "command": self.command,
            "args": self.args, "env": self.env, "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any], system: bool = False) -> "MCPServer":
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            name=d.get("name", ""),
            command=d.get("command", ""),
            args=d.get("args", []),
            env=d.get("env", {}),
            enabled=d.get("enabled", True),
            system=system,
        )


def _load_file(path: Path, system: bool = False) -> list[MCPServer]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw if isinstance(raw, list) else raw.get("servers", [])
        return [MCPServer.from_dict(d, system=system) for d in entries]
    except Exception:
        return []


class MCPManager:
    """Manages MCP server configurations."""

    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or USER_MCPS_FILE
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

    # ── read ─────────────────────────────────────────────────────────

    def list_servers(self) -> list[MCPServer]:
        """Return user MCPs + read-only system MCPs."""
        servers = _load_file(self.config_file, system=False)
        servers += _load_file(SYSTEM_MCPS_FILE, system=True)
        return servers

    def _load_user(self) -> list[MCPServer]:
        return _load_file(self.config_file, system=False)

    def _save(self, servers: list[MCPServer]) -> None:
        self.config_file.write_text(
            json.dumps([s.to_dict() for s in servers], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── write ────────────────────────────────────────────────────────

    def add(self, name: str, command: str,
             args: list[str] | None = None,
             env:  dict[str, str] | None = None) -> MCPServer:
        servers = self._load_user()
        srv = MCPServer(id=str(uuid.uuid4())[:8], name=name,
                        command=command, args=args or [], env=env or {})
        servers.append(srv)
        self._save(servers)
        return srv

    def remove(self, server_id: str) -> bool:
        servers = self._load_user()
        new = [s for s in servers if s.id != server_id]
        if len(new) < len(servers):
            self._save(new)
            return True
        return False

    def toggle(self, server_id: str) -> Optional[MCPServer]:
        servers = self._load_user()
        for s in servers:
            if s.id == server_id:
                s.enabled = not s.enabled
                self._save(servers)
                return s
        return None

    # ── export ───────────────────────────────────────────────────────

    def export_pi_format(self) -> dict[str, Any]:
        """Export enabled servers in pi's mcpServers JSON format."""
        return {
            "mcpServers": {
                s.name: {"command": s.command, "args": s.args, "env": s.env}
                for s in self.list_servers()
                if s.enabled
            }
        }
