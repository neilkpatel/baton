#!/bin/bash
# Re-render the Baton menu-bar icon from its SVG source.
# Produces a 40x40 transparent PNG (2x of the 20pt menu-bar display size) that
# menubar.py hands to rumps as a template icon. Run after editing baton-drive.svg.
set -euo pipefail
cd "$(dirname "$0")"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SVG="baton-drive.svg"
BIG="_baton-drive-512.png"
OUT="baton-drive.png"

# High-res render (transparent bg), then downsample for clean antialiasing.
"$CHROME" --headless --disable-gpu --hide-scrollbars \
  --default-background-color=00000000 \
  --force-device-scale-factor=1 --window-size=512,512 \
  --screenshot="$BIG" "file://$PWD/$SVG" 2>/dev/null

sips -z 40 40 "$BIG" --out "$OUT" >/dev/null
rm -f "$BIG"
echo "wrote $OUT ($(sips -g pixelWidth -g pixelHeight "$OUT" | tail -2 | tr -s ' ' | paste -sd' ' -))"
