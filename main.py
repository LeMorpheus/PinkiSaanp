#!/usr/bin/env python3
"""PinkiSaanp stdin/stdout entry point.

    python -u main.py                      # MiniAICups protocol (References/paperio)
    python -u main.py --protocol generic   # one JSON state per line -> "UP"/"DOWN"/...
    python -u main.py --protocol generic --y-down --objective score

Only stdout carries answers; nothing is written to stderr (the reference
runner treats stderr output as an error).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pinkisaanp import AiCupsAdapter, BotConfig, GenericAdapter, PinkiSaanp  # noqa: E402


def build_config(args):
    objective = args.objective or ('territory' if args.protocol == 'generic' else 'score')
    factory = BotConfig.territory if objective == 'territory' else BotConfig.aicups
    overrides = {'time_budget': args.budget}
    if args.wall_encloses:
        overrides['wall_encloses'] = True
    return factory(**overrides)


def run_aicups(args):
    bot = PinkiSaanp(build_config(args))
    adapter = AiCupsAdapter(max_tick=args.max_tick)
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        kind = msg.get('type')
        if kind == 'start_game':
            adapter.start(msg.get('params', {}))
            continue
        if kind == 'end_game':
            break
        view = adapter.view(msg.get('params', {}))
        if view is None:
            out.write(json.dumps({'command': 'up'}) + '\n')
            out.flush()
            continue
        decision = bot.decide(view)
        out.write(json.dumps({'command': adapter.command(decision.direction),
                              'debug': decision.debug()[:190]}) + '\n')
        out.flush()


def run_generic(args):
    bot = PinkiSaanp(build_config(args))
    adapter = GenericAdapter(y_down=args.y_down, upper=not args.lower)
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            state = json.loads(line)
            view = adapter.view(state)
            decision = bot.decide(view)
            out.write(adapter.command(decision.direction) + '\n')
        except Exception:
            out.write('UP\n' if not args.lower else 'up\n')
        out.flush()


def main():
    ap = argparse.ArgumentParser(description='PinkiSaanp Paper.io bot')
    ap.add_argument('--protocol', choices=('aicups', 'generic'), default='aicups')
    ap.add_argument('--objective', choices=('score', 'territory'), default=None,
                    help='score (banked points, aicups default) or territory (generic default)')
    ap.add_argument('--budget', type=float, default=0.12, help='seconds of search per move')
    ap.add_argument('--max-tick', type=int, default=1500, help='aicups MAX_TICK_COUNT')
    ap.add_argument('--y-down', action='store_true', help='generic: UP decreases y')
    ap.add_argument('--lower', action='store_true', help='generic: answer in lower case')
    ap.add_argument('--wall-encloses', action='store_true', help='arena edge closes loops')
    args = ap.parse_args()
    if args.protocol == 'generic':
        run_generic(args)
    else:
        run_aicups(args)


if __name__ == '__main__':
    main()
