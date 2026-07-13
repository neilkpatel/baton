#!/usr/bin/env python3
"""Baton local server. Serves index.html and GET /api/state (live collector run).

Bound to 127.0.0.1 ONLY — the payload contains your prompts, cwds, and automation
prompts. Never bind 0.0.0.0. Stdlib only, no pip deps.
"""
import os, sys, json, argparse, http.server, socketserver

import collectors

HERE = os.path.dirname(os.path.abspath(__file__))
PREFS_PATH = os.path.expanduser("~/.config/baton/prefs.json")


def _apply_seen(state):
    """Overlay the menu bar's acknowledgements (prefs.json `seen`) so both UIs
    agree on what's still waiting. Same rule as menubar.py: a hand-off is
    acknowledged iff its id maps to its current lastActive signature — a NEW
    answer changes lastActive, so it re-surfaces everywhere at once."""
    try:
        with open(PREFS_PATH) as f:
            seen = json.load(f).get("seen", {})
    except Exception:
        return state
    if seen:
        for t in state["tracks"]:
            if t["status"] == "waiting" and seen.get(t["id"]) == t.get("lastActive"):
                t["acknowledged"] = True
    return state


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype, no_store=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/api/state":
            try:
                body = json.dumps(_apply_seen(collectors.collect_all())).encode()
                self._send(200, body, "application/json", no_store=True)
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode(),
                           "application/json", no_store=True)
            return

        # static files (index.html, etc.) — confined to this dir
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        fp = os.path.normpath(os.path.join(HERE, rel))
        if not fp.startswith(HERE) or not os.path.isfile(fp):
            self._send(404, b"not found", "text/plain")
            return
        ctype = ("text/html" if fp.endswith(".html")
                 else "application/json" if fp.endswith(".json")
                 else "image/svg+xml" if fp.endswith(".svg")
                 else "text/plain")
        with open(fp, "rb") as f:
            self._send(200, f.read(), ctype)

    def log_message(self, *args):
        pass  # quiet — never log request bodies/payloads to disk


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("BATON_PORT", "8787")))
    args = ap.parse_args()
    srv = Server(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"🎽  Baton running → {url}   (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        srv.shutdown()


if __name__ == "__main__":
    main()
