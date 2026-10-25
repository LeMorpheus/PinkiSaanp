#!/usr/bin/env python3
"""Placement metrics from arena.py logs: win rate (1st places, ties split), mean placement
(1-4, ties get the average rank), last-place rate (ties split) and mean tiles per bot.

    python3 tools/ranks.py LOG [LOG...]                 # all bots in the logs
    python3 tools/ranks.py --pair LOG_A NAME_A LOG_B NAME_B
        same seeds run twice (one bot swapped): per-game paired differences
"""
import re
import sys
from collections import defaultdict


def games(path):
    out = {}
    for line in open(path):
        m = re.match(r'game (\d+): (.*)  TLE', line)
        if m:
            out[int(m.group(1))] = [(n, int(v)) for n, v in re.findall(r'P\d (\w+)=(\d+)', m.group(2))]
    return out


def places(scores):
    """name -> (placement, win share, last share, tiles); ties share ranks."""
    vals = [s for _, s in scores]
    res = {}
    for name, s in scores:
        above = sum(1 for v in vals if v > s)
        tied = sum(1 for v in vals if v == s)
        place = above + (tied + 1) / 2.0
        win = 1.0 / tied if above == 0 else 0.0
        below = sum(1 for v in vals if v < s)
        last = 1.0 / tied if below == 0 else 0.0
        res.setdefault(name, []).append((place, win, last, s))
    return res


def summary(rows):
    n = len(rows)
    m = lambda k: sum(r[k] for r in rows) / n
    sd = lambda k: (sum((r[k] - m(k)) ** 2 for r in rows) / max(1, n - 1)) ** 0.5 / n ** 0.5
    return n, m(1), sd(1), m(0), sd(0), m(2), m(3)


def main():
    a = sys.argv[1:]
    if a and a[0] == '--pair':
        ga, na, gb, nb = games(a[1]), a[2], games(a[3]), a[4]
        keys = sorted(set(ga) & set(gb))
        ra = [places(ga[k])[na][0] for k in keys]
        rb = [places(gb[k])[nb][0] for k in keys]
        for lab, rows in ((na, ra), (nb, rb)):
            n, w, ws, p, ps, l, t = summary(rows)
            print('%-10s n=%d  win %.1f%% +- %.1f  place %.2f +- %.2f  last %.1f%%  tiles %.0f' % (
                lab, n, 100 * w, 100 * ws, p, ps, 100 * l, t))
        d = [(x[0] - y[0], x[1] - y[1], x[3] - y[3]) for x, y in zip(ra, rb)]
        n = len(d)
        for k, lab, sc in ((1, 'win', 100), (0, 'place', 1), (2, 'tiles', 1)):
            mu = sum(x[k] for x in d) / n
            se = (sum((x[k] - mu) ** 2 for x in d) / max(1, n - 1)) ** 0.5 / n ** 0.5
            print('  paired %s diff %+.2f +- %.2f' % (lab, sc * mu, sc * se))
        return
    per = defaultdict(list)
    for path in a:
        for scores in games(path).values():
            for name, rows in places(scores).items():
                per[name].extend(rows)
    for name, rows in sorted(per.items(), key=lambda kv: -summary(kv[1])[1]):
        n, w, ws, p, ps, l, t = summary(rows)
        print('%-10s seats=%3d  win %5.1f%% +- %4.1f  place %.2f +- %.2f  last %5.1f%%  tiles %.0f' % (
            name, n, 100 * w, 100 * ws, p, ps, 100 * l, t))


if __name__ == '__main__':
    main()
