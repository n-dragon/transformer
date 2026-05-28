"""Cron job manager — scheduled Pi agent sessions.

Cron jobs are stored in ~/.pi/agent/crons.json.
The CronRunner background thread checks every 30 s and fires jobs
whose schedule matches the current minute.

Requires: pip install croniter
"""

from __future__ import annotations

import json
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

CRONS_FILE = Path.home() / ".pi" / "agent" / "crons.json"

try:
    from croniter import croniter as _croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False

# ── Human-readable presets shown in the modal ────────────────────────────────
PRESETS = [
    ("Toutes les heures",      "0 * * * *"),
    ("Chaque jour à 9h",       "0 9 * * *"),
    ("Lundi–vendredi à 9h",    "0 9 * * 1-5"),
    ("Chaque lundi à 9h",      "0 9 * * 1"),
    ("Chaque dimanche à 18h",  "0 18 * * 0"),
    ("Toutes les 15 min",      "*/15 * * * *"),
    ("Personnalisé…",          ""),
]

DOW_LABELS = {
    "0": "dim", "1": "lun", "2": "mar", "3": "mer",
    "4": "jeu", "5": "ven", "6": "sam",
    "1-5": "lun–ven", "*": "chaque jour",
}


def _humanize(expr: str) -> str:
    """Best-effort human label for a cron expression."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return expr
    m, h, dom, mon, dow = parts
    if dom == "*" and mon == "*":
        day = DOW_LABELS.get(dow, f"dow={dow}")
        if m == "0" and h != "*":
            return f"Chaque {day} à {h}h"
        if m.startswith("*/") and h == "*" and dow == "*":
            return f"Toutes les {m[2:]} min"
        if m == "0" and h == "*":
            return f"Toutes les heures ({day})"
    return expr


@dataclass
class CronJob:
    id:           str
    name:         str
    schedule:     str          # standard 5-field cron expression
    prompt:       str          # message forwarded to pi -p
    session_name: str          = ""
    enabled:      bool         = True
    last_run:     Optional[str] = None
    created_at:   str          = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def schedule_label(self) -> str:
        return _humanize(self.schedule)

    @property
    def next_run_label(self) -> str:
        if not HAS_CRONITER or not self.enabled:
            return "—"
        try:
            nxt = _croniter(self.schedule, datetime.now()).get_next(datetime)
            return nxt.strftime("%d/%m %H:%M")
        except Exception:
            return "?"

    @property
    def last_run_label(self) -> str:
        if not self.last_run:
            return "jamais"
        try:
            dt = datetime.fromisoformat(self.last_run)
            return dt.strftime("%d/%m %H:%M")
        except Exception:
            return self.last_run[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "schedule": self.schedule,
            "prompt": self.prompt, "session_name": self.session_name,
            "enabled": self.enabled, "last_run": self.last_run,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CronJob":
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            name=d.get("name", ""),
            schedule=d.get("schedule", "0 9 * * *"),
            prompt=d.get("prompt", ""),
            session_name=d.get("session_name", ""),
            enabled=d.get("enabled", True),
            last_run=d.get("last_run"),
            created_at=d.get("created_at", datetime.now().isoformat()),
        )


class CronManager:
    """CRUD for cron jobs; persists to ~/.pi/agent/crons.json."""

    def __init__(self, crons_file: Optional[Path] = None):
        self.crons_file = crons_file or CRONS_FILE
        self.crons_file.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[CronJob]:
        if not self.crons_file.exists():
            return []
        try:
            return [CronJob.from_dict(d)
                    for d in json.loads(self.crons_file.read_text(encoding="utf-8"))]
        except Exception:
            return []

    def _save(self, jobs: list[CronJob]) -> None:
        self.crons_file.write_text(
            json.dumps([j.to_dict() for j in jobs], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def list_jobs(self) -> list[CronJob]:
        return self._load()

    def create(self, name: str, schedule: str, prompt: str,
               session_name: str = "") -> CronJob:
        jobs = self._load()
        job = CronJob(id=str(uuid.uuid4())[:8], name=name,
                      schedule=schedule, prompt=prompt,
                      session_name=session_name)
        jobs.append(job)
        self._save(jobs)
        return job

    def delete(self, job_id: str) -> bool:
        jobs = self._load()
        new = [j for j in jobs if j.id != job_id]
        if len(new) < len(jobs):
            self._save(new)
            return True
        return False

    def toggle(self, job_id: str) -> Optional[CronJob]:
        jobs = self._load()
        for j in jobs:
            if j.id == job_id:
                j.enabled = not j.enabled
                self._save(jobs)
                return j
        return None

    def mark_ran(self, job_id: str) -> None:
        jobs = self._load()
        for j in jobs:
            if j.id == job_id:
                j.last_run = datetime.now().isoformat()
        self._save(jobs)


class CronRunner:
    """Background thread — fires cron jobs as scheduled.

    Calls on_fire(job) on the calling side; the callback must be
    thread-safe (use call_from_thread in Textual apps).
    """

    def __init__(self, manager: CronManager, pi_installed: bool,
                 on_fire: Optional[Callable[[CronJob], None]] = None):
        self._manager     = manager
        self._pi_ok       = pi_installed
        self._on_fire     = on_fire
        self._stop        = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not HAS_CRONITER:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="cron-runner")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            for job in self._manager.list_jobs():
                if not job.enabled or not job.prompt:
                    continue
                try:
                    cron = _croniter(job.schedule, now)
                    prev = cron.get_prev(datetime)
                    age  = (now - prev).total_seconds()
                    if age > 60:
                        continue
                    # Skip if already ran this minute
                    if job.last_run:
                        last_dt = datetime.fromisoformat(job.last_run)
                        if (now - last_dt).total_seconds() < 60:
                            continue
                    self._fire(job)
                except Exception:
                    pass
            self._stop.wait(30)

    def _fire(self, job: CronJob) -> None:
        self._manager.mark_ran(job.id)
        if self._on_fire:
            self._on_fire(job)
        if self._pi_ok:
            cmd = ["pi", "-p", job.prompt]
            if job.session_name:
                cmd += ["--session", job.session_name]
            try:
                subprocess.Popen(cmd,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                pass
