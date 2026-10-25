"""Loop planning and ability evaluation (exact bitboard captures).

A loop leaves our territory M at start s, runs leg1 (a cells, d1) and leg2
(b cells, d2 perpendicular), then returns straight (rev d1, then rev d2) and
finally greedily down the distance field to M.  It closes as soon as the head
is 4-adjacent to M or to an earlier path cell (the engine fills holes of
area + head).  Gain = |new cells| + steal bonus for enemy cells; ranked by
gain per move after a cut-risk penalty.  Thousands of rectangles are ranked
with 2D prefix sums, the best few are replayed exactly.
"""

import math
from time import perf_counter

from .board import DX, DY, OPP, INF, popcount

A_LIST = (2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 22, 27, 33, 40)
B_LIST = (2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 22, 27, 33, 40, 48)
W_STEAL = 0.8          # extra value of a cell taken from an enemy
RISK_K = 1.0 / 40000.0
STYLE_W = {'aggr': 0.8, 'neutral': 0.4, 'timid': 0.15}   # how likely each kind goes for our trail


class Plan:
    __slots__ = ('cells', 'gain', 'cost', 'rate', 'capture', 'kind', 'bullet_at', 'bullet_dir', 'trail')

    def __init__(self, cells, gain, cost, capture, kind='loop'):
        self.cells = cells
        self.gain = gain
        self.cost = cost
        self.rate = gain / (cost + 2.0)
        self.capture = capture
        self.kind = kind
        self.bullet_at = None      # index into cells where we fire instead of walking on
        self.bullet_dir = None
        self.trail = 0

    def __repr__(self):
        return '<%s n=%d gain=%.0f cost=%.1f rate=%.2f%s>' % (
            self.kind, len(self.cells), self.gain, self.cost, self.rate,
            ' bullet@%d' % self.bullet_at if self.bullet_at is not None else '')


class Planner:
    def __init__(self, world, deadline, extra_block=0, rng=None, opts=None):
        self.rng = rng
        opts = opts or {}
        self.risk_k = RISK_K * opts.get('risk_mult', 1.0)
        self.nodeadline = opts.get('nodeadline', 0)     # debug: deterministic planning
        self.chaos = opts.get('chaos', 0.0)              # weight of the reckless-enemy exposure penalty
        self.bomb_steal = opts.get('bombsteal', 0) or opts.get('holy', 0)
        self.widen = opts.get('widen', 0)              # bomb value per tile that thickens a neck
        self._reach = None
        self.w = world
        self.b = world.b
        self.deadline = deadline
        w = world
        b = self.b
        self.M = w.mine
        self.hb = b.bit[w.head]
        self.enemy_all = 0
        for m in w.enemy.values():
            self.enemy_all |= m
        self.block = w.wall | w.brk | w.objs | extra_block
        self.passable = b.full & ~self.block
        self._dist_m = None

    def out_of_time(self, reserve=0.0):
        return not self.nodeadline and perf_counter() > self.deadline - reserve

    # ------------------------------------------------------------------
    def value_of(self, new):
        return popcount(new) + W_STEAL * popcount(new & self.enemy_all)

    def capture_of(self, pathmask):
        """New cells (path + enclosed) if our area grows by pathmask."""
        b = self.b
        area = self.M | self.hb | pathmask
        new = (b.holes(area) | pathmask) & ~self.M & ~self.w.wall
        return new

    def dist_m(self):
        if self._dist_m is None:
            self._dist_m = self.b.distance_field(self.M | self.hb, self.passable | self.M, limit=120)
        return self._dist_m

    # ------------------------------------------------------------------
    def danger(self, cells_mask):
        """Density of enemy evidence near a region (1 = nobody seen nearby)."""
        w = self.w
        b = self.b
        dens = 1.0
        near = cells_mask
        for _ in range(3):
            near = b.dilate(b.dilate(b.dilate(b.dilate(near))))
        # near = region dilated by 12
        for lab, (cell, ts) in w.heads.items():
            age = w.t - ts
            if age < 80 and b.bit[cell] & near:
                dens += 25.0 * math.exp(-age / 40.0)
        if self.enemy_all & near:
            dens += 6.0
        return dens

    def risk_penalty(self, trail_len, cost, region):
        if not self.M:
            return 0.0
        dens = self.danger(region)
        p = 1.0 - math.exp(-trail_len * cost * dens * self.risk_k)
        return p * popcount(self.M)

    def _enemy_reach(self):
        """Per recently seen enemy: cumulative BFS rings from where it was, its age, its weight."""
        if self._reach is None:
            w = self.w
            b = self.b
            free = self.passable | self.M
            out = []
            for lab, (cell, ts) in w.heads.items():
                age = w.t - ts
                if age > 40:
                    continue
                wgt = STYLE_W[w.enemy_style(lab)] * math.exp(-age / 40.0)
                cum = [b.bit[cell]]
                cur = cum[0]
                for _ in range(36):
                    cur = b.dilate(cur) & free | cur
                    cum.append(cur)
                out.append((cum, age, wgt))
            self._reach = out
        return self._reach

    def chaos_risk(self, pathmask, cost):
        """Chance that some enemy, assumed to come straight at us, is on our trail before we close."""
        safe = 1.0
        for cum, age, wgt in self._enemy_reach():
            if not cum[-1] & pathmask:
                continue
            lo, hi = 0, len(cum) - 1          # first ring touching the path
            while lo < hi:
                mid = (lo + hi) // 2
                if cum[mid] & pathmask:
                    hi = mid
                else:
                    lo = mid + 1
            reach = max(0, lo - age)
            if reach < cost:
                safe *= 1.0 - wgt * (cost - reach) / cost
        return 1.0 - safe

    # ------------------------------------------------------------------
    def _prefix(self):
        """2D prefix sums of claimable value (0 for ours / unbreakable walls)."""
        w = self.w
        b = self.b
        n = b.w
        M = self.M
        wall = w.wall
        ea = self.enemy_all
        bit = b.bit
        P = [[0.0] * (n + 1) for _ in range(n + 1)]
        mine_cells = set(b.cells(M))
        wall_cells = set(b.cells(wall))
        enemy_cells = set(b.cells(ea))
        for y in range(n):
            row = P[y + 1]
            prev = P[y]
            acc = 0.0
            base = y * n
            for x in range(n):
                i = base + x
                if i in mine_cells or i in wall_cells:
                    v = 0.0
                elif i in enemy_cells:
                    v = 1.0 + W_STEAL
                else:
                    v = 1.0
                acc += v
                row[x + 1] = prev[x + 1] + acc
        return P

    @staticmethod
    def _rect(P, x0, y0, x1, y1):
        if x0 > x1:
            x0, x1 = x1, x0
        if y0 > y1:
            y0, y1 = y1, y0
        return P[y1 + 1][x1 + 1] - P[y0][x1 + 1] - P[y1 + 1][x0] + P[y0][x0]

    def _starts(self, max_dist=10, k=7):
        """Head plus nearby boundary cells of M (reached through M)."""
        w = self.w
        b = self.b
        h = w.head
        M = self.M | self.hb
        out = [(h, [])]
        if not self.M:
            return out
        inner = M & self.passable | self.hb
        dist = b.distance_field(self.hb, inner, limit=max_dist)
        boundary = M & b.dilate(self.passable & ~M)
        cand = [(dist[c], c) for c in b.cells(boundary) if dist[c] < INF and c != h]
        if not cand:
            return out
        cand.sort()
        hx, hy = w.x, w.y
        sectors = {}
        for dd, c in cand:
            x, y = c % b.w, c // b.w
            ang = math.atan2(y - hy, x - hx)
            sec = int((ang + math.pi) / (2 * math.pi) * 8) % 8
            if sec not in sectors:
                sectors[sec] = c
        for c in list(sectors.values())[:k - 1]:
            out.append((c, self._path_in(dist, c)))
        return out

    def _path_in(self, dist, target):
        b = self.b
        path = [target]
        c = target
        while dist[c] > 1:
            for n in b.nbr[c]:
                if n >= 0 and dist[n] == dist[c] - 1:
                    c = n
                    break
            else:
                return None
            path.append(c)
        path.reverse()
        return path

    # ------------------------------------------------------------------
    def plan_loops(self, max_leg=40, top=100):
        w = self.w
        b = self.b
        bit = b.bit
        nbr = b.nbr
        n = b.w
        M = self.M
        passable = self.passable
        P = self._prefix()
        cands = []
        starts = self._starts()
        a_list = [a for a in A_LIST if a <= max_leg]
        b_list = [v for v in B_LIST if v <= max_leg + 8]
        for s, prefix in starts:
            if prefix is None:
                continue
            sx, sy = s % n, s // n
            pre = len(prefix)
            for d1 in range(4):
                first = nbr[s][d1]
                if first < 0 or not (bit[first] & passable) or (M and bit[first] & M):
                    continue
                # straight run out of M along d1
                run1 = 0
                c = s
                amax = a_list[-1] if a_list else 0
                while run1 < amax:
                    c2 = nbr[c][d1]
                    if c2 < 0 or not (bit[c2] & passable) or bit[c2] & M:
                        break
                    run1 += 1
                    c = c2
                for a in a_list:
                    if a > run1:
                        break
                    ex = sx + DX[d1] * a
                    ey = sy + DY[d1] * a
                    e1 = ey * n + ex
                    for d2 in ((d1 + 1) & 3, (d1 + 3) & 3):
                        run2 = 0
                        c = e1
                        while run2 < b_list[-1]:
                            c2 = nbr[c][d2]
                            if c2 < 0 or not (bit[c2] & passable) or bit[c2] & M:
                                break
                            run2 += 1
                            c = c2
                        for bb in b_list:
                            if bb > run2:
                                break
                            fx = ex + DX[d2] * bb
                            fy = ey + DY[d2] * bb
                            val = self._rect(P, sx, sy, fx, fy)
                            cost = pre + 2 * a + bb + (0 if M else bb)
                            score = val / (cost + 2.0)
                            if self.rng is not None:
                                score *= 1.0 + 0.2 * self.rng.random()
                            cands.append((score, s, prefix, d1, a, d2, bb))
        cands.sort(reverse=True)
        best = None
        evaluated = 0
        seen = set()
        for cand in cands:
            if evaluated >= top or self.out_of_time(0.006):    # leave time for the frontier walk
                break
            _, s, prefix, d1, a, d2, bb = cand
            key = (s, d1, a, d2, bb)
            if key in seen:
                continue
            seen.add(key)
            plan = self._build(s, prefix, d1, a, d2, bb)
            evaluated += 1
            if plan and (best is None or plan.rate > best.rate):
                best = plan
        return best

    def _build(self, s, prefix, d1, a, d2, bb):
        """Construct the exact loop path and score it."""
        w = self.w
        b = self.b
        bit = b.bit
        nbr = b.nbr
        M = self.M
        Mh = M | self.hb
        passable = self.passable
        path = list(prefix)
        out_cells = []
        c = s
        for _ in range(a):
            c = nbr[c][d1]
            out_cells.append(c)
        for _ in range(bb):
            c = nbr[c][d2]
            out_cells.append(c)
        pset = set(out_cells)
        pset.add(s)
        prev = out_cells[-2] if len(out_cells) > 1 else s

        def closes(cell, prev_cell):
            for nb in nbr[cell]:
                if nb < 0 or nb == prev_cell:
                    continue
                if bit[nb] & Mh or nb in pset:
                    return True
            return False

        ret = []
        closed = False
        cur = c
        for ld in (OPP[d1], OPP[d2]):
            steps = 0
            while steps < 120:
                nx = nbr[cur][ld]
                if nx < 0 or not (bit[nx] & passable) or nx in pset:
                    break
                p_cell = cur
                cur = nx
                ret.append(cur)
                pset.add(cur)
                steps += 1
                if closes(cur, p_cell):
                    closed = True
                    break
            if closed:
                break
        if not closed and M:
            dist = self.dist_m()
            for _ in range(80):
                bestn = None
                for nb in nbr[cur]:
                    if nb < 0 or nb in pset or not (bit[nb] & (passable | M)):
                        continue
                    if bestn is None or dist[nb] < dist[bestn]:
                        bestn = nb
                if bestn is None or dist[bestn] >= INF:
                    break
                p_cell = cur
                cur = bestn
                ret.append(cur)
                pset.add(cur)
                if closes(cur, p_cell) or bit[cur] & M:
                    closed = True
                    break
        if not closed:
            return None
        cells = path + out_cells + ret
        pm = b.mask(out_cells) | b.mask(ret)
        new = self.capture_of(pm)
        gain = self.value_of(new)
        trail = len(out_cells) + len(ret)
        cost = len(cells)
        # Dash: every straight run of >=3 can be compressed (charge-limited).
        dashes = min(self._straight_runs(cells), w.dash.c + cost // 20)
        cost_eff = cost - 2 * dashes
        plan = Plan(cells, gain, cost_eff, new)
        plan.trail = trail
        # Bullet return: the last straight stretch of the return can be shot.
        if ret and len(ret) >= 4 and (w.gun.c >= 1 or w.gun.timer + len(path) + len(out_cells) >= w.gun.r):
            dr = self._dir(out_cells[-1], ret[0])
            k = 1
            while k < len(ret) and self._dir(ret[k - 1], ret[k]) == dr:
                k += 1
            if k == len(ret) and k >= 4:
                idx = len(path) + len(out_cells)
                alt = Plan(cells, gain, idx - 2 * min(dashes, self._straight_runs(cells[:idx])) + 1.5, new)
                alt.bullet_at = idx
                alt.bullet_dir = dr
                alt.trail = len(out_cells)
                if alt.rate > plan.rate:
                    plan = alt
        region = pm | new
        pen = self.risk_penalty(plan.trail, plan.cost, region)
        if self.chaos and self.M:
            pen += self.chaos * self.chaos_risk(pm, plan.cost) * popcount(self.M)
        plan.gain -= pen
        plan.rate = plan.gain / (plan.cost + 2.0)
        return plan

    def _dir(self, a, c):
        for d, nb in enumerate(self.b.nbr[a]):
            if nb == c:
                return d
        return None

    def _straight_runs(self, cells):
        """Non-overlapping straight triples in a path (each can be one dash)."""
        runs = 0
        k = 0
        n = len(cells)
        while k + 2 < n:
            d0 = self._dir(cells[k], cells[k + 1])
            if d0 is not None and self._dir(cells[k + 1], cells[k + 2]) == d0:
                runs += 1
                k += 3
            else:
                k += 1
        return runs

    # ------------------------------------------------------------------
    def best_bomb(self, discount=0):
        """Best bomb target: (gain, i, j)."""
        w = self.w
        b = self.b
        bit = b.bit
        hx, hy = w.x, w.y
        reach = b.dilate(self.M | self.hb)
        thin = 0
        if self.widen and self.M:
            # tiles next to our necks (land with <= 2 own neighbours): filling them thickens us
            s = b.stride
            M = self.M
            # >= 3 own neighbours always includes an opposite pair
            three = ((M << 1) & (M >> 1) & ((M << s) | (M >> s))) | ((M << s) & (M >> s) & ((M << 1) | (M >> 1)))
            thin = b.dilate(M & ~three) & ~M
        cands = []
        for j in range(-4, 5):
            for i in range(-4, 5):
                if not (0 < i * i + j * j <= 16):
                    continue
                x, y = hx + i, hy + j
                if not (0 <= x < b.w and 0 <= y < b.h):
                    continue
                c = y * b.w + x
                if bit[c] & (w.wall | w.brk | w.objs):
                    continue
                disk = b.disk(c, 9) & ~w.wall & ~w.objs
                if not (disk & reach):
                    continue
                new = disk & ~self.M & ~self.hb
                g = self.value_of(new & ~discount) + 0.2 * popcount(new & discount)
                if thin:
                    g += self.widen * popcount(new & thin)
                cands.append((g, i, j, new))
        if not cands:
            return None
        cands.sort(reverse=True)
        pool = cands[:4]
        ea = self.enemy_all
        if self.bomb_steal and ea:
            # Disks over enemy necks cut whole territories off their owner.
            over = sorted((c for c in cands[4:] if c[3] & ea), key=lambda c: -popcount(c[3] & ea))
            pool = pool + over[:4]
        best = None
        for g, i, j, new in pool:
            if best is not None and self.out_of_time():
                break
            extra = self.capture_of(new) & ~new
            g2 = g + self.value_of(extra & ~discount)
            if self.bomb_steal and new & ea:
                g2 += self.steal_by(new & ea)
            if best is None or g2 > best[0]:
                best = (g2, i, j)
        return best

    def best_bullet(self, discount=0):
        """Best bullet direction: (gain, d)."""
        w = self.w
        b = self.b
        bit = b.bit
        h = w.head
        best = None
        for d in range(4):
            first = b.nbr[h][d]
            if first < 0 or bit[first] & (w.wall | w.brk | w.objs):
                continue
            line = w.ray(h, d)
            if not line:
                continue
            lm = b.mask(line)
            new = self.capture_of(lm)
            g = self.value_of(new & ~discount) + 0.2 * popcount(new & discount)
            g += self.steal_by(lm)
            if best is None or g > best[0]:
                best = (g, d)
        return best

    # ------------------------------------------------------------------
    def steal_by(self, removed):
        """Enemy cells cut off from their owner if `removed` stops being theirs."""
        w = self.w
        total = 0
        for lab, E in w.enemy.items():
            if E & removed:
                total += popcount(w.cut_off(lab, E & ~removed, removed))
        return total

    def best_wall_cut(self):
        """Breakable wall placed on an enemy tile that disconnects part of it."""
        w = self.w
        b = self.b
        bit = b.bit
        hx, hy = w.x, w.y
        if not self.enemy_all & w.vis:
            return None
        best = None
        for j in range(-4, 5):
            for i in range(-4, 5):
                if not (0 < i * i + j * j <= 16):
                    continue
                x, y = hx + i, hy + j
                if not (0 <= x < b.w and 0 <= y < b.h):
                    continue
                c = y * b.w + x
                if not (bit[c] & self.enemy_all & w.vis) or bit[c] & w.objs or w.no_build.get(c, -1) >= w.t:
                    continue
                if not self._los(hx, hy, x, y):
                    continue
                g = self.steal_by(bit[c])
                if g and (best is None or g > best[0]):
                    best = (g, i, j)
        return best

    def _los(self, x0, y0, x1, y1):
        """No objects on tiles crossed by the segment between tile centres."""
        w = self.w
        return self.b.los(x0, y0, x1, y1, w.wall | w.brk | w.objs)
