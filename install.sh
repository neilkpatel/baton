#!/usr/bin/env bash
# Baton — one-command install.
#
#   curl -fsSL https://raw.githubusercontent.com/neilkpatel/baton/main/install.sh | bash
#
# What it does: clones (or updates) Baton into ~/.baton, sets up an isolated
# Python venv, and installs a login LaunchAgent so the 🎽 menu bar app starts
# automatically and relaunches if it crashes. Everything is local; nothing
# leaves your machine.
#
# Flags:
#   --no-autostart   set everything up but skip the login LaunchAgent
#   --uninstall      stop Baton and remove the LaunchAgent (code + prefs kept)
#
# Env:
#   BATON_DIR        install location (default ~/.baton). Running this script
#                    from inside a git checkout installs from that checkout.
set -euo pipefail

REPO="https://github.com/neilkpatel/baton.git"
LABEL="com.baton.menubar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="/tmp/baton-menubar.log"
UID_N="$(id -u)"

AUTOSTART=1
for arg in "$@"; do
  case "$arg" in
    --no-autostart) AUTOSTART=0 ;;
    --uninstall)
      launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
      rm -f "$PLIST"
      echo "Baton autostart removed (code and prefs left in place)."
      echo "To fully remove: rm -rf ~/.baton ~/.config/baton"
      exit 0 ;;
    *) echo "unknown flag: $arg (try --no-autostart or --uninstall)" >&2; exit 1 ;;
  esac
done

[ "$(uname)" = "Darwin" ] || { echo "Baton is a macOS menu bar app — macOS only." >&2; exit 1; }

# --- where the code lives -----------------------------------------------------
# If this script sits next to menubar.py we're inside a checkout — install from it.
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SRC_DIR" ] && [ -f "$SRC_DIR/menubar.py" ]; then
  DIR="$SRC_DIR"
  echo "Installing from checkout: $DIR"
else
  DIR="${BATON_DIR:-$HOME/.baton}"
  if [ -d "$DIR/.git" ]; then
    echo "Updating $DIR …"
    git -C "$DIR" pull --ff-only
  else
    echo "Cloning Baton into $DIR …"
    git clone --depth 1 "$REPO" "$DIR"
  fi
fi

# --- python -------------------------------------------------------------------
# Prefer a modern python3 (3.11+ enables the Codex-automations collector).
PY=""
for cand in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
[ -n "$PY" ] || { echo "python3 not found — install Python 3 (e.g. 'brew install python') and re-run." >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || { echo "Python 3.9+ required (found: $("$PY" --version))." >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || echo "note: $("$PY" --version) works, but Codex scheduled-automation tracking needs 3.11+."

echo "Setting up venv with $PY …"
[ -d "$DIR/.venv" ] || "$PY" -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install --quiet -r "$DIR/requirements.txt"
"$DIR/.venv/bin/python" -c "import rumps" \
  || { echo "venv setup failed (rumps didn't import) — see pip output above." >&2; exit 1; }

# --- autostart ------------------------------------------------------------------
if [ "$AUTOSTART" = 1 ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DIR/.venv/bin/python</string>
    <string>$DIR/menubar.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST_EOF
  launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_N" "$PLIST"
  echo
  echo "🎽 Baton is running — look for the relay runner in your menu bar."
  echo "   It starts at login and relaunches if it crashes."
  echo "   Restart after editing code:  launchctl kickstart -k gui/$UID_N/$LABEL"
  echo "   Uninstall autostart:         bash $DIR/install.sh --uninstall"
else
  echo
  echo "Setup done (no autostart). Run it with:"
  echo "   $DIR/.venv/bin/python $DIR/menubar.py"
fi
