#!/usr/bin/env python3
"""PinkiSaanp - Codewars Agent Showdown bot. Reads 11x11 views, answers one command per line.

The judge's clock includes interpreter startup and module compilation (no
bytecode is shipped), and all four bots start at once.  So the first moves
follow a fixed opening (nobody can reach us that early; the map and spawn are
identical for everyone) while the bot is loaded one module per move; the
brain then replays the frames it missed and takes over.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Start of the corner loop the planner itself opens with: (3,3) -> (1,3) -> (1,9) -> (4,9).
OPENING = ('A', 'A', 'JS', 'S', 'S', 'S', 'D', 'D', 'D')
SETUP = ('pinki.board', 'pinki.mapdata', 'pinki.world', 'pinki.planner', 'pinki.tactics', 'pinki.brain')


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
    frames = []
    brain = None
    sent = None
    while brain is None:
        rows = read_frame(stdin)
        if rows is None:
            return
        if len(frames) >= len(OPENING):
            break                       # setup somehow not done: fall through and load now
        if not send(out, OPENING[len(frames)]):
            return
        frames.append(rows)
        if len(frames) == 1:
            sys.path.insert(0, HERE)
            from time import perf_counter
        sent = perf_counter()           # the next move's clock is already running
        k = len(frames) - 1
        if k < len(SETUP):
            __import__(SETUP[k])        # one module compile per move
        else:
            brain = build(frames)
            rows = None
    if brain is None:
        brain = build(frames)
    if rows is not None:
        act(brain, rows, sent, out)
        sent = None
    while True:
        rows = read_frame(stdin)
        if rows is None:
            return
        if not act(brain, rows, sent, out):
            return
        sent = None


def build(frames):
    from pinki.brain import Brain
    brain = Brain(log=os.environ.get('PINKI_LOG', '1') == '1', variant=load_variant())
    try:
        brain.replay(frames, OPENING)
    except Exception:
        pass
    import gc
    gc.collect()
    gc.freeze()     # the big static tables never need rescanning
    return brain


def act(brain, rows, sent, out):
    try:
        action = brain.act(rows, sent)
    except Exception:
        action = 'I'
    return send(out, action)


if __name__ == '__main__':
    main()
