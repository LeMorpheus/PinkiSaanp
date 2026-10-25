#!/usr/bin/env python3
"""Headless games in the *official* MiniAICups engine (References/paperio).

Requires the reference runner's dependencies: ``pip install "pyglet<2" networkx``.

    python sim/reference_match.py --games 6 --lineup pinki,hunter,cautious,greedy,simple_bot,simple_bot

Each bot runs as its own subprocess over the real JSON protocol, so this
exercises main.py + AiCupsAdapter exactly as the competition server would
(sub-cell motion, nitro / slowdown / saw bonuses, 1500 engine ticks).
"""

import argparse
import asyncio
import os
import random
import sys
from collections import defaultdict
from time import perf_counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, 'References', 'paperio', 'local_runner')
sys.path.insert(0, REF)

from clients import FileClient, SimplePythonClient  # noqa: E402
from constants import CONSTS  # noqa: E402
from game_objects.game import Game  # noqa: E402


def make_client(spec, seed):
    if spec == 'simple_bot':
        return SimplePythonClient()
    if spec == 'pinki':
        cmd = [sys.executable, '-u', os.path.join(ROOT, 'main.py')]
    else:
        cmd = [sys.executable, '-u', os.path.join(ROOT, 'sim', 'aicups_bot.py'), spec, str(seed)]
    return FileClient(cmd, os.devnull)


def play(lineup, seed):
    random.seed(seed)
    specs = lineup[:]
    clients = [make_client(s, seed * 7 + i) for i, s in enumerate(specs)]
    names = {}
    counts = defaultdict(int)
    for c, s in zip(clients, specs):
        counts[s] += 1
        names[id(c)] = s if counts[s] == 1 else '%s#%d' % (s, counts[s])
    game = Game(clients)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    game.send_game_start()
    while True:
        over = loop.run_until_complete(game.game_loop())
        if over or game.tick >= CONSTS.MAX_TICK_COUNT:
            break
    game.send_game_end()
    results = []
    for p in game.losers + game.players:
        death = next((e for e in game.events if e['player']['id'] == p.id), None)
        results.append({'name': names[id(p.client)], 'score': p.score,
                        'territory': len(p.territory.points) if p in game.players else 0,
                        'alive': p in game.players,
                        'death': (death['tick_num'], death['event']) if death else None})
    for c in clients:
        proc = getattr(c, 'process', None)
        if proc is not None:
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
    loop.close()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=4)
    ap.add_argument('--lineup', default='pinki,hunter,cautious,greedy,simple_bot,simple_bot')
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args()
    base = args.lineup.split(',')
    totals = defaultdict(lambda: defaultdict(float))
    t0 = perf_counter()
    for g in range(args.games):
        k = g % len(base)  # rotate seats: start positions differ per seat
        lineup = base[k:] + base[:k]
        res = play(lineup, args.seed + g)
        ranked = sorted(res, key=lambda r: -r['score'])
        print('game %d: %s' % (g, ', '.join('%s=%d%s' % (
            r['name'], r['score'], '' if r['alive'] else '(%s@%d)' % (r['death'][1], r['death'][0]))
            for r in ranked)), flush=True)
        best = ranked[0]['score']
        for r in res:
            s = totals[r['name'].split('#')[0]]
            s['n'] += 1
            s['score'] += r['score']
            s['alive'] += r['alive']
            s['win'] += r['score'] == best
    print('%-11s %5s %8s %7s %6s' % ('bot', 'seats', 'score', 'alive%', 'win%'))
    for name, s in sorted(totals.items(), key=lambda kv: -kv[1]['score'] / kv[1]['n']):
        print('%-11s %5d %8.1f %7.0f %6.0f' % (name, s['n'], s['score'] / s['n'],
                                              100 * s['alive'] / s['n'], 100 * s['win'] / s['n']))
    print('wall time %.0fs' % (perf_counter() - t0))


if __name__ == '__main__':
    main()
