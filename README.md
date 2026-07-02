# Baton 🎽

**A local command center for every AI agent you have in flight** — Claude Code sessions and
Codex threads, in one glance, so you always know *which one needs you right now*.

As agents do more work unattended, the hard part stops being *doing the work* and becomes
*knowing which of your N running things is waiting on a decision*. Baton reads the signals your
machine already emits (zero manual entry) and surfaces the one that matters: the
**🎽 "the baton's with you"** bucket — an agent ran its leg and handed back to you. That's the
thing that's easy to drop when you're looking elsewhere.

It lives in your **macOS menu bar** (`🎽 N waiting`); click for the full picture, click any
session to **jump straight to it**.

---

## What it does

- **Menu bar glance** — the title is a live count of sessions waiting on you. Always visible,
  updates in **under a second** (it *watches* your session files with FSEvents rather than
  polling, so it's both instant and battery-cheap — it idles until something actually changes).
- **Two agents, one view** — the dropdown groups what's waiting by tool (Claude Code / Codex),
  then Working, then Done.
- **Click to jump** — click a Claude session and its **Terminal.app tab** comes to the front;
  click a Codex thread and it opens in **Codex** via its `codex://` deep link. No more hunting
  through windows.
- **Accurate "waiting" signals, per tool:**
  - **Claude Code** — a session that's idle with an assistant answer as its last turn = waiting.
  - **Codex** — mirrors Codex's own **unread (blue-dot)** state, so a thread you've already
    opened doesn't nag you.
- **Optional hand-off notifications** — off by default (the menu bar is the calm channel); one
  toggle turns on a banner the moment a baton comes back.
- **Recognizable labels** — each session is titled by Claude Code's own running summary
  (`ai-title`), so you know what it's about at a glance.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python menubar.py          # 🎽 appears in your menu bar
```

Auto-start at login is handled by a `launchd` LaunchAgent (`com.neil.baton-menubar`). There's
also a full HTML dashboard (`server.py` + `index.html`) for the rich multi-tab view:

```bash
bash start.sh        # python3 server.py --port 8787  → http://127.0.0.1:8787
```

## How it works

Every source is a **collector** that normalizes into one `track` record, so the UI never changes
as sources are added:

```
{ id, source, title, project, status, lastActive, detail, alive, extras }
status ∈ waiting | working | done | idle | scheduled
```

| Source | Read from | Signal |
|---|---|---|
| **Claude Code** | `~/.claude/sessions/{pid}.json` + transcripts | live `busy`/`idle` + last turn → working vs **waiting-on-you** |
| **Codex threads** | `~/.codex/session_index.jsonl` + `.codex-global-state.json` | **unread (blue-dot)** → waiting; rollout transcript → the agent's closing line |
| **Codex automations** | `~/.codex/automations/*/automation.toml` | scheduled pipelines → next/last run |

Claude Code (`~/.claude`) and Codex (`~/.codex`) are separate tools with separate state dirs —
Baton reads both independently. Detection is **event-driven** (FSEvents on the session dir) with
a slow safety-net poll.

## Stack

Single-file collectors + menu bar app in **stdlib Python** (plus `rumps` for the menu bar and
`pyobjc-framework-FSEvents` for the watcher, in an isolated `.venv`). The dashboard is
dependency-free vanilla HTML/CSS/JS. No build step, no framework.

## Security & privacy

Entirely local. The payload contains your real prompts and working directories, so the dashboard
server **binds to `127.0.0.1` only** — never `0.0.0.0`. Captured state (`state.json`) is
git-ignored; only the scrubbed `state.example.json` is committed. The repo is private.

## Files

`menubar.py` (the app) · `collectors.py` (the signal readers) · `server.py` + `index.html`
(dashboard) · `start.sh` · `requirements.txt` · `state.example.json` (the `track` contract).
