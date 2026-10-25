"""Round-robin style benchmark: PinkiSaanp vs baseline bots over many seeds.

    python -m sim.tournament --games 40 --lineup pinki,greedy,cautious,hunter,random,greedy
    python -m sim.tournament --games 1 --html replay.html     # watch one game
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from time import perf_counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinkisaanp import BotConfig  # noqa: E402
from sim.engine import Engine  # noqa: E402
from sim.opponents import REGISTRY, GenericPinkiAgent, PinkiAgent  # noqa: E402


# Named PinkiSaanp configurations for tuning, e.g. --lineup pinki,pinki:bold,pinki:safe
VARIANTS = {
    'bold': dict(margin_mid=-0.4, ram_p=0.6, life_future_weight=0.3),
    'safe': dict(margin_mid=-1.6, ram_p=0.95, life_future_weight=0.8),
    'greedy': dict(loop_len_per_threat=3.5, w_exposure=0.1, max_leg=16),
    'noexpo': dict(w_exposure=0.0),
    'raider': dict(w_enemy=8.0),
    'terr': dict(w_enemy=2.0, w_kill=25.0, w_kill_territory=0.6,
                 life_territory_weight=1.0, life_future_weight=0.35),  # BotConfig.territory()
    'ram50': dict(ram_p=0.5),
    'ram25': dict(ram_p=0.25),
}


def make_agent(name, seed, cfg_overrides):
    if name == 'pinkigen':
        return GenericPinkiAgent(BotConfig(**cfg_overrides))
    if name.startswith('pinki'):
        overrides = dict(cfg_overrides)
        if ':' in name:
            overrides.update(VARIANTS[name.split(':', 1)[1]])
        return PinkiAgent(BotConfig(**overrides))
    return REGISTRY[name](seed)


def play(lineup, seed, size, steps, cfg_overrides=None, record=False):
    agents = []
    counts = defaultdict(int)
    for k, name in enumerate(lineup):
        counts[name] += 1
        label = name if counts[name] == 1 else '%s#%d' % (name, counts[name])
        agents.append((label, make_agent(name, seed * 31 + k, cfg_overrides or {})))
    eng = Engine(size[0], size[1], agents, max_steps=steps, seed=seed, record=record)
    res = eng.run()
    return eng, res


def summarize(all_results, hero='pinki'):
    by = defaultdict(lambda: defaultdict(float))
    games = len(all_results)
    for res in all_results:
        best_score = max(r['score'] for r in res)
        best_terr = max(r['territory'] for r in res)
        for r in res:
            s = by[r['name'].split('#')[0]]
            s['n'] += 1
            s['score'] += r['score']
            s['terr'] += r['territory']
            s['alive'] += 1 if r['alive'] else 0
            s['kills'] += r['kills']
            s['crashes'] += r.get('crashes', 0)
            s['win_score'] += 1 if r['score'] == best_score else 0
            s['win_terr'] += 1 if r['territory'] == best_terr and r['alive'] else 0
            s['think_avg'] = max(s['think_avg'], r['think_avg_ms'])
            s['think_max'] = max(s['think_max'], r['think_max_ms'])
    lines = ['%-10s %6s %8s %7s %7s %7s %8s %8s %8s %8s' % (
        'bot', 'seats', 'score', 'terr', 'alive%', 'kills', 'win%sc', 'win%ter', 'avg ms', 'max ms')]
    for name, s in sorted(by.items(), key=lambda kv: -kv[1]['score'] / kv[1]['n']):
        n = s['n']
        lines.append('%-10s %6d %8.1f %7.1f %7.0f %7.2f %8.0f %8.0f %8.1f %8.1f' % (
            name, n, s['score'] / n, s['terr'] / n, 100 * s['alive'] / n, s['kills'] / n,
            100 * s['win_score'] / n, 100 * s['win_terr'] / n, s['think_avg'], s['think_max']))
    crashes = {k: int(v['crashes']) for k, v in by.items() if v['crashes']}
    lines.append('games: %d%s' % (games, '  CRASHES: %s' % crashes if crashes else ''))
    return '\n'.join(lines)


def death_report(all_results, hero='pinki'):
    reasons = defaultdict(int)
    for res in all_results:
        for r in res:
            if r['name'].startswith(hero) and r['death']:
                why = r['death'][1]
                reasons[why.split(' ')[0] if ' by ' in why or ' with ' in why else why] += 1
    return dict(reasons)


def _play_job(job):
    lineup, seed, size, steps, overrides = job
    return play(lineup, seed, size, steps, overrides)[1]


def _report(args, seed, res):
    if not args.verbose:
        return
    ranked = sorted(res, key=lambda r: -r['score'])
    print('seed %d: %s' % (seed, ', '.join(
        '%s=%d/%d%s' % (r['name'], r['score'], r['territory'],
                        '' if r['alive'] else '(%s@%d)' % (r['death'][1], r['death'][0]))
        for r in ranked)), flush=True)


def write_html(replay, path):
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'viewer.html'), encoding='utf-8') as f:
        html = f.read()
    blob = json.dumps(replay, separators=(',', ':'))
    html = html.replace('/*__REPLAY__*/null', blob)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=20)
    ap.add_argument('--lineup', default='pinki,greedy,cautious,hunter,random,greedy')
    ap.add_argument('--size', default='31x31')
    ap.add_argument('--steps', type=int, default=250)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--html', help='write a pink/white replay viewer for the first game')
    ap.add_argument('--json', help='write the first game replay as JSON')
    ap.add_argument('--set', action='append', default=[], help='BotConfig override k=v')
    ap.add_argument('-v', '--verbose', action='store_true', help='one line per game')
    ap.add_argument('-j', '--jobs', type=int, default=1, help='parallel game processes')
    args = ap.parse_args()
    w, h = (int(v) for v in args.size.lower().split('x'))
    lineup = args.lineup.split(',')
    overrides = {}
    for kv in args.set:
        k, v = kv.split('=', 1)
        overrides[k] = float(v) if v.replace('.', '', 1).lstrip('-').isdigit() else v
    t0 = perf_counter()
    results = []
    first = 0
    if args.html or args.json:
        eng, res = play(lineup, args.seed, (w, h), args.steps, overrides, record=True)
        results.append(res)
        _report(args, args.seed, res)
        rep = eng.replay()
        if args.json:
            with open(args.json, 'w', encoding='utf-8') as f:
                json.dump(rep, f)
        if args.html:
            write_html(rep, args.html)
        first = 1
    jobs = [(lineup, args.seed + g, (w, h), args.steps, overrides) for g in range(first, args.games)]
    if args.jobs > 1 and len(jobs) > 1:
        from multiprocessing import Pool
        with Pool(args.jobs) as pool:
            for job, res in zip(jobs, pool.imap(_play_job, jobs)):
                results.append(res)
                _report(args, job[1], res)
    else:
        for job in jobs:
            res = _play_job(job)
            results.append(res)
            _report(args, job[1], res)
    print(summarize(results))
    print('pinki deaths:', death_report(results))
    print('wall time %.1fs' % (perf_counter() - t0))


if __name__ == '__main__':
    main()
