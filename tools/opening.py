#!/usr/bin/env python3
"""Opening benchmark: our bot alone (3 idle opponents), area at given ticks, mean over seeds.

    python3 tools/opening.py --variant '{"top": 60}' --seeds 12 --ticks 150,300,450
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, 'Rules', 'agent-showdown-test-suite-main')
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from swings import frames, count  # noqa: E402


def run(job):
    seed, spec, ticks, src, tag = job
    name = '_op_%s_%d' % (tag, abs(seed))
    d = os.path.join(KIT, 'my_bots', name)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(src, d, ignore=shutil.ignore_patterns('__pycache__'))
    v = dict(spec)
    if seed > 0:
        v['seed'] = seed
    with open(os.path.join(d, 'variant.json'), 'w') as f:
        json.dump(v, f)
    rep = 'out/replays/%s.pbrp' % name
    subprocess.run(['./testkit', '-n', str(max(ticks)), '-r', rep, '--no-logs', 'my_bots/' + name,
                    'my_bots/idle', 'my_bots/idle', 'my_bots/idle'], cwd=KIT, capture_output=True)
    out = {}
    for t, g in frames(os.path.join(KIT, rep)):
        if t in ticks:
            out[t] = count(g)['A']
    shutil.rmtree(d, ignore_errors=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', default='{}')
    ap.add_argument('--seeds', type=int, default=12)
    ap.add_argument('--ticks', default='150,300,450')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--src', default=os.path.join(ROOT, 'submission', 'PinkiSaanp'))
    ap.add_argument('--tag', default='x')
    ap.add_argument('--noseed', action='store_true', help='run the shipped (unseeded) configuration')
    a = ap.parse_args()
    ticks = [int(t) for t in a.ticks.split(',')]
    spec = json.loads(a.variant)
    seeds = [0] * a.seeds if a.noseed else range(1, a.seeds + 1)
    jobs = [(s if not a.noseed else -k, spec, ticks, a.src, a.tag) for k, s in enumerate(seeds)]
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(run, jobs))
    for t in ticks:
        vals = [r.get(t, 0) for r in res]
        print('t=%d mean %.0f min %d max %d' % (t, sum(vals) / len(vals), min(vals), max(vals)))


if __name__ == '__main__':
    main()
