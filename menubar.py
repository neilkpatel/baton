#!/usr/bin/env python3
"""Baton menu bar app — the ambient "is the baton with me?" glance.

Lives in the macOS menu bar. The title shows the live "baton's with you"
(waiting) count; the dropdown lists what's waiting on you, what ran while you
were away, and what's working, and can open the full HTML dashboard.

Reads collectors directly — no server needed to glance. "Open full dashboard"
spins up server.py on demand (127.0.0.1 only). Read-only; never mutates state.

Run:  .venv/bin/python menubar.py     (or double-click baton.command)
Deps: rumps (in .venv). Stdlib otherwise.
"""
import os, sys, socket, subprocess, time, webbrowser

import rumps

import collectors

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("BATON_PORT", "8787"))
URL = f"http://127.0.0.1:{PORT}"
REFRESH_SEC = 20          # collectors are cheap; git is cached ~60s inside the process
MAX_ITEMS = 8             # tracks listed per bucket before "…and N more"
TITLE_LEN = 46            # dropdown item label width


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


class Baton(rumps.App):
    def __init__(self):
        super().__init__("🎽", quit_button=None)
        self._timer = rumps.Timer(self.refresh, REFRESH_SEC)
        self._timer.start()
        self.refresh(None)

    # --- helpers ---------------------------------------------------------
    def _uniq(self, title, seen):
        """rumps keys menu items by title; two ~/ sessions can collide.
        Append invisible thin-spaces to guarantee a unique key, same look."""
        while title in seen:
            title += " "
        seen.add(title)
        return title

    def _header(self, text, seen):
        it = rumps.MenuItem(self._uniq(text, seen))  # no callback => greyed/disabled
        return it

    def _section(self, emoji, label, group, seen):
        rows = [self._header(f"{emoji} {label} ({len(group)})", seen)]
        for t in group[:MAX_ITEMS]:
            lbl = self._uniq("    " + collectors._trunc(t["title"], TITLE_LEN), seen)
            rows.append(rumps.MenuItem(lbl, callback=self.open_dashboard))
        if len(group) > MAX_ITEMS:
            rows.append(self._header(f"    …and {len(group) - MAX_ITEMS} more", seen))
        return rows

    # --- main loop -------------------------------------------------------
    def refresh(self, _):
        try:
            state = collectors.collect_all()
        except Exception as e:
            self.title = "🎽 ⚠"
            self.menu.clear()
            self.menu = [rumps.MenuItem(f"error: {e}"[:80]), None,
                         rumps.MenuItem("Quit Baton", callback=rumps.quit_application)]
            return

        tracks = state["tracks"]
        waiting = [t for t in tracks if t["status"] == "waiting"]
        done = [t for t in tracks if t["status"] == "done"]
        working = [t for t in tracks if t["status"] == "working"]

        # Menu bar title = the hero signal: how many batons are waiting on me.
        self.title = f"🎽 {len(waiting)} waiting"

        stamp = time.strftime("%-I:%M %p", time.localtime(state["generatedAt"] / 1000))
        seen = set()
        rows = [self._header(f"Baton · updated {stamp}", seen), None]
        rows += self._section("🎽", "Baton's with you", waiting, seen) + [None]
        rows += self._section("✅", "Done, unreviewed", done, seen) + [None]
        rows += self._section("🟢", "Working", working, seen) + [None]
        rows += [
            rumps.MenuItem("Open full dashboard →", callback=self.open_dashboard),
            rumps.MenuItem("Refresh now", callback=self.refresh),
            None,
            rumps.MenuItem("Quit Baton", callback=rumps.quit_application),
        ]
        self.menu.clear()
        self.menu = rows

    # --- actions ---------------------------------------------------------
    def open_dashboard(self, _):
        _ensure_server()
        webbrowser.open(URL)


if __name__ == "__main__":
    os.chdir(HERE)
    Baton().run()
