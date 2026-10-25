#!/usr/bin/env python3
"""PinkiSaanp - Codewars Agent Showdown bot. Reads 11x11 views, answers one command per line.

The judge's clock for move 1 includes interpreter startup, so move 1 is answered
before the bot modules are imported (frame 0 is identical in every game); the
import + setup cost then lands on move 2 instead of stacking up.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIRST_MOVE = 'W'


def load_variant():
    """Optional variant.json next to bot.py (used only for local A/B testing)."""
    try:
        import json
        with open(os.path.join(HERE, 'variant.json')) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def read_frame(stdin):
    rows = []
    for _ in range(11):
        line = stdin.readline()
        if not line:
            return None
        rows.append(line.rstrip('\r\n'))
    return rows


def send(out, action):
    try:
        out.write(action + '\n')
        out.flush()
        return True
    except BrokenPipeError:
        return False


def main():
    stdin = sys.stdin
    out = sys.stdout
    first = read_frame(stdin)
    if first is None or not send(out, FIRST_MOVE):
        return
    sys.path.insert(0, HERE)
    from pinki.brain import Brain
    brain = Brain(log=os.environ.get('PINKI_LOG', '1') == '1', variant=load_variant())
    try:
        brain.prime(first, FIRST_MOVE)
    except Exception:
        pass
    import gc
    gc.collect()
    gc.freeze()     # the big static tables never need rescanning
    while True:
        rows = read_frame(stdin)
        if rows is None:
            return
        try:
            action = brain.act(rows)
        except Exception:
            action = 'I'
        if not send(out, action):
            return


if __name__ == '__main__':
    main()
