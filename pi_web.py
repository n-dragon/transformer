"""
Pi Agent — Web UI
Run:   python pi_web.py
Open:  http://localhost:8000
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pi_sessions import SessionManager, Session
from pi_skills   import SkillManager, Skill
from pi_mcps     import MCPManager, MCPServer
from pi_crons    import CronManager, CronJob, CronRunner, PRESETS, HAS_CRONITER

# ─────────────────────────────────────────────────────────────────────────────
# Singletons
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Pi Agent Web UI")

session_manager = SessionManager()
skill_manager   = SkillManager()
mcp_manager     = MCPManager()
cron_manager    = CronManager()


def _pi_ok() -> bool:
    try:
        r = subprocess.run(["pi", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

PI_INSTALLED = _pi_ok()

cron_runner = CronRunner(
    manager=cron_manager,
    pi_installed=PI_INSTALLED,
)
cron_runner.start()

# ─────────────────────────────────────────────────────────────────────────────
# Chat logic
# ─────────────────────────────────────────────────────────────────────────────

_SLASH = {
    "/help":  lambda sk, mc, cr: (
        "**Commandes disponibles**\n\n"
        "| Commande | Description |\n|---|---|\n"
        "| `/skills` | Lister les skills |\n"
        "| `/skill:name` | Invoquer un skill |\n"
        "| `/mcps` | Lister les MCPs |\n"
        "| `/crons` | Lister les crons |\n"
        "| `/help` | Cette aide |"
    ),
    "/skills": lambda sk, mc, cr: (
        "**Skills disponibles**\n\n" +
        "\n".join(f"- `/skill:{s.name}` {'[local]' if not s.is_global else ''} — {s.first_line}" for s in sk)
        if sk else "*Aucun skill trouvé.*"
    ),
    "/mcps": lambda sk, mc, cr: (
        "**Serveurs MCP**\n\n" +
        "\n".join(f"- {'●' if m.enabled else '○'} `{m.name}`{'  [sys]' if m.system else ''} — `{m.summary}`" for m in mc)
        if mc else "*Aucun MCP configuré.*"
    ),
    "/crons": lambda sk, mc, cr: (
        "**Crons planifiés**\n\n" +
        "\n".join(f"- {'●' if j.enabled else '○'} **{j.name}** — {j.schedule_label} · prochain : {j.next_run_label}" for j in cr)
        if cr else "*Aucun cron planifié.*"
    ),
}


def _process_message(content: str, session: Session) -> str:
    # Slash commands handled locally
    if content.startswith("/"):
        key = content.split(":")[0].lower()
        fn = _SLASH.get(key)
        if fn:
            return fn(
                skill_manager.list_skills(),
                mcp_manager.list_servers(),
                cron_manager.list_jobs(),
            )

    if PI_INSTALLED:
        cmd = ["pi", "-p", content, "--session", str(session.path)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return r.stdout.strip() or r.stderr.strip() or "(Pas de réponse)"
        except subprocess.TimeoutExpired:
            return "Délai dépassé (120 s)."
    else:
        q = content.lower()
        if any(w in q for w in ["bonjour", "salut", "hello"]):
            return (
                "Bonjour ! Je suis **Pi (π)**, votre agent IA.\n\n"
                "Pi n'est pas encore installé :\n"
                "```bash\nnpm install -g @earendil-works/pi-coding-agent\n```\n\n"
                "Sessions, Skills, MCPs et Crons sont gérés localement."
            )
        return (
            f"*(pi non installé)* Votre message : *\"{content}\"*\n\n"
            "Activez le chat complet :\n"
            "```bash\nnpm install -g @earendil-works/pi-coding-agent\n```"
        )

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class CreateSession(BaseModel):
    name: str = ""

class CreateSkill(BaseModel):
    name: str
    description: str = ""
    content: str = ""

class UpdateSkill(BaseModel):
    content: str

class CreateMCP(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}

class CreateCron(BaseModel):
    name: str
    schedule: str
    prompt: str
    session_name: str = ""

# ─────────────────────────────────────────────────────────────────────────────
# REST API
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    return {
        "pi_installed": PI_INSTALLED,
        "has_croniter": HAS_CRONITER,
        "sessions": len(session_manager.list_sessions()),
        "skills": len(skill_manager.list_skills()),
        "mcps": len(mcp_manager.list_servers()),
        "crons": len(cron_manager.list_jobs()),
    }

# Sessions
@app.get("/api/sessions")
def list_sessions():
    return [
        {"id": s.id, "name": s.display_name, "preview": s.preview,
         "message_count": s.message_count,
         "created_at": s.created_at.isoformat()}
        for s in session_manager.list_sessions()
    ]

@app.post("/api/sessions", status_code=201)
def create_session(body: CreateSession):
    s = session_manager.create(body.name)
    return {"id": s.id, "name": s.display_name}

@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    sessions = session_manager.list_sessions()
    s = next((x for x in sessions if x.id == session_id), None)
    if not s:
        raise HTTPException(404, "Session not found")
    return {
        "id": s.id, "name": s.display_name,
        "messages": [
            {"role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in s.messages
        ],
    }

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    session_manager.delete(session_id)
    return {"ok": True}

# Skills
@app.get("/api/skills")
def list_skills(q: str = ""):
    skills = skill_manager.search(q) if q else skill_manager.list_skills()
    return [
        {"name": s.name, "display_name": s.display_name,
         "description": s.first_line, "is_global": s.is_global}
        for s in skills
    ]

@app.post("/api/skills", status_code=201)
def create_skill(body: CreateSkill):
    sk = skill_manager.create(body.name, description=body.description, content=body.content)
    return {"name": sk.name, "display_name": sk.display_name}

@app.get("/api/skills/{name}")
def get_skill(name: str):
    sk = skill_manager.get_skill(name)
    if not sk:
        raise HTTPException(404, "Skill not found")
    return {"name": sk.name, "display_name": sk.display_name,
            "content": sk.content(), "path": str(sk.path)}

@app.put("/api/skills/{name}")
def update_skill(name: str, body: UpdateSkill):
    sk = skill_manager.get_skill(name)
    if not sk:
        raise HTTPException(404, "Skill not found")
    sk.save(body.content)
    return {"ok": True}

@app.delete("/api/skills/{name}")
def delete_skill(name: str):
    sk = skill_manager.get_skill(name)
    if sk:
        skill_manager.delete(sk)
    return {"ok": True}

# MCPs
@app.get("/api/mcps")
def list_mcps():
    return [
        {"id": m.id, "name": m.name, "command": m.command,
         "args": m.args, "env": m.env, "enabled": m.enabled,
         "system": m.system, "summary": m.summary}
        for m in mcp_manager.list_servers()
    ]

@app.post("/api/mcps", status_code=201)
def create_mcp(body: CreateMCP):
    srv = mcp_manager.add(body.name, body.command, args=body.args, env=body.env)
    return {"id": srv.id, "name": srv.name}

@app.post("/api/mcps/{mcp_id}/toggle")
def toggle_mcp(mcp_id: str):
    srv = mcp_manager.toggle(mcp_id)
    if not srv:
        raise HTTPException(404, "MCP not found")
    return {"id": srv.id, "enabled": srv.enabled}

@app.delete("/api/mcps/{mcp_id}")
def delete_mcp(mcp_id: str):
    mcp_manager.remove(mcp_id)
    return {"ok": True}

# Crons
@app.get("/api/crons")
def list_crons():
    return [
        {"id": j.id, "name": j.name, "schedule": j.schedule,
         "schedule_label": j.schedule_label, "prompt": j.prompt,
         "session_name": j.session_name, "enabled": j.enabled,
         "last_run_label": j.last_run_label, "next_run_label": j.next_run_label}
        for j in cron_manager.list_jobs()
    ]

@app.get("/api/crons/presets")
def get_cron_presets():
    return [{"label": l, "expr": e} for l, e in PRESETS if e]

@app.post("/api/crons", status_code=201)
def create_cron(body: CreateCron):
    job = cron_manager.create(
        body.name, body.schedule, body.prompt,
        session_name=body.session_name,
    )
    return {"id": job.id, "name": job.name}

@app.post("/api/crons/{cron_id}/toggle")
def toggle_cron(cron_id: str):
    job = cron_manager.toggle(cron_id)
    if not job:
        raise HTTPException(404, "Cron not found")
    return {"id": job.id, "enabled": job.enabled}

@app.delete("/api/crons/{cron_id}")
def delete_cron(cron_id: str):
    cron_manager.delete(cron_id)
    return {"ok": True}

# ─────────────────────────────────────────────────────────────────────────────
# WebSocket — chat
# ─────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_chat(ws: WebSocket, session_id: str):
    await ws.accept()
    sessions = session_manager.list_sessions()
    session = next((s for s in sessions if s.id == session_id), None)
    if not session:
        await ws.close(code=4004)
        return
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            if data.get("type") != "message":
                continue
            content = data.get("content", "").strip()
            if not content:
                continue

            session.add_message("user", content)
            await ws.send_text(json.dumps({"type": "thinking"}))

            response = await asyncio.to_thread(_process_message, content, session)
            session.add_message("assistant", response)

            # Stream word-by-word for UX effect
            words = response.split(" ")
            buf = ""
            for i, word in enumerate(words):
                buf += word + (" " if i < len(words) - 1 else "")
                if len(buf) >= 8 or i == len(words) - 1:
                    await ws.send_text(json.dumps({"type": "chunk", "content": buf}))
                    buf = ""
                    await asyncio.sleep(0.012)

            await ws.send_text(json.dumps({"type": "done"}))

    except WebSocketDisconnect:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Frontend SPA
# ─────────────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>π Pi Agent</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;--surface:#161b22;--surface2:#21262d;
  --border:#30363d;--border2:#21262d;
  --text:#e6edf3;--text2:#c9d1d9;--muted:#8b949e;
  --blue:#388bfd;--blue2:#58a6ff;
  --green:#3fb950;--green2:#238636;
  --yellow:#d29922;--purple:#8957e5;--red:#f85149;
  --font:'Segoe UI',system-ui,sans-serif;
  --mono:'Cascadia Code','Fira Code','Consolas',monospace;
  --sidebar:280px;--topbar:48px;
}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font);font-size:14px;overflow:hidden}

/* ── Topbar ──────────────────────────────────────────────────── */
#topbar{
  position:fixed;top:0;left:0;right:0;height:var(--topbar);
  background:var(--surface);border-bottom:1px solid var(--border2);
  display:flex;align-items:center;padding:0 20px;z-index:100;gap:12px;
}
#topbar-icon{font-size:20px;font-weight:700;color:var(--text)}
#topbar-title{font-weight:600;font-size:15px;color:var(--text);flex:1}
#topbar-status{font-size:12px;padding:3px 10px;border-radius:20px;
  background:var(--surface2);border:1px solid var(--border);color:var(--green)}
#topbar-status.warn{color:var(--yellow)}

/* ── Layout ──────────────────────────────────────────────────── */
#layout{
  display:flex;height:100vh;padding-top:var(--topbar);
}

/* ── Sidebar ─────────────────────────────────────────────────── */
#sidebar{
  width:var(--sidebar);min-width:var(--sidebar);
  background:var(--bg);border-right:1px solid var(--border2);
  display:flex;flex-direction:column;overflow:hidden;
}
#tab-nav{
  display:grid;grid-template-columns:1fr 1fr 1fr 1fr;
  border-bottom:1px solid var(--border2);
}
.tab-btn{
  background:transparent;border:none;padding:10px 4px;
  color:var(--muted);font-size:12px;font-weight:500;cursor:pointer;
  border-bottom:2px solid transparent;transition:color .15s,border-color .15s;
}
.tab-btn:hover{color:var(--text2)}
.tab-btn.active{color:var(--blue2);border-bottom-color:var(--blue2)}
.tab-pane{display:none;flex-direction:column;overflow:hidden;flex:1}
.tab-pane.active{display:flex}
.pane-inner{flex:1;overflow-y:auto;padding:4px 0}
.action-btn{
  display:flex;align-items:center;gap:6px;
  width:100%;padding:8px 16px;background:transparent;border:none;
  color:var(--blue2);font-size:13px;cursor:pointer;text-align:left;
  transition:background .1s;
}
.action-btn:hover{background:var(--surface2)}
.search-box{
  margin:8px 12px;padding:7px 10px;background:var(--bg);
  border:1px solid var(--border);border-radius:6px;
  color:var(--text);font-size:13px;outline:none;width:calc(100% - 24px);
}
.search-box:focus{border-color:var(--blue)}
.list-item{
  display:flex;align-items:center;padding:7px 16px;cursor:pointer;
  gap:8px;border-left:2px solid transparent;transition:background .1s;
}
.list-item:hover{background:var(--surface2)}
.list-item.active{background:#1f3a5f;border-left-color:var(--blue);color:var(--blue2)}
.list-item-icon{font-size:11px;color:var(--muted);flex-shrink:0}
.list-item-icon.on{color:var(--green)}
.list-item-icon.off{color:var(--muted)}
.list-item-body{flex:1;min-width:0}
.list-item-name{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.list-item-sub{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.list-item-badge{font-size:10px;padding:1px 5px;border-radius:4px;
  background:var(--surface2);color:var(--muted);border:1px solid var(--border);flex-shrink:0}
.list-item-badge.sys{color:var(--purple);border-color:var(--purple)}
.list-item-actions{display:flex;gap:4px;opacity:0;transition:opacity .15s}
.list-item:hover .list-item-actions{opacity:1}
.icon-btn{
  background:transparent;border:none;cursor:pointer;
  padding:2px 5px;border-radius:3px;color:var(--muted);font-size:12px;
}
.icon-btn:hover{background:var(--surface);color:var(--text)}
.icon-btn.del:hover{color:var(--red)}

/* ── Main ────────────────────────────────────────────────────── */
#main{flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden}

/* ── Chat log ────────────────────────────────────────────────── */
#chat-log{
  flex:1;overflow-y:auto;padding:24px 32px;scroll-behavior:smooth;
}
#chat-empty{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  height:100%;gap:12px;color:var(--muted);
}
#chat-empty .big-pi{font-size:48px;opacity:.3}
#chat-empty p{font-size:14px}
.msg{display:flex;gap:12px;margin-bottom:24px;animation:fadeIn .2s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.msg-avatar{
  width:28px;height:28px;border-radius:6px;display:flex;align-items:center;
  justify-content:center;font-size:12px;font-weight:700;flex-shrink:0;margin-top:2px;
}
.msg.user .msg-avatar{background:var(--blue);color:#fff}
.msg.assistant .msg-avatar{background:var(--green2);color:#fff}
.msg-content{flex:1;min-width:0;padding-top:4px}
.msg-role{font-size:11px;font-weight:600;color:var(--muted);margin-bottom:6px;
  text-transform:uppercase;letter-spacing:.5px}
.msg.user .msg-role{color:var(--blue2)}
.msg.assistant .msg-role{color:var(--green)}
.msg-text{color:var(--text2);line-height:1.65}
.msg.user .msg-text{color:var(--text);font-weight:500}
/* Markdown inside .msg-text */
.msg-text h1,.msg-text h2,.msg-text h3{color:var(--text);margin:14px 0 8px;font-weight:600}
.msg-text h1{font-size:16px;border-bottom:1px solid var(--border);padding-bottom:6px}
.msg-text h2{font-size:15px}
.msg-text h3{font-size:14px}
.msg-text p{margin-bottom:10px}
.msg-text ul,.msg-text ol{padding-left:20px;margin-bottom:10px}
.msg-text li{margin-bottom:4px}
.msg-text code{
  background:var(--surface2);padding:2px 6px;border-radius:4px;
  font-family:var(--mono);font-size:12px;color:#e6edf3;
}
.msg-text pre{
  background:var(--surface2);border:1px solid var(--border);
  border-radius:8px;padding:14px 16px;margin:10px 0;overflow-x:auto;
}
.msg-text pre code{background:none;padding:0;font-size:12.5px;line-height:1.55}
.msg-text blockquote{
  border-left:3px solid var(--blue);padding:8px 14px;
  background:var(--surface2);border-radius:0 6px 6px 0;margin:10px 0;color:var(--text2);
}
.msg-text table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
.msg-text th{background:var(--surface);padding:8px 12px;border:1px solid var(--border);
  color:var(--text2);font-weight:600;text-align:left}
.msg-text td{padding:8px 12px;border:1px solid var(--border);color:var(--text2)}
.msg-text a{color:var(--blue2);text-decoration:none}
.msg-text a:hover{text-decoration:underline}
.msg-text hr{border:none;border-top:1px solid var(--border);margin:14px 0}
.thinking-dots::after{
  content:'…';animation:dots 1.2s steps(4,end) infinite;
}
@keyframes dots{0%,20%{content:''}40%{content:'.'}60%{content:'..'}80%,100%{content:'...'}}

/* ── Input bar ───────────────────────────────────────────────── */
#inputbar{
  border-top:1px solid var(--border2);background:var(--surface);padding:12px 20px;
}
#input-hint{font-size:11px;color:var(--muted);margin-bottom:8px}
#input-row{display:flex;gap:10px;align-items:flex-end}
#chat-input{
  flex:1;background:var(--bg);border:1px solid var(--border);
  border-radius:8px;padding:10px 14px;color:var(--text);
  font-family:var(--font);font-size:14px;line-height:1.5;
  resize:none;outline:none;max-height:120px;overflow-y:auto;
  transition:border-color .15s;
}
#chat-input:focus{border-color:var(--blue)}
#send-btn{
  padding:10px 18px;background:var(--blue);border:none;border-radius:8px;
  color:#fff;font-size:13px;font-weight:600;cursor:pointer;
  transition:background .15s;white-space:nowrap;
}
#send-btn:hover{background:var(--blue2)}
#send-btn:disabled{opacity:.5;cursor:not-allowed}

/* ── Modals ──────────────────────────────────────────────────── */
#modal-backdrop{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);
  z-index:200;align-items:center;justify-content:center;
}
#modal-backdrop.open{display:flex}
.modal{
  background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:24px;width:520px;max-width:95vw;
  max-height:90vh;overflow-y:auto;
}
.modal.wide{width:820px}
.modal h2{font-size:16px;font-weight:600;margin-bottom:16px;color:var(--text)}
.form-group{margin-bottom:14px}
.form-group label{display:block;font-size:12px;font-weight:500;
  color:var(--muted);margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
.form-group input,.form-group select,.form-group textarea{
  width:100%;padding:8px 12px;background:var(--bg);border:1px solid var(--border);
  border-radius:6px;color:var(--text);font-size:13px;outline:none;
  transition:border-color .15s;font-family:var(--font);
}
.form-group input:focus,.form-group select:focus,.form-group textarea:focus{
  border-color:var(--blue);
}
.form-group textarea{resize:vertical;min-height:80px;font-family:var(--mono);font-size:12px}
.form-group select option{background:var(--surface)}
.form-hint{font-size:11px;color:var(--muted);margin-top:4px}
.modal-footer{display:flex;gap:8px;justify-content:flex-end;margin-top:20px}
.btn{padding:8px 16px;border-radius:6px;font-size:13px;font-weight:500;cursor:pointer;border:none}
.btn-default{background:var(--surface2);color:var(--text2);border:1px solid var(--border)}
.btn-default:hover{background:var(--border2)}
.btn-primary{background:var(--blue);color:#fff}
.btn-primary:hover{background:var(--blue2)}
.btn-green{background:var(--green2);color:#fff}
.btn-green:hover{background:var(--green)}
/* Skill editor split view */
#editor-split{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:10px}
#skill-editor-ta{height:340px;font-family:var(--mono);font-size:12.5px;line-height:1.6}
#skill-preview{
  background:var(--bg);border:1px solid var(--border);border-radius:6px;
  padding:12px 16px;height:340px;overflow-y:auto;
  font-size:13px;line-height:1.65;color:var(--text2);
}
#editor-split-label{display:flex;justify-content:space-between;font-size:11px;
  color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px}

/* ── Scrollbar ───────────────────────────────────────────────── */
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--surface2);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:var(--border)}
</style>
</head>
<body>

<!-- Topbar -->
<header id="topbar">
  <span id="topbar-icon">π</span>
  <span id="topbar-title">Pi Agent</span>
  <span id="topbar-status">● chargement…</span>
</header>

<!-- Layout -->
<div id="layout">

  <!-- Sidebar -->
  <aside id="sidebar">
    <nav id="tab-nav">
      <button class="tab-btn active" data-tab="sessions">Sessions</button>
      <button class="tab-btn" data-tab="skills">Skills</button>
      <button class="tab-btn" data-tab="mcps">MCPs</button>
      <button class="tab-btn" data-tab="crons">Crons</button>
    </nav>

    <!-- Sessions -->
    <div id="pane-sessions" class="tab-pane active">
      <button class="action-btn" onclick="openModal('new-session')">＋  Nouvelle session</button>
      <div class="pane-inner" id="sessions-list"></div>
    </div>

    <!-- Skills -->
    <div id="pane-skills" class="tab-pane">
      <input class="search-box" id="skill-search" placeholder="Rechercher un skill…" oninput="loadSkills(this.value)">
      <button class="action-btn" onclick="openModal('new-skill')">＋  Nouveau skill</button>
      <div class="pane-inner" id="skills-list"></div>
    </div>

    <!-- MCPs -->
    <div id="pane-mcps" class="tab-pane">
      <button class="action-btn" onclick="openModal('new-mcp')">＋  Nouveau MCP</button>
      <div class="pane-inner" id="mcps-list"></div>
    </div>

    <!-- Crons -->
    <div id="pane-crons" class="tab-pane">
      <button class="action-btn" onclick="openModal('new-cron')">＋  Nouveau cron</button>
      <div class="pane-inner" id="crons-list"></div>
    </div>
  </aside>

  <!-- Main -->
  <main id="main">
    <div id="chat-log">
      <div id="chat-empty">
        <div class="big-pi">π</div>
        <p>Sélectionnez ou créez une session pour commencer</p>
      </div>
    </div>
    <div id="inputbar">
      <div id="input-hint">Commandes : /skills · /mcps · /crons · /help — Entrée pour envoyer</div>
      <div id="input-row">
        <textarea id="chat-input" rows="1" placeholder="Votre message…" disabled></textarea>
        <button id="send-btn" onclick="sendMessage()" disabled>Envoyer ↵</button>
      </div>
    </div>
  </main>
</div>

<!-- Modal backdrop -->
<div id="modal-backdrop" onclick="closeModal(event)">

  <!-- New Session -->
  <div class="modal" id="modal-new-session">
    <h2>Nouvelle session</h2>
    <div class="form-group">
      <label>Nom (optionnel)</label>
      <input id="ns-name" placeholder="ex: Refactoring auth module" onkeydown="if(e.key==='Enter')createSession()">
    </div>
    <div class="modal-footer">
      <button class="btn btn-default" onclick="closeModal()">Annuler</button>
      <button class="btn btn-primary" onclick="createSession()">Créer</button>
    </div>
  </div>

  <!-- New Skill -->
  <div class="modal" id="modal-new-skill">
    <h2>Nouveau skill</h2>
    <div class="form-group">
      <label>Nom</label>
      <input id="nsk-name" placeholder="ex: refactor-python">
    </div>
    <div class="form-group">
      <label>Description (usage)</label>
      <input id="nsk-desc" placeholder="ex: refactoriser du code Python">
    </div>
    <div class="modal-footer">
      <button class="btn btn-default" onclick="closeModal()">Annuler</button>
      <button class="btn btn-green" onclick="createSkill()">Créer et éditer</button>
    </div>
  </div>

  <!-- Skill Editor -->
  <div class="modal wide" id="modal-skill-editor">
    <h2 id="skill-editor-title">Éditer le skill</h2>
    <div id="editor-split-label">
      <span>Markdown</span><span>Aperçu</span>
    </div>
    <div id="editor-split">
      <textarea id="skill-editor-ta" oninput="updatePreview()"></textarea>
      <div id="skill-preview"></div>
    </div>
    <div class="form-hint" id="skill-editor-path"></div>
    <div class="modal-footer">
      <button class="btn btn-default" onclick="closeModal()">Fermer</button>
      <button class="btn btn-green" onclick="saveSkill()">Sauvegarder  Ctrl+S</button>
    </div>
  </div>

  <!-- New MCP -->
  <div class="modal" id="modal-new-mcp">
    <h2>Nouveau serveur MCP</h2>
    <div class="form-group">
      <label>Nom</label>
      <input id="nm-name" placeholder="ex: filesystem">
    </div>
    <div class="form-group">
      <label>Commande</label>
      <input id="nm-cmd" placeholder="ex: npx">
    </div>
    <div class="form-group">
      <label>Arguments (séparés par des espaces)</label>
      <input id="nm-args" placeholder="ex: -y @modelcontextprotocol/server-filesystem /tmp">
    </div>
    <div class="form-group">
      <label>Variables d'env (KEY=val, optionnel)</label>
      <input id="nm-env" placeholder="ex: API_KEY=secret TOKEN=abc">
    </div>
    <div class="modal-footer">
      <button class="btn btn-default" onclick="closeModal()">Annuler</button>
      <button class="btn btn-primary" onclick="createMCP()">Ajouter</button>
    </div>
  </div>

  <!-- New Cron -->
  <div class="modal" id="modal-new-cron">
    <h2>Nouveau cron planifié</h2>
    <div class="form-group">
      <label>Nom</label>
      <input id="nc-name" placeholder="ex: Standup quotidien">
    </div>
    <div class="form-group">
      <label>Fréquence</label>
      <select id="nc-preset" onchange="onPresetChange()"></select>
    </div>
    <div class="form-group" id="nc-custom-group" style="display:none">
      <label>Expression cron personnalisée</label>
      <input id="nc-expr" placeholder="ex: 0 9 * * 1-5">
      <div class="form-hint">min heure jour_du_mois mois jour_semaine</div>
    </div>
    <div class="form-group">
      <label>Prompt à envoyer à Pi</label>
      <input id="nc-prompt" placeholder="ex: Génère le rapport de standup">
    </div>
    <div class="form-group">
      <label>Nom de session (optionnel)</label>
      <input id="nc-session" placeholder="ex: daily-standup">
    </div>
    <div class="modal-footer">
      <button class="btn btn-default" onclick="closeModal()">Annuler</button>
      <button class="btn btn-primary" onclick="createCron()">Créer</button>
    </div>
  </div>

</div>

<script>
// ─── Config ────────────────────────────────────────────────────────────────

marked.setOptions({
  highlight: (code, lang) => {
    if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, {language: lang}).value;
    return hljs.highlightAuto(code).value;
  },
  breaks: true,
  gfm: true,
});

// ─── State ─────────────────────────────────────────────────────────────────

let activeSessionId = null;
let ws = null;
let streaming = false;
let streamEl = null;
let streamBuf = '';
let editingSkillName = null;

// ─── Tabs ──────────────────────────────────────────────────────────────────

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('pane-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'mcps') loadMCPs();
    if (btn.dataset.tab === 'crons') loadCrons();
  });
});

// ─── Status ────────────────────────────────────────────────────────────────

async function loadStatus() {
  const r = await fetch('/api/status');
  const d = await r.json();
  const el = document.getElementById('topbar-status');
  if (d.pi_installed) {
    el.textContent = '● pi ready';
    el.className = '';
  } else {
    el.textContent = '● pi non installé';
    el.className = 'warn';
  }
}

// ─── Sessions ──────────────────────────────────────────────────────────────

async function loadSessions() {
  const r = await fetch('/api/sessions');
  const sessions = await r.json();
  const el = document.getElementById('sessions-list');
  if (!sessions.length) {
    el.innerHTML = '<div style="padding:12px 16px;color:var(--muted);font-size:12px">Aucune session</div>';
    return;
  }
  el.innerHTML = sessions.map(s => `
    <div class="list-item ${s.id === activeSessionId ? 'active' : ''}" onclick="openSession('${s.id}')">
      <span class="list-item-icon ${s.id === activeSessionId ? 'on' : ''}">●</span>
      <div class="list-item-body">
        <div class="list-item-name">${esc(s.name)}</div>
        <div class="list-item-sub">${esc(s.preview)} · ${s.message_count} msg</div>
      </div>
      <div class="list-item-actions">
        <button class="icon-btn del" onclick="deleteSession(event,'${s.id}')" title="Supprimer">✕</button>
      </div>
    </div>`).join('');
}

async function openSession(id) {
  activeSessionId = id;
  connectWS(id);
  const r = await fetch(`/api/sessions/${id}`);
  const s = await r.json();
  const log = document.getElementById('chat-log');
  log.innerHTML = '';
  s.messages.forEach(m => appendMessage(m.role, m.content));
  if (!s.messages.length) {
    log.innerHTML = '<div id="chat-empty"><div class="big-pi">π</div><p>' + esc(s.name) + '</p></div>';
  }
  document.getElementById('chat-input').disabled = false;
  document.getElementById('send-btn').disabled = false;
  document.getElementById('chat-input').focus();
  loadSessions();
  scrollToBottom();
}

async function createSession() {
  const name = document.getElementById('ns-name').value.trim();
  const r = await fetch('/api/sessions', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name})});
  const s = await r.json();
  closeModal();
  document.getElementById('ns-name').value = '';
  await loadSessions();
  openSession(s.id);
}

async function deleteSession(e, id) {
  e.stopPropagation();
  if (!confirm('Supprimer cette session ?')) return;
  await fetch(`/api/sessions/${id}`, {method:'DELETE'});
  if (activeSessionId === id) {
    activeSessionId = null;
    if (ws) { ws.close(); ws = null; }
    document.getElementById('chat-log').innerHTML =
      '<div id="chat-empty"><div class="big-pi">π</div><p>Sélectionnez ou créez une session</p></div>';
    document.getElementById('chat-input').disabled = true;
    document.getElementById('send-btn').disabled = true;
  }
  loadSessions();
}

// ─── Skills ────────────────────────────────────────────────────────────────

async function loadSkills(q = '') {
  const url = q ? `/api/skills?q=${encodeURIComponent(q)}` : '/api/skills';
  const r = await fetch(url);
  const skills = await r.json();
  const el = document.getElementById('skills-list');
  if (!skills.length) {
    el.innerHTML = '<div style="padding:12px 16px;color:var(--muted);font-size:12px">Aucun skill</div>';
    return;
  }
  el.innerHTML = skills.map(s => `
    <div class="list-item" onclick="editSkill('${s.name}')">
      <span class="list-item-icon on">◆</span>
      <div class="list-item-body">
        <div class="list-item-name">${esc(s.display_name)}</div>
        <div class="list-item-sub">${esc(s.description || '—')}</div>
      </div>
      ${!s.is_global ? '<span class="list-item-badge">local</span>' : ''}
      <div class="list-item-actions">
        <button class="icon-btn del" onclick="deleteSkill(event,'${s.name}')" title="Supprimer">✕</button>
      </div>
    </div>`).join('');
}

async function createSkill() {
  const name = document.getElementById('nsk-name').value.trim();
  const description = document.getElementById('nsk-desc').value.trim();
  if (!name) { document.getElementById('nsk-name').focus(); return; }
  await fetch('/api/skills', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, description})});
  closeModal();
  document.getElementById('nsk-name').value = '';
  document.getElementById('nsk-desc').value = '';
  await loadSkills();
  editSkill(name.toLowerCase().replace(/\s+/g,'-').replace(/_/g,'-'));
}

async function editSkill(name) {
  const r = await fetch(`/api/skills/${name}`);
  if (!r.ok) return;
  const sk = await r.json();
  editingSkillName = name;
  document.getElementById('skill-editor-title').textContent = `Skill : ${sk.display_name}`;
  document.getElementById('skill-editor-path').textContent = sk.path;
  document.getElementById('skill-editor-ta').value = sk.content;
  updatePreview();
  openModal('skill-editor');
}

function updatePreview() {
  const md = document.getElementById('skill-editor-ta').value;
  document.getElementById('skill-preview').innerHTML = marked.parse(md);
  document.getElementById('skill-preview').querySelectorAll('pre code').forEach(b => hljs.highlightElement(b));
}

async function saveSkill() {
  if (!editingSkillName) return;
  const content = document.getElementById('skill-editor-ta').value;
  await fetch(`/api/skills/${editingSkillName}`, {method:'PUT',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({content})});
  closeModal();
  loadSkills();
}

async function deleteSkill(e, name) {
  e.stopPropagation();
  if (!confirm(`Supprimer le skill "${name}" ?`)) return;
  await fetch(`/api/skills/${name}`, {method:'DELETE'});
  loadSkills();
}

// ─── MCPs ──────────────────────────────────────────────────────────────────

async function loadMCPs() {
  const r = await fetch('/api/mcps');
  const mcps = await r.json();
  const el = document.getElementById('mcps-list');
  if (!mcps.length) {
    el.innerHTML = '<div style="padding:12px 16px;color:var(--muted);font-size:12px">Aucun MCP configuré</div>';
    return;
  }
  el.innerHTML = mcps.map(m => `
    <div class="list-item">
      <span class="list-item-icon ${m.enabled ? 'on' : 'off'}" style="cursor:pointer" onclick="toggleMCP('${m.id}','${m.system}')" title="${m.enabled ? 'Désactiver' : 'Activer'}">${m.enabled ? '●' : '○'}</span>
      <div class="list-item-body">
        <div class="list-item-name">${esc(m.name)}</div>
        <div class="list-item-sub" title="${esc(m.command + ' ' + m.args.join(' '))}">${esc(m.summary)}</div>
      </div>
      ${m.system ? '<span class="list-item-badge sys">sys</span>' : ''}
      ${!m.system ? `<div class="list-item-actions">
        <button class="icon-btn del" onclick="deleteMCP(event,'${m.id}')" title="Supprimer">✕</button>
      </div>` : ''}
    </div>`).join('');
}

async function createMCP() {
  const name = document.getElementById('nm-name').value.trim();
  const command = document.getElementById('nm-cmd').value.trim();
  const argsRaw = document.getElementById('nm-args').value.trim();
  const envRaw = document.getElementById('nm-env').value.trim();
  if (!name || !command) { document.getElementById(!name ? 'nm-name' : 'nm-cmd').focus(); return; }
  const args = argsRaw ? argsRaw.split(/\s+/) : [];
  const env = {};
  envRaw.split(/\s+/).filter(Boolean).forEach(pair => {
    const [k, ...rest] = pair.split('='); if(k) env[k] = rest.join('=');
  });
  await fetch('/api/mcps', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, command, args, env})});
  closeModal();
  ['nm-name','nm-cmd','nm-args','nm-env'].forEach(id => document.getElementById(id).value = '');
  loadMCPs();
}

async function toggleMCP(id, isSystem) {
  if (isSystem === 'True') return;
  await fetch(`/api/mcps/${id}/toggle`, {method:'POST'});
  loadMCPs();
}

async function deleteMCP(e, id) {
  e.stopPropagation();
  if (!confirm('Supprimer ce MCP ?')) return;
  await fetch(`/api/mcps/${id}`, {method:'DELETE'});
  loadMCPs();
}

// ─── Crons ─────────────────────────────────────────────────────────────────

async function loadCrons() {
  const r = await fetch('/api/crons');
  const crons = await r.json();
  const el = document.getElementById('crons-list');
  if (!crons.length) {
    el.innerHTML = '<div style="padding:12px 16px;color:var(--muted);font-size:12px">Aucun cron planifié</div>';
    return;
  }
  el.innerHTML = crons.map(j => `
    <div class="list-item">
      <span class="list-item-icon ${j.enabled ? 'on' : 'off'}" style="cursor:pointer" onclick="toggleCron('${j.id}')" title="${j.enabled ? 'Désactiver' : 'Activer'}">${j.enabled ? '●' : '○'}</span>
      <div class="list-item-body">
        <div class="list-item-name">${esc(j.name)}</div>
        <div class="list-item-sub">${esc(j.schedule_label)} · prochain : ${esc(j.next_run_label)}</div>
      </div>
      <div class="list-item-actions">
        <button class="icon-btn del" onclick="deleteCron(event,'${j.id}')" title="Supprimer">✕</button>
      </div>
    </div>`).join('');
}

async function loadCronPresets() {
  const r = await fetch('/api/crons/presets');
  const presets = await r.json();
  const sel = document.getElementById('nc-preset');
  sel.innerHTML = presets.map(p => `<option value="${esc(p.expr)}">${esc(p.label)}</option>`).join('') +
    '<option value="custom">Personnalisé…</option>';
}

function onPresetChange() {
  const val = document.getElementById('nc-preset').value;
  const grp = document.getElementById('nc-custom-group');
  if (val === 'custom') {
    grp.style.display = '';
    document.getElementById('nc-expr').focus();
  } else {
    grp.style.display = 'none';
    document.getElementById('nc-expr').value = val;
  }
}

async function createCron() {
  const name = document.getElementById('nc-name').value.trim();
  const prompt = document.getElementById('nc-prompt').value.trim();
  let schedule = document.getElementById('nc-preset').value;
  if (schedule === 'custom') schedule = document.getElementById('nc-expr').value.trim();
  const session_name = document.getElementById('nc-session').value.trim();
  if (!name || !prompt) { document.getElementById(!name ? 'nc-name' : 'nc-prompt').focus(); return; }
  if (!schedule) schedule = '0 9 * * *';
  await fetch('/api/crons', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, schedule, prompt, session_name})});
  closeModal();
  ['nc-name','nc-prompt','nc-session','nc-expr'].forEach(id => document.getElementById(id).value = '');
  loadCrons();
}

async function toggleCron(id) {
  await fetch(`/api/crons/${id}/toggle`, {method:'POST'});
  loadCrons();
}

async function deleteCron(e, id) {
  e.stopPropagation();
  if (!confirm('Supprimer ce cron ?')) return;
  await fetch(`/api/crons/${id}`, {method:'DELETE'});
  loadCrons();
}

// ─── WebSocket / Chat ──────────────────────────────────────────────────────

function connectWS(sessionId) {
  if (ws) { ws.onclose = null; ws.close(); }
  ws = new WebSocket(`ws://${location.host}/ws/${sessionId}`);
  ws.onmessage = handleWS;
  ws.onerror = () => console.warn('WS error');
}

function handleWS(event) {
  const msg = JSON.parse(event.data);
  if (msg.type === 'thinking') {
    // Remove empty placeholder if present
    const empty = document.getElementById('chat-empty');
    if (empty) empty.remove();
    streamEl = appendMessage('assistant', '', true);
    streamBuf = '';
    streaming = true;
    document.getElementById('send-btn').disabled = true;
    document.getElementById('chat-input').disabled = true;
  } else if (msg.type === 'chunk' && streamEl) {
    streamBuf += msg.content;
    streamEl.querySelector('.msg-text').innerHTML = marked.parse(streamBuf);
    streamEl.querySelectorAll('pre code').forEach(b => hljs.highlightElement(b));
    scrollToBottom();
  } else if (msg.type === 'done') {
    streaming = false;
    if (streamEl) {
      streamEl.querySelector('.msg-text').classList.remove('thinking-dots');
    }
    streamEl = null;
    streamBuf = '';
    document.getElementById('send-btn').disabled = false;
    document.getElementById('chat-input').disabled = false;
    document.getElementById('chat-input').focus();
    loadSessions();
  }
}

function appendMessage(role, content, thinking = false) {
  const empty = document.getElementById('chat-empty');
  if (empty) empty.remove();
  const log = document.getElementById('chat-log');
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  const avatar = role === 'user' ? 'Y' : 'π';
  const label  = role === 'user' ? 'Vous' : 'Pi';
  const textHtml = thinking
    ? '<span class="thinking-dots">Génération</span>'
    : (role === 'user' ? esc(content) : marked.parse(content));
  div.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-content">
      <div class="msg-role">${label}</div>
      <div class="msg-text">${textHtml}</div>
    </div>`;
  div.querySelectorAll('pre code').forEach(b => hljs.highlightElement(b));
  log.appendChild(div);
  scrollToBottom();
  return div;
}

function sendMessage() {
  if (!ws || streaming || !activeSessionId) return;
  const inp = document.getElementById('chat-input');
  const content = inp.value.trim();
  if (!content) return;
  inp.value = '';
  inp.style.height = 'auto';
  appendMessage('user', content);
  ws.send(JSON.stringify({type: 'message', content}));
}

// ─── Input auto-resize + keyboard ─────────────────────────────────────────

document.getElementById('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
document.getElementById('chat-input').addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});
document.addEventListener('keydown', e => {
  if (e.ctrlKey && e.key === 's' && document.getElementById('modal-backdrop').classList.contains('open')) {
    e.preventDefault();
    saveSkill();
  }
});

// ─── Modals ────────────────────────────────────────────────────────────────

function openModal(name) {
  document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
  document.getElementById(`modal-${name}`).style.display = 'block';
  document.getElementById('modal-backdrop').classList.add('open');
  setTimeout(() => {
    const first = document.querySelector(`#modal-${name} input, #modal-${name} textarea`);
    if (first) first.focus();
  }, 50);
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('modal-backdrop')) return;
  document.getElementById('modal-backdrop').classList.remove('open');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('modal-backdrop').classList.remove('open');
});

// ─── Helpers ───────────────────────────────────────────────────────────────

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function scrollToBottom() {
  const log = document.getElementById('chat-log');
  log.scrollTop = log.scrollHeight;
}

// ─── Init ──────────────────────────────────────────────────────────────────

(async () => {
  await loadStatus();
  await loadSessions();
  await loadSkills();
  await loadCronPresets();
})();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(HTML)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("π  Pi Agent Web UI")
    print("→  http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
