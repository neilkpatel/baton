#!/usr/bin/env python3
"""Assemble the demo GIF from rendered frames. Usage: gif.py <frames_dir> <out.gif>"""
import sys, glob
from PIL import Image

frames_dir, out = sys.argv[1], sys.argv[2]
paths = sorted(glob.glob(f"{frames_dir}/f*.png"))
assert len(paths) == 40, f"expected 40 frames, got {len(paths)}"

W = 900  # downscale from 2x render for crisp text at reasonable file size
imgs = []
for p in paths:
    im = Image.open(p).convert("RGB")
    imgs.append(im.resize((W, int(W * im.height / im.width)), Image.LANCZOS))

def dur(f):
    if f == 0: return 900
    if f in (6, 9, 12): return 500          # count ticks 1, 2, 3
    if 15 <= f <= 19: return 70             # dropdown scale-in
    if 20 <= f <= 27: return 70             # cursor travel
    if f in (28, 29): return 250            # hover pause
    if 30 <= f <= 32: return 120            # click flash
    if f == 33: return 600                  # dropdown closes, count drops
    if f == 39: return 1600                 # end hold
    return 120

imgs[0].save(out, save_all=True, append_images=imgs[1:],
             duration=[dur(f) for f in range(40)], loop=0, optimize=True)
print(f"wrote {out}")
