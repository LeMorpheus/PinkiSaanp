#!/usr/bin/env python3
"""Smoke-test bot: random walk that occasionally tries every ability.

I/O (per README): read an 11x11 grid (11 lines), reply with ONE line, flush.
The game sends a grid at start and after each action. We always see ourselves
as Player 1 ('1') spawning top-left, so D/S head toward the map centre.
"""
import random
import sys

VIEW = 11  # 2 * view_distance + 1

MOVES = ["D", "D", "S", "S", "A", "W", "I"]
DIRS = "WASD"


def read_view():
    rows = []
    for _ in range(VIEW):
        line = sys.stdin.readline()
        if not line:  # EOF: game is over
            return None
        rows.append(line.rstrip("\n"))
    return rows


def offset():
    """Random (i, j) with 0 < i^2 + j^2 <= 16."""
    while True:
        i, j = random.randint(-4, 4), random.randint(-4, 4)
        if 0 < i * i + j * j <= 16:
            return i, j


def choose(move_no):
    # Every 10th move try an ability so all command parsers get exercised.
    if move_no % 10 == 9:
        kind = random.choice("JGXBC")
        if kind in "JGX":
            return f"{kind}{random.choice(DIRS)}"
        i, j = offset()
        return f"{kind} {i} {j}"
    return random.choice(MOVES)


def main():
    move_no = 0
    while True:
        view = read_view()
        if view is None:
            break
        action = choose(move_no)
        try:
            print(action, flush=True)
        except BrokenPipeError:  # game already exited after the last move
            break
        if move_no % 100 == 0:  # keep the log small
            print(f"move {move_no}: sent {action!r}, center={view[VIEW // 2][VIEW // 2]!r}",
                  file=sys.stderr, flush=True)
        move_no += 1


if __name__ == "__main__":
    main()