#!/usr/bin/env python3
"""Recapture docs/menubar.png: the dropdown screenshot embedded in the social
card and the demo GIF (see scene.html).

Runs a throwaway Baton instance fed FAKE tracks (never your real sessions),
opens its menu programmatically, and screenshots its OWN menu window via
CGWindowListCreateImage. Capturing your own process's windows needs no
Screen Recording permission, so this works headlessly on a stock Mac.

Run from the repo root:  .venv/bin/python docs/src/capture_menubar.py
Needs pyobjc-framework-Quartz in the venv (dev-only, not in requirements.txt).
A second runner icon appears in the menu bar for ~3 seconds; that's this.
"""
import os, sys, time, threading, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "..", "menubar.png")
sys.path.insert(0, ROOT)

import collectors

NOW = int(time.time() * 1000)


def _mk(i, src, title, status):
    return {"id": f"{src}:demo{i}", "source": src, "title": title, "project": "",
            "status": status, "lastActive": NOW - i * 60000, "detail": "",
            "alive": True, "extras": {}}


def fake_state():
    tracks = [
        _mk(1, "claude", "Fix push-notification permissions bug", "waiting"),
        _mk(2, "claude", "Refactor checkout-flow error handling", "waiting"),
        _mk(3, "codex_thread", "Analyze churn cohort data", "waiting"),
        _mk(4, "claude", "Migrate CI pipeline to GitHub Actions", "working"),
        _mk(5, "claude", "Draft API versioning proposal", "working"),
        _mk(6, "codex_automation", "nightly-backup-check", "done"),
    ]
    return {"generatedAt": NOW, "tracks": tracks, "counts": {}, "errors": []}


collectors.collect_all = fake_state

import menubar
# Point prefs at a scratch file so the demo instance can never touch (or prune)
# your real ~/.config/baton/prefs.json, and skip the frontmost-tab osascript.
menubar.PREFS_PATH = os.path.join(tempfile.gettempdir(), "baton-capture-prefs.json")
menubar._frontmost_terminal_tty = lambda: ""

import rumps
from Quartz import (CGWindowListCopyWindowInfo, kCGWindowListOptionAll,
                    kCGNullWindowID, CGWindowListCreateImageFromArray, CGRectNull,
                    kCGWindowImageBestResolution, kCGWindowImageBoundsIgnoreFraming,
                    CGImageDestinationCreateWithURL, CGImageDestinationAddImage,
                    CGImageDestinationFinalize)
from CoreFoundation import CFURLCreateFromFileSystemRepresentation


DBG = os.path.join(tempfile.gettempdir(), "baton-capture-debug.log")


def _log(msg):
    with open(DBG, "a") as f:
        f.write(msg + "\n")
        f.flush()
        os.fsync(f.fileno())


def _capture_and_exit():
    try:
        time.sleep(1.6)   # menu is open and fully rendered by now
        pid = os.getpid()
        wins = [w for w in (CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID) or [])
                if w.get("kCGWindowOwnerPID") == pid]
        _log(f"own windows: {[(int(w['kCGWindowNumber']), dict(w['kCGWindowBounds'])) for w in wins]}")
        if not wins:
            _log("FAIL: no own windows"); os._exit(1)
        menu_win = max(wins, key=lambda w: w["kCGWindowBounds"]["Height"])  # the open dropdown
        # NB: must be the FromArray variant — the single-window CGWindowListCreateImage
        # returns None here, while own-window FromArray needs no Screen Recording TCC.
        img = CGWindowListCreateImageFromArray(
            CGRectNull, [int(menu_win["kCGWindowNumber"])],
            kCGWindowImageBestResolution | kCGWindowImageBoundsIgnoreFraming)
        if img is None:
            _log("FAIL: CGWindowListCreateImageFromArray returned None"); os._exit(1)
        out = os.path.abspath(OUT).encode()
        url = CFURLCreateFromFileSystemRepresentation(None, out, len(out), False)
        dest = CGImageDestinationCreateWithURL(url, "public.png", 1, None)
        CGImageDestinationAddImage(dest, img, None)
        ok = CGImageDestinationFinalize(dest)
        _log(f"wrote {os.path.abspath(OUT)}" if ok else "FAIL: png write")
        os._exit(0 if ok else 1)
    except Exception:
        import traceback
        _log("THREAD EXC:\n" + traceback.format_exc())
        os._exit(1)


app = menubar.Baton()


def _open_menu(_):
    try:
        _log("timer fired; opening menu")
        threading.Thread(target=_capture_and_exit, daemon=True).start()
        # performClick blocks the main loop in menu tracking; the thread above
        # shoots the open menu and exits the whole demo process.
        app._nsapp.nsstatusitem.button().performClick_(None)
    except Exception:
        import traceback
        _log("TIMER EXC:\n" + traceback.format_exc())
        os._exit(1)


_t = rumps.Timer(_open_menu, 1.5)
_t.start()
_log("pre-run")
try:
    app.run()
    _log("run returned")
except SystemExit as e:
    _log(f"SystemExit: {e.code}")
    raise
except BaseException:
    import traceback
    _log("RUN EXC:\n" + traceback.format_exc())
    raise
