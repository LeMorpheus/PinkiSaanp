#!/usr/bin/env python3
"""List big one-tick territory swings in a .pbrp replay (who lost, who gained).

    python3 tools/swings.py out/replays/a100.pbrp [min_tiles] [--show]
--show prints the 31x31 neighbourhood of the loser's head the tick before.
"""

import struct
import sys

ALPHABET = '~.#*1234ABCDHJKLUIOPQWER6789!@$%'


def frames(path):
    d = open(path, 'rb').read()
    w, h = d[5], d[6]
    n = struct.unpack_from('<H', d, 20)[0]
    off = 22
    grid = [['~'] * w for _ in range(h)]

    def apply(off, n):
        for _ in range(n):
            t, x1, y1, x2, y2 = d[off:off + 5]
            off += 5
            ch = ALPHABET[t] if t < len(ALPHABET) else '?'
            for y in range(min(y1, y2), max(y1, y2) + 1):
                row = grid[h - 1 - y]
                for x in range(min(x1, x2), max(x1, x2) + 1):
                    row[x] = ch
        return off

    off = apply(off, n)
    tick = 0
    yield tick, grid
    while off + 6 <= len(d):
        tick = struct.unpack_from('<I', d, off)[0]
        n = struct.unpack_from('<H', d, off + 4)[0]
        off = apply(off + 6, n)
        yield tick, grid


def count(grid):
    out = dict.fromkeys('ABCD', 0)
    for row in grid:
        for ch in row:
            if ch in out:
                out[ch] += 1
    return out


def heads(grid):
    out = {}
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            if ch in '1234':
                out[ch] = (x, y)
    return out


def main():
    path = sys.argv[1]
    lim = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 150
    show = '--show' in sys.argv
    prev = None
    prev_grid = None
    for tick, grid in frames(path):
        c = count(grid)
        if prev is not None:
            delta = {k: c[k] - prev[k] for k in c}
            losers = [k for k in delta if delta[k] <= -lim]
            for k in losers:
                gainer = max(delta, key=lambda q: delta[q])
                print('tick %4d: P%d lost %5d (had %5d)  P%d %+d   %s' % (
                    tick, 'ABCD'.index(k) + 1, -delta[k], prev[k], 'ABCD'.index(gainer) + 1,
                    delta[gainer], c))
                if show:
                    hd = heads(prev_grid).get(str('ABCD'.index(k) + 1))
                    if hd:
                        x0, y0 = max(0, hd[0] - 15), max(0, hd[1] - 15)
                        for row in prev_grid[y0:y0 + 31]:
                            print('   ' + ''.join(row[x0:x0 + 31]))
        prev = c
        prev_grid = [r[:] for r in grid] if show else None


if __name__ == '__main__':
    main()
