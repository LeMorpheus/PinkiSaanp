#!/usr/bin/env python3
"""Print a window of a replay around a player's head: peek.py file.pbrp LABEL T0 T1 [half_w half_h]"""
import sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from swings import frames, count, heads  # noqa: E402

path, lab, t0, t1 = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
hw = int(sys.argv[5]) if len(sys.argv) > 5 else 25
hh = int(sys.argv[6]) if len(sys.argv) > 6 else 10
for t, g in frames(path):
    if t0 <= t <= t1:
        hd = heads(g)
        print('=== tick', t, count(g), hd)
        hx, hy = hd.get(lab, (50, 50))
        x0, y0 = max(0, min(100 - 2 * hw - 1, hx - hw)), max(0, min(100 - 2 * hh - 1, hy - hh))
        for y in range(y0, y0 + 2 * hh + 1):
            print('%3d ' % y + ''.join(g[y][x0:x0 + 2 * hw + 1]))
    if t > t1:
        break
