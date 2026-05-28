"""
Pi Agent UI — Claude Code-style terminal interface for Pi Agent.

Usage:
    python pi_ui.py

Features:
    - Chat sessions (JSONL, compatible with pi agent)
    - Skill management (read/write ~/.pi/agent/skills/)
    - Wraps the pi CLI when installed; falls back to local responses
    - Command history (↑/↓), Ctrl+N session, Ctrl+K skill, Ctrl+L clear
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Generator

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RichLog, Static, TextArea
from textual import events, work, on
from rich.markdown import Markdown
from rich.rule import Rule
from rich.text import Text

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pi_sessions import SessionManager, Session
from pi_skills import SkillManager, Skill


# ─────────────────────────────────────────────────────────────
# Agent backend
# ─────────────────────────────────────────────────────────────

def _pi_installed() -> bool:
    try:
        r = subprocess.run(["pi", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _call_pi(message: str, session_path: Optional[Path] = None) -> str:
    cmd = ["pi", "-p", message]
    if session_path:
        cmd += ["--session", str(session_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        return r.stdout.strip() or r.stderr.strip() or "(Pas de réponse)"
    except subprocess.TimeoutExpired:
        return "Délai dépassé (90 s)."
    except FileNotFoundError:
        return ""


def _local_response(message: str) -> str:
    q = message.lower()
    if any(w in q for w in ["bonjour", "salut", "hello", "hi", "coucou"]):
        return (
            "Bonjour! Je suis **Pi (π)**.\n\n"
            "Pi n'est pas encore installé. Pour l'installer :\n"
            "```bash\nnpm install -g @earendil-works/pi-coding-agent\n```\n\n"
            "En attendant, vous pouvez gérer vos **sessions** et **skills** depuis le panneau de gauche."
        )
    if any(w in q for w in ["skill", "compétence"]):
        return (
            "Les **skills** Pi sont des fichiers Markdown dans `~/.pi/agent/skills/`.\n\n"
            "```markdown\n# Mon Skill\nUtilise ce skill quand...\n\n## Steps\n1. ...\n```\n\n"
            "Utilisez **Ctrl+K** ou le bouton `+` dans le panneau Skills."
        )
    if any(w in q for w in ["session"]):
        return (
            "Les **sessions** Pi sont des fichiers JSONL dans `~/.pi/agent/sessions/`.\n\n"
            "Chaque message a un `id` et un `parent_id` pour former un arbre de conversation "
            "(branching).\n\nUtilisez **Ctrl+N** pour créer une nouvelle session."
        )
    return (
        f"*(Pi non installé)* Votre message : *\"{message}\"*\n\n"
        "Installez Pi pour activer le chat complet :\n"
        "```bash\nnpm install -g @earendil-works/pi-coding-agent\n```"
    )


# ─────────────────────────────────────────────────────────────
# Modal screens
# ─────────────────────────────────────────────────────────────

class NewSessionModal(ModalScreen[Optional[str]]):
    BINDINGS = [("escape", "dismiss(None)", "Annuler")]

    DEFAULT_CSS = """
    NewSessionModal {
        align: center middle;
    }
    NewSessionModal > Container {
        background: #161b22;
        border: round #388bfd;
        padding: 2 4;
        width: 60;
        height: auto;
    }
    NewSessionModal Label { color: #c9d1d9; margin-bottom: 1; }
    NewSessionModal Input { margin-bottom: 2; }
    NewSessionModal .row { layout: horizontal; height: auto; align: right middle; }
    NewSessionModal Button { margin-left: 2; }
    """

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Nouvelle session", markup=True)
            yield Label("Nom (optionnel) :")
            yield Input(placeholder="ex: Refactoring auth module", id="sname")
            with Container(classes="row"):
                yield Button("Annuler", id="cancel")
                yield Button("Créer", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#sname", Input).focus()

    @on(Input.Submitted, "#sname")
    def _submit(self, e: Input.Submitted) -> None:
        self.dismiss(e.value.strip() or None)

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.dismiss(self.query_one("#sname", Input).value.strip() or None)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class NewSkillModal(ModalScreen[Optional[Skill]]):
    BINDINGS = [("escape", "dismiss(None)", "Annuler")]

    DEFAULT_CSS = """
    NewSkillModal {
        align: center middle;
    }
    NewSkillModal > Container {
        background: #161b22;
        border: round #238636;
        padding: 2 4;
        width: 64;
        height: auto;
    }
    NewSkillModal Label { color: #c9d1d9; margin-bottom: 1; }
    NewSkillModal Input { margin-bottom: 2; }
    NewSkillModal .row { layout: horizontal; height: auto; align: right middle; }
    NewSkillModal Button { margin-left: 2; }
    """

    def __init__(self, skill_manager: SkillManager) -> None:
        super().__init__()
        self._sm = skill_manager

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Nouveau skill")
            yield Label("Nom du skill :")
            yield Input(placeholder="ex: refactor-python", id="sname")
            yield Label("Description :")
            yield Input(placeholder="ex: refactoriser du code Python", id="sdesc")
            with Container(classes="row"):
                yield Button("Annuler", id="cancel")
                yield Button("Créer", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#sname", Input).focus()

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        name = self.query_one("#sname", Input).value.strip()
        desc = self.query_one("#sdesc", Input).value.strip()
        if name:
            self.dismiss(self._sm.create(name, description=desc))
        else:
            self.query_one("#sname", Input).focus()

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class SkillEditorModal(ModalScreen[Optional[str]]):
    BINDINGS = [
        ("escape", "dismiss(None)", "Fermer"),
        ("ctrl+s", "save", "Sauvegarder"),
    ]

    DEFAULT_CSS = """
    SkillEditorModal {
        align: center middle;
    }
    SkillEditorModal > Container {
        background: #161b22;
        border: round #238636;
        padding: 1 2;
        width: 90%;
        height: 80%;
    }
    SkillEditorModal Label { color: #8b949e; height: 1; }
    SkillEditorModal TextArea { height: 1fr; margin: 1 0; }
    SkillEditorModal .row { layout: horizontal; height: auto; align: right middle; }
    SkillEditorModal Button { margin-left: 2; }
    """

    def __init__(self, skill: Skill) -> None:
        super().__init__()
        self.skill = skill

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(f"  {self.skill.path}")
            yield TextArea(self.skill.content(), language="markdown", id="editor")
            with Container(classes="row"):
                yield Button("Fermer", id="close")
                yield Button("Sauvegarder  Ctrl+S", variant="primary", id="save")

    def action_save(self) -> None:
        content = self.query_one("#editor", TextArea).text
        self.skill.save(content)
        self.dismiss(content)

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.dismiss(None)


# ─────────────────────────────────────────────────────────────
# Main application
# ─────────────────────────────────────────────────────────────

WELCOME = """\
# π  Pi Agent

Agent IA open-source pour le développement logiciel.
[earendil-works/pi](https://github.com/earendil-works/pi)

**Skills** · `~/.pi/agent/skills/`
**Sessions** · `~/.pi/agent/sessions/`

Tapez un message, ou utilisez les panneaux à gauche.
"""

CSS = """
Screen {
    background: #0d1117;
    layers: default overlay;
}

/* ── Top bar ─────────────────────────────── */
#topbar {
    dock: top;
    height: 3;
    background: #161b22;
    border-bottom: solid #21262d;
    layout: horizontal;
    padding: 0 2;
    align: left middle;
}
#topbar-title {
    width: 1fr;
    color: #e6edf3;
    text-style: bold;
    content-align: left middle;
}
#topbar-status {
    width: auto;
    color: #3fb950;
    content-align: right middle;
}

/* ── Footer ──────────────────────────────── */
#footer {
    dock: bottom;
    height: 1;
    background: #161b22;
    color: #8b949e;
    padding: 0 2;
    border-top: solid #21262d;
}

