#!/usr/bin/env python3
"""Classify big territory losses in replays: mechanism and what the victim kept.

    python3 tools/losses.py runs-lineup.json out/replays/a*.pbrp
The first argument may instead be a comma list of seat names (P1..P4) applied to every replay.
Mechanism: wall (new '*'), bomb (cutter bomb went off), bullet (cutter bullet nearby), head.
"""

import json
import sys
from collections import defaultdict

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from swings import frames, count  # noqa: E402

BULLETS = {p: set() for p in range(4)}
ALPHABET = '~.#*1234ABCDHJKLUIOPQWER6789!@$%'
for i in range(12, 28):
    BULLETS[(i - 12) // 4].add(ALPHABET[i])
BOMB = '!@$%'


def comp_size(grid, start, paint):
    if start is None:
        return 0
    seen = {start}
    stack = [start]
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < 100 and 0 <= ny < 100 and (nx, ny) not in seen and grid[ny][nx] == paint:
                seen.add((nx, ny))
                stack.append((nx, ny))
    return len(seen) - 1


def analyse(path, names, lim, out):
    prev = None
    for t, g in frames(path):
        c = count(g)
        if prev is not None:
            pc = count(prev)
            for k, paint in enumerate('ABCD'):
                loss = pc[paint] - c[paint]
                if loss < lim:
                    continue
                gains = {q: c[q] - pc[q] for q in 'ABCD'}
                gq = max(gains, key=gains.get)
                cutter = 'ABCD'.index(gq) if gains[gq] > loss // 3 else None
                lab = str(k + 1)
                head = None
                for y in range(100):
                    x = g[y].index(lab) if lab in g[y] else -1
                    if x >= 0:
                        head = (x, y)
                        break
                ph = None
                for y in range(100):
                    x = prev[y].index(lab) if lab in prev[y] else -1
                    if x >= 0:
                        ph = (x, y)
                        break
                own_nb = 0
                if ph:
                    x, y = ph
                    own_nb = sum(1 for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                                 if 0 <= nx < 100 and 0 <= ny < 100 and prev[ny][nx] == paint)
                mech = 'head'
                if cutter is None:
                    mech = 'self/air'
                else:
                    newwall = any(g[y][x] == '*' and prev[y][x] != '*' for y in range(100) for x in range(100))
                    bomb_gone = any(prev[y][x] == BOMB[cutter] and g[y][x] != BOMB[cutter]
                                    for y in range(100) for x in range(100))
                    bul = BULLETS[cutter]
                    bullet = any(ch in bul for row in prev for ch in row) or any(ch in bul for row in g for ch in row)
                    if bomb_gone:
                        mech = 'bomb'
                    elif newwall:
                        mech = 'wall'
                    elif bullet:
                        mech = 'bullet'
                kept = comp_size(g, head, paint)
                rec = dict(file=path.rsplit('/', 1)[-1], t=t, victim=names[k],
                           cutter=names[cutter] if cutter is not None else '-', loss=loss, had=pc[paint],
                           mech=mech, kept=c[paint], head_nb=own_nb, head_comp=kept)
                out.append(rec)
        prev = [r[:] for r in g]


def main():
    spec = sys.argv[1]
    lim = 200
    paths = sys.argv[2:]
    out = []
    lineups = {}
    if spec.endswith('.json'):
        lineups = json.load(open(spec))
    for p in paths:
        key = p.rsplit('/', 1)[-1]
        names = lineups.get(key) or spec.split(',')
        analyse(p, names, lim, out)
    for r in out:
        print('%(file)s t=%(t)4d %(victim)-10s lost %(loss)5d/%(had)5d to %(cutter)-10s via %(mech)-8s '
              'head_nb=%(head_nb)d kept=%(kept)d' % r)
    agg = defaultdict(lambda: [0, 0])
    for r in out:
        a = agg[(r['victim'], r['mech'])]
        a[0] += 1
        a[1] += r['loss']
    print()
    for (v, m), (n, s) in sorted(agg.items()):
        print('%-10s %-8s n=%3d tiles=%6d' % (v, m, n, s))


if __name__ == '__main__':
    main()
