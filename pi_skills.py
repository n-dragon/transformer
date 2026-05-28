"""Skill management — reads/writes ~/.pi/agent/skills/*.md"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

GLOBAL_SKILLS_DIR = Path.home() / ".pi" / "agent" / "skills"
LOCAL_DIRS = [Path(".agents") / "skills", Path(".pi") / "skills"]

SKILL_TEMPLATE = """\
# {name}

Use this skill when the user asks to {description}.

## Steps

1. First step
2. Second step
3. Third step
"""


@dataclass
class Skill:
    name: str
    path: Path
    is_global: bool = True

    @property
    def display_name(self) -> str:
        return self.name.replace("-", " ").replace("_", " ").title()

    @property
    def first_line(self) -> str:
        try:
            lines = [l.strip() for l in self.path.read_text().splitlines() if l.strip()]
            return lines[1][:60] if len(lines) > 1 else ""
        except Exception:
            return ""

    def content(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def save(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")


class SkillManager:
    def __init__(self):
        GLOBAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    def _dirs(self) -> list[tuple[Path, bool]]:
        result: list[tuple[Path, bool]] = [(GLOBAL_SKILLS_DIR, True)]
        for d in LOCAL_DIRS:
            if d.exists():
                result.append((d, False))
        return result

    def list_skills(self) -> list[Skill]:
        seen: set[str] = set()
        skills: list[Skill] = []
        for directory, is_global in self._dirs():
            for path in sorted(directory.glob("*.md")):
                if path.stem not in seen:
                    seen.add(path.stem)
                    skills.append(Skill(name=path.stem, path=path, is_global=is_global))
            for path in sorted(directory.glob("*/SKILL.md")):
                n = path.parent.name
                if n not in seen:
                    seen.add(n)
                    skills.append(Skill(name=n, path=path, is_global=is_global))
        return skills

    def search(self, query: str) -> list[Skill]:
        q = query.lower()
        return [s for s in self.list_skills()
                if q in s.name.lower() or q in s.first_line.lower()]

    def create(self, name: str, description: str = "", content: str = "",
               global_skill: bool = True) -> Skill:
        d = GLOBAL_SKILLS_DIR if global_skill else LOCAL_DIRS[0]
        d.mkdir(parents=True, exist_ok=True)
        safe = name.lower().replace(" ", "-").replace("_", "-")
        path = d / f"{safe}.md"
        body = content or SKILL_TEMPLATE.format(
            name=name, description=description or name.lower()
        )
        path.write_text(body, encoding="utf-8")
        return Skill(name=safe, path=path, is_global=global_skill)

    def delete(self, skill: Skill) -> bool:
        try:
            skill.path.unlink()
            return True
        except Exception:
            return False
