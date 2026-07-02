# Baton 🎽

**A local command center for everything you have in flight** — every AI agent, session, job, and
active project, across every tool, in one view.

As agents do more work unattended, the hard part stops being *doing the work* and becomes
*knowing which of your N running things needs you right now*. Baton reads the signals your
machine already emits (zero manual entry) and sorts everything into action-states. The hero is
the **"the baton's with you"** bucket: agents run their leg, then hand the baton back when they
need a decision — and that's the thing that's easy to drop when you're looking elsewhere.

> North star: a pluggable signal bus with one universal "where's the baton" view on top. Every
> source is a collector that emits the same `track` record, so adding a new signal (Codex &
> Claude today; browser tabs, terminal jobs, CI runs, cloud agents tomorrow) is ~30 lines and
> the UI never changes.

---

## Status: Phase 1 (mockup)

The dashboard is built and runs on **realistic sample data** so the look, feel, and information
architecture are real. The live collectors (`server.py` + `collectors.py`) land in Phases 2–4.

### Run the mock right now

```bash
open index.html
```

That's it — open the file directly. It tries to fetch `/api/state`; when that's unavailable it
falls back to built-in `SAMPLE_TRACKS`, so you see the full UI with no server. A **"mock data"**
chip in the header tells you which mode you're in. Manual to-dos you add persist in `localStorage`.

### Run it live (Phase 2+, once the server exists)

```bash
bash start.sh          # python3 server.py --port 8787  &&  open http://127.0.0.1:8787
```

---

## Signal sources (what gets auto-detected)

| Source | Where it's read | Gives us |
|---|---|---|
| **Claude Code** (star) | `~/.claude/sessions/{PID}.json` + transcripts | live `busy`/`idle` status, cwd, session name → **working vs. waiting-on-you** |
| **Codex threads** | `~/.codex/session_index.jsonl` | named threads + last-active (recency only) |
| **Codex automations** | `~/.codex/automations/*/automation.toml` | scheduled pipelines → next/last run, overdue flags |
| **Git work-in-flight** | `~/Desktop/Projects/*` | uncommitted changes + last commit → working vs. ready-to-review |
| Processes / launchd | `ps`, `launchctl list` | supporting liveness + recurring jobs |

Claude Code (`~/.claude`) and Codex (`~/.codex`) are **separate tools with separate state dirs** —
Baton reads both independently.

## The `track` contract

Everything on screen is a normalized `track` (see `state.example.json` for the full shape):

```
{ id, source, title, project, status, lastActive, detail, alive, extras }
status ∈ working | waiting | done | idle | scheduled
```

Buckets: 🎽 waiting ("the baton's with you") · ✅ done-unreviewed · 🟢 working · ⚪ idle/stale · ⏰ scheduled.
The server owns the facts; the browser owns user-state (reviewed / snoozed / manual to-dos / order)
in `localStorage` under `neil-baton-v1`.

## Tabs

- **Now** — buckets, with 🎽 and ✅ pinned to the top (the stuff that needs you).
- **By Project** — every signal for a folder together (busy Claude + 3 uncommitted files + a thread).
- **Scheduled** — automations by next run; overdue flagged.
- **Manual** — lightweight to-do lane for things no tool is tracking.

## Security

The live payload contains your prompts, cwds, and automation prompts. The server **binds to
`127.0.0.1` only** — never `0.0.0.0`. Captured state (`state.json` etc.) is git-ignored;
`state.example.json` is committed and must stay **scrubbed** of real content.

## Build order

1. **Phase 1 — Mockup** ✅ (this) — full UI on sample data, schema locked.
2. **Phase 2 — Server + Claude** — `server.py` + `collect_claude_sessions()`; the 🎽 bucket goes live.
3. **Phase 3 — Codex** — threads + automations (stdlib RRULE parser).
4. **Phase 4 — Git + processes + manual + launchd** — By-Project tab, 60s git cache.