/* ── Sidebar ─────────────────────────────── */
#sidebar {
    dock: left;
    width: 28;
    background: #0d1117;
    border-right: solid #21262d;
    padding: 0;
    overflow-y: auto;
}
.sec-title {
    color: #8b949e;
    text-style: bold;
    padding: 1 2 0 2;
    height: 2;
    content-align: left bottom;
}
.add-btn {
    width: 100%;
    height: 2;
    background: transparent;
    color: #58a6ff;
    border: none;
    padding: 0 2;
    content-align: left middle;
    text-align: left;
}
.add-btn:hover { background: #21262d; }
.add-btn:focus { border: none; }

.s-item {
    width: 100%;
    height: 2;
    background: transparent;
    color: #c9d1d9;
    border: none;
    padding: 0 3;
    text-align: left;
    content-align: left middle;
}
.s-item:hover { background: #21262d; }
.s-item:focus { border: none; }
.s-item.active {
    background: #1f3a5f;
    color: #58a6ff;
}

#skill-search {
    margin: 0 2;
    height: 2;
    background: #0d1117;
    color: #c9d1d9;
    border: solid #30363d;
}
#skill-search:focus { border: solid #388bfd; }

/* ── Main area ───────────────────────────── */
#main {
    background: #0d1117;
    layout: vertical;
}
#chat-log {
    height: 1fr;
    background: #0d1117;
    padding: 1 3;
}
#inputbar {
    height: 5;
    background: #161b22;
    border-top: solid #21262d;
    padding: 1 2;
}
#chat-input {
    background: #0d1117;
    color: #e6edf3;
    border: solid #30363d;
    height: 3;
}
#chat-input:focus { border: solid #388bfd; }
"""


class PiAgentApp(App[None]):
    """Claude Code-style TUI for Pi Agent."""

    DEFAULT_CSS = CSS
    BINDINGS = [
        Binding("ctrl+n", "new_session", "Nouvelle session"),
        Binding("ctrl+k", "new_skill", "Nouveau skill"),
        Binding("ctrl+l", "clear_chat", "Effacer"),
        Binding("ctrl+c", "quit", "Quitter"),
    ]

    current_session: reactive[Optional[Session]] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self.session_manager = SessionManager()
        self.skill_manager = SkillManager()
        self._sessions: list[Session] = []
        self._skills: list[Skill] = []
        self._cmd_history: list[str] = []
        self._hist_idx: int = -1
        self._skill_query: str = ""
        self._pi_ok: bool = False

    # ── Compose ──────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Container(id="topbar"):
            yield Label("  π  Pi Agent", id="topbar-title")
            yield Label("● démarrage…", id="topbar-status")

        with Container(id="sidebar"):
            yield Static("SESSIONS", classes="sec-title")
            yield Button("＋  Nouvelle session", id="btn-new-session", classes="add-btn")
            yield Container(id="sessions-list")

            yield Static("SKILLS", classes="sec-title")
            yield Input(placeholder="  Rechercher…", id="skill-search")
            yield Button("＋  Nouveau skill", id="btn-new-skill", classes="add-btn")
            yield Container(id="skills-list")

        with Vertical(id="main"):
            yield RichLog(id="chat-log", markup=True, highlight=True,
                          wrap=True, auto_scroll=True)
            with Container(id="inputbar"):
                yield Input(
                    placeholder="Message (pi -p …) — ↑↓ historique",
                    id="chat-input",
                )

        yield Static(
            "Ctrl+N Session  │  Ctrl+K Skill  │  Ctrl+L Effacer  │  Ctrl+C Quitter",
            id="footer",
        )

    def on_mount(self) -> None:
        self._pi_ok = _pi_installed()
        self._refresh_sessions()
        self._refresh_skills()

        log = self.query_one("#chat-log", RichLog)
        log.write(Markdown(WELCOME))
        if not self._pi_ok:
            log.write(Markdown(
                "> **Pi non installé** — sessions et skills actifs, chat local uniquement.  \n"
                "> `npm install -g @earendil-works/pi-coding-agent`"
            ))
            log.write("")

        self.query_one("#topbar-status", Label).update(
            "● pi ready" if self._pi_ok else "[yellow]● pi non installé[/yellow]"
        )
        self.query_one("#chat-input", Input).focus()

    # ── Sidebar helpers ───────────────────────────────────────

    def _refresh_sessions(self) -> None:
        self._sessions = self.session_manager.list_sessions()
        container = self.query_one("#sessions-list", Container)
        container.remove_children()
        for s in self._sessions:
            active = self.current_session and self.current_session.id == s.id
            classes = "s-item" + (" active" if active else "")
            label = f"{'● ' if active else '  '}{s.display_name[:20]}"
            btn = Button(label, id=f"sess-{s.id}", classes=classes)
            container.mount(btn)

    def _refresh_skills(self) -> None:
        if self._skill_query:
            self._skills = self.skill_manager.search(self._skill_query)
        else:
            self._skills = self.skill_manager.list_skills()
        container = self.query_one("#skills-list", Container)
        container.remove_children()
        for skill in self._skills:
            btn = Button(f"  {skill.display_name[:22]}", id=f"skill-{skill.name}", classes="s-item")
            container.mount(btn)

    def _switch_session(self, session: Session) -> None:
        self.current_session = session
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write(Markdown(f"**{session.display_name}** · {session.message_count} messages"))
        log.write(Rule())
        for msg in session.messages:
            self._render_message(msg.role, msg.content, log)
        self._refresh_sessions()

    def _render_message(self, role: str, content: str,
                        log: Optional[RichLog] = None) -> None:
        if log is None:
            log = self.query_one("#chat-log", RichLog)
        log.write("")
        if role == "user":
            t = Text()
            t.append(" you ", style="bold black on #388bfd")
            t.append(f"  {content}", style="bold #e6edf3")
            log.write(t)
        else:
            t = Text()
            t.append("  π  ", style="bold black on #238636")
            log.write(t)
            log.write(Markdown(content))
        log.write("")

    # ── Actions ───────────────────────────────────────────────

    def action_new_session(self) -> None:
        def _done(name: Optional[str]) -> None:
            if name is not None:
                s = self.session_manager.create(name or "")
                self._switch_session(s)
                self.query_one("#chat-log", RichLog).write(
                    Markdown(f"*Session **{s.display_name}** créée.*")
                )
        self.push_screen(NewSessionModal(), _done)

    def action_new_skill(self) -> None:
        def _created(skill: Optional[Skill]) -> None:
            if skill:
                self._refresh_skills()
                def _edited(content: Optional[str]) -> None:
                    if content is not None:
                        self.query_one("#chat-log", RichLog).write(
                            Markdown(f"*Skill **{skill.display_name}** sauvegardé.*")
                        )
                self.push_screen(SkillEditorModal(skill), _edited)
        self.push_screen(NewSkillModal(self.skill_manager), _created)

    def action_clear_chat(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write(Markdown("*Historique effacé.*"))

    # ── Button routing ────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""

        if bid == "btn-new-session":
            self.action_new_session()
        elif bid == "btn-new-skill":
            self.action_new_skill()
        elif bid.startswith("sess-"):
            sid = bid[5:]
            sess = next((s for s in self._sessions if s.id == sid), None)
            if sess:
                self._switch_session(sess)
        elif bid.startswith("skill-"):
            skill_name = bid[6:]
            skill = next((s for s in self._skills if s.name == skill_name), None)
            if skill:
                def _edited(content: Optional[str]) -> None:
                    if content is not None:
                        self.query_one("#chat-log", RichLog).write(
                            Markdown(f"*Skill **{skill.display_name}** sauvegardé.*")
                        )
                self.push_screen(SkillEditorModal(skill), _edited)

    # ── Search ────────────────────────────────────────────────

    @on(Input.Changed, "#skill-search")
    def _skill_search_changed(self, event: Input.Changed) -> None:
        self._skill_query = event.value.strip()
        self._refresh_skills()

    # ── Chat input ────────────────────────────────────────────

    @on(Input.Submitted, "#chat-input")
    def _on_chat_submit(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message:
            return
        self.query_one("#chat-input", Input).value = ""
        self._cmd_history.insert(0, message)
        self._hist_idx = -1

        if not self.current_session:
            self.current_session = self.session_manager.create()
            self._refresh_sessions()

        self.current_session.add_message("user", message)
        self._render_message("user", message)
        self._process(message, self.current_session)

    def on_key(self, event: events.Key) -> None:
        inp = self.query_one("#chat-input", Input)
        if self.focused is not inp:
            return
        if event.key == "up":
            if self._cmd_history and self._hist_idx < len(self._cmd_history) - 1:
                self._hist_idx += 1
                inp.value = self._cmd_history[self._hist_idx]
                inp.cursor_position = len(inp.value)
            event.prevent_default()
        elif event.key == "down":
            if self._hist_idx > 0:
                self._hist_idx -= 1
                inp.value = self._cmd_history[self._hist_idx]
                inp.cursor_position = len(inp.value)
            elif self._hist_idx == 0:
                self._hist_idx = -1
                inp.value = ""
            event.prevent_default()

    # ── Worker ────────────────────────────────────────────────

    @work(thread=True)
    def _process(self, message: str, session: Session) -> None:
        def _log(content) -> None:
            self.call_from_thread(
                lambda c=content: self.query_one("#chat-log", RichLog).write(c)
            )
        def _status(text: str) -> None:
            self.call_from_thread(
                lambda t=text: self.query_one("#topbar-status", Label).update(t)
            )

        _status("[yellow]● thinking…[/yellow]")

        prefix = Text()
        prefix.append("  π  ", style="bold black on #238636")
        _log("")
        _log(prefix)

        if self._pi_ok:
            response = _call_pi(message, session_path=session.path)
            if not response:
                response = "(Pi n'a pas renvoyé de réponse)"
        else:
            response = _local_response(message)

        _log(Markdown(response))
        _log("")

        self.call_from_thread(lambda: session.add_message("assistant", response))
        self.call_from_thread(self._refresh_sessions)
        _status("● pi ready" if self._pi_ok else "[yellow]● pi non installé[/yellow]")


def main() -> None:
    PiAgentApp().run()


if __name__ == "__main__":
    main()
