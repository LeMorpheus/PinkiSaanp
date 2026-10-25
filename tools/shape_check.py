#!/usr/bin/env python3
"""For each big loss of NAME in replays, run pinki.shape on the board just before it.

    python3 tools/shape_check.py NAME out/lineups.json out/replays/a1*.pbrp
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'submission', 'PinkiSaanp'))
from swings import frames, count  # noqa: E402
from pinki.board import Board, popcount  # noqa: E402
from pinki.shape import analyse  # noqa: E402

B = Board(100, 100)


def mask(grid, ch):
    m = 0
    bit = B.bit
    for y, row in enumerate(grid):
        for x, c in enumerate(row):
            if c == ch:
                m |= bit[y * 100 + x]
    return m


def main():
    name = sys.argv[1]
    lineups = json.load(open(sys.argv[2]))
    stats = {'n': 0, 'head_in_heavy': 0, 'flag': 0, 'lost': 0, 'lost_flagged': 0}
    for path in sys.argv[3:]:
        lineup = lineups.get(os.path.basename(path))
        if not lineup or name not in lineup:
            continue
        k = lineup.index(name)
        paint, lab = 'ABCD'[k], str(k + 1)
        prev = None
        hist = []
        for t, g in frames(path):
            c = count(g)
            if prev is not None and prev[0][paint] - c[paint] >= 300:
                pg = hist[0] if hist else prev[1]   # board ~5 ticks before
                M = mask(pg, paint)
                hm = mask(pg, lab)
                sh = analyse(B, M, hm)
                risk = sh.at_risk()
                kept = c[paint]
                loss = prev[0][paint] - kept
                inh = sh.head_blob == sh.heavy
                flag = risk >= max(300, 0.3 * sh.area)
                stats['n'] += 1
                stats['head_in_heavy'] += inh
                stats['flag'] += flag
                stats['lost'] += loss
                stats['lost_flagged'] += loss if flag else 0
                print('%s t=%d lost %d kept %d | blobs=%d heavy=%s head=%s risk=%d area=%d flag=%d' % (
                    os.path.basename(path), t, loss, kept, len(sh.blobs),
                    sh.blobs[sh.heavy][0] if sh.heavy is not None else None,
                    sh.blobs[sh.head_blob][0] if sh.head_blob is not None else None,
                    risk, sh.area, flag))
            prev = (c, [r[:] for r in g])
            hist.append(prev[1])
            if len(hist) > 5:
                hist.pop(0)
    print(stats)


if __name__ == '__main__':
    main()
