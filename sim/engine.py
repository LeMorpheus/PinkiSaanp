"""Local Paper.io engine that mirrors References/paperio/local_runner rules.

One engine step = every living player advances one cell, simultaneously.
Per-step resolution order (same as game_objects/game.py):

  1. read every bot's direction (a reversal is ignored, like the server);
  2. move; leaving the arena kills;
  3. extend trails; re-entering own territory with a trail closes the loop and
     computes the capture (trail cleared *before* collision checks, so closing
     on the tick an enemy arrives saves you);
  4. losses: someone's head on your trail (excluding your head cell) kills you
     (+50 to the cutter, self-cuts count); head-on contact kills the player
     with the longer-or-equal trail; an empty territory kills;
  5. cells claimed by two captures at once go to nobody; a head standing inside
     somebody else's capture is "painted" to death;
  6. captures are applied (1 point per neutral cell, 5 per enemy cell) and the
     dead are removed (their land becomes neutral).
"""

import math
import random
from time import perf_counter

from pinkisaanp.geometry import Board, allowed_dirs, popcount
from pinkisaanp.state import GameView, PlayerView

NEUTRAL_SCORE = 1
ENEMY_SCORE = 5
LINE_KILL_SCORE = 50
SUBSTEPS = 6  # reference: WIDTH 30 / SPEED 5


class SimPlayer:
    def __init__(self, pid, name, agent, head, terr):
        self.pid = pid
        self.name = name
        self.agent = agent
        self.head = head
        self.prev = head
        self.dir = None
        self.trail = []
        self.trail_mask = 0
        self.terr = terr
        self.alive = True
        self.score = 0
        self.kills = 0
        self.death = None
        self.think_time = 0.0
        self.max_think = 0.0
        self.pending = 0
        self.prev_trail_len = 0
        self.crashes = 0


def start_cells(w, h, n, rng):
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    r = 0.31 * min(w, h)
    off = rng.random() * 2 * math.pi
    out = []
    for k in range(n):
        a = off + 2 * math.pi * k / n
        x = int(round(cx + r * math.cos(a)))
        y = int(round(cy + r * math.sin(a)))
        out.append((min(max(x, 1), w - 2), min(max(y, 1), h - 2)))
    return out


