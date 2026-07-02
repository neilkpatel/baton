"""Baton collectors — read the signals your machine already emits and normalize
each into a `track` record. Stdlib only, no pip deps. Read-only; never mutates state.

track = {id, source, title, project, status, lastActive(ms), detail, alive, extras}
status in {working, waiting, done, idle, scheduled}

Two lanes: claude/codex/automations are cheap → computed every request (hot).
git shells out across ~48 repos → cached (cold). See collect_all().
"""
import os, re, glob, json, time, subprocess
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
SESSIONS_DIR = os.path.join(HOME, ".claude", "sessions")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
CODEX_INDEX = os.path.join(HOME, ".codex", "session_index.jsonl")
CODEX_SESSIONS = os.path.join(HOME, ".codex", "sessions")
CODEX_ARCHIVED = os.path.join(HOME, ".codex", "archived_sessions")
CODEX_STATE = os.path.join(HOME, ".codex", ".codex-global-state.json")
AUTOMATIONS_GLOB = os.path.join(HOME, ".codex", "automations", "*", "automation.toml")
PROJECTS_ROOT = os.path.join(HOME, "Desktop", "Projects")

MIN, HR, DAY = 60_000, 3_600_000, 86_400_000


def now_ms():
    return int(time.time() * 1000)


def _short(path):
    """Collapse the home dir to ~ for display."""
    if path and path.startswith(HOME):
        return "~" + path[len(HOME):]
    return path or ""


def _ago(ts):
    if not ts:
        return "unknown"
    d = now_ms() - ts
    if d < MIN:
        return "just now"
    if d < HR:
        return f"{round(d / MIN)}m ago"
    if d < DAY:
        return f"{round(d / HR)}h ago"
    days = round(d / DAY)
    return "yesterday" if days == 1 else f"{days}d ago"


def _iso_ms(s):
    if not s:
        return 0
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def _alive(pid):
    """Liveness without spawning a process. os.kill(pid,0) = signal-test only."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


# ----------------------------------------------------------------------------
# Claude Code sessions — the star signal
# ----------------------------------------------------------------------------
def _trunc(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _clean(s):
    """One-line, collapsed whitespace, harness/command wrappers + image tags stripped."""
    s = (s or "").strip()
    if s.startswith("<") or s.startswith("Caveat:"):
        return ""  # slash-command wrapper, local-command-stdout, or injected caveat
    s = re.sub(r"\[Image[^\]]*\]", "", s)  # drop pasted-image placeholders ("[Image #2]", "[Image: source: …]")
    return re.sub(r"\s+", " ", s).strip()


def _text_from_content(c):
    """Pull human/assistant prose out of a message `content` (str or block list).
    Ignores tool_use / tool_result blocks — those aren't the turn's meaning."""
    if isinstance(c, str):
        return _clean(c)
    if isinstance(c, list):
        for b in reversed(c):
            if isinstance(b, dict) and b.get("type") == "text":
                t = _clean(b.get("text"))
                if t:
                    return t
    return ""


def _ttys():
    """pid -> controlling tty, one ps call. Terminal.app reports it as '/dev/<tty>',
    so a click can map a session back to its exact terminal tab."""
    out = {}
    try:
        raw = subprocess.check_output(["ps", "-Ao", "pid=,tty="], text=True)
    except Exception:
        return out
    for line in raw.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            try:
                out[int(parts[0])] = parts[1].strip()
            except ValueError:
                pass
    return out


def _last_context(session_id):
    """Single tail read of the transcript → what this session is *about*.
    Returns dict: role/block of the last meaningful entry (for waiting-detection),
    plus `ask` (most recent real user prompt) and `answer` (last assistant prose)."""
    empty = {"role": None, "block": None, "ask": "", "answer": "", "topic": "", "aiTitle": ""}
    cands = glob.glob(os.path.join(PROJECTS_DIR, "*", session_id + ".jsonl"))
    if not cands:
        return empty
    try:
        with open(cands[0], "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 262144))  # last 256KB holds the final turns
            chunk = f.read().decode("utf-8", "ignore")
    except Exception:
        return empty
    last = ask = answer = topic = ai_title = None
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        typ = o.get("type")
        if typ == "ai-title":                    # Claude Code's own running summary of the session
            at = _clean(o.get("aiTitle"))
            if at:
                ai_title = at
            continue
        if typ not in ("user", "assistant"):
            continue
        last = o
        msg = o.get("message")
        c = msg.get("content") if isinstance(msg, dict) else None
        text = _text_from_content(c)
        if not text:
            continue
        if typ == "user":
            ask = text
            if len(text) >= 15:      # last *substantive* prompt — survives thin "yes"/"go"/image turns
                topic = text
        else:
            answer = text
    if not last:
        return empty
    role = last.get("type")
    block = None
    msg = last.get("message")
    if isinstance(msg, dict):
        c = msg.get("content")
        if isinstance(c, list) and c:
            lb = c[-1]
            block = lb.get("type") if isinstance(lb, dict) else "text"
        elif isinstance(c, str):
            block = "text"
    return {"role": role, "block": block, "ask": ask or "", "answer": answer or "",
            "topic": topic or "", "aiTitle": ai_title or ""}


def collect_claude():
    out = []
    ttys = _ttys()
    for f in glob.glob(os.path.join(SESSIONS_DIR, "*.json")):
        try:
            with open(f) as fh:
                s = json.load(fh)
        except Exception:
            continue
        sid = s.get("sessionId")
        if not sid:
            continue
        pid = s.get("pid")
        alive = _alive(pid)
        cwd = s.get("cwd") or ""
        name = s.get("name") or ""
        derived = s.get("nameSource") == "derived"
        updated = s.get("updatedAt") or s.get("statusUpdatedAt") or 0
        raw = s.get("status")

        ctx = _last_context(sid) if sid else {"role": None, "block": None, "ask": "",
                                              "answer": "", "topic": "", "aiTitle": ""}
        ask, answer, topic = ctx["ask"], ctx["answer"], ctx.get("topic", "")
        theme = ctx.get("aiTitle", "")

        # The specific current thing (used in the detail line): last substantive
        # prompt (skips thin "yes"/"go"/pasted-image turns), then any prompt, then answer.
        about = topic or ask or answer

        # Headline = the session THEME. Prefer a deliberate (non-derived) name, then
        # Claude Code's own running summary (ai-title), then the specific ask.
        title = (name if name and not derived
                 else theme or _trunc(about, 70) or name or (os.path.basename(cwd) if cwd else sid[:8]))

        if not alive:
            status, detail = "idle", "Session ended"
        elif raw == "busy":
            status = "working"
            detail = f"Working on: {_trunc(about, 90)}" if about else "Claude is working"
        else:  # alive but not busy → waiting on you, or genuinely idle
            age = now_ms() - updated if updated else DAY * 999
            if ctx["role"] == "assistant" and ctx["block"] == "text" and age < DAY:
                status = "waiting"
                detail = (f"Answered — baton's with you: {_trunc(answer or about, 90)}"
                          if (answer or about) else "Claude answered and is waiting — the baton's with you")
            else:
                status, detail = "idle", f"Idle — last active {_ago(updated)}"

        out.append({
            "id": "claude:" + sid, "source": "claude", "title": title,
            "project": _short(cwd), "status": status, "lastActive": updated,
            "detail": detail, "alive": alive,
            "extras": {"sessionName": name, "pid": pid, "tty": ttys.get(pid, ""),
                       "ask": ask, "answer": answer},
        })
    return out


# ----------------------------------------------------------------------------
# Codex threads — waiting detected from the rollout transcript's task_complete
# ----------------------------------------------------------------------------
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_codex_roll_cache = {"ts": 0.0, "map": {}}
CODEX_ROLL_TTL = 30.0


def _codex_rollouts():
    """thread-id -> newest rollout .jsonl path. Cached ~30s (globbing is the cost)."""
    if _codex_roll_cache["map"] and time.time() - _codex_roll_cache["ts"] < CODEX_ROLL_TTL:
        return _codex_roll_cache["map"]
    out = {}
    for pat in (os.path.join(CODEX_SESSIONS, "**", "rollout-*.jsonl"),
                os.path.join(CODEX_ARCHIVED, "rollout-*.jsonl")):
        for p in glob.glob(pat, recursive=True):
            m = _UUID_RE.search(os.path.basename(p))
            if not m:
                continue
            tid = m.group(0)
            if tid not in out or os.path.getmtime(p) > os.path.getmtime(out[tid]):
                out[tid] = p
    _codex_roll_cache.update(ts=time.time(), map=out)
    return out


def _codex_tail_state(path):
    """Read the rollout tail → (completed, answer). completed=True when the last
    turn-boundary event is `task_complete` (agent finished → the baton's with you)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 131072))
            chunk = f.read().decode("utf-8", "ignore")
    except Exception:
        return (False, "")
    completed, answer = None, ""
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        typ = e.get("type")
        payload = e.get("payload") if isinstance(e.get("payload"), dict) else e
        sub = payload.get("type")
        if typ == "event_msg":
            if sub == "task_complete":
                completed = True
            elif sub in ("task_started", "turn_aborted", "error", "stream_error"):
                completed = False
            elif sub == "agent_message":
                a = _clean(payload.get("message") or payload.get("text") or "")
                if a:
                    answer = a
        elif typ == "response_item" and sub == "message" and payload.get("role") == "assistant":
            a = _text_from_content(payload.get("content"))
            if a:
                answer = a
    return (bool(completed), answer)


_codex_unread_cache = {"ts": 0.0, "ids": set()}
CODEX_UNREAD_TTL = 15.0


def _codex_unread_ids():
    """The set of Codex thread ids with the blue 'unread' dot — Codex's own signal
    that a thread has output you haven't looked at. Lives in the Electron UI state
    under `unread-thread-ids-by-host-v1`. This IS Codex's 'baton's with you'."""
    if time.time() - _codex_unread_cache["ts"] < CODEX_UNREAD_TTL:
        return _codex_unread_cache["ids"]
    ids = set()
    try:
        d = json.load(open(CODEX_STATE, encoding="utf-8"))
        atom = d.get("electron-persisted-atom-state")
        a = json.loads(atom) if isinstance(atom, str) else atom
        for host, lst in (a.get("unread-thread-ids-by-host-v1") or {}).items():
            if isinstance(lst, list):
                ids.update(lst)
    except Exception:
        pass
    _codex_unread_cache.update(ts=time.time(), ids=ids)
    return ids


def collect_codex_threads(within_days=3):
    if not os.path.exists(CODEX_INDEX):
        return []
    # Dedupe by thread NAME (keep newest) — automations spawn many same-named threads
    # ("Automation Hub Refresh" x N); collapsing them keeps the view about distinct work.
    best = {}
    try:
        with open(CODEX_INDEX, errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                tid = o.get("id")
                if not tid:
                    continue
                name = o.get("thread_name") or "(untitled thread)"
                ts = _iso_ms(o.get("updated_at"))
                if name not in best or ts > best[name]["ts"]:
                    best[name] = {"id": tid, "name": name, "ts": ts}
    except Exception:
        return []
    out = []
    cutoff = now_ms() - within_days * DAY
    unread = _codex_unread_ids()   # the blue-dot set = genuinely waiting on you
    rollouts = _codex_rollouts()
    for v in best.values():
        tid = v["id"]
        is_unread = tid in unread
        # Always show unread (a blue dot persists); others only if recent.
        if not is_unread and v["ts"] < cutoff:
            continue
        age = now_ms() - v["ts"]
        answer = ""
        if is_unread:
            path = rollouts.get(tid)
            if path:
                _, answer = _codex_tail_state(path)   # agent's closing line, for the detail
            status = "waiting"
            detail = (f"Codex — baton's with you: {_trunc(answer, 90)}"
                      if answer else "Codex has unread output — the baton's with you")
        elif age < 30 * MIN:
            status = "working"
            detail = "Codex is working · " + _ago(v["ts"])
        else:
            status = "idle"
            detail = "Codex thread · last active " + _ago(v["ts"])

        out.append({
            "id": "codex_thread:" + tid, "source": "codex_thread", "title": v["name"],
            "project": "", "status": status, "lastActive": v["ts"],
            "detail": detail, "alive": age < 30 * MIN,
            "extras": {"answer": answer, "threadId": tid},
        })
    return out


# ----------------------------------------------------------------------------
# Codex automations — scheduled pipelines (+ a minimal RRULE engine)
# ----------------------------------------------------------------------------
import tomllib

_WD = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _parse_rrule(rrule_str):
    """rrule_str like 'DTSTART:20260621T030000\\nRRULE:FREQ=DAILY;BYHOUR=3;...'"""
    dtstart, rule = None, {}
    for tok in re.split(r"\s+", (rrule_str or "").strip()):
        if tok.startswith("DTSTART:"):
            v = tok[len("DTSTART:"):].rstrip("Z")
            try:
                dtstart = datetime.strptime(v, "%Y%m%dT%H%M%S")
            except Exception:
                dtstart = None
        elif tok.startswith("RRULE:"):
            for kv in tok[len("RRULE:"):].split(";"):
                if "=" in kv:
                    k, val = kv.split("=", 1)
                    rule[k.upper()] = val.upper()
    return dtstart, rule


def _runs(rrule_str, now_dt, horizon_days=31):
    """Return (last_run, next_run) datetimes for the simple FREQ shapes present."""
    dtstart, rule = _parse_rrule(rrule_str)
    if not dtstart:
        return (None, None)
    freq = rule.get("FREQ", "")
    interval = int(rule.get("INTERVAL", "1") or 1)
    count = rule.get("COUNT")
    count = int(count) if (count and count.isdigit()) else None
    hh = int(rule.get("BYHOUR", dtstart.hour) or 0)
    mm = int(rule.get("BYMINUTE", 0) or 0)
    ss = int(rule.get("BYSECOND", 0) or 0)
    end = now_dt + timedelta(days=horizon_days)
    occ = []

    if freq == "DAILY":
        d = dtstart.replace(hour=hh, minute=mm, second=ss, microsecond=0)
        i = 0
        while d <= end and (count is None or i < count) and i < 20000:
            occ.append(d); d += timedelta(days=interval); i += 1
    elif freq == "WEEKLY":
        days = sorted(_WD[x] for x in rule.get("BYDAY", "").split(",") if x in _WD) or [dtstart.weekday()]
        week0 = (dtstart - timedelta(days=dtstart.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        w = 0
        while w < 20000:
            wk = week0 + timedelta(weeks=w * interval)
            if wk > end + timedelta(weeks=interval):
                break
            for dow in days:
                d = (wk + timedelta(days=dow)).replace(hour=hh, minute=mm, second=ss, microsecond=0)
                if d >= dtstart and d <= end:
                    occ.append(d)
            w += 1
    elif freq == "MINUTELY":
        d = dtstart.replace(second=ss, microsecond=0)
        cap = now_dt + timedelta(days=1)
        i = 0
        while d <= cap and (count is None or i < count) and i < 100000:
            occ.append(d); d += timedelta(minutes=interval); i += 1
    else:
        return (None, None)

    occ.sort()
    last = nxt = None
    for d in occ:
        if d <= now_dt:
            last = d
        elif nxt is None:
            nxt = d
    return (last, nxt)


def _describe_rrule(rrule_str):
    _, rule = _parse_rrule(rrule_str)
    freq = rule.get("FREQ", "")
    hh = rule.get("BYHOUR")
    iv = rule.get("INTERVAL")
    suffix = f" {int(hh):02d}:00" if hh else ""
    if freq == "DAILY":
        return ("daily" if not iv or iv == "1" else f"every {iv} days") + suffix
    if freq == "WEEKLY":
        pre = "weekly" if not iv or iv == "1" else f"every {iv} weeks"
        return f"{pre} {rule.get('BYDAY','')}".strip() + suffix
    if freq == "MINUTELY":
        return f"every {iv or 1} min"
    return "scheduled"


def collect_automations():
    out = []
    now_dt = datetime.now()
    for f in glob.glob(AUTOMATIONS_GLOB):
        try:
            with open(f, "rb") as fh:
                d = tomllib.load(fh)
        except Exception:
            continue
        if str(d.get("status", "")).upper() != "ACTIVE":
            continue
        slug = os.path.basename(os.path.dirname(f))
        name = d.get("name") or slug
        cwds = d.get("cwds") or []
        proj = _short(cwds[0]) if cwds else ""
        rrule = d.get("rrule") or ""
        last, nxt = _runs(rrule, now_dt)
        last_ms = int(last.timestamp() * 1000) if last else 0
        next_ms = int(nxt.timestamp() * 1000) if nxt else 0
        # "ran since you last looked" → surface as done-unreviewed (frontend clears via seen[])
        recently_ran = last_ms and (now_ms() - last_ms) < 12 * HR
        status = "done" if recently_ran else "scheduled"
        detail = (f"ran {_ago(last_ms)} · {_describe_rrule(rrule)}" if recently_ran
                  else _describe_rrule(rrule))
        out.append({
            "id": "automation:" + slug, "source": "codex_automation", "title": name,
            "project": proj, "status": status,
            "lastActive": last_ms or d.get("updated_at", 0), "detail": detail, "alive": True,
            "extras": {"nextRun": next_ms, "lastRun": last_ms,
                       "model": d.get("model", ""), "rrule": rrule},
        })
    return out


# ----------------------------------------------------------------------------
# Git work-in-flight — cold lane, cached
# ----------------------------------------------------------------------------
_git_cache = {"ts": 0.0, "data": []}
GIT_TTL = 45  # seconds


def _git(args, cwd, timeout=5):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout)


def collect_git(force=False):
    if not force and (time.time() - _git_cache["ts"]) < GIT_TTL:
        return _git_cache["data"]
    out = []
    try:
        entries = sorted(os.listdir(PROJECTS_ROOT))
    except FileNotFoundError:
        entries = []
    for entry in entries:
        p = os.path.join(PROJECTS_ROOT, entry)
        if not os.path.isdir(p) or not os.path.isdir(os.path.join(p, ".git")):
            continue
        try:
            st = _git(["status", "--porcelain"], p)
            changed = len([l for l in st.stdout.splitlines() if l.strip()])
            lg = _git(["log", "-1", "--format=%ct\x1f%s"], p)
            ct, subj = 0, ""
            if lg.stdout.strip():
                parts = lg.stdout.strip().split("\x1f", 1)
                ct = int(parts[0]) * 1000
                subj = parts[1] if len(parts) > 1 else ""
        except Exception:
            continue
        age = now_ms() - ct if ct else DAY * 999
        # Skip the noise: repos whose last commit is ancient (abandoned), unless brand new (no commits).
        if ct and age > 21 * DAY:
            continue
        if changed == 0:
            if age > 14 * DAY:
                continue  # clean and not recent — nothing in flight here
            status = "idle"; detail = f"clean · last commit {_ago(ct)}"
        elif not ct:
            status = "done"; detail = f"{changed} uncommitted · new repo — ready to commit"
        elif age < 2 * HR:
            status = "working"; detail = f"{changed} changed · last commit {_ago(ct)}"
        elif age < 7 * DAY:
            status = "done"; detail = f"{changed} uncommitted · last commit {_ago(ct)} — ready to review or commit"
        else:
            status = "idle"; detail = f"{changed} uncommitted · last commit {_ago(ct)} (stale)"
        out.append({
            "id": "git:" + entry, "source": "git", "title": entry, "project": _short(p),
            "status": status, "lastActive": ct, "detail": detail, "alive": True,
            "extras": {"changedCount": changed, "lastCommit": ct, "subject": subj},
        })
    _git_cache["ts"] = time.time()
    _git_cache["data"] = out
    return out


# ----------------------------------------------------------------------------
# Assemble
# ----------------------------------------------------------------------------
def collect_all():
    tracks, errors = [], []
    # git repo tracking intentionally omitted — not relevant to this workflow
    # (collect_git remains defined but unused; re-add here to bring it back).
    for name, fn in (("claude", collect_claude),
                     ("codex_thread", collect_codex_threads),
                     ("codex_automation", collect_automations)):
        try:
            tracks.extend(fn())
        except Exception as e:
            errors.append({"source": name, "msg": str(e)})
    counts = {k: 0 for k in ("working", "waiting", "done", "idle", "scheduled")}
    for t in tracks:
        if t["status"] in counts:
            counts[t["status"]] += 1
    return {"generatedAt": now_ms(), "tracks": tracks, "counts": counts, "errors": errors}


if __name__ == "__main__":
    print(json.dumps(collect_all(), indent=2, default=str))
