# Pi Agent UI — Spécifications fonctionnelles et techniques

> Version 1.0 — Mai 2026  
> Dépôt : `n-dragon/transformer` · Branche : `claude/pi-agent-ui-skz5U`

---

## Table des matières

1. [Contexte et objectifs](#1-contexte-et-objectifs)
2. [Spécifications fonctionnelles](#2-spécifications-fonctionnelles)
   - 2.1 Sessions de chat
   - 2.2 Skills
   - 2.3 Serveurs MCP
   - 2.4 Crons planifiés
   - 2.5 Interface de chat
3. [Spécifications techniques](#3-spécifications-techniques)
   - 3.1 Architecture
   - 3.2 Stack technique
   - 3.3 Structure des fichiers
   - 3.4 Formats de données
   - 3.5 Stockage
   - 3.6 Intégration pi CLI
4. [Raccourcis clavier](#4-raccourcis-clavier)
5. [Contraintes et limites](#5-contraintes-et-limites)
6. [Roadmap](#6-roadmap)

---

## 1. Contexte et objectifs

### 1.1 Contexte

**Pi** (`@earendil-works/pi-coding-agent`) est un agent IA open-source en TypeScript
conçu pour le développement logiciel. Il expose un CLI (`pi`) et supporte :
- Sessions de conversation persistantes (JSONL avec structure en arbre)
- Skills réutilisables (fichiers Markdown)
- Serveurs MCP (Model Context Protocol)
- Modes d'intégration : interactive, JSON, RPC, SDK

### 1.2 Objectifs du projet

Construire une **interface terminal style Claude Code** par-dessus Pi, offrant :

| Objectif | Description |
|---|---|
| Productivité | Gérer sessions, skills, MCPs et crons depuis une seule UI |
| Découvrabilité | Lister et rechercher les ressources Pi disponibles |
| Automatisation | Planifier des sessions Pi via des expressions cron |
| Compatibilité | Rester compatible avec les fichiers natifs Pi (`~/.pi/agent/`) |
| Résilience | Fonctionner même sans Pi installé (mode dégradé) |

---

## 2. Spécifications fonctionnelles

### 2.1 Sessions de chat

**Description** : Chaque conversation est une session persistante, représentée
par un fichier JSONL. Les sessions sont organisées par date de modification
(les plus récentes en premier).

**Fonctionnalités :**

| # | Fonctionnalité | Comportement |
|---|---|---|
| SF-01 | Créer une session | L'utilisateur saisit un nom optionnel. Une session vide est créée immédiatement et activée. |
| SF-02 | Lister les sessions | Le panneau Sessions affiche toutes les sessions triées par date de modification. La session active est marquée `●`. |
| SF-03 | Ouvrir une session | Un clic charge l'historique complet dans la zone de chat. |
| SF-04 | Session automatique | Si aucune session n'est active lors de l'envoi d'un message, une session est créée automatiquement. |
| SF-05 | Persistance | Chaque message (user + assistant) est sauvegardé dans le fichier JSONL en temps réel. |

**Règles métier :**
- Le nom d'une session peut être vide (défaut : `Session DD/MM HH:MM`).
- L'ID de session est un UUID v4.
- Une session sans message affiche *"Nouvelle session"* comme aperçu.

---

### 2.2 Skills

**Description** : Les skills sont des fichiers Markdown décrivant des instructions
réutilisables pour l'agent. Ils sont stockés dans `~/.pi/agent/skills/` (globaux)
ou `.pi/skills/` (locaux au projet).

**Fonctionnalités :**

| # | Fonctionnalité | Comportement |
|---|---|---|
| SF-10 | Lister les skills | Affichage de tous les skills globaux et locaux dans le panneau Skills. |
| SF-11 | Rechercher | Filtrage en temps réel par nom et première ligne de description. |
| SF-12 | Créer un skill | Saisie du nom et d'une description → création du fichier Markdown avec template. Ouverture immédiate de l'éditeur. |
| SF-13 | Éditer un skill | Éditeur de texte intégré (Markdown, `Ctrl+S` pour sauvegarder). |
| SF-14 | Lister dans le chat | La commande `/skills` affiche tous les skills disponibles avec leur badge [global] ou [local]. |
| SF-15 | Invoquer dans le chat | `/skill:nom` transmet le skill à Pi lors de l'appel suivant. |

**Format d'un skill (`~/.pi/agent/skills/mon-skill.md`) :**

```markdown
# Mon Skill

Use this skill when the user asks to …

## Steps

1. Première étape
2. Deuxième étape
3. Troisième étape
```

**Règles métier :**
- Le nom est normalisé en kebab-case (`Mon Skill` → `mon-skill`).
- Les skills locaux (`.pi/skills/`) ont priorité sur les globaux en cas de conflit de nom.
- Badge `[sys]` réservé aux MCPs ; les skills ont badge `[local]` si non globaux.

---

### 2.3 Serveurs MCP (Model Context Protocol)

**Description** : Les MCPs étendent les capacités de Pi en lui donnant accès à des
outils externes (système de fichiers, bases de données, APIs…). Deux niveaux :
- **User** : `~/.pi/agent/mcps.json` — modifiable par l'utilisateur
- **System** : `/etc/pi/agent/mcps.json` — lecture seule, partagé entre tous les utilisateurs

**Fonctionnalités :**

| # | Fonctionnalité | Comportement |
|---|---|---|
| SF-20 | Lister tous les MCPs | Affichage des MCPs user + system dans le panneau MCPs. Badge `[sys]` pour les MCPs système. |
| SF-21 | Ajouter un MCP (user) | Saisie : nom, commande, arguments, variables d'environnement. |
| SF-22 | Activer / désactiver | Clic sur un MCP user bascule son état `enabled`. Les MCPs désactivés n'apparaissent pas dans l'export Pi. |
| SF-23 | Supprimer | Les MCPs user sont supprimables. Les MCPs system sont en lecture seule. |
| SF-24 | Export Pi | Export au format `mcpServers` compatible Pi/Claude Desktop via `MCPManager.export_pi_format()`. |
| SF-25 | Commande chat `/mcps` | Liste les MCPs avec leur statut (●/○) et leur commande. |

**Format `~/.pi/agent/mcps.json` :**

```json
[
  {
    "id": "a1b2c3d4",
    "name": "filesystem",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    "env": {},
    "enabled": true
  }
]
```

---

### 2.4 Crons planifiés

**Description** : Système de planification permettant de lancer automatiquement
des sessions Pi à intervalles réguliers, définis par une expression cron standard.

**Fonctionnalités :**

| # | Fonctionnalité | Comportement |
|---|---|---|
| SF-30 | Créer un cron | Saisie : nom, fréquence (preset ou expression custom), prompt, nom de session optionnel. |
| SF-31 | Presets | 6 presets proposés : toutes les heures, chaque jour 9h, lun–ven 9h, lundi 9h, dimanche 18h, toutes les 15 min. |
| SF-32 | Expression custom | Champ libre pour expression cron 5 champs (`min heure dom mois dow`). |
| SF-33 | Activer / désactiver | Toggle par clic sur l'item dans le panneau Crons. |
| SF-34 | Exécution automatique | Thread background vérifiant toutes les 30 s si un job doit être lancé. |
| SF-35 | Notification chat | Un message système apparaît dans le chat quand un cron se déclenche. |
| SF-36 | Historique | `last_run` et `next_run` affichés dans le panneau. |
| SF-37 | Commande `/crons` | Liste les crons avec leur fréquence et prochaine exécution. |

**Format `~/.pi/agent/crons.json` :**

```json
[
  {
    "id": "e5f6g7h8",
    "name": "Standup quotidien",
    "schedule": "0 9 * * 1-5",
    "prompt": "Génère le résumé de standup",
    "session_name": "daily-standup",
    "enabled": true,
    "last_run": "2026-05-28T09:00:02",
    "created_at": "2026-05-28T10:30:00"
  }
]
```

**Règles métier :**
- Un cron ne se déclenche qu'une fois par minute (protection anti-doublon via `last_run`).
- Si Pi n'est pas installé, le thread cron tourne mais n'exécute pas de commande Pi (notification UI uniquement).
- La précision de déclenchement est ±30 s (intervalle de vérification du thread).

---

### 2.5 Interface de chat

**Fonctionnalités :**

| # | Fonctionnalité | Comportement |
|---|---|---|
| SF-40 | Envoi de message | `Entrée` envoie le message. Traitement en thread background. |
| SF-41 | Historique | `↑` / `↓` navigue dans l'historique des commandes de la session. |
| SF-42 | Commandes internes | `/help`, `/skills`, `/mcps`, `/crons` répondent localement sans appeler Pi. |
| SF-43 | Passage à Pi | Tout autre message est transmis à `pi -p "message" --session <path>`. |
| SF-44 | Mode dégradé | Si Pi n'est pas installé, une réponse locale explique comment l'installer. |
| SF-45 | Indicateur thinking | La status bar passe en `● thinking…` (jaune) pendant le traitement. |
| SF-46 | Effacer | `Ctrl+L` efface l'affichage (ne supprime pas la session). |
| SF-47 | Rendu Markdown | Les réponses de l'agent sont rendues en Markdown (titres, code, listes, tableaux). |

---

## 3. Spécifications techniques

### 3.1 Architecture

```
pi_ui.py                  ← Orchestrateur principal (App Textual)
│
├── pi_sessions.py        ← Couche données : sessions JSONL
├── pi_skills.py          ← Couche données : skills Markdown
├── pi_mcps.py            ← Couche données : MCPs JSON
├── pi_crons.py           ← Couche données + runner : crons JSON + thread
│
└── [pi CLI]              ← Processus externe (optionnel)
    └── pi -p <msg> --session <path>
```

**Flux d'un message utilisateur :**

```
Input.Submitted
    │
    ├─ message.startswith("/") ?
    │       └─ _handle_slash() → réponse locale
    │
    └─ sinon
            ├─ session.add_message("user", msg)
            ├─ _render_msg("user", msg)
            └─ @work(thread=True) _process()
                    ├─ pi installé ? → _call_pi(msg, session.path)
                    └─ sinon        → _local_reply(msg)
                    │
                    └─ session.add_message("assistant", response)
                       _render_msg("assistant", response)
                       _refresh_sessions()
```

**Flux d'un cron :**

```
CronRunner._loop()  [daemon thread, toutes les 30 s]
    │
    └─ pour chaque CronJob enabled
            ├─ croniter.get_prev() → âge < 60 s ?
            ├─ last_run < 60 s ? → skip
            └─ _fire(job)
                    ├─ manager.mark_ran(job.id)
                    ├─ on_fire(job) → call_from_thread → notification chat
                    └─ pi installé ? → subprocess.Popen("pi -p <prompt>")
```

---

### 3.2 Stack technique

| Composant | Technologie | Version | Rôle |
|---|---|---|---|
| UI framework | [Textual](https://textual.textualize.io/) | 8.2.7 | TUI full-screen, widgets, CSS, events |
| Rendu terminal | [Rich](https://rich.readthedocs.io/) | 15.0.0 | Markdown, Text stylé, Rule |
| Cron parsing | [croniter](https://pypi.org/project/croniter/) | 6.2.2 | Expressions cron 5 champs |
| Langage | Python | 3.11+ | Runtime |
| Agent IA | pi CLI | latest | `npm install -g @earendil-works/pi-coding-agent` |
| Stockage | Système de fichiers | — | JSON, JSONL, Markdown |

**Installation des dépendances Python :**

```bash
pip install textual rich croniter
```

---

### 3.3 Structure des fichiers

```
transformer/
├── pi_ui.py          # Application Textual principale (App, modals, CSS)
├── pi_sessions.py    # SessionManager + Session + ChatMessage
├── pi_skills.py      # SkillManager + Skill
├── pi_mcps.py        # MCPManager + MCPServer
├── pi_crons.py       # CronManager + CronJob + CronRunner
└── transformer.py    # Implémentation Transformer (NumPy) — contexte originel
```

**Données persistées à l'exécution :**

```
~/.pi/agent/
├── sessions/
│   ├── <uuid>.jsonl          # une session = un fichier
│   └── <uuid>.jsonl
├── skills/
│   ├── mon-skill.md          # un skill = un fichier Markdown
│   └── autre-skill.md
├── mcps.json                 # liste des serveurs MCP user
└── crons.json                # liste des crons planifiés

/etc/pi/agent/
└── mcps.json                 # MCPs système (lecture seule, tous utilisateurs)
```

---

### 3.4 Formats de données

#### Session JSONL

Chaque ligne est un objet JSON. Structure compatible avec le format natif Pi.

```
{"type":"session_header","id":"<uuid>","name":"Mon projet","created_at":"2026-05-28T10:00:00"}
{"type":"message","id":"a1b2","parent_id":null,"role":"user","content":"Bonjour","timestamp":"…"}
{"type":"message","id":"c3d4","parent_id":"a1b2","role":"assistant","content":"Bonjour !","timestamp":"…"}
```

- `parent_id` forme un arbre (branching natif Pi).
- L'ordre des messages suit l'ordre des lignes.

#### Skill Markdown

```markdown
# Nom du Skill

Use this skill when the user asks to <description>.

## Steps

1. Étape 1
2. Étape 2
3. Étape 3
```

#### MCPs JSON (`~/.pi/agent/mcps.json`)

```json
[{"id":"…","name":"…","command":"…","args":[…],"env":{},"enabled":true}]
```

#### Crons JSON (`~/.pi/agent/crons.json`)

```json
[{"id":"…","name":"…","schedule":"0 9 * * 1-5","prompt":"…","session_name":"…",
  "enabled":true,"last_run":"2026-05-28T09:00:02","created_at":"…"}]
```

---

### 3.5 Stockage

| Ressource | Chemin | Format | Accès |
|---|---|---|---|
| Sessions | `~/.pi/agent/sessions/<uuid>.jsonl` | JSONL | Lecture/écriture |
| Skills globaux | `~/.pi/agent/skills/<name>.md` | Markdown | Lecture/écriture |
| Skills locaux | `.pi/skills/<name>.md` | Markdown | Lecture/écriture |
| MCPs user | `~/.pi/agent/mcps.json` | JSON array | Lecture/écriture |
| MCPs système | `/etc/pi/agent/mcps.json` | JSON array | Lecture seule |
| Crons | `~/.pi/agent/crons.json` | JSON array | Lecture/écriture |

Tous les répertoires sont créés automatiquement au premier démarrage (`mkdir -p`).

---

### 3.6 Intégration pi CLI

L'UI détecte la présence de Pi au démarrage :

```python
subprocess.run(["pi", "--version"], capture_output=True, timeout=5)
```

**Mode Pi installé :**

```bash
pi -p "<message>" --session ~/.pi/agent/sessions/<uuid>.jsonl
```

- Timeout : 120 s
- Stdout capturé et affiché dans le chat en Markdown.
- La session JSONL est partagée entre l'UI et Pi → l'historique reste cohérent.

**Mode dégradé (Pi non installé) :**

- Sessions, Skills, MCPs, Crons fonctionnent normalement (gestion de fichiers pure).
- Les messages chat reçoivent une réponse locale explicative.
- La status bar affiche `● pi non installé` en jaune.

---

## 4. Raccourcis clavier

| Raccourci | Action |
|---|---|
| `Ctrl+N` | Nouvelle session |
| `Ctrl+K` | Nouveau skill |
| `Ctrl+M` | Nouveau MCP |
| `Ctrl+R` | Nouveau cron |
| `Ctrl+L` | Effacer l'affichage du chat |
| `Ctrl+C` | Quitter l'application |
| `↑` / `↓` | Naviguer dans l'historique des commandes |
| `Ctrl+S` | Sauvegarder (dans l'éditeur de skill) |
| `Escape` | Fermer un modal |

**Commandes chat :**

| Commande | Description |
|---|---|
| `/help` | Afficher l'aide complète |
| `/skills` | Lister tous les skills disponibles |
| `/skill:name` | Invoquer un skill dans le prochain message Pi |
| `/mcps` | Lister les serveurs MCP configurés |
| `/crons` | Lister les crons avec leur prochain déclenchement |

---

## 5. Contraintes et limites

| # | Contrainte | Impact |
|---|---|---|
| CL-01 | Pas de streaming Pi | La réponse de Pi est affichée en bloc (pas mot à mot). |
| CL-02 | Précision cron ±30 s | Le thread vérifie toutes les 30 s → déclenchement jamais instantané. |
| CL-03 | MCPs système read-only | `/etc/pi/agent/mcps.json` ne peut pas être modifié via l'UI. |
| CL-04 | Pas d'autocomplete | La saisie `@skill` ne propose pas encore de complétion automatique. |
| CL-05 | Session branching UI | Le branching natif Pi (`/fork`, `/tree`) n'est pas exposé dans l'UI. |
| CL-06 | Pas de multi-modèle | Le modèle Pi utilisé est celui configuré dans l'environnement Pi. |

---

## 6. Roadmap

### v1.1 — Streaming et UX
- [ ] Streaming word-by-word via `pi --mode json`
- [ ] Autocomplétion des skills en tapant `@`
- [ ] Renommage de session en double-cliquant
- [ ] Suppression de session/skill/MCP/cron depuis le panneau

### v1.2 — Sessions avancées
- [ ] Visualisation de l'arbre de session (`/tree`)
- [ ] Branching (`/fork`) depuis n'importe quel message
- [ ] Export d'une session en Markdown

### v1.3 — Intégration Pi avancée
- [ ] Sélection du modèle (`--model`) dans la status bar
- [ ] Niveau de thinking (`--thinking`) configurable
- [ ] Mode SDK TypeScript via `pi --mode rpc`

### v1.4 — Multi-utilisateurs
- [ ] Interface d'administration des MCPs système (`/etc/pi/agent/mcps.json`)
- [ ] Partage de skills via packages Pi (`pi install`)
- [ ] Sessions partagées entre utilisateurs (NFS / S3)
