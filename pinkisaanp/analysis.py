"""Per-tick board analysis: threat/influence maps and timing facts.

Everything downstream (planner, FSM, A*) reads from one ``Analysis`` object
that is built once per decision in a few milliseconds:

* ``EnemyModel.danger[T]``: bitboard of cells the enemy can occupy within ``T``
  of *our* moves (speed- and lag-adjusted, no-reverse on its first move,
  blocked only by walls and its own trail).  This is the threat influence map.
* ``threat[c]``: earliest time any enemy can reach cell ``c``.
* ``dist_home[c]`` / ``dist_me[c]``: our BFS distances (home field doubles as the
  admissible A* heuristic).
* ``home_time``: earliest time an enemy can be back on its own land, i.e. the
  deadline before which its trail can be cut.
* ``pocket``: the region an enemy would enclose if it returned home along its
  shortest path (standing there when it closes = being painted to death).
"""

import math

from .geometry import INF, popcount


class EnemyModel:
    __slots__ = ('p', 'layers', 'danger', 'home_time', 'body', 'next_cells',
                 'pocket', 'trail_len', 'home_path', 'pred')

    def min_arrival(self, mask):
        """Earliest of our time steps at which this enemy can touch ``mask``."""
        danger = self.danger
        if not mask or not (danger[-1] & mask):
            return INF
        lo, hi = 0, len(danger) - 1
        while lo < hi:
            mid = (lo + hi) >> 1
            if danger[mid] & mask:
                hi = mid
            else:
                lo = mid + 1
        return lo


def _steps_within(T, lag, speed):
    """Cells an enemy can advance from its head within T of our moves."""
    if T <= lag:
        return 0
    return int(math.floor((T - lag) * speed + 1e-9))