class Engine:
    def __init__(self, w, h, agents, max_steps=250, seed=0, wall_encloses=False,
                 record=False, shuffle=True):
        self.board = b = Board(w, h)
        self.rng = random.Random(seed)
        self.max_steps = max_steps
        self.wall_encloses = wall_encloses
        self.step_no = 0
        order = list(range(len(agents)))
        if shuffle:
            self.rng.shuffle(order)
        starts = start_cells(w, h, len(agents), self.rng)
        self.players = []
        for slot, k in enumerate(order):
            name, agent = agents[k]
            x, y = starts[slot]
            head = b.idx(x, y)
            terr = 0
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if b.inside(x + dx, y + dy):
                        terr |= b.bit[b.idx(x + dx, y + dy)]
            self.players.append(SimPlayer(k, name, agent, head, terr))
        self.frames = [] if record else None
        self.events = []
        if record:
            self._record({})

    # ------------------------------------------------------------------
    def alive(self):
        return [p for p in self.players if p.alive]

    def view_for(self, p):
        b = self.board
        me = PlayerView(p.pid, p.head, p.dir, p.trail, p.terr, b, score=p.score, is_me=True)
        others = [PlayerView(q.pid, q.head, q.dir, q.trail, q.terr, b, score=q.score)
                  for q in self.players if q.alive and q is not p]
        return GameView(b, me, others, tick=self.step_no,
                        steps_left=self.max_steps - self.step_no)

    def run(self):
        while self.step_no < self.max_steps and self.alive():
            self.step()
        return self.results()

    def step(self):
        b = self.board
        bit = b.bit
        live = self.alive()
        states = {}
        # 1. decisions
        for p in live:
            view = self.view_for(p)
            t0 = perf_counter()
            try:
                d = p.agent.act(view)
            except Exception as exc:  # a crashing bot keeps its heading
                self.events.append((self.step_no, p.name, 'crash %r' % exc))
                p.crashes += 1
                d = p.dir
            el = perf_counter() - t0
            p.think_time += el
            p.max_think = max(p.max_think, el)
            if d is None:
                d = p.dir if p.dir is not None else 0
            if d not in allowed_dirs(p.dir):
                d = p.dir
            p.dir = d
            st = getattr(p.agent, 'state_label', None)
            if st:
                states[p.pid] = st()
        # 2. move
        dead = {}
        for p in live:
            p.prev = p.head
            p.prev_trail_len = len(p.trail)
            n = b.nbr[p.head][p.dir]
            if n < 0:
                dead[p] = 'wall'
            else:
                p.head = n
        # 3. trails and captures (points are banked only by survivors of the step)
        captures = {}
        for p in live:
            p.pending = 0
            if p in dead:
                continue
            hb = bit[p.head]
            if not (hb & p.terr) or p.trail:
                p.trail.append(p.head)
                p.trail_mask |= hb
            if hb & p.terr and len(p.trail) > 1:
                cap = b.capture(p.terr, p.trail_mask, self.wall_encloses)
                if cap:
                    captures[p] = cap
                    p.pending += NEUTRAL_SCORE * popcount(cap)
                p.trail = []
                p.trail_mask = 0
        # 4. losses
        for p in live:
            if p in dead:
                continue
            body = p.trail_mask & ~(bit[p.trail[-1]] if p.trail else 0)
            for q in live:
                if q in dead and dead[q] == 'wall':
                    continue
                if bit[q.head] & body:
                    if q is p:
                        dead[p] = 'self-cut'
                    else:
                        dead.setdefault(p, 'cut by %s' % q.name)
                        q.pending += LINE_KILL_SCORE
                        q.kills += 1
        for i, p in enumerate(live):
            for q in live[i + 1:]:
                if dead.get(p) == 'wall' or dead.get(q) == 'wall':
                    continue
                k = self._contact(p, q)
                if k:
                    lp = len(p.trail) if k == SUBSTEPS else p.prev_trail_len
                    lq = len(q.trail) if k == SUBSTEPS else q.prev_trail_len
                    if lp >= lq:
                        dead.setdefault(p, 'head-on with %s' % q.name)
                    if lq >= lp:
                        dead.setdefault(q, 'head-on with %s' % p.name)
                    if lp != lq:  # no points in the reference, but it is a kill
                        (q if lp > lq else p).kills += 1
        for p in live:
            if not p.terr and p not in dead:
                dead[p] = 'no territory'
        # 5. contested cells and painting
        valid = {p: c for p, c in captures.items() if p not in dead}
        resolved = {}
        for p, c in valid.items():
            mine = c
            for q, c2 in valid.items():
                if q is not p:
                    mine &= ~c2
            resolved[p] = mine
        # Reference Player.is_ate: a player sitting on a cell centre is painted
        # only if its previous cell is inside the capture too (stepping onto a
        # trail as it closes, from outside, is survivable - COLLISIONS.md #6).
        for p in live:
            if p in dead:
                continue
            for q, c in resolved.items():
                if q is not p and bit[p.head] & c and bit[p.prev] & c:
                    dead[p] = 'painted by %s' % q.name
                    break
        # 6. apply
        for p, c in resolved.items():
            if p in dead:
                continue
            p.terr |= c
            for q in live:
                if q is not p and q.terr & c:
                    removed = q.terr & c
                    q.terr &= ~c
                    p.pending += (ENEMY_SCORE - NEUTRAL_SCORE) * popcount(removed)
        for p in live:
            if p not in dead:
                p.score += p.pending
        for p, why in dead.items():
            p.alive = False
            p.death = (self.step_no, why)
            p.terr = 0
            p.trail = []
            p.trail_mask = 0
            self.events.append((self.step_no, p.name, why))
        self.step_no += 1
        if self.frames is not None:
            self._record(states)

    def _contact(self, p, q):
        """First substep (1..6) at which the two squares overlap, else 0."""
        b = self.board
        w = b.w
        if b.manhattan(p.head, q.head) > 2 and b.manhattan(p.prev, q.prev) > 2:
            return 0
        px0, py0 = p.prev % w, p.prev // w
        px1, py1 = p.head % w, p.head // w
        qx0, qy0 = q.prev % w, q.prev // w
        qx1, qy1 = q.head % w, q.head // w
        for k in range(1, SUBSTEPS + 1):
            f = k / float(SUBSTEPS)
            dx = (px0 + (px1 - px0) * f) - (qx0 + (qx1 - qx0) * f)
            dy = (py0 + (py1 - py0) * f) - (qy0 + (qy1 - qy0) * f)
            if abs(dx) < 1 - 1e-9 and abs(dy) < 1 - 1e-9:
                return k
        return 0

    # ------------------------------------------------------------------
    def results(self):
        out = []
        for p in self.players:
            out.append({'pid': p.pid, 'name': p.name, 'score': p.score,
                        'territory': popcount(p.terr), 'alive': p.alive,
                        'kills': p.kills, 'death': p.death, 'crashes': p.crashes,
                        'think_avg_ms': 1000 * p.think_time / max(1, self.step_no),
                        'think_max_ms': 1000 * p.max_think})
        return out

    def _record(self, states):
        b = self.board
        owner = ['.'] * b.n
        for p in self.players:
            if p.alive:
                for c in b.cells(p.terr):
                    owner[c] = str(p.pid)
        self.frames.append({
            's': self.step_no,
            'o': ''.join(owner),
            'p': [{'id': p.pid, 'h': p.head, 't': list(p.trail), 'a': p.alive,
                   'sc': p.score, 'st': states.get(p.pid, '')} for p in self.players],
        })

    def replay(self):
        return {'w': self.board.w, 'h': self.board.h, 'max_steps': self.max_steps,
                'players': [{'id': p.pid, 'name': p.name} for p in self.players],
                'frames': self.frames or [], 'events': self.events}
