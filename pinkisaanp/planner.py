"""Candidate route generation and exact route evaluation.

A *route* is the list of cells we would visit, ending the moment the trail
closes on our territory (or, for DEFENDING walks, never leaving it).  Every
route is replayed against the real rules: self-crossing invalidates it, a
closing triggers an exact bitboard capture, enemy trails crossed before the
victim can get home score a kill, and every trail cell is checked against
each enemy's reach table.

Utility of a route (see STRATEGY.md section 2):

    margin_e  = arrival_e(trail) - deadline_e
    p_e       = sigmoid((margin_mid - margin_e) / margin_scale)
    P_survive = prod_e (1 - p_e) * (1 - pocket/head-on penalties)
    EV        = P_survive * (Gain + KillValue) - (1 - P_survive) * V_life - Exposure
    U         = EV / (T_close + time_overhead)
"""

import math
from time import perf_counter

from .geometry import INF, allowed_dirs, popcount, reverse
from .pathfinding import astar, manhattan_field


class Route:
    __slots__ = ('kind', 'cells', 't_close', 'gain', 'kill_value', 'kills',
                 'p_survive', 'ev', 'utility', 'margin', 'new_trail', 'note',
                 'target')

    def __init__(self, kind, cells):
        self.kind = kind
        self.cells = cells
        self.t_close = 0
        self.gain = 0.0
        self.kill_value = 0.0
        self.kills = ()
        self.p_survive = 1.0
        self.ev = 0.0
        self.utility = -INF
        self.margin = INF
        self.new_trail = 0
        self.note = ''
        self.target = None

    @property
    def first(self):
        return self.cells[0] if self.cells else None

    def __repr__(self):
        return '<%s len=%d T=%d gain=%.1f kill=%.1f ps=%.3f m=%s U=%.3f>' % (
            self.kind, len(self.cells), self.t_close, self.gain, self.kill_value,
            self.p_survive, self.margin, self.utility)


def _sigmoid(x):
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


