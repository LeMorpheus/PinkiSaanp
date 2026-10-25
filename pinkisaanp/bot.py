"""PinkiSaanp: the decision loop.

    view -> Analysis (threat maps, ~2-5 ms)
         -> Planner: home / attack / commit / rectangle / defend candidates
            (time-boxed, smallest loops first)
         -> StateMachine.select -> (state, route)
         -> move guard (never reverse, never a wall, never our own trail)
         -> direction

Any exception anywhere falls through to a survival move, so the bot always
answers in time with a legal direction.
"""

from time import perf_counter

from .analysis import Analysis
from .config import BotConfig
from .fsm import DEFENDING, StateMachine
from .geometry import DIR_NAMES, INF, allowed_dirs, popcount
from .planner import Planner


class Decision:
    __slots__ = ('direction', 'state', 'route', 'elapsed', 'candidates', 'note')

    def __init__(self, direction, state, route=None, elapsed=0.0, candidates=0, note=''):
        self.direction = direction
        self.state = state
        self.route = route
        self.elapsed = elapsed
        self.candidates = candidates
        self.note = note

    @property
    def name(self):
        return DIR_NAMES[self.direction]

    def debug(self):
        r = self.route
        if r is None:
            return '%s %s %.0fms' % (self.state, self.note, self.elapsed * 1000)
        return '%s %s len=%d T=%d gain=%.0f kill=%.0f ps=%.2f U=%.2f n=%d %.0fms' % (
            self.state, r.kind, len(r.cells), r.t_close, r.gain, r.kill_value,
            r.p_survive, r.utility, self.candidates, self.elapsed * 1000)


class PinkiSaanp:
    NAME = 'PinkiSaanp'

    def __init__(self, cfg=None, strict=False):
        self.cfg = cfg or BotConfig()
        self.strict = strict  # tests: re-raise instead of falling back
        self.fsm = StateMachine(self.cfg)
        self.rate = self.cfg.rate_prior
        self.plan = None
        self.last_area = None
        self.max_elapsed = 0.0
        self.total_elapsed = 0.0
        self.decisions = 0
        self.last = None

    # ------------------------------------------------------------------
    def decide(self, view):
        t0 = perf_counter()
        deadline = t0 + self.cfg.time_budget
        try:
            decision = self._decide(view, deadline)
        except Exception as exc:  # never crash, never time out
            if self.strict:
                raise
            decision = Decision(survival_move(view), DEFENDING, note='fallback:%s' % type(exc).__name__)
        decision.elapsed = perf_counter() - t0
        self.total_elapsed += decision.elapsed
        self.max_elapsed = max(self.max_elapsed, decision.elapsed)
        self.decisions += 1
        self.last = decision
        return decision

    def _decide(self, view, deadline):
        cfg = self.cfg
        me = view.me
        b = view.board
        area = popcount(me.terr)
        if self.last_area is not None:
            gained = max(0, area - self.last_area)
            self.rate += cfg.rate_ema * (gained - self.rate)
        self.last_area = area

        an = Analysis(view, cfg)
        planner = Planner(an, cfg, self.rate, deadline)
        routes = []
        # Order matters under the time budget: survival first, then kills,
        # then the plan we are already executing, then fresh loops.
        routes.extend(planner.home_routes())
        routes.extend(planner.attack_routes())
        routes.extend(planner.ram_routes())
        commit = planner.continue_route(self.plan)
        if commit is not None:
            commit.utility += abs(commit.utility) * cfg.commit_bonus
            routes.append(commit)
        if not planner.timed_out:
            routes.extend(planner.rectangle_routes())
        routes.extend(planner.defend_routes())

        state, route = self.fsm.select(an, routes)
        direction = None
        if route is not None and route.cells:
            direction = self._dir_to(b, me.head, route.cells[0])
            if direction is None or not legal(view, direction):
                direction = None
        if direction is None:
            route = None
            direction = survival_move(view, an)
        self.plan = list(route.cells) if route is not None else None
        return Decision(direction, state, route, candidates=planner.evaluated)

    @staticmethod
    def _dir_to(b, a, c):
        for d, n in enumerate(b.nbr[a]):
            if n == c:
                return d
        return None

    # ------------------------------------------------------------------
    def stats(self):
        n = max(1, self.decisions)
        return {'decisions': self.decisions, 'avg_ms': 1000 * self.total_elapsed / n,
                'max_ms': 1000 * self.max_elapsed, 'states': list(self.fsm.history[-8:])}


def legal(view, d):
    me = view.me
    if d not in allowed_dirs(me.dir):
        return False
    n = view.board.nbr[me.head][d]
    if n < 0:
        return False
    return not (view.board.bit[n] & me.trail_mask)


def survival_move(view, an=None):
    """Last-resort move: legal, keeps the largest free area, heads home, dodges heads."""
    b = view.board
    me = view.me
    bit = b.bit
    blocked = me.trail_mask
    best = None
    best_key = None
    for d in allowed_dirs(me.dir):
        n = b.nbr[me.head][d]
        if n < 0 or bit[n] & blocked:
            continue
        area = popcount(b.flood(bit[n], b.full & ~(blocked | bit[me.head])))
        home = an.dist_home[n] if an is not None else 0
        danger = 0
        for e in view.enemies:
            if b.manhattan(e.head, n) <= 1 and not (bit[n] & me.terr):
                danger += 1
        key = (min(area, 40), -danger, -home if home < INF else -999, area)
        if best_key is None or key > best_key:
            best_key = key
            best = d
    if best is None:  # every move is fatal: keep heading where we were going
        return me.dir if me.dir is not None else 0
    return best
