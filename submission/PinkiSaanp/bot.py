#!/usr/bin/env python3
"""PinkiSaanp - Codewars Agent Showdown bot. Reads 11x11 views, answers one command per line."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pinki.brain import Brain  # noqa: E402


def load_variant():
    """Optional variant.json next to bot.py (used only for local A/B testing)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'variant.json')
    try:
        import json
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    brain = Brain(log=os.environ.get('PINKI_LOG', '1') == '1', variant=load_variant())
    stdin = sys.stdin
    out = sys.stdout
    while True:
        rows = []
        for _ in range(11):
            line = stdin.readline()
            if not line:
                return
            rows.append(line.rstrip('\r\n'))
        try:
            action = brain.act(rows)
        except Exception:
            action = 'I'
        try:
            out.write(action + '\n')
            out.flush()
        except BrokenPipeError:
            return


if __name__ == '__main__':
    main()
