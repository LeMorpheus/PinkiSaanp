#!/usr/bin/env python3
"""Wall-hugger bot (right-hand rule).

Phase 1: walk straight (starting RIGHT) until the way ahead is blocked.
Phase 2: keep the wall on our right. Each move, try in order:
         turn right, go straight, turn left, turn back. Idle if boxed in.

Directions are in the bot's own view frame (we always see ourselves as
Player 1 at the top-left), so no un-flipping is needed.
"""
import sys

VIEW = 11
C = VIEW // 2  # our tile in the view

# Clockwise order, so right = +1, back = +2, left = +3 (mod 4).
DIRS = [("W", 0, -1), ("D", 1, 0), ("S", 0, 1), ("A", -1, 0)]

# Walls, void, bombs, other players. Air, any paint and bullets are passable
# (a bullet that meets a player just breaks).
BLOCKED = set("#*~!@$%234")


def read_view():
    rows = []
    for _ in range(VIEW):
        line = sys.stdin.readline()
        if not line:
            return None
        rows.append(line.rstrip("\n"))
    return rows


def free(view, h):
    _, dx, dy = DIRS[h]
    try:
        return view[C + dy][C + dx] not in BLOCKED
    except IndexError:
        return False


def decide(view, heading, hugging):
    """Return (new_heading, hugging, action)."""
    if not hugging:
        if free(view, heading):
            return heading, False, DIRS[heading][0]
        # Reached a wall: turn left so the wall ends up on our right.
        heading = (heading + 3) % 4
        hugging = True
    for turn in (1, 0, 3, 2):  # right, straight, left, back
        h = (heading + turn) % 4
        if free(view, h):
            return h, True, DIRS[h][0]
    return heading, True, "I"


def main():
    heading, hugging = 1, False  # start heading RIGHT (towards the map centre)
    move_no = 0
    while True:
        view = read_view()
        if view is None:
            break
        heading, hugging, action = decide(view, heading, hugging)
        try:
            print(action, flush=True)
        except BrokenPipeError:  # game already exited after the last move
            break
        if move_no % 100 == 0:
            print(f"move {move_no}: {action} heading={DIRS[heading][0]} hugging={hugging}",
                  file=sys.stderr, flush=True)
        move_no += 1


if __name__ == "__main__":
    main()