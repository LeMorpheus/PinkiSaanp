#!/usr/bin/env python3
"""Run many official-testkit games in parallel and aggregate final tile scores.

    python3 tools/arena.py --sync --lineup PinkiSaanp,PinkiV1,wall_hug,random --games 16 --rotate

--sync copies submission/PinkiSaanp and every baselines/* bot into the kit's
my_bots/.  --snap NAME=DIR copies any other bot dir in as NAME.  --seeded gives
each game its own copy of every Pinki* bot with a distinct variant seed, so
repeated seatings are not near-identical replays.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'submission', 'PinkiSaanp')
BASE = os.path.join(ROOT, 'baselines')
KIT = os.path.join(ROOT, 'Rules', 'agent-showdown-test-suite-main')
BUILTIN = ('random', 'wall_hug')
IGNORE = shutil.ignore_patterns('__pycache__')


def copy_bot(src, name, variant=None):
    dst = os.path.join(KIT, 'my_bots', name)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, ignore=IGNORE)
    if variant is not None:
        with open(os.path.join(dst, 'variant.json'), 'w') as f:
            json.dump(variant, f)
    return dst


def sync(variants, snaps, src=SRC):
    copy_bot(src, 'PinkiSaanp')
    for name in os.listdir(BASE):
        if os.path.isdir(os.path.join(BASE, name)):
            copy_bot(os.path.join(BASE, name), name)
    for name, path in snaps.items():
        copy_bot(path, name)
    for name, spec in variants.items():
        copy_bot(src, name, spec)


def read_variant(name):
    try:
        with open(os.path.join(KIT, 'my_bots', name, 'variant.json')) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def play(job):
    gid, lineup, moves, seeded = job
    args = []
    tmp = []
    for k, name in enumerate(lineup):
        if name in BUILTIN:
            args.append(name)
        elif seeded:
            v = dict(read_variant(name))
            v['seed'] = gid * 10 + k
            gname = '_g%d_%d_%s' % (gid, k, name)
            copy_bot(os.path.join(KIT, 'my_bots', name), gname, v)
            tmp.append(gname)
            args.append('my_bots/' + gname)
        else:
            args.append('my_bots/' + name)
    rep = 'out/replays/a%d.pbrp' % gid
    logdir = 'runs/a%d' % gid
    shutil.rmtree(os.path.join(KIT, logdir), ignore_errors=True)
    cmd = ['./testkit', '-n', str(moves), '-r', rep, '--log-dir', logdir] + args
    out = subprocess.run(cmd, cwd=KIT, capture_output=True, text=True).stdout
    scores = {}
    for m in re.finditer(r'P(\d) \(([^)]+)\): (\d+) tiles', out):
        scores[int(m.group(1))] = (lineup[int(m.group(1)) - 1], int(m.group(3)))
    tles = [int(x) for x in re.findall(r'TLEs:\s+(\d+)', out)]
    mx = [float(x) for x in re.findall(r'max: ([\d.]+) ms', out)]
    errs = []
    for k in range(1, 5):
        try:
            with open(os.path.join(KIT, logdir, 'player%d.log' % k)) as f:
                txt = f.read()
        except OSError:
            txt = ''
        errs.append(len(re.findall(r'(decide|update) error', txt)))
    for g in tmp:
        shutil.rmtree(os.path.join(KIT, 'my_bots', g), ignore_errors=True)
    return gid, lineup, scores, tles, mx, errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lineup', default='PinkiSaanp,PinkiV1,wall_hug,random')
    ap.add_argument('--games', type=int, default=8)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--moves', type=int, default=2000)
    ap.add_argument('--sync', action='store_true')
    ap.add_argument('--rotate', action='store_true', help='rotate seats each game')
    ap.add_argument('--seeded', action='store_true', help='distinct variant seed per game')
    ap.add_argument('--variant', action='append', default=[], help='NAME=JSON copy of the submission')
    ap.add_argument('--snap', action='append', default=[], help='NAME=DIR copy of another bot dir')
    ap.add_argument('--start', type=int, default=100)
    ap.add_argument('--src', default=SRC, help='bot dir used for PinkiSaanp and --variant copies')
    args = ap.parse_args()
    variants = dict((v.split('=', 1)[0], json.loads(v.split('=', 1)[1])) for v in args.variant)
    snaps = dict(s.split('=', 1) for s in args.snap)
    if args.sync:
        sync(variants, snaps, args.src)
    base = args.lineup.split(',')
    jobs = []
    for g in range(args.games):
        k = g % len(base) if args.rotate else 0
        jobs.append((args.start + g, base[k:] + base[:k], args.moves, args.seeded))
    lpath = os.path.join(KIT, 'out', 'lineups.json')
    try:
        with open(lpath) as f:
            lineups = json.load(f)
    except (OSError, ValueError):
        lineups = {}
    for gid, lineup, _, _ in jobs:
        lineups['a%d.pbrp' % gid] = lineup
    os.makedirs(os.path.dirname(lpath), exist_ok=True)
    with open(lpath, 'w') as f:
        json.dump(lineups, f)
    tot = defaultdict(lambda: [0, 0, 0.0, 0, 0, 0.0])  # sum, seats, wins, tle, errors, max_ms
    a_name, b_name = base[0], base[1]
    h2h = [0, 0, 0, []]  # a wins, b wins, ties, per-game a-b differences
    with ThreadPoolExecutor(args.jobs) as ex:
        for gid, lineup, scores, tles, mx, errs in ex.map(play, jobs):
            sa = sum(v[1] for v in scores.values() if v[0] == a_name)
            sb = sum(v[1] for v in scores.values() if v[0] == b_name)
            if a_name != b_name and scores:
                h2h[0 if sa > sb else 1 if sb > sa else 2] += 1
                h2h[3].append(sa - sb)
            best = max(v[1] for v in scores.values()) if scores else 0
            nbest = sum(1 for v in scores.values() if v[1] == best)
            line = ', '.join('P%d %s=%d' % (k, v[0], v[1]) for k, v in sorted(scores.items()))
            print('game %d: %s  TLE=%s max_ms=%s err=%s' % (gid, line, tles, [round(x) for x in mx], errs),
                  flush=True)
            for k, (name, s) in scores.items():
                r = tot[name]
                r[0] += s
                r[1] += 1
                r[2] += (1.0 / nbest) if s == best else 0.0
                r[3] += tles[k - 1] if k - 1 < len(tles) else 0
                r[4] += errs[k - 1]
                r[5] = max(r[5], mx[k - 1] if k - 1 < len(mx) else 0)
    print('%-12s %6s %8s %6s %5s %5s %7s' % ('bot', 'seats', 'avg', 'win%', 'TLE', 'err', 'max_ms'))
    for name, (s, n, wins, tle, err, mxx) in sorted(tot.items(), key=lambda kv: -kv[1][0] / kv[1][1]):
        print('%-12s %6d %8.1f %6.0f %5d %5d %7.1f' % (name, n, s / n, 100.0 * wins / n, tle, err, mxx))
    d = h2h[3]
    if d:
        mean = sum(d) / len(d)
        sd = (sum((x - mean) ** 2 for x in d) / max(1, len(d) - 1)) ** 0.5
        print('h2h %s vs %s: %d-%d-%d  mean diff %+.0f +- %.0f (1 s.e.)' % (
            a_name, b_name, h2h[0], h2h[1], h2h[2], mean, sd / len(d) ** 0.5))


if __name__ == '__main__':
    main()
