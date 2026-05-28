"""
Pi Agent UI — Claude Code-style terminal interface.

Features:
  • Sessions      Ctrl+N  create / switch / persist (JSONL)
  • Skills        Ctrl+K  create / search / edit (Markdown)
  • MCPs          Ctrl+M  add / toggle / remove per-user + system
  • Crons         Ctrl+R  schedule recurring pi sessions
  • In-chat cmds  /skills /mcps /crons /help

Run:  python pi_ui.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Input, Label, RichLog,
    Select, Static, TabbedContent, TabPane, TextArea,
)
from textual import events, work, on
from rich.markdown import Markdown
from rich.rule import Rule
from rich.text import Text

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pi_sessions import SessionManager, Session
from pi_skills   import SkillManager, Skill
from pi_mcps     import MCPManager, MCPServer
from pi_crons    import CronManager, CronJob, CronRunner, PRESETS, HAS_CRONITER


# ─────────────────────────────────────────────────────────────────────────────
# Agent backend helpers
# ─────────────────────────────────────────────────────────────────────────────

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
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return r.stdout.strip() or r.stderr.strip() or "(Pas de réponse)"
    except subprocess.TimeoutExpired:
        return "Délai dépassé (120 s)."
    except FileNotFoundError:
        return ""


def _local_reply(message: str, skills: list[Skill],
                 mcps: list[MCPServer], crons: list[CronJob]) -> str:
    q = message.lower()
    if any(w in q for w in ["bonjour", "salut", "hello", "hi"]):
        return (
            "Bonjour ! Je suis **Pi (π)**.\n\n"
            "Pi n'est pas encore installé. Pour l'activer :\n"
            "```bash\nnpm install -g @earendil-works/pi-coding-agent\n```\n\n"
            "Sessions, Skills, MCPs et Crons sont gérés localement."
        )
    return (
        f"*(pi non installé)* Message : *\"{message}\"*\n\n"
        "Installez Pi pour activer le vrai chat :\n"
        "```bash\nnpm install -g @earendil-works/pi-coding-agent\n```"
    )


# ─────────────────────────────────────────────────────────────────────────────
# In-chat command handling (intercepts /skills /mcps /crons /help)
# ─────────────────────────────────────────────────────────────────────────────

def _handle_slash(cmd: str, skills: list[Skill],
                  mcps: list[MCPServer], crons: list[CronJob]) -> Optional[str]:
    """Return a markdown string if the command is handled locally, else None."""
    c = cmd.strip().lower()

    if c in ("/help", "/aide"):
        return (
            "**Commandes disponibles**\n\n"
            "| Commande | Description |\n"
            "|---|---|\n"
            "| `/skills` | Lister les skills disponibles |\n"
            "| `/skill:name` | Lancer un skill |\n"
            "| `/mcps` | Lister les serveurs MCP |\n"
            "| `/crons` | Lister les crons planifiés |\n"
            "| `/help` | Cette aide |\n\n"
            "Gérez Sessions, Skills, MCPs et Crons dans le panneau de gauche."
        )

    if c == "/skills":
        if not skills:
            return "*Aucun skill trouvé dans `~/.pi/agent/skills/`.*"
        lines = ["**Skills disponibles**\n"]
        for s in skills:
            badge = "[global]" if s.is_global else "[local]"
            lines.append(f"- `/skill:{s.name}` {badge}  \n  {s.first_line}")
        return "\n".join(lines)

    if c == "/mcps":
        if not mcps:
            return "*Aucun serveur MCP configuré.*"
        lines = ["**Serveurs MCP**\n"]
        for m in mcps:
            status = "●" if m.enabled else "○"
            badge  = " [sys]" if m.system else ""
            lines.append(f"- {status} `{m.name}`{badge}  \n  `{m.summary}`")
        return "\n".join(lines)

    if c == "/crons":
        if not crons:
            return "*Aucun cron planifié.*"
        lines = ["**Crons planifiés**\n"]
        for j in crons:
            status = "●" if j.enabled else "○"
            lines.append(
                f"- {status} **{j.name}**  \n"
                f"  {j.schedule_label} — prochain : {j.next_run_label}"
            )
        return "\n".join(lines)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Modal: New Session
# ─────────────────────────────────────────────────────────────────────────────

class NewSessionModal(ModalScreen[Optional[str]]):
    BINDINGS = [("escape", "dismiss(None)", "Annuler")]
    DEFAULT_CSS = """
    NewSessionModal { align: center middle; }
    NewSessionModal > Container {
        background: #161b22; border: round #388bfd;
        padding: 2 4; width: 62; height: auto;
    }
    NewSessionModal Label  { color: #c9d1d9; margin-bottom: 1; }
    NewSessionModal Input  { margin-bottom: 2; }
    NewSessionModal .row   { layout: horizontal; height: auto; align: right middle; }
    NewSessionModal Button { margin-left: 2; }
    """

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Nouvelle session")
            yield Label("Nom (optionnel) :")
            yield Input(placeholder="ex: Refactoring auth module", id="name")
            with Container(classes="row"):
                yield Button("Annuler", id="cancel")
                yield Button("Créer", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    @on(Input.Submitted, "#name")
    def _submit(self, e: Input.Submitted) -> None:
        self.dismiss(e.value.strip() or None)

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.dismiss(self.query_one("#name", Input).value.strip() or None)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


# ─────────────────────────────────────────────────────────────────────────────
# Modal: New + Edit Skill
# ─────────────────────────────────────────────────────────────────────────────

class NewSkillModal(ModalScreen[Optional[Skill]]):
    BINDINGS = [("escape", "dismiss(None)", "Annuler")]
    DEFAULT_CSS = """
    NewSkillModal { align: center middle; }
    NewSkillModal > Container {
        background: #161b22; border: round #238636;
        padding: 2 4; width: 64; height: auto;
    }
    NewSkillModal Label  { color: #c9d1d9; margin-bottom: 1; }
    NewSkillModal Input  { margin-bottom: 2; }
    NewSkillModal .row   { layout: horizontal; height: auto; align: right middle; }
    NewSkillModal Button { margin-left: 2; }
    """

    def __init__(self, sm: SkillManager) -> None:
        super().__init__()
        self._sm = sm

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Nouveau skill")
            yield Label("Nom :")
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

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class SkillEditorModal(ModalScreen[Optional[str]]):
    BINDINGS = [("escape", "dismiss(None)", "Fermer"), ("ctrl+s", "save", "Sauv.")]
    DEFAULT_CSS = """
    SkillEditorModal { align: center middle; }
    SkillEditorModal > Container {
        background: #161b22; border: round #238636;
        padding: 1 2; width: 90%; height: 80%;
    }
    SkillEditorModal Label    { color: #8b949e; height: 1; }
    SkillEditorModal TextArea { height: 1fr; margin: 1 0; }
    SkillEditorModal .row     { layout: horizontal; height: auto; align: right middle; }
    SkillEditorModal Button   { margin-left: 2; }
    """

    def __init__(self, skill: Skill) -> None:
        super().__init__()
        self.skill = skill

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(f"  {self.skill.path}")
            yield TextArea(self.skill.content(), language="markdown", id="ed")
            with Container(classes="row"):
                yield Button("Fermer", id="close")
                yield Button("Sauvegarder  Ctrl+S", variant="primary", id="save")

    def action_save(self) -> None:
        content = self.query_one("#ed", TextArea).text
        self.skill.save(content)
        self.dismiss(content)

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.dismiss(None)


# ─────────────────────────────────────────────────────────────────────────────
# Modal: New MCP
# ─────────────────────────────────────────────────────────────────────────────

class NewMCPModal(ModalScreen[Optional[MCPServer]]):
    BINDINGS = [("escape", "dismiss(None)", "Annuler")]
    DEFAULT_CSS = """
    NewMCPModal { align: center middle; }
    NewMCPModal > Container {
        background: #161b22; border: round #8957e5;
        padding: 2 4; width: 68; height: auto;
    }
    NewMCPModal Label  { color: #c9d1d9; margin-bottom: 1; }
    NewMCPModal Input  { margin-bottom: 2; }
    NewMCPModal Static { color: #8b949e; margin-bottom: 1; }
    NewMCPModal .row   { layout: horizontal; height: auto; align: right middle; }
    NewMCPModal Button { margin-left: 2; }
    """

    def __init__(self, mm: MCPManager) -> None:
        super().__init__()
        self._mm = mm

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Nouveau serveur MCP")
            yield Static("Les MCPs sont partagés pour tous vos projets pi.")
            yield Label("Nom :")
            yield Input(placeholder="ex: filesystem", id="mname")
            yield Label("Commande :")
            yield Input(placeholder="ex: npx", id="mcmd")
            yield Label("Arguments (séparés par des espaces) :")
            yield Input(placeholder="ex: -y @modelcontextprotocol/server-filesystem /tmp", id="margs")
            yield Label("Variables d'env (KEY=val KEY2=val2, optionnel) :")
            yield Input(placeholder="ex: API_KEY=secret", id="menv")
            with Container(classes="row"):
                yield Button("Annuler", id="cancel")
                yield Button("Ajouter", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#mname", Input).focus()

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        name = self.query_one("#mname", Input).value.strip()
        cmd  = self.query_one("#mcmd",  Input).value.strip()
        args_raw = self.query_one("#margs", Input).value.strip()
        env_raw  = self.query_one("#menv",  Input).value.strip()

        if not name or not cmd:
            self.query_one("#mname" if not name else "#mcmd", Input).focus()
            return

        args = args_raw.split() if args_raw else []
        env: dict[str, str] = {}
        for pair in env_raw.split():
            if "=" in pair:
                k, _, v = pair.partition("=")
                env[k] = v

        self.dismiss(self._mm.add(name, cmd, args=args, env=env))

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


# ─────────────────────────────────────────────────────────────────────────────
# Modal: New Cron
# ─────────────────────────────────────────────────────────────────────────────

_PRESET_OPTIONS = [(label, expr) for label, expr in PRESETS]


class NewCronModal(ModalScreen[Optional[CronJob]]):
    BINDINGS = [("escape", "dismiss(None)", "Annuler")]
    DEFAULT_CSS = """
    NewCronModal { align: center middle; }
    NewCronModal > Container {
        background: #161b22; border: round #d29922;
        padding: 2 4; width: 70; height: auto;
    }
    NewCronModal Label  { color: #c9d1d9; margin-bottom: 1; }
    NewCronModal Input  { margin-bottom: 2; }
    NewCronModal Select { margin-bottom: 1; }
    NewCronModal Static { color: #8b949e; height: 1; margin-bottom: 1; }
    NewCronModal .row   { layout: horizontal; height: auto; align: right middle; }
    NewCronModal Button { margin-left: 2; }
    """

    def __init__(self, cm: CronManager) -> None:
        super().__init__()
        self._cm = cm
        self._custom_mode = False

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Nouveau cron planifié")
            yield Label("Nom :")
            yield Input(placeholder="ex: Standup quotidien", id="cname")
            yield Label("Fréquence :")
            opts = [(label, label) for label, _ in _PRESET_OPTIONS]
            yield Select(opts, value=opts[0][1], id="cpreset")
            yield Label("Expression cron (si personnalisé) :")
            yield Input(placeholder="ex: 0 9 * * 1-5", id="cexpr", disabled=True)
            yield Static("min heure jour mois jour_semaine")
            yield Label("Prompt à envoyer à Pi :")
            yield Input(placeholder="ex: Génère le rapport de standup", id="cprompt")
            yield Label("Nom de session (optionnel) :")
            yield Input(placeholder="ex: Standup", id="csession")
            with Container(classes="row"):
                yield Button("Annuler", id="cancel")
                yield Button("Créer", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#cname", Input).focus()

    @on(Select.Changed, "#cpreset")
    def _preset_changed(self, e: Select.Changed) -> None:
        label = str(e.value)
        custom = (label == "Personnalisé…")
        expr_input = self.query_one("#cexpr", Input)
        expr_input.disabled = not custom
        if not custom:
            for lbl, expr in _PRESET_OPTIONS:
                if lbl == label:
                    expr_input.value = expr
                    break

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        name    = self.query_one("#cname",    Input).value.strip()
        prompt  = self.query_one("#cprompt",  Input).value.strip()
        expr    = self.query_one("#cexpr",    Input).value.strip()
        session = self.query_one("#csession", Input).value.strip()

        if not name or not prompt:
            self.query_one("#cname" if not name else "#cprompt", Input).focus()
            return

        # Resolve schedule from preset if not custom
        if not expr:
            preset_label = str(self.query_one("#cpreset", Select).value)
            for lbl, e in _PRESET_OPTIONS:
                if lbl == preset_label and e:
                    expr = e
                    break
        if not expr:
            expr = "0 9 * * *"

        self.dismiss(self._cm.create(name, expr, prompt, session_name=session))

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

APP_CSS = """
Screen { background: #0d1117; }

/* ── Topbar ────────────────────────────────────── */
#topbar {
    dock: top; height: 3;
    background: #161b22;
    border-bottom: solid #21262d;
    layout: horizontal; padding: 0 2;
    align: left middle;
}
#topbar-title  { width: 1fr; color: #e6edf3; text-style: bold; }
#topbar-status { width: auto; color: #3fb950; }

/* ── Footer ─────────────────────────────────────── */
#footer {
    dock: bottom; height: 1;
    background: #161b22;
    border-top: solid #21262d;
    color: #8b949e; padding: 0 2;
}

/* ── Sidebar ────────────────────────────────────── */
#sidebar {
    dock: left; width: 30;
    background: #0d1117;
    border-right: solid #21262d;
}
TabbedContent { height: 1fr; }
TabbedContent TabPane {
    padding: 0;
    background: #0d1117;
}

.add-btn {
    width: 100%; height: 2;
    background: transparent; border: none;
    color: #58a6ff; text-align: left; padding: 0 2;
}
.add-btn:hover  { background: #21262d; }
.add-btn:focus  { border: none; }

.s-item {
    width: 100%; height: 2;
    background: transparent; border: none;
    color: #c9d1d9; text-align: left; padding: 0 3;
}
.s-item:hover  { background: #21262d; }
.s-item:focus  { border: none; }
.s-item.active { background: #1f3a5f; color: #58a6ff; }

.s-item-dim {
    width: 100%; height: 1;
    background: transparent; border: none;
    color: #8b949e; text-align: left; padding: 0 4;
    text-style: italic;
}
.s-item-dim:hover { background: #21262d; }
.s-item-dim:focus { border: none; }

#skill-search {
    margin: 0 2 0 2; height: 2;
    background: #0d1117; color: #c9d1d9;
    border: solid #30363d;
}
#skill-search:focus { border: solid #388bfd; }

/* ── Main ───────────────────────────────────────── */
#main { background: #0d1117; layout: vertical; }

#chat-log {
    height: 1fr;
    background: #0d1117;
    padding: 1 3;
}

#inputbar {
    height: 5; background: #161b22;
    border-top: solid #21262d; padding: 1 2;
}
#chat-input {
    background: #0d1117; color: #e6edf3;
    border: solid #30363d; height: 3;
}
#chat-input:focus { border: solid #388bfd; }
"""

WELCOME = """\
# π  Pi Agent

Agent IA open-source — [earendil-works/pi](https://github.com/earendil-works/pi)

**Sessions** · JSONL persistantes (`~/.pi/agent/sessions/`)
**Skills** · Markdown réutilisables (`~/.pi/agent/skills/`)
**MCPs** · Serveurs Model Context Protocol
**Crons** · Sessions planifiées automatiques

Commandes chat : `/skills`  `/mcps`  `/crons`  `/help`
"""


# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────

class PiAgentApp(App[None]):
    """Claude Code-style TUI for Pi Agent."""

    DEFAULT_CSS = APP_CSS

    BINDINGS = [
        Binding("ctrl+n", "new_session", "Session"),
        Binding("ctrl+k", "new_skill",   "Skill"),
        Binding("ctrl+m", "new_mcp",     "MCP"),
        Binding("ctrl+r", "new_cron",    "Cron"),
        Binding("ctrl+l", "clear_chat",  "Effacer"),
        Binding("ctrl+c", "quit",        "Quitter"),
    ]

    current_session: reactive[Optional[Session]] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self.session_manager = SessionManager()
        self.skill_manager   = SkillManager()
        self.mcp_manager     = MCPManager()
        self.cron_manager    = CronManager()
        self._sessions: list[Session]   = []
        self._skills:   list[Skill]     = []
        self._mcps:     list[MCPServer] = []
        self._crons:    list[CronJob]   = []
        self._cmd_history: list[str] = []
        self._hist_idx:    int = -1
        self._skill_q:     str = ""
        self._pi_ok:       bool = False
        self._cron_runner: Optional[CronRunner] = None

    # ── Layout ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # Top bar
        with Container(id="topbar"):
            yield Label("  π  Pi Agent", id="topbar-title")
            yield Label("● démarrage…", id="topbar-status")

        # Sidebar with 4 tabs
        with Container(id="sidebar"):
            with TabbedContent(id="sidebar-tabs"):

                with TabPane("Sessions", id="tab-sessions"):
                    yield Button("＋  Nouvelle session",
                                 id="btn-new-session", classes="add-btn")
                    yield Container(id="sessions-list")

                with TabPane("Skills", id="tab-skills"):
                    yield Input(placeholder="  Rechercher…", id="skill-search")
                    yield Button("＋  Nouveau skill",
                                 id="btn-new-skill", classes="add-btn")
                    yield Container(id="skills-list")

                with TabPane("MCPs", id="tab-mcps"):
                    yield Button("＋  Nouveau MCP",
                                 id="btn-new-mcp", classes="add-btn")
                    yield Container(id="mcps-list")

                with TabPane("Crons", id="tab-crons"):
                    yield Button("＋  Nouveau cron",
                                 id="btn-new-cron", classes="add-btn")
                    yield Container(id="crons-list")

        # Main chat area
        with Vertical(id="main"):
            yield RichLog(id="chat-log", markup=True, highlight=True,
                          wrap=True, auto_scroll=True)
            with Container(id="inputbar"):
                yield Input(
                    placeholder="Message (/help pour les commandes) — ↑↓ historique",
                    id="chat-input",
                )

        yield Static(
            "^N Session  ^K Skill  ^M MCP  ^R Cron  ^L Effacer  ^C Quitter",
            id="footer",
        )

    # ── Mount ────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._pi_ok = _pi_installed()
        self._refresh_all()

        log = self.query_one("#chat-log", RichLog)
        log.write(Markdown(WELCOME))
        if not self._pi_ok:
            log.write(Markdown(
                "> **Pi non installé** — chat local uniquement.  \n"
                "> `npm install -g @earendil-works/pi-coding-agent`"
            ))
        log.write("")

        status = self.query_one("#topbar-status", Label)
        status.update("● pi ready" if self._pi_ok else "[yellow]● pi non installé[/yellow]")

        # Start cron runner
        self._cron_runner = CronRunner(
            manager=self.cron_manager,
            pi_installed=self._pi_ok,
            on_fire=self._on_cron_fired,
        )
        self._cron_runner.start()

        self.query_one("#chat-input", Input).focus()

    def on_unmount(self) -> None:
        if self._cron_runner:
            self._cron_runner.stop()

    # ── Refresh helpers ──────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        self._refresh_sessions()
        self._refresh_skills()
        self._refresh_mcps()
        self._refresh_crons()

    def _refresh_sessions(self) -> None:
        self._sessions = self.session_manager.list_sessions()
        c = self.query_one("#sessions-list", Container)
        c.remove_children()
        for s in self._sessions:
            active = self.current_session and self.current_session.id == s.id
            cls   = "s-item" + (" active" if active else "")
            label = f"{'● ' if active else '  '}{s.display_name[:21]}"
            c.mount(Button(label, id=f"sess-{s.id}", classes=cls))

    def _refresh_skills(self) -> None:
        self._skills = (self.skill_manager.search(self._skill_q)
                        if self._skill_q else self.skill_manager.list_skills())
        c = self.query_one("#skills-list", Container)
        c.remove_children()
        for sk in self._skills:
            badge = "" if sk.is_global else " [local]"
            c.mount(Button(f"  {sk.display_name[:20]}{badge}",
                           id=f"skill-{sk.name}", classes="s-item"))

    def _refresh_mcps(self) -> None:
        self._mcps = self.mcp_manager.list_servers()
        c = self.query_one("#mcps-list", Container)
        c.remove_children()
        for m in self._mcps:
            badge  = " [sys]" if m.system else ""
            dot    = "●" if m.enabled else "○"
            label  = f"  {dot} {m.name[:16]}{badge}"
            c.mount(Button(label, id=f"mcp-{m.id}", classes="s-item"))
            if not m.system:
                c.mount(Button(f"     {m.summary[:24]}",
                               id=f"mcptog-{m.id}", classes="s-item-dim"))

    def _refresh_crons(self) -> None:
        self._crons = self.cron_manager.list_jobs()
        c = self.query_one("#crons-list", Container)
        c.remove_children()
        for j in self._crons:
            dot   = "●" if j.enabled else "○"
            label = f"  {dot} {j.name[:20]}"
            c.mount(Button(label, id=f"cron-{j.id}", classes="s-item"))
            c.mount(Button(f"     {j.schedule_label[:24]}",
                           id=f"croninfo-{j.id}", classes="s-item-dim"))

    # ── Session / chat helpers ───────────────────────────────────────────────

    def _switch_session(self, session: Session) -> None:
        self.current_session = session
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write(Markdown(f"**{session.display_name}** · {session.message_count} messages"))
        log.write(Rule())
        for msg in session.messages:
            self._render_msg(msg.role, msg.content, log)
        self._refresh_sessions()

    def _render_msg(self, role: str, content: str,
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

    # ── Actions ──────────────────────────────────────────────────────────────

    def action_new_session(self) -> None:
        def _done(name: Optional[str]) -> None:
            if name is not None:
                s = self.session_manager.create(name or "")
                self._switch_session(s)
                self.query_one("#chat-log", RichLog).write(
                    Markdown(f"*Session **{s.display_name}** créée.*"))
        self.push_screen(NewSessionModal(), _done)

    def action_new_skill(self) -> None:
        def _created(skill: Optional[Skill]) -> None:
            if skill:
                self._refresh_skills()
                def _edited(content: Optional[str]) -> None:
                    if content is not None:
                        self.query_one("#chat-log", RichLog).write(
                            Markdown(f"*Skill **{skill.display_name}** sauvegardé.*"))
                self.push_screen(SkillEditorModal(skill), _edited)
        self.push_screen(NewSkillModal(self.skill_manager), _created)

    def action_new_mcp(self) -> None:
        def _done(srv: Optional[MCPServer]) -> None:
            if srv:
                self._refresh_mcps()
                self.query_one("#chat-log", RichLog).write(
                    Markdown(f"*MCP **{srv.name}** ajouté.*"))
        self.push_screen(NewMCPModal(self.mcp_manager), _done)

    def action_new_cron(self) -> None:
        def _done(job: Optional[CronJob]) -> None:
            if job:
                self._refresh_crons()
                self.query_one("#chat-log", RichLog).write(
                    Markdown(
                        f"*Cron **{job.name}** créé — {job.schedule_label}.*\n"
                        + ("" if HAS_CRONITER else
                           "\n> ⚠ `croniter` non installé — la planification est inactive.")
                    ))
        self.push_screen(NewCronModal(self.cron_manager), _done)

    def action_clear_chat(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write(Markdown("*Historique effacé.*"))

    # ── Button routing ────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""

        if bid == "btn-new-session": self.action_new_session(); return
        if bid == "btn-new-skill":   self.action_new_skill();   return
        if bid == "btn-new-mcp":     self.action_new_mcp();     return
        if bid == "btn-new-cron":    self.action_new_cron();    return

        if bid.startswith("sess-"):
            sid = bid[5:]
            s = next((x for x in self._sessions if x.id == sid), None)
            if s:
                self._switch_session(s)

        elif bid.startswith("skill-"):
            name = bid[6:]
            sk = next((x for x in self._skills if x.name == name), None)
            if sk:
                def _ed(content: Optional[str]) -> None:
                    if content is not None:
                        self.query_one("#chat-log", RichLog).write(
                            Markdown(f"*Skill **{sk.display_name}** sauvegardé.*"))
                self.push_screen(SkillEditorModal(sk), _ed)

        elif bid.startswith("mcptog-"):
            mid = bid[7:]
            srv = self.mcp_manager.toggle(mid)
            if srv:
                self._refresh_mcps()

        elif bid.startswith("mcp-"):
            mid = bid[4:]
            m = next((x for x in self._mcps if x.id == mid), None)
            if m and not m.system:
                self.mcp_manager.toggle(mid)
                self._refresh_mcps()

        elif bid.startswith("cron-"):
            jid = bid[5:]
            j = self.cron_manager.toggle(jid)
            if j:
                self._refresh_crons()

        elif bid.startswith("croninfo-"):
            pass  # info row — no action

    # ── Skill search ──────────────────────────────────────────────────────────

    @on(Input.Changed, "#skill-search")
    def _skill_search(self, e: Input.Changed) -> None:
        self._skill_q = e.value.strip()
        self._refresh_skills()

    # ── Chat input ────────────────────────────────────────────────────────────

    @on(Input.Submitted, "#chat-input")
    def _on_chat(self, e: Input.Submitted) -> None:
        message = e.value.strip()
        if not message:
            return
        self.query_one("#chat-input", Input).value = ""
        self._cmd_history.insert(0, message)
        self._hist_idx = -1

        # Intercept slash commands
        if message.startswith("/"):
            local = _handle_slash(message, self._skills, self._mcps, self._crons)
            if local is not None:
                self._render_msg("user", message)
                self._render_msg("assistant", local)
                return

        # Ensure active session
        if not self.current_session:
            self.current_session = self.session_manager.create()
            self._refresh_sessions()

        self.current_session.add_message("user", message)
        self._render_msg("user", message)
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

    # ── Cron callback (thread-safe) ──────────────────────────────────────────

    def _on_cron_fired(self, job: CronJob) -> None:
        self.call_from_thread(
            lambda j=job: (
                self.query_one("#chat-log", RichLog).write(
                    Markdown(f"**[Cron]** *{j.name}* lancé — `{j.schedule_label}`")
                ),
                self._refresh_crons(),
            )
        )

    # ── Worker ───────────────────────────────────────────────────────────────

    @work(thread=True)
    def _process(self, message: str, session: Session) -> None:
        def _log(c) -> None:
            self.call_from_thread(
                lambda x=c: self.query_one("#chat-log", RichLog).write(x)
            )
        def _status(t: str) -> None:
            self.call_from_thread(
                lambda s=t: self.query_one("#topbar-status", Label).update(s)
            )

        _status("[yellow]● thinking…[/yellow]")

        prefix = Text()
        prefix.append("  π  ", style="bold black on #238636")
        _log("")
        _log(prefix)

        if self._pi_ok:
            response = _call_pi(message, session_path=session.path) or "(Pas de réponse)"
        else:
            response = _local_reply(message, self._skills, self._mcps, self._crons)

        _log(Markdown(response))
        _log("")

        self.call_from_thread(lambda r=response: session.add_message("assistant", r))
        self.call_from_thread(self._refresh_sessions)
        _status("● pi ready" if self._pi_ok else "[yellow]● pi non installé[/yellow]")


# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    PiAgentApp().run()


if __name__ == "__main__":
    main()
