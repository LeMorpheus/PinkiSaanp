#!/usr/bin/env python3
"""Run a baseline opponent over the MiniAICups stdin/stdout protocol.

    python -u sim/aicups_bot.py hunter       # random | greedy | cautious | hunter

Lets the official local runner (or sim/reference_match.py) pit PinkiSaanp
against the same baselines used by the internal tournament.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinkisaanp.adapters import AiCupsAdapter  # noqa: E402
from sim.opponents import REGISTRY  # noqa: E402


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else 'hunter'
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else None
    bot = REGISTRY[name](seed)
    adapter = AiCupsAdapter()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        kind = msg.get('type')
        if kind == 'start_game':
            adapter.start(msg.get('params', {}))
            continue
        if kind == 'end_game':
            break
        view = adapter.view(msg.get('params', {}))
        try:
            d = bot.act(view)
        except Exception:
            d = view.me.dir if view.me.dir is not None else 0
        sys.stdout.write(json.dumps({'command': adapter.command(d)}) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
