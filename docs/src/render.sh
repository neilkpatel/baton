#!/usr/bin/env bash
# Regenerate all docs/ media from scene.html (banner, social card, demo GIF frames).
# Run from docs/src/. Assemble the GIF afterwards with gif.py.
set -euo pipefail
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT="$(cd .. && pwd)"
FRAMES="${TMPDIR:-/tmp}/baton-frames"
mkdir -p "$FRAMES"

shot() { # shot <w> <h> <dsf> <query> <outfile>
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --force-device-scale-factor="$3" --window-size="$1,$2" \
    --screenshot="$5" "file://$PWD/scene.html?$4" 2>/dev/null
}

shot 1280 320 2 "mode=banner" "$OUT/banner.png"
shot 1280 640 1 "mode=social" "$OUT/social-preview.png"
for f in $(seq 0 39); do
  shot 800 500 2 "mode=frame&f=$f" "$FRAMES/$(printf 'f%02d' "$f").png"
  printf '.'
done
echo " frames in $FRAMES"
python3 gif.py "$FRAMES" "$OUT/demo.gif"
