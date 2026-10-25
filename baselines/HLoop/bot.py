#!/usr/bin/env python3
"""Lightweight reactive opponent model ("intuition bot") for A/B tests.

Purely local (11x11 view, no map, no search), microseconds per move.  variant.json:
  {"mode": "loop" | "aggro" | "spray", "seed": N}
  loop : greedy rectangle loops out of its land; panics home when an enemy head is within 3.
  aggro: chases visible enemy heads, walks across enemy paint, shoots lines of enemy paint,
         walls the last own tile behind an enemy head; loops when nothing is in sight.
  spray: biased random walk with loops, fires and bombs whenever it can.
"""
import json
import os
import random
import sys

DIRS = 'WASD'
DX = (0, -1, 0, 1)
DY = (-1, 0, 1, 0)
FREE = set('.ABCD')
C = 5


def load():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'variant.json')) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class Bot:
    def __init__(self, v):
        self.mode = v.get('mode', 'loop')
        self.rng = random.Random(v.get('seed', 1))
        self.t = 0
        self.me = None
        self.paint = None
        self.out = False
        self.dir = 3
        self.leg = 0
        self.steps = 0
        self.legs = (5, 5)
        self.turn = 1
        self.last_gun = -100
        self.last_bomb = -100
        self.walls = 5
        self.wall_t = 0

    def at(self, rows, x, y):
        if 0 <= y < 11 and 0 <= x < 11:
            return rows[y][x]
        return '~'

    def free(self, rows, d):
        return self.at(rows, C + DX[d], C + DY[d]) in FREE

    def enemies(self, rows):
        out = []
        for y in range(11):
            for x in range(11):
                ch = rows[y][x]
                if ch in '1234' and (x, y) != (C, C):
                    out.append((x, y, ch))
        return out

    def step_toward(self, rows, tx, ty, prefer=None):
        best = None
        for d in range(4):
            if not self.free(rows, d):
                continue
            nx, ny = C + DX[d], C + DY[d]
            dist = abs(nx - tx) + abs(ny - ty)
            bonus = -0.5 if prefer and self.at(rows, nx, ny) in prefer else 0
            k = (dist + bonus, self.rng.random())
            if best is None or k < best[0]:
                best = (k, d)
        return None if best is None else DIRS[best[1]]

    def home_step(self, rows):
        """BFS in view to the nearest own paint cell."""
        seen = {(C, C): None}
        q = [(C, C)]
        for x, y in q:
            for d in range(4):
                nx, ny = x + DX[d], y + DY[d]
                if (nx, ny) in seen or self.at(rows, nx, ny) not in FREE:
                    continue
                seen[(nx, ny)] = (x, y) if (x, y) != (C, C) else d
                if self.at(rows, nx, ny) == self.paint:
                    p = (nx, ny)
                    while not isinstance(seen[p], int):
                        p = seen[p]
                    return DIRS[seen[p]]
                q.append((nx, ny))
        return None

    def start_loop(self, rows):
        opts = []
        for d in range(4):
            if not self.free(rows, d):
                continue
            run = 0
            for k in range(1, 6):
                ch = self.at(rows, C + DX[d] * k, C + DY[d] * k)
                if ch not in FREE or ch == self.paint:
                    break
                run += 1
            opts.append((run + self.rng.random(), d))
        if not opts:
            return False
        opts.sort(reverse=True)
        self.dir = opts[0][1]
        self.legs = (self.rng.randint(3, 10), self.rng.randint(3, 12))
        self.turn = self.rng.choice((1, 3))
        self.leg = 0
        self.steps = 0
        self.out = True
        return True

    def loop_move(self, rows):
        if not self.out and not self.start_loop(rows):
            return 'I'
        heading = (self.dir + self.turn * self.leg) % 4
        limit = self.legs[0] if self.leg in (0, 2) else self.legs[1]
        if self.leg < 3 and self.steps >= limit:
            self.leg += 1
            self.steps = 0
            heading = (self.dir + self.turn * self.leg) % 4
        if not self.free(rows, heading):
            for alt in ((heading + self.turn) % 4, (heading - self.turn) % 4, (heading + 2) % 4):
                if self.free(rows, alt):
                    heading = alt
                    break
            else:
                return 'I'
        self.steps += 1
        if self.at(rows, C + DX[heading], C + DY[heading]) == self.paint and self.leg >= 1:
            self.out = False            # stepping back onto our land closes the loop
        return DIRS[heading]

    def gun_dir(self, rows, want):
        best = None
        for d in range(4):
            n = 0
            for k in range(1, 11):
                ch = self.at(rows, C + DX[d] * k, C + DY[d] * k)
                if ch not in FREE:
                    break
                if ch in want:
                    n += 1
            if best is None or n > best[0]:
                best = (n, d)
        return best

    def act(self, rows):
        if self.me is None:
            self.me = rows[C][C] if rows[C][C] in '1234' else '1'
            self.paint = 'ABCD'['1234'.index(self.me)]
        self.t += 1
        if self.t - self.wall_t >= 5:
            self.walls = min(30, self.walls + 1)
            self.wall_t = self.t
        foes = self.enemies(rows)
        enemy_paint = set('ABCD') - {self.paint}
        gun_ready = self.t >= 21 and self.t - self.last_gun >= 20
        bomb_ready = self.t >= 16 and self.t - self.last_bomb >= 16
        if self.mode == 'loop':
            near = [f for f in foes if max(abs(f[0] - C), abs(f[1] - C)) <= 3]
            if near and self.out:
                a = self.home_step(rows)
                if a:
                    return a
            return self.loop_move(rows)
        if self.mode == 'aggro':
            if gun_ready:
                n, d = self.gun_dir(rows, enemy_paint)
                if n >= 3:
                    self.last_gun = self.t
                    return 'G' + DIRS[d]
            for x, y, ch in foes:
                their = 'ABCD'['1234'.index(ch)]
                own = [(x + DX[d], y + DY[d]) for d in range(4) if self.at(rows, x + DX[d], y + DY[d]) == their]
                if len(own) == 1 and self.walls > 0:
                    i, j = own[0][0] - C, own[0][1] - C
                    if 0 < i * i + j * j <= 16:
                        self.walls -= 1
                        return 'C %d %d' % (i, j)
            if foes:
                x, y, _ = min(foes, key=lambda f: abs(f[0] - C) + abs(f[1] - C))
                a = self.step_toward(rows, x, y, prefer=enemy_paint)
                if a:
                    self.out = True
                    return a
            cells = [(x, y) for y in range(11) for x in range(11) if rows[y][x] in enemy_paint]
            if cells:
                x, y = min(cells, key=lambda c: abs(c[0] - C) + abs(c[1] - C))
                a = self.step_toward(rows, x, y, prefer=enemy_paint)
                if a:
                    self.out = True
                    return a
            return self.loop_move(rows)
        # spray
        if gun_ready:
            n, d = self.gun_dir(rows, set('.') | enemy_paint)
            if n >= 4:
                self.last_gun = self.t
                return 'G' + DIRS[d]
        if bomb_ready and self.rng.random() < 0.5:
            i, j = self.rng.choice([(i, j) for i in range(-4, 5) for j in range(-4, 5) if 0 < i * i + j * j <= 16])
            if self.at(rows, C + i, C + j) in FREE:
                self.last_bomb = self.t
                return 'B %d %d' % (i, j)
        if self.rng.random() < 0.3:
            opts = [d for d in range(4) if self.free(rows, d)]
            if opts:
                self.out = False
                return DIRS[self.rng.choice(opts)]
        return self.loop_move(rows)


def main():
    bot = Bot(load())
    while True:
        rows = []
        for _ in range(11):
            line = sys.stdin.readline()
            if not line:
                return
            rows.append((line.rstrip('\n') + '~' * 11)[:11])
        try:
            a = bot.act(rows)
        except Exception:
            a = 'I'
        sys.stdout.write(a + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
