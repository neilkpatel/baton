# Baton — context for Claude sessions

**Baton** is a local-only macOS command center for everything in flight on Neil's machine: every
AI agent, session, scheduled job, and active project, in one "where's the baton right now" view.
Named for commercialization (the relay hand-off metaphor = the killer feature: agents work, then
hand the baton back to you). Plan of record: `~/.claude/plans/eager-whistling-bee.md`.

## Stack & house style
- Single-file vanilla **HTML/CSS/JS**, no build step, no framework. Matches the family
  (`6_25_26_ai-job-hunt`, `6_10_26_worldcup`). Dark theme tokens:
  `--bg:#0b0f14 --panel:#121821 --panel2:#171f2b --line:#243040 --ink:#e8eef6 --muted:#94a3b8`
  `--accent:#2dd4bf --accent2:#38bdf8 --gold:#fbbf24 --red:#f87171 --green:#34d399 --purple:#a78bfa`.
- Backend (Phase 2+): **stdlib-only Python** `http.server.ThreadingHTTPServer`, bound to
  `127.0.0.1`, no pip deps. Python 3.14 (has `tomllib`; use `os.kill(pid,0)` for liveness).

## The contract (do not break)
Everything is a `track`: `{id, source, title, project, status, lastActive(ms), detail, alive, extras}`,
`status ∈ working|waiting|done|idle|scheduled`. `id` is stable per source (`claude:{sessionId}`,
`codex_thread:{id}`, `automation:{name}`, `git:{dirname}`, `manual:{uuid}`) and is the localStorage
key for seen/dismissed/order. `/api/state` → `{generatedAt, tracks[], counts{}, errors[]}`.
The frontend renders purely from `tracks` + a localStorage overlay (`neil-baton-v1`), so the
Phase-1 mock (`SAMPLE_TRACKS` in index.html) and live data drive the identical UI.

## Collectors (Phases 2–4) — verified facts
- **Claude (star):** `~/.claude/sessions/{PID}.json` → `status` is only `busy`/`idle`, plus
  `updatedAt`, `cwd`, `sessionId`, optional `name`. For waiting-vs-working on `idle`: glob the
  transcript `~/.claude/projects/*/{sessionId}.jsonl`, filter entries to `type in {user,assistant}`
  (drop `system`/`summary`/`file-history-snapshot`/`permission-mode` noise), take the last — an
  assistant text answer = **waiting** ("baton's with you"). The project-dir name encoding is
  **lossy/irreversible** — never decode it; read `cwd` from the session JSON or from inside the JSONL.
- **Codex threads:** `~/.codex/session_index.jsonl` (one JSON/line: `id`, `thread_name`,
  `updated_at` ISO-Z). No working/waiting signal → classify by recency. Dedupe by `id`.
- **Codex automations:** `~/.codex/automations/*/automation.toml` (parse with `tomllib`). Filter
  `status=="ACTIVE"`. RRULEs are simple — only `FREQ=DAILY/WEEKLY/MINUTELY` with `BYHOUR/BYDAY/INTERVAL`
  and a `DTSTART` line → ~40-line stdlib parser computes next/last run. "Ran since you last looked"
  (`lastRun` > localStorage `seen[id]`) ⇒ done-unreviewed.
- **Git:** iterate `~/Desktop/Projects/*`; guard `isdir` + `.git`. `git status --porcelain` (changed
  count) + `git log -1 --format=%ct%x1f%s`. Include only repos with changes OR commit <14d. Cache ~60s.
- **Claude ≠ Codex:** separate tools, separate state dirs (`~/.claude` vs `~/.codex`). Not a shared backend.

## Status derivation
working: claude busy · git changes+commit<2h · codex thread <30m.
waiting: claude idle + last transcript entry is assistant text + <24h.
done: git changes gone stale · automation ran since `seen`.
idle: alive but >24h, or dead PID. scheduled: active automation w/ future nextRun.

## Files
`index.html` (UI + Phase-1 SAMPLE_TRACKS) · `server.py` (Phase 2+) · `collectors.py` (Phase 2+) ·
`start.sh` · `state.example.json` (scrubbed contract) · `.gitignore` (ignores real `state*.json`).

## Security
Bind `127.0.0.1` only. Payload has real prompts/cwds — never `0.0.0.0`, never log it, keep
`state.example.json` scrubbed (it's the one committed file that could leak).

## Conventions
Git configured (`neilkpatel@gmail.com` / `Neil Patel`). Not committed yet — ask Neil before
committing/pushing. Naming convention `M_D_YY_projectname`.