class Planner:
    def __init__(self, an, cfg, rate, deadline):
        self.an = an
        self.cfg = cfg
        self.b = an.board
        self.me = an.me
        self.deadline = deadline
        self.timed_out = False
        steps_left = an.view.steps_left
        self.steps_left = steps_left if steps_left is not None else cfg.default_max_steps
        self.v_life = max(cfg.life_min,
                          cfg.life_territory_weight * an.my_area
                          + cfg.life_future_weight * rate * self.steps_left)
        self.evaluated = 0
        # Greed cap: planned trail length grows with distance to nearest threat.
        nt = an.nearest_threat
        cap = cfg.loop_len_max if nt >= INF else cfg.loop_len_min + cfg.loop_len_per_threat * nt
        self.trail_cap = int(max(cfg.loop_len_min, min(cfg.loop_len_max, cap)))
        self._headon = {}

    # ------------------------------------------------------------------
    # evaluation
    # ------------------------------------------------------------------
    def out_of_time(self):
        if perf_counter() > self.deadline:
            self.timed_out = True
        return self.timed_out

    def headon_risk(self, src, dst, t, my_len):
        """P(dying in a head-on collision) on our move ``src -> dst`` (move #t, 1 or 2).

        Contact is tested exactly like the reference engine: both squares move
        in 6 sub-steps and touch when |dx| < 1 and |dy| < 1.  Trail lengths only
        change at cell centres, so contact before the centre compares the
        lengths *before* the move (``my_len`` and the enemy's), and at the centre
        the lengths after it.  The longer-or-equal trail dies.
        """
        key = (src, dst, t)
        r = self._headon.get(key)
        if r is not None:
            return r
        b = self.b
        bit = b.bit
        nbr = b.nbr
        w = b.w
        me = self.me
        sx, sy, dx_, dy_ = src % w, src // w, dst % w, dst // w
        bd = bit[dst]
        my_after = 0 if bd & me.terr else my_len + 1
        lose_p = self.cfg.headon_lose_p * (1.0 if t == 1 else 0.4)
        r = 0.0
        for em in self.an.enemies:
            p = em.p
            if b.manhattan(p.head, src) > 2 * t + 1:
                continue
            body = p.trail_mask & ~bit[p.head]
            starts = [(p.head, p.dir, len(p.trail))]
            if t == 2:  # where the enemy may stand after its first move
                nxt = []
                for d in allowed_dirs(p.dir):
                    e1 = nbr[p.head][d]
                    if e1 >= 0 and not (bit[e1] & body):
                        nxt.append((e1, d, 0 if bit[e1] & p.terr else len(p.trail) + 1))
                starts = nxt
            for e0, ed, e_len in starts:
                ex, ey = e0 % w, e0 // w
                for d in allowed_dirs(ed):
                    e1 = nbr[e0][d]
                    if e1 < 0 or bit[e1] & body:
                        continue
                    k = _contact(sx, sy, dx_, dy_, ex, ey, e1 % w, e1 // w)
                    if not k:
                        continue
                    if k < 6:
                        mine, theirs = my_len, e_len
                    else:
                        mine = my_after
                        theirs = 0 if bit[e1] & p.terr else e_len + 1
                    if mine >= theirs:
                        r = max(r, lose_p)
        self._headon[key] = r
        return r

    def evaluate(self, kind, cells, target=None):
        """Replay ``cells`` under the game rules and fill in a Route (or None)."""
        self.evaluated += 1
        if not cells:
            return None
        an = self.an
        cfg = self.cfg
        b = self.b
        bit = b.bit
        me = self.me
        terr = me.terr
        trail = me.trail_mask
        body_union = an.body_union
        pocket_union = an.pocket_union
        expo = an.expo
        ram = an.ram_contact
        t = 0
        t_close = 0
        closed_trail = 0
        exposure = 0.0
        kills = []
        killed = set()
        pocket_last = None
        cur_len = len(me.trail)
        ram_margin = INF
        for c in cells:
            t += 1
            bc = bit[c]
            if bc & trail:
                return None  # crossing our own trail is suicide
            if cur_len and t >= 3:  # moves 1-2 get the exact sub-step test below
                rm = ram[c] - t
                if rm < ram_margin:
                    ram_margin = rm
            if bc & body_union:
                for em in an.vulnerable:
                    if bc & em.body and em not in killed and t < em.home_time - cfg.kill_buffer:
                        killed.add(em)
                        kills.append((em, t, trail | (0 if bc & terr else bc)))
            if bc & pocket_union:
                if pocket_last is None:
                    pocket_last = {}
                for em in an.enemies:
                    if bc & em.pocket:
                        pocket_last[em] = t
            if bc & terr:
                if trail:
                    t_close = t
                    closed_trail = trail
                    break
            else:
                trail |= bc
                cur_len += 1
                exposure += expo[c]
        if t_close == 0:
            if trail:  # route ends outside: not a complete plan
                return None
            t_close = t  # pure in-territory walk

        r = Route(kind, cells[:t])
        r.t_close = t_close
        r.target = target
        if t_close > self.steps_left:
            return None  # cannot bank it before the game ends

        # ---- gain ----------------------------------------------------------
        gain = 0.0
        if closed_trail:
            new = b.capture(terr, closed_trail, cfg.wall_encloses)
            n_enemy = popcount(new & an.enemy_terr)
            gain = cfg.w_neutral * (popcount(new) - n_enemy) + cfg.w_enemy * n_enemy
            if new & an.bonus_mask:
                for cb, kind_b in an.bonus_cells.items():
                    if bit[cb] & new:
                        gain += cfg.w_bonus.get(kind_b, 0.0)
        r.gain = gain
        r.new_trail = closed_trail & ~me.trail_mask

        # ---- kills ---------------------------------------------------------
        kill_value = 0.0
        kill_time = {}
        for em, tk, snap in kills:
            kill_value += cfg.w_kill + cfg.w_kill_territory * popcount(em.p.terr)
            kill_time[em] = (tk, snap)
        ram_ids = ()
        ram_pk = None
        if an.ram_targets:
            ram_value, ram_pk = self._ram_kills(r.cells, killed)
            kill_value += ram_value
            ram_ids = tuple(em.p.pid for em in ram_pk)
        r.kills = tuple(em.p.pid for em, _, _ in kills) + ram_ids
        r.kill_value = kill_value

        # ---- survival -------------------------------------------------------
        p_survive = 1.0
        min_margin = INF
        if closed_trail or kills:
            mid = cfg.margin_mid
            scale = cfg.margin_scale
            for em in an.enemies:
                if em in kill_time:
                    tk, snap = kill_time[em]
                    arrival = em.min_arrival(snap)
                    deadline = tk + 1  # simultaneous cut = mutual death
                else:
                    if not closed_trail:
                        continue
                    arrival = em.min_arrival(closed_trail)
                    deadline = t_close
                if arrival >= INF:
                    continue
                m = arrival - deadline
                if m < min_margin:
                    min_margin = m
                if m < 8:
                    p_cut = _sigmoid((mid - m) / scale)
                    if ram_pk and em in ram_pk:
                        p_cut *= 1.0 - ram_pk[em]  # dead on contact if it keeps its line
                    p_survive *= 1.0 - p_cut
        if pocket_last:
            for em, tl in pocket_last.items():
                if em in kill_time and kill_time[em][0] < em.home_time:
                    continue
                if tl >= em.home_time - 0.5:
                    p_survive *= 1.0 - cfg.pocket_p
        if ram_margin < 8:
            p_survive *= 1.0 - cfg.ram_p * _sigmoid((cfg.ram_margin_mid - ram_margin) / cfg.margin_scale)
        len0 = len(me.trail)
        p_survive *= 1.0 - self.headon_risk(me.head, cells[0], 1, len0)
        if len(cells) > 1:
            len1 = 0 if bit[cells[0]] & terr else len0 + 1
            p_survive *= 1.0 - self.headon_risk(cells[0], cells[1], 2, len1)
        r.margin = min_margin
        r.p_survive = p_survive

        # ---- exposure (wall hugging): open flanks x threat proximity ----------
        exposure *= cfg.w_exposure

        r.ev = p_survive * (gain + kill_value) - (1.0 - p_survive) * self.v_life - exposure
        r.utility = r.ev / (t_close + cfg.time_overhead)
        return r

    def _ram_kills(self, cells, killed):
        """Expected value of head-on kills against enemies heading home.

        The enemy is assumed to follow its shortest path home (``em.pred``).
        Contact is tested with the exact sub-step rule; we win it when our
        trail is strictly shorter at that moment (pre-move lengths before the
        cell centre, post-move at it).  Confidence decays with lookahead.
        """
        an = self.an
        cfg = self.cfg
        b = self.b
        bit = b.bit
        w = b.w
        terr = self.me.terr
        prev = self.me.head
        len_before = len(self.me.trail)
        value = 0.0
        hit = {}
        for t in range(1, min(cfg.ram_horizon, len(cells)) + 1):
            c = cells[t - 1]
            after = 0 if bit[c] & terr else len_before + 1
            for em in an.ram_targets:
                pred = em.pred
                if t >= len(pred) or em in killed or em in hit:
                    continue
                e0, e1 = pred[t - 1], pred[t]
                if b.manhattan(c, e1) > 2:
                    continue
                k = _contact(prev % w, prev // w, c % w, c // w, e0 % w, e0 // w, e1 % w, e1 // w)
                if not k:
                    continue
                e_before = em.trail_len + t - 1
                if k < 6:
                    mine, theirs = len_before, e_before
                else:
                    mine, theirs = after, (0 if bit[e1] & em.p.terr else e_before + 1)
                if mine < theirs:
                    pk = cfg.ram_kill_p * cfg.ram_kill_decay ** (t - 1)
                    value += pk * (cfg.w_kill + cfg.w_kill_territory * popcount(em.p.terr))
                    hit[em] = pk
            prev = c
            len_before = after
        return value, hit

    # ------------------------------------------------------------------
    # route builders
    # ------------------------------------------------------------------
    def ram_routes(self):
        """ATTACKING by head-on: intercept a homeward enemy while our trail is shorter."""
        an = self.an
        cfg = self.cfg
        b = self.b
        me = self.me
        out = []
        for em in an.ram_targets:
            if em.trail_len <= len(me.trail):
                continue  # we would not win the contact
            pred = em.pred
            for t in range(1, min(cfg.ram_horizon, len(pred) - 1) + 1):
                target = pred[t]
                if b.manhattan(me.head, target) > t + 1:
                    continue  # cannot be there in time
                if self.out_of_time():
                    return out
                path = astar(an, me.head, me.dir, b.bit[target], an.my_block,
                             manhattan_field(b, target), max_nodes=600,
                             deadline=self.deadline, risk=False)
                if not path or len(path) > t + 1:
                    continue
                route = path
                if not (b.bit[path[-1]] & me.terr) or me.trail_mask:
                    if not any(b.bit[c] & me.terr for c in path):
                        d_last = _dir_between(b, path[-2] if len(path) > 1 else me.head, path[-1])
                        blocked = an.my_block | b.mask(path) | (b.bit[me.head] if me.trail_mask else 0)
                        tail = self._home_tail(path[-1], d_last, blocked, None)
                        if not tail:
                            continue
                        route = path + tail
                r = self.evaluate('ram', route)
                if r and r.kills:
                    out.append(r)
        return out

    def _walk(self, start, d, n, blocked, stop_mask=0):
        """Straight walk of up to n cells; stops early on entering stop_mask."""
        nbr = self.b.nbr
        bit = self.b.bit
        out = []
        c = start
        for _ in range(n):
            c = nbr[c][d]
            if c < 0 or bit[c] & blocked:
                return None
            out.append(c)
            if bit[c] & stop_mask:
                break
        return out

    def _home_tail(self, start, d, blocked, prefer, exact=True):
        """Cells from ``start`` (heading ``d``) back into territory avoiding ``blocked``.

        Greedy descent on the home distance field with a preferred heading,
        falling back to a full A* (when ``exact``) if the planned trail blocks
        the descent.  Rectangle loops skip the fallback: there are hundreds of
        them and a blocked descent means the shape is a poor loop anyway.
        """
        an = self.an
        b = self.b
        bit = b.bit
        nbr = b.nbr
        dist = an.dist_home
        terr = self.me.terr
        out = []
        c = start
        cur_d = d
        blocked_now = blocked
        for _ in range(dist[start] + 6 if dist[start] < INF else 0):
            best = None
            best_key = None
            for nd in allowed_dirs(cur_d):
                n = nbr[c][nd]
                if n < 0 or bit[n] & blocked_now:
                    continue
                dn = dist[n]
                if dn >= INF:
                    continue
                key = (dn, 0 if nd == prefer else (1 if nd == cur_d else 2))
                if best_key is None or key < best_key:
                    best_key = key
                    best = (n, nd)
            if best is None or best_key[0] > dist[c]:
                break
            c, cur_d = best
            out.append(c)
            if bit[c] & terr:
                return out
            blocked_now |= bit[c]
        if not exact:
            return None
        # Greedy failed: exact search from where we stand.
        path = astar(an, start, d, terr, blocked, dist, max_nodes=2500,
                     deadline=self.deadline)
        return path

    def home_routes(self):
        """RETREAT candidates: safest A* home and the pure-shortest path home."""
        an = self.an
        me = self.me
        out = []
        if not me.trail_mask:
            return out
        seen = set()
        for risk in (True, False):
            path = astar(an, me.head, me.dir, me.terr, an.my_block, an.dist_home,
                         max_nodes=8000, deadline=self.deadline + 0.05, risk=risk)
            if path and tuple(path) not in seen:
                seen.add(tuple(path))
                r = self.evaluate('home', path)
                if r:
                    out.append(r)
        return out

    def rectangle_routes(self):
        """EXPANDING candidates: out-a, across-b, back-home loops in every orientation.

        Enumerated smallest-perimeter first, so a time-out still leaves the
        small, quick loops that the strategy prefers.
        """
        an = self.an
        cfg = self.cfg
        b = self.b
        bit = b.bit
        me = self.me
        terr = me.terr
        head = me.head
        cap = self.trail_cap
        max_leg = min(cfg.max_leg, cap)
        inside = bool(bit[head] & terr) and not me.trail_mask
        out = []

        # Leg 0: if at home, slide straight to the edge of the territory first.
        prefixes = []
        for d1 in allowed_dirs(me.dir):
            pre = []
            c = head
            if inside:
                ok = True
                for _ in range(b.w + b.h):
                    c2 = b.nbr[c][d1]
                    if c2 < 0:
                        ok = False
                        break
                    if not (bit[c2] & terr):
                        break
                    pre.append(c2)
                    c = c2
                if not ok:
                    continue
            prefixes.append((d1, pre, c))

        params = []
        for a in range(1, max_leg + 1):
            for bb in range(0, max_leg + 1):
                if a + bb + a > cap + 2:
                    continue
                params.append((a + bb, a, bb))
        params.sort()

        blocked0 = an.my_block | (0 if inside else bit[head])
        for _, a, bb in params:
            for d1, pre, c0 in prefixes:
                if self.out_of_time():
                    return out
                leg1 = self._walk(c0, d1, a, blocked0, terr if not inside else 0)
                if leg1 is None:
                    continue
                if inside and any(bit[c] & terr for c in leg1):
                    continue  # re-entered home inside leg 1: covered by smaller a
                cells1 = pre + leg1
                end1 = cells1[-1] if cells1 else head
                blocked1 = blocked0 | b.mask(leg1)
                if bit[end1] & terr:
                    if bb == 0:
                        r = self.evaluate('expand', cells1)
                        if r:
                            out.append(r)
                    continue
                turns = (d1,) if bb == 0 else ((d1 + 1) & 3, (d1 + 3) & 3)
                for d2 in turns:
                    if bb == 0:
                        cells2, end2, dir2, blocked2 = cells1, end1, d1, blocked1
                    else:
                        leg2 = self._walk(end1, d2, bb, blocked1, terr)
                        if leg2 is None:
                            continue
                        cells2 = cells1 + leg2
                        end2 = leg2[-1]
                        dir2 = d2
                        blocked2 = blocked1 | b.mask(leg2)
                        if bit[end2] & terr:
                            r = self.evaluate('expand', cells2)
                            if r:
                                out.append(r)
                            continue
                    tail = self._home_tail(end2, dir2, blocked2, reverse(d1), exact=False)
                    if tail:
                        r = self.evaluate('expand', cells2 + tail)
                        if r:
                            out.append(r)
        return out

    def attack_routes(self):
        """ATTACKING candidates: shortest-risk path onto a vulnerable trail, then home."""
        an = self.an
        cfg = self.cfg
        b = self.b
        me = self.me
        out = []
        dist_me = an.dist_me
        for em in an.vulnerable:
            body_cells = b.cells(em.body)
            reachable = [(dist_me[c], c) for c in body_cells
                         if dist_me[c] < em.home_time - cfg.kill_buffer]
            if not reachable:
                continue
            reachable.sort()
            for _, target in reachable[:cfg.max_attack_targets]:
                if self.out_of_time():
                    return out
                h = manhattan_field(b, target)
                path = astar(an, me.head, me.dir, b.bit[target], an.my_block, h,
                             max_nodes=4000, deadline=self.deadline)
                if not path:
                    continue
                if b.bit[path[-1]] & me.terr:
                    route = path
                else:
                    d_last = _dir_between(b, path[-2] if len(path) > 1 else me.head, path[-1])
                    blocked = an.my_block | b.mask(path)
                    if me.trail_mask:
                        blocked |= b.bit[me.head]
                    tail = self._home_tail(path[-1], d_last, blocked, None)
                    if not tail:
                        continue
                    route = path + tail
                r = self.evaluate('attack', route, target=em.p.pid)
                if r and r.kills:
                    out.append(r)
        return out

    def defend_routes(self):
        """DEFENDING candidates: walks that stay inside our territory."""
        b = self.b
        bit = b.bit
        nbr = b.nbr
        me = self.me
        terr = me.terr
        if me.trail_mask:
            return []
        depth = self.cfg.defend_lookahead
        threat = self.an.threat
        best = {}

        # Depth-limited DFS (no reverse, no revisits) inside the territory.
        def dfs(c, d, path, seen, score):
            if len(path) == depth:
                first = path[0]
                if first not in best or score > best[first][0]:
                    best[first] = (score, list(path))
                return True
            found = False
            for nd in allowed_dirs(d):
                n = nbr[c][nd]
                if n < 0 or not (bit[n] & terr) or n in seen:
                    continue
                th = threat[n]
                s = score + (min(th, 20) if th < INF else 20)
                seen.add(n)
                path.append(n)
                if dfs(n, nd, path, seen, s):
                    found = True
                path.pop()
                seen.discard(n)
                if found and len(path) >= 2:
                    break  # one continuation is enough deeper in the tree
            return found

        for d in allowed_dirs(me.dir):
            n = nbr[me.head][d]
            if n < 0 or not (bit[n] & terr):
                continue
            th = threat[n]
            dfs(n, d, [n], {me.head, n}, min(th, 20) if th < INF else 20)
        out = []
        for first, (score, path) in best.items():
            r = self.evaluate('defend', path)
            if r:
                r.utility += 1e-4 * score  # tie-break: stay far from enemy heads
                r.note = 'safety=%d' % score
                out.append(r)
        return out

    def continue_route(self, prev_cells):
        """Re-evaluate the remainder of last tick's plan (plan commitment)."""
        if not prev_cells:
            return None
        me = self.me
        if prev_cells[0] != me.head or len(prev_cells) < 2:
            return None
        r = self.evaluate('commit', prev_cells[1:])
        return r


def _contact(ax0, ay0, ax1, ay1, bx0, by0, bx1, by1):
    """First of 6 sub-steps at which two moving unit squares overlap (0 = never)."""
    for k in range(1, 7):
        f = k / 6.0
        if abs((ax0 + (ax1 - ax0) * f) - (bx0 + (bx1 - bx0) * f)) < 0.999 and \
                abs((ay0 + (ay1 - ay0) * f) - (by0 + (by1 - by0) * f)) < 0.999:
            return k
    return 0


def _dir_between(b, a, c):
    for d, n in enumerate(b.nbr[a]):
        if n == c:
            return d
    return None
