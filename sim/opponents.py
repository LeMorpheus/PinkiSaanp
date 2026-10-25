"""Baseline opponents that model the bots PinkiSaanp will meet in a hackathon.

* RandomSafe     - random walker that at least avoids walls and its own trail.
* GreedyLooper   - big rectangle loops, zero threat awareness (the common
                   "works on my machine" hackathon bot).
* CautiousLooper - medium loops, runs home when an enemy gets close to its
                   trail (BFS race test like the Stanford "safe builder").
* Hunter         - cautious looper that also dives at exposed enemy trails it
                   can reach before their owner gets home.
"""

import random

from pinkisaanp.geometry import INF, allowed_dirs


def _legal(view, d):
    me = view.me
    n = view.board.nbr[me.head][d]
    return n >= 0 and not (view.board.bit[n] & me.trail_mask)


def _home_field(view):
    b = view.board
    me = view.me
    block = me.trail_mask & ~b.bit[me.head]
    return b.distance_field(me.terr, b.full & ~block)


def _step_down(view, field, rng=None):
    """Move that decreases ``field``; ties broken randomly."""
    b = view.board
    me = view.me
    best = []
    best_v = INF
    for d in allowed_dirs(me.dir):
        if not _legal(view, d):
            continue
        v = field[b.nbr[me.head][d]]
        if v < best_v:
            best_v, best = v, [d]
        elif v == best_v:
            best.append(d)
    if not best:
        return None
    return (rng or random).choice(best)


def _any_legal(view, rng):
    me = view.me
    opts = [d for d in allowed_dirs(me.dir) if _legal(view, d)]
    if not opts:
        return me.dir if me.dir is not None else 0
    if me.dir in opts and rng.random() < 0.7:
        return me.dir
    return rng.choice(opts)


class RandomSafe:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)

    def act(self, view):
        b = view.board
        me = view.me
        opts = []
        for d in allowed_dirs(me.dir):
            if not _legal(view, d):
                continue
            n = b.nbr[me.head][d]
            room = b.flood(b.bit[n], b.full & ~me.trail_mask)
            if room:
                opts.append(d)
        if not opts:
            return _any_legal(view, self.rng)
        if me.dir in opts and self.rng.random() < 0.75:
            return me.dir
        return self.rng.choice(opts)