class Analysis:
    def __init__(self, view, cfg):
        self.view = view
        self.cfg = cfg
        self.board = b = view.board
        self.me = me = view.me
        horizon = cfg.horizon
        if view.steps_left is not None:
            horizon = max(4, min(horizon, int(view.steps_left) + 2))
        self.horizon = horizon
        full = b.full
        bit = b.bit

        # ---- our own distance fields -----------------------------------
        self.my_block = me.trail_mask & ~bit[me.head]
        passable = full & ~self.my_block
        self.dist_home = b.distance_field(me.terr, passable)
        my_layers = b.reach_layers(me.head, me.dir, passable, b.n)
        self.dist_me = self._decode_masks(my_layers)

        # ---- enemy threat models ----------------------------------------
        enemies = []
        body_union = 0
        pocket_union = 0
        for p in view.enemies:
            em = EnemyModel()
            em.p = p
            e_pass = full & ~(p.trail_mask & ~bit[p.head])
            kmax = _steps_within(horizon, p.lag, p.speed) + 1
            em.layers = layers = b.reach_layers(p.head, p.dir, e_pass, kmax)
            last = len(layers) - 1
            em.danger = [layers[min(last, _steps_within(T, p.lag, p.speed))]
                         for T in range(horizon + 1)]
            em.trail_len = len(p.trail)
            em.body = p.trail_mask & ~bit[p.head]
            em.home_path = None
            em.pocket = 0
            if not p.trail_mask:
                em.home_time = 0.0
            else:
                k = next((k for k, lay in enumerate(layers) if lay & p.terr), None)
                if k is None:
                    em.home_time = float(INF)
                else:
                    em.home_time = p.lag + k / p.speed
                    if em.trail_len >= 2:
                        em.home_path = self._backtrack(layers, k, p.terr)
                        if em.home_path:
                            fence = p.trail_mask | b.mask(em.home_path)
                            em.pocket = b.capture(p.terr, fence, cfg.wall_encloses) & ~fence
            em.next_cells = em.danger[1] | bit[p.head] if horizon >= 1 else bit[p.head]
            if em.body and em.home_time > 0:
                body_union |= em.body
            pocket_union |= em.pocket
            enemies.append(em)
        self.enemies = enemies
        self.vulnerable = [em for em in enemies if em.body and em.home_time > 0]
        # Ram targets: enemies with a trail heading home along a predictable path.
        # Meeting their head while our trail is shorter kills them (head-on rule).
        for em in enemies:
            p = em.p
            em.pred = None
            if em.home_path and p.lag < 0.05 and abs(p.speed - 1.0) < 1e-6:
                em.pred = [p.head] + em.home_path
        self.ram_targets = [em for em in enemies if em.pred]
        self.body_union = body_union
        self.pocket_union = pocket_union

        # ---- combined threat influence map ---------------------------------
        danger_all = [0] * (horizon + 1)
        for em in enemies:
            for T in range(horizon + 1):
                danger_all[T] |= em.danger[T]
        self.danger_all = danger_all
        self.threat = self._decode_masks(danger_all)

        # Rammer contact map: enemies whose trail is (nearly) empty win every
        # head-on against us while we carry a trail, and squares touch one cell
        # early (diagonal approach), so their reach is dilated by one cell.  An
        # enemy still outside becomes a rammer the moment it can be back home.
        ram = [0] * (horizon + 1)
        for em in enemies:
            if em.trail_len <= cfg.ram_trail_len:
                start = 0
            elif em.home_time < horizon:
                start = int(math.ceil(em.home_time))
            else:
                continue
            for T in range(start, horizon + 1):
                ram[T] |= em.danger[T]
        self.ram_contact = self._decode_masks([b.dilate(m) for m in ram])
        # Exposure weight per cell: open flanks (wall hugging) x threat proximity.
        tau = cfg.exposure_tau
        decay = [math.exp(-T / tau) for T in range(horizon + 1)]
        open_sides = b.open_sides
        threat = self.threat
        self.expo = [(open_sides[c] - 2) * decay[threat[c]]
                     if threat[c] < INF and open_sides[c] > 2 else 0.0
                     for c in range(b.n)]

        enemy_terr = 0
        for p in view.enemies:
            enemy_terr |= p.terr
        self.enemy_terr = enemy_terr & ~me.terr
        self.bonus_cells = {c: kind for c, kind in view.bonuses}
        self.bonus_mask = b.mask(self.bonus_cells)
        self.my_area = popcount(me.terr)

        # Distance from the nearest threat to our exposure (head, trail, home edge).
        frontier = me.trail_mask | bit[me.head] | (b.dilate(me.terr) & ~me.terr)
        self.nearest_threat = self.min_arrival_all(frontier)

    # ------------------------------------------------------------------
    def min_arrival_all(self, mask):
        danger = self.danger_all
        if not mask or not danger or not (danger[-1] & mask):
            return INF
        lo, hi = 0, len(danger) - 1
        while lo < hi:
            mid = (lo + hi) >> 1
            if danger[mid] & mask:
                hi = mid
            else:
                lo = mid + 1
        return lo

    def _decode_masks(self, masks):
        """Cumulative masks -> per-cell first time index (INF if never)."""
        out = [INF] * self.board.n
        prev = 0
        cells = self.board.cells
        for T, m in enumerate(masks):
            new = m & ~prev
            if new:
                for c in cells(new):
                    out[c] = T
                prev = m
        return out

    def _backtrack(self, layers, k, target):
        """One shortest path (cells after the head) that ends in ``target``."""
        b = self.board
        bit = b.bit
        hit = layers[k] & target
        if not hit or k == 0:
            return None
        cur = b.cells(hit & -hit)[0]
        path = [cur]
        for j in range(k - 1, 0, -1):
            exact = layers[j] & ~layers[j - 1]  # cells at distance exactly j
            nxt = None
            for n in b.nbr[cur]:
                if n >= 0 and bit[n] & exact:
                    nxt = n
                    break
            if nxt is None:
                return None
            cur = nxt
            path.append(cur)
        path.reverse()
        return path
