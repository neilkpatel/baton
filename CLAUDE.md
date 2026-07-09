# Baton — context for Claude sessions

**Baton** is a local-only macOS command center for every AI agent you have in flight —
Claude Code sessions, Codex threads, and scheduled automations — in one
"where's the baton right now" view. The relay hand-off metaphor is the product: agents run
their leg, then hand the baton back to you. The hero bucket is 🎽 **"the baton's with you"**
(an agent finished its turn and is waiting on your decision).

## Stack & house style
- Dashboard: single-file vanilla **HTML/CSS/JS**, no build step, no framework. Dark theme tokens:
  `--bg:#0b0f14 --panel:#121821 --panel2:#171f2b --line:#243040 --ink:#e8eef6 --muted:#94a3b8`
  `--accent:#2dd4bf --accent2:#38bdf8 --gold:#fbbf24 --red:#f87171 --green:#34d399 --purple:#a78bfa`.
- Backend: **stdlib-only Python** `http.server.ThreadingHTTPServer`, bound to
  `127.0.0.1`, no pip deps. Python 3.10+ (uses `tomllib` when available; `os.kill(pid,0)` for liveness).
- Menu bar app (`menubar.py`): `rumps` + `pyobjc-framework-FSEvents` in an isolated `.venv/`
  (the only two pip deps in the project, see `requirements.txt`).

## The contract (do not break)
Everything is a `track`: `{id, source, title, project, status, lastActive(ms), detail, alive, extras}`,
`status ∈ working|waiting|done|idle|scheduled`. `id` is stable per source (`claude:{sessionId}`,
`codex_thread:{id}`, `automation:{name}`, `git:{dirname}`, `manual:{uuid}`) and is the localStorage
key for seen/dismissed/order. `/api/state` → `{generatedAt, tracks[], counts{}, errors[]}`.
The frontend renders purely from `tracks` + a localStorage overlay (`baton-v1`), so the
sample mock (`SAMPLE_TRACKS` in index.html) and live data drive the identical UI.

## Collectors — verified facts
- **Claude Code (star):** `~/.claude/sessions/{PID}.json` → `status` is only `busy`/`idle`, plus
  `updatedAt`, `cwd`, `sessionId`, optional `name`. For waiting-vs-working on `idle`: glob the
  transcript `~/.claude/projects/*/{sessionId}.jsonl`, filter entries to `type in {user,assistant}`
  (drop `system`/`summary`/`file-history-snapshot`/`permission-mode` noise), take the last — an
  assistant text answer = **waiting** ("baton's with you"). The project-dir name encoding is
  **lossy/irreversible** — never decode it; read `cwd` from the session JSON or from inside the JSONL.
- **Codex threads:** `~/.codex/session_index.jsonl` (one JSON/line: `id`, `thread_name`,
  `updated_at` ISO-Z). Waiting = Codex's own **unread (blue-dot)** state, read from
  `~/.codex/.codex-global-state.json` (`electron-persisted-atom-state` →
  `unread-thread-ids-by-host-v1`). Rollout transcript (`~/.codex/sessions/…rollout-*.jsonl`,
  matched by UUID in filename) supplies the agent's closing line. Dedupe by thread name
  (automations spawn many same-named threads).
- **Codex automations:** `~/.codex/automations/*/automation.toml` (parse with `tomllib`). Filter
  `status=="ACTIVE"`. RRULEs are simple — only `FREQ=DAILY/WEEKLY/MINUTELY` with `BYHOUR/BYDAY/INTERVAL`
  and a `DTSTART` line → ~40-line stdlib parser computes next/last run. "Ran since you last looked"
  (`lastRun` > seen) ⇒ done-unreviewed.
- **Claude ≠ Codex:** separate tools, separate state dirs (`~/.claude` vs `~/.codex`). Not a shared backend.

## Status derivation
working: claude busy · codex thread <30m.
waiting: claude idle + last transcript entry is assistant text + <24h · codex thread unread.
done: automation ran since seen.
idle: alive but >24h, or dead PID. scheduled: active automation w/ future nextRun.

The menu bar app additionally overlays **click-to-acknowledge** (`seen: {trackId: lastActive}`
in `~/.config/baton/prefs.json`): a clicked hand-off leaves the count until the session produces
a NEW answer, and the Claude tab currently frontmost in Terminal is excluded while you're looking at it.

## Files
`menubar.py` (menu bar app) · `collectors.py` (signal readers) · `server.py` + `index.html`
(dashboard) · `start.sh` · `install.sh` (one-command install + LaunchAgent) ·
`state.example.json` (scrubbed contract) · `.gitignore` (ignores real `state*.json`).

## Security
Bind `127.0.0.1` only. The live payload has real prompts/cwds — never `0.0.0.0`, never log it,
keep `state.example.json` and `SAMPLE_TRACKS` scrubbed (they're the committed things that could leak).
Baton is strictly read-only over `~/.claude` and `~/.codex` — it never mutates session state.
