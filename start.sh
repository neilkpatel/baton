#!/usr/bin/env bash
# Launch Baton and open it in your browser.
cd "$(dirname "$0")"
PORT="${BATON_PORT:-8787}"
python3 server.py --port "$PORT" &
SRV=$!
sleep 0.7
open "http://127.0.0.1:$PORT" 2>/dev/null || echo "open http://127.0.0.1:$PORT"
echo "Baton server pid $SRV — Ctrl-C to stop (or: kill $SRV)"
wait $SRV
