#!/usr/bin/env python3
"""Run many official-testkit games in parallel and aggregate final tile scores.

Run inside WSL from ~/cw:
    python3 /mnt/e/Projects/Agent_Showdown/tools/arena.py --sync \
        --lineup PinkiSaanp,PinkiB,wall_hug,random --games 4 --jobs 4
Variants: --variant PinkiB='{"seed": 2, "max_leg": 30}' creates my_bots/PinkiB.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

SRC = '/mnt/e/Projects/Agent_Showdown/submission/PinkiSaanp'
KIT = os.path.expanduser('~/cw')


def sync(variants):
    dst = os.path.join(KIT, 'my_bots', 'PinkiSaanp')
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns('__pycache__', 'variant.json'))
    for name, spec in variants.items():
        d = os.path.join(KIT, 'my_bots', name)
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(dst, d)
        with open(os.path.join(d, 'variant.json'), 'w') as f:
            json.dump(spec, f)


def bot_arg(name):
    if name in ('random', 'wall_hug'):
        return name
    return 'my_bots/' + name


def play(job):
    gid, lineup, moves = job
    rep = 'out/replays/a%d.pbrp' % gid
    cmd = ['./testkit', '-n', str(moves), '-r', rep, '--log-dir', 'runs/a%d' % gid] + [bot_arg(n) for n in lineup]
    out = subprocess.run(cmd, cwd=KIT, capture_output=True, text=True).stdout
    scores = {}
    for m in re.finditer(r'P(\d) \(([^)]+)\): (\d+) tiles', out):
        scores[int(m.group(1))] = (m.group(2), int(m.group(3)))
    tles = [int(x) for x in re.findall(r'TLEs:\s+(\d+)', out)]
    mx = [float(x) for x in re.findall(r'max: ([\d.]+) ms', out)]
    return gid, lineup, scores, tles, mx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lineup', default='PinkiSaanp,wall_hug,random,wall_hug')
    ap.add_argument('--games', type=int, default=2)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--moves', type=int, default=2000)
    ap.add_argument('--sync', action='store_true')
    ap.add_argument('--rotate', action='store_true', help='rotate seats each game')
    ap.add_argument('--variant', action='append', default=[])
    ap.add_argument('--start', type=int, default=100)
    args = ap.parse_args()
    variants = {}
    for v in args.variant:
        name, spec = v.split('=', 1)
        variants[name] = json.loads(spec)
    if args.sync:
        sync(variants)
    base = args.lineup.split(',')
    jobs = []
    for g in range(args.games):
        k = g % len(base) if args.rotate else 0
        jobs.append((args.start + g, base[k:] + base[:k], args.moves))
    tot = defaultdict(lambda: [0, 0, 0])  # sum, games, wins
    with ThreadPoolExecutor(args.jobs) as ex:
        for gid, lineup, scores, tles, mx in ex.map(play, jobs):
            best = max(v[1] for v in scores.values()) if scores else 0
            line = ', '.join('P%d %s=%d' % (k, v[0].split('/')[-1], v[1]) for k, v in sorted(scores.items()))
            print('game %d: %s  TLE=%s max_ms=%s' % (gid, line, tles, [round(x) for x in mx]), flush=True)
            for k, (name, s) in scores.items():
                name = name.split('/')[-1]
                tot[name][0] += s
                tot[name][1] += 1
                tot[name][2] += s == best
    print('%-12s %6s %8s %6s' % ('bot', 'seats', 'avg', 'win%'))
    for name, (s, n, wins) in sorted(tot.items(), key=lambda kv: -kv[1][0] / kv[1][1]):
        print('%-12s %6d %8.1f %6.0f' % (name, n, s / n, 100.0 * wins / n))


if __name__ == '__main__':
    main()