class GreedyLooper:
    """Out ``a`` cells, across ``b`` cells, then straight home."""

    def __init__(self, seed=None, amin=4, amax=11, threat_check=False, hunt=False):
        self.rng = random.Random(seed)
        self.amin = amin
        self.amax = amax
        self.threat_check = threat_check
        self.hunt = hunt
        self.plan = []
        self.homing = False

    def _new_plan(self, view):
        me = view.me
        rng = self.rng
        dirs = [d for d in allowed_dirs(me.dir) if _legal(view, d)]
        if not dirs:
            return []
        d1 = rng.choice(dirs)
        d2 = (d1 + rng.choice((1, 3))) & 3
        a = rng.randint(self.amin, self.amax)
        bb = rng.randint(self.amin, self.amax)
        # walk to the edge first (unknown length): encode as a marker
        return [('edge', d1)] + [d1] * a + [d2] * bb

    def _threatened(self, view, field):
        me = view.me
        if not me.trail_mask:
            return False
        b = view.board
        my_home = field[me.head]
        for e in view.enemies:
            # BFS from the enemy over everything except its own trail
            df = b.distance_field(b.bit[e.head], b.full & ~(e.trail_mask & ~b.bit[e.head]),
                                  limit=my_home + 3)
            best = min((df[c] for c in b.cells(me.trail_mask)), default=INF)
            if best <= my_home + 1:
                return True
        return False

    def _hunt(self, view):
        b = view.board
        me = view.me
        if not view.enemies:
            return None
        mine = b.distance_field(b.bit[me.head], b.full & ~(me.trail_mask & ~b.bit[me.head]),
                                limit=25)
        best = None
        for e in view.enemies:
            if not e.trail_mask:
                continue
            ef = b.distance_field(b.bit[e.head], b.full & ~(e.trail_mask & ~b.bit[e.head]),
                                  limit=30)
            e_home = min((ef[c] for c in b.cells(e.terr)), default=INF)
            for c in b.cells(e.trail_mask & ~b.bit[e.head]):
                if mine[c] < e_home and (best is None or mine[c] < best[0]):
                    best = (mine[c], c)
        if best is None:
            return None
        field = b.distance_field(b.bit[best[1]], b.full & ~me.trail_mask)
        return _step_down(view, field, self.rng)

    def act(self, view):
        me = view.me
        b = view.board
        inside = bool(b.bit[me.head] & me.terr) and not me.trail_mask
        if self.hunt:
            d = self._hunt(view)
            if d is not None:
                self.plan = []
                self.homing = True
                return d
        if inside:
            self.homing = False
            if not self.plan:
                self.plan = self._new_plan(view)
        field = None
        if me.trail_mask:
            field = _home_field(view)
            if self.threat_check and self._threatened(view, field):
                self.homing = True
                self.plan = []
        if self.homing or (me.trail_mask and not self.plan):
            self.homing = True
            if field is None:
                field = _home_field(view)
            d = _step_down(view, field, self.rng)
            return d if d is not None else _any_legal(view, self.rng)
        while self.plan:
            step = self.plan[0]
            if isinstance(step, tuple):  # ('edge', d): go straight until we leave home
                d = step[1]
                if not inside:
                    self.plan.pop(0)
                    continue
                if d in allowed_dirs(me.dir) and _legal(view, d):
                    return d
                self.plan = []
                break
            self.plan.pop(0)
            if step in allowed_dirs(me.dir) and _legal(view, step):
                return step
            self.plan = []
            break
        if me.trail_mask:
            self.homing = True
            field = field or _home_field(view)
            d = _step_down(view, field, self.rng)
            if d is not None:
                return d
        return _any_legal(view, self.rng)


def CautiousLooper(seed=None):
    return GreedyLooper(seed, amin=3, amax=7, threat_check=True)


def Hunter(seed=None):
    return GreedyLooper(seed, amin=3, amax=7, threat_check=True, hunt=True)


class PinkiAgent:
    """Adapter so the engine can drive PinkiSaanp directly with GameViews."""

    def __init__(self, cfg=None, strict=True):
        from pinkisaanp import PinkiSaanp
        # Strict in the simulator: a planner exception surfaces as an engine
        # 'crash' event instead of being masked by the survival fallback.
        self.bot = PinkiSaanp(cfg, strict=strict)

    def act(self, view):
        return self.bot.decide(view).direction

    def state_label(self):
        last = self.bot.last
        return last.state if last else ''


class GenericPinkiAgent(PinkiAgent):
    """PinkiSaanp driven through GenericAdapter: screen coordinates (y down),
    no headings in the state - exercises the hackathon-style input path."""

    def __init__(self, cfg=None, strict=True):
        super().__init__(cfg, strict)
        from pinkisaanp import GenericAdapter
        self.adapter = GenericAdapter(y_down=True)

    def act(self, view):
        b = view.board
        h = b.h

        def pt(c):
            return [c % b.w, h - 1 - c // b.w]

        players = []
        for p in [view.me] + view.enemies:
            players.append({'id': p.pid, 'position': pt(p.head),
                            'territory': [pt(c) for c in b.cells(p.terr)],
                            'trail': [pt(c) for c in p.trail if c != p.head]})
        state = {'width': b.w, 'height': h, 'me': view.me.pid, 'tick': view.tick,
                 'max_ticks': view.tick + (view.steps_left or 0), 'players': players}
        name = self.adapter.command(self.bot.decide(self.adapter.view(state)).direction)
        return ('UP', 'RIGHT', 'DOWN', 'LEFT').index(name)


REGISTRY = {
    'random': RandomSafe,
    'greedy': GreedyLooper,
    'cautious': CautiousLooper,
    'hunter': Hunter,
}
