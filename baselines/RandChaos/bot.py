#!/usr/bin/env python3
"""Test opponent: random walker that also fires every ability as soon as it has charge.

Moves keep a random heading for a random number of steps and avoid visible walls,
so it roams far (more chaos than the kit's random_walk) and cuts whatever its
random bullets, bombs and walls happen to cross.
"""
import json
import os
import random
import sys

VIEW = 11
C = VIEW // 2
DIRS = 'WASD'
DXY = {'W': (0, -1), 'A': (-1, 0), 'S': (0, 1), 'D': (1, 0)}
BLOCK = set('#*~1234!@$%GHKL')


def read_view():
    rows = []
    for _ in range(VIEW):
        line = sys.stdin.readline()
        if not line:
            return None
        rows.append(line.rstrip('\n'))
    return rows


def offset(r=4):
    while True:
        i, j = random.randint(-r, r), random.randint(-r, r)
        if 0 < i * i + j * j <= r * r:
            return i, j


def main():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'variant.json')) as f:
            random.seed(json.load(f).get('seed'))
    except (OSError, ValueError):
        pass
    t = 0
    heading = random.choice('DS')
    left = random.randint(3, 12)
    bullet = dict(charge=0, last=-100, next=20)
    bomb = dict(charge=0, last=-100, next=15)
    dash = dict(charge=1, last=-100, next=20)

    def tick(ab, mx, rech):
        if ab['charge'] < mx and t >= ab['next']:
            ab['charge'] += 1
            ab['next'] = t + rech

    while True:
        view = read_view()
        if view is None:
            break
        tick(bullet, 3, 20)
        tick(bomb, 1, 15)
        tick(dash, 2, 20)
        free = [d for d in DIRS if view[C + DXY[d][1]][C + DXY[d][0]] not in BLOCK]
        left -= 1
        if left <= 0 or heading not in free:
            heading = random.choice(free) if free else random.choice(DIRS)
            left = random.randint(3, 12)
        act = heading
        if not free:
            act = 'X' + heading          # boxed in: break out
        r = random.random()
        if act[0] == 'X':
            pass
        elif bomb['charge'] and t - bomb['last'] > 15 and r < 0.5:
            i, j = offset()
            act = 'B %d %d' % (i, j)
            bomb['charge'] -= 1
            bomb['last'] = t
        elif bullet['charge'] and t - bullet['last'] > 2 and r < 0.3:
            act = 'G' + random.choice(DIRS)
            bullet['charge'] -= 1
            bullet['last'] = t
        elif r > 0.995:
            i, j = offset()
            act = 'C %d %d' % (i, j)
        elif dash['charge'] and t - dash['last'] > 5 and r > 0.9:
            act = 'J' + heading
            dash['charge'] -= 1
            dash['last'] = t
        try:
            print(act, flush=True)
        except BrokenPipeError:
            break
        t += 1


if __name__ == '__main__':
    main()
