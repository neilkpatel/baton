#!/usr/bin/env python3
"""Baton menu bar app — the ambient "is the baton with me?" glance.

The menu bar title shows the live waiting count. Click the icon for the full
dropdown (waiting → working → done): each track is CLICKABLE to jump to it — a
Claude session raises its Terminal.app tab, a Codex thread opens via codex://
deep link. "Open full dashboard" spins up server.py on demand (127.0.0.1 only).
Read-only; never mutates your session state.

Run:  .venv/bin/python menubar.py     (or double-click baton.command)
Deps: rumps (in .venv). Stdlib otherwise.
"""
import os, sys, socket, subprocess, time, json, webbrowser

import rumps

try:
    import FSEvents
    import CoreFoundation
    _HAVE_FSEVENTS = True
except Exception:
    _HAVE_FSEVENTS = False

import collectors

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(HERE, "icons", "baton-color.png")   # colorful relay-runner mark
_HAVE_ICON = os.path.exists(ICON_PATH)                        # color icon (template=False → real colors)
PORT = int(os.environ.get("BATON_PORT", "8787"))
URL = f"http://127.0.0.1:{PORT}"
POLL_SEC = 5              # pure-poll interval when the file watcher is unavailable
FALLBACK_SEC = 15         # slow safety-net poll when the watcher IS active (git/recency/relative times)
WATCH_LATENCY = 0.3       # FSEvents coalesce window → sub-second hand-off detection
MAX_ITEMS = 8             # tracks listed per bucket before "…and N more"
TITLE_LEN = 46            # dropdown item label width
PEEK_LEN = 40             # menu bar one-line peek at the top pending session

PREFS_PATH = os.path.expanduser("~/.config/baton/prefs.json")
NOTIFY_SOUND = ""         # silent by default; the menu bar is the ambient channel

SOURCE_LABEL = {"claude": "Claude Code", "codex_thread": "Codex",
                "codex_automation": "Automation", "git": "Git", "manual": "Manual"}
SOURCE_ORDER = ["claude", "codex_thread", "codex_automation", "git", "manual"]


# --------------------------------------------------------------------------
# Preferences — small JSON so the notify choice survives login/restart.
# --------------------------------------------------------------------------
def _load_prefs():
    d = {"notify": False, "seen": {}}   # banner OFF by default; seen = acknowledged hand-offs
    try:
        with open(PREFS_PATH) as f:
            d.update(json.load(f))
    except Exception:
        pass
    return d


def _save_prefs(prefs):
    try:
        os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
        with open(PREFS_PATH, "w") as f:
            json.dump(prefs, f)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
def _notify(title, message, subtitle="", sound=NOTIFY_SOUND):
    """macOS notification via osascript — reliable from an unbundled app."""
    def esc(s):
        return (s or "").replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    if subtitle:
        script += f' subtitle "{esc(subtitle)}"'
    if sound:
        script += f' sound name "{esc(sound)}"'
    try:
        subprocess.run(["osascript", "-e", script],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass


def _jump_to_terminal(tty):
    """Raise the Terminal.app tab whose tty matches. tty like 'ttys002'."""
    dev = tty if tty.startswith("/dev/") else "/dev/" + tty
    script = (
        'tell application "Terminal"\n'
        '  activate\n'
        '  repeat with w in windows\n'
        '    repeat with t in tabs of w\n'
        f'      if (tty of t) is "{dev}" then\n'
        '        set selected of t to true\n'
        '        set index of w to 1\n'
        '        return\n'
        '      end if\n'
        '    end repeat\n'
        '  end repeat\n'
        'end tell'
    )
    try:
        subprocess.run(["osascript", "-e", script],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass


def _open_codex_thread(tid):
    """Jump to a Codex thread via its registered deep link (com.openai.codex)."""
    try:
        subprocess.run(["open", f"codex://threads/{tid}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass


_FRONT_CACHE = {"tty": "", "ts": 0.0}
_FRONT_TTL = 2.0          # brief cache: reflects tab-switches fast without an osascript per event


def _frontmost_terminal_tty():
    """tty of the Terminal tab you currently have OPEN (front window's selected tab),
    or '' when Terminal isn't the frontmost app. We ask Terminal's own `frontmost`
    property — no Accessibility grant needed, just the Terminal automation we already
    use to jump. Short-cached so a burst of file-watch events doesn't spawn an
    osascript each time. Fails open (''), so exclusion never hides more than intended."""
    now = time.time()
    if now - _FRONT_CACHE["ts"] < _FRONT_TTL:
        return _FRONT_CACHE["tty"]
    # The `is running` guard matters: a bare `tell application "Terminal"` LAUNCHES
    # Terminal just to answer the question — on a machine whose user lives in
    # iTerm/Ghostty, Baton would silently relaunch Terminal.app on every refresh.
    script = ('set theTty to ""\n'
              'if application "Terminal" is running then\n'
              '  tell application "Terminal"\n'
              '    if frontmost then\n'
              '      try\n'
              '        set theTty to (tty of selected tab of front window) as text\n'
              '      end try\n'
              '    end if\n'
              '  end tell\n'
              'end if\n'
              'theTty')
    try:
        out = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=3)
        tty = (out.stdout or "").strip().replace("/dev/", "")
    except Exception:
        tty = ""
    _FRONT_CACHE["tty"] = tty
    _FRONT_CACHE["ts"] = now
    return tty


def _server_up():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def _ensure_server():
    """Start server.py detached if it isn't already listening. Bound to loopback."""
    if _server_up():
        return
    subprocess.Popen(
        [sys.executable, os.path.join(HERE, "server.py"), "--port", str(PORT)],
        cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(40):
        if _server_up():
            return
        time.sleep(0.1)


_APP = None  # the running Baton instance, so the C-level FSEvents callback can reach it


def _fsevents_cb(streamRef, clientInfo, num, paths, flags, ids):
    """Fires (on the main run loop) the moment ~/.claude/sessions changes."""
    if _APP is not None:
        try:
            _APP.refresh(None)
        except Exception:
            pass


class Baton(rumps.App):
    def __init__(self):
        super().__init__("Baton",
                         icon=ICON_PATH if _HAVE_ICON else None,
                         template=False, quit_button=None)
        self._waiting_ids = set()   # which sessions were waiting last refresh
        self._primed = False        # skip the first pass so login doesn't fire a burst
        self.prefs = _load_prefs()
        global _APP
        _APP = self
        self._fsstream = None
        watching = self._start_watcher()   # event-driven: refresh the instant a session flips
        self._timer = rumps.Timer(self.refresh, FALLBACK_SEC if watching else POLL_SEC)
        self._timer.start()
        self.refresh(None)

    def _start_watcher(self):
        """Watch ~/.claude/sessions with FSEvents so a hand-off is caught in <1s
        instead of on the next poll — and we idle (no wakeups) in between. Returns
        False if FSEvents is unavailable, in which case we fall back to POLL_SEC."""
        if not _HAVE_FSEVENTS:
            return False
        try:
            stream = FSEvents.FSEventStreamCreate(
                None, _fsevents_cb, None, [collectors.SESSIONS_DIR],
                FSEvents.kFSEventStreamEventIdSinceNow, WATCH_LATENCY,
                FSEvents.kFSEventStreamCreateFlagFileEvents
                | FSEvents.kFSEventStreamCreateFlagNoDefer)
            if not stream:
                return False
            FSEvents.FSEventStreamScheduleWithRunLoop(
                stream, CoreFoundation.CFRunLoopGetCurrent(),
                CoreFoundation.kCFRunLoopDefaultMode)
            if not FSEvents.FSEventStreamStart(stream):
                return False
            self._fsstream = stream   # keep a ref so it isn't garbage-collected
            return True
        except Exception:
            return False

    # --- menu building ---------------------------------------------------
    def _uniq(self, title, seen):
        """rumps keys menu items by title; two sessions can collide.
        Append invisible spaces to guarantee a unique key, same look."""
        while title in seen:
            title += " "
        seen.add(title)
        return title

    def _header(self, text, seen):
        return rumps.MenuItem(self._uniq(text, seen))  # no callback => greyed/disabled

    def _action_for(self, track):
        """Clicking a track jumps to where it lives: Claude → its Terminal tab,
        git → the project folder, everything else → the dashboard. If the track is
        a waiting hand-off, going to it also *acknowledges* it, so it drops off the
        count until it produces a new answer."""
        ex = track.get("extras") or {}
        src = track.get("source")
        tty = ex.get("tty") or ""
        if src == "claude" and tty.startswith("ttys"):
            base = lambda sender, tty=tty: _jump_to_terminal(tty)
        elif src == "codex_thread" and ex.get("threadId"):
            base = lambda sender, tid=ex["threadId"]: _open_codex_thread(tid)
        else:
            base = self.open_dashboard

        def handler(sender, track=track, base=base):
            if track.get("status") == "waiting":
                self._mark_seen(track)
            base(sender)
            self.refresh(None)            # count drops the instant you go deal with it
        return handler

    def _section(self, emoji, label, group, seen):
        rows = [self._header(f"{emoji} {label} ({len(group)})", seen)]
        for t in group[:MAX_ITEMS]:
            lbl = self._uniq("    " + collectors._trunc(t["title"], TITLE_LEN), seen)
            rows.append(rumps.MenuItem(lbl, callback=self._action_for(t)))
        if len(group) > MAX_ITEMS:
            rows.append(self._header(f"    …and {len(group) - MAX_ITEMS} more", seen))
        return rows

    def _waiting_section(self, waiting, seen):
        """The hero bucket, sub-grouped by tool (Claude Code / Codex / …)."""
        rows = [self._header(f"🎽 Baton's with you ({len(waiting)})", seen)]
        by_src = {}
        for t in waiting:
            by_src.setdefault(t["source"], []).append(t)
        srcs = ([s for s in SOURCE_ORDER if s in by_src]
                + [s for s in by_src if s not in SOURCE_ORDER])
        for s in srcs:
            items = by_src[s]
            rows.append(self._header(f"    {SOURCE_LABEL.get(s, s)} ({len(items)})", seen))
            for t in items[:MAX_ITEMS]:
                lbl = self._uniq("       " + collectors._trunc(t["title"], TITLE_LEN - 3), seen)
                rows.append(rumps.MenuItem(lbl, callback=self._action_for(t)))
            if len(items) > MAX_ITEMS:
                rows.append(self._header(f"       …and {len(items) - MAX_ITEMS} more", seen))
        return rows

    # --- main loop -------------------------------------------------------
    def refresh(self, _):
        try:
            state = collectors.collect_all()
        except Exception as e:
            self.title = " ⚠" if _HAVE_ICON else "🎽 ⚠"   # runner icon stays; flag the error
            self.menu.clear()
            self.menu = [rumps.MenuItem(f"error: {e}"[:80]), None,
                         rumps.MenuItem("Quit Baton", callback=rumps.quit_application)]
            return

        tracks = state["tracks"]
        # Acknowledged hand-offs drop off the count until they produce a NEW answer.
        # A session is "seen" iff its id maps to its current lastActive signature —
        # a fresh answer changes lastActive, so a real new hand-off re-surfaces. This
        # is what makes the number go DOWN when you actually deal with a session
        # (otherwise an answered-but-unreplied session lingers as "waiting" for 24h).
        seen_sig = self.prefs.setdefault("seen", {})

        # A Claude session you currently have OPEN in Terminal counts as READ — the
        # same way opening a Codex thread clears its blue dot. Claude Code has no
        # native read/unread flag, so "you're looking at the tab" is the truest signal
        # we have. Persist it as seen at its current answer so it STAYS cleared after
        # you switch tabs, and only re-surfaces when that session answers again.
        front = _frontmost_terminal_tty()
        if front:
            for t in tracks:
                if (t.get("status") == "waiting" and t.get("source") == "claude"
                        and (t.get("extras") or {}).get("tty") == front
                        and seen_sig.get(t["id"]) != t.get("lastActive")):
                    seen_sig[t["id"]] = t.get("lastActive")
                    _save_prefs(self.prefs)

        waiting = [t for t in tracks if t["status"] == "waiting"
                   and seen_sig.get(t["id"]) != t.get("lastActive")]

        # Prune signatures for tracks that no longer exist (keep prefs bounded) —
        # but NEVER on a pass where a collector errored: its tracks are missing,
        # not gone, and pruning then would wipe those acks so every one of them
        # resurrects as "waiting" when the collector recovers a refresh later.
        if seen_sig and not state.get("errors"):
            live = {t["id"] for t in tracks}
            stale = [k for k in seen_sig if k not in live]
            if stale:
                for k in stale:
                    del seen_sig[k]
                _save_prefs(self.prefs)
        self._waiting_now = list(waiting)
        done = [t for t in tracks if t["status"] == "done"]
        working = [t for t in tracks if t["status"] == "working"]

        # Menu bar title: just the clean count. The *what* (themes) lives one click
        # away in the dropdown — a status-bar title truncates and looks sloppy.
        n = len(waiting)
        # The runner mark carries the identity; show the count only when >0 so an
        # idle bar is just the clean glyph (no nagging "0"). Emoji fallback if the
        # icon asset is ever missing.
        noun = "baton" if n == 1 else "batons"
        if _HAVE_ICON:
            self.title = f" {n} {noun} for you" if n else ""
        else:
            self.title = f"🎽 {n} {noun} for you" if n else "🎽"

        # Push the hand-off — only if you've opted the banner on (default off).
        cur = {t["id"] for t in waiting}
        if self._primed and self.prefs.get("notify", False):
            new = [t for t in waiting if t["id"] not in self._waiting_ids]
            if len(new) == 1:
                _notify("🎽 The baton's with you", collectors._trunc(new[0]["title"], 120),
                        subtitle=new[0].get("project") or "")
            elif len(new) > 1:
                _notify("🎽 The baton's with you", f"{len(new)} sessions just handed back to you")
        self._waiting_ids = cur
        self._primed = True

        stamp = time.strftime("%-I:%M %p", time.localtime(state["generatedAt"] / 1000))
        seen = set()
        rows = [self._header("↩ Click a session to jump and clear it", seen),
                self._header(f"Baton · updated {stamp}", seen), None]
        rows += self._waiting_section(waiting, seen) + [None]
        rows += self._section("🟢", "Working", working, seen) + [None]
        rows += self._section("✅", "Done, unreviewed", done, seen) + [None]

        notify_item = rumps.MenuItem("Notify me on hand-off", callback=self.toggle_notify)
        notify_item.state = 1 if self.prefs.get("notify", False) else 0
        rows += [
            rumps.MenuItem("Open full dashboard →", callback=self.open_dashboard),
            rumps.MenuItem("Refresh now", callback=self.refresh),
        ]
        if self._waiting_now:
            rows.append(rumps.MenuItem(f"✓ Mark all {len(self._waiting_now)} as seen",
                                       callback=self.clear_waiting))
        rows += [
            None,
            notify_item,
            None,
            rumps.MenuItem("Quit Baton", callback=rumps.quit_application),
        ]
        self.menu.clear()
        self.menu = rows

    # --- actions ---------------------------------------------------------
    def _mark_seen(self, track):
        """Acknowledge a hand-off: remember this exact answer so it leaves the
        count until the session answers again (signature = lastActive)."""
        self.prefs.setdefault("seen", {})[track["id"]] = track.get("lastActive")
        _save_prefs(self.prefs)

    def clear_waiting(self, _):
        """Mark every currently-waiting session as seen → the count goes to 0
        until something genuinely new hands back to you."""
        seen_sig = self.prefs.setdefault("seen", {})
        for t in getattr(self, "_waiting_now", []):
            seen_sig[t["id"]] = t.get("lastActive")
        _save_prefs(self.prefs)
        self.refresh(None)

    def open_dashboard(self, _):
        _ensure_server()
        webbrowser.open(URL)

    def toggle_notify(self, sender):
        self.prefs["notify"] = not self.prefs.get("notify", False)
        sender.state = 1 if self.prefs["notify"] else 0
        _save_prefs(self.prefs)


if __name__ == "__main__":
    os.chdir(HERE)
    Baton().run()
