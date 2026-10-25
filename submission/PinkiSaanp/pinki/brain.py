"""Decision loop: FSM (EXPAND / RETREAT / ATTACK) over the loop planner + abilities."""

import random
import sys
from time import perf_counter

from .board import DX, DY, INF, KEYS, popcount
from .planner import Plan, Planner
from .shape import analyse, bfs_path, central_cell
from .tactics import Tactics
from .world import World

BUDGET = 0.050          # seconds of thinking per move (judge limit is 100 ms)
EXPAND, RETREAT, ATTACK, ROAM = 'EXPAND', 'RETREAT', 'ATTACK', 'ROAM'


class Brain:
    def __init__(self, log=False, variant=None):
        self.variant = variant or {}
        self.rng = random.Random(self.variant['seed']) if 'seed' in self.variant else None
        self.w = World()
        self.plan = None
        self.pi = 0
        self.state = EXPAND
        self.last_action = None
        self.base = 0                # territory snapshot before the current excursion
        self.prev_area = 0
        self.blocked_wait = 0
        self.bullet_block = None     # (cell, until_t): our fresh bullet sits there
        self.fails = 0
        self.avoid = {}              # cell -> until_t (contested tiles)
        self.alert = -100            # last tick an enemy head was close
        self.shape = None
        self.shape_t = -100
        self.reloc_t = -100          # last relocation to the heavy blob
        v = self.variant
        self.opt_heavy = v.get('heavy', 0)
        self.reloc_min = v.get('reloc_min', 300)
        self.reloc_frac = v.get('reloc_frac', 0.3)
        self.heavy_bonus = v.get('heavy_bonus', 2.5)
        self.opt_linedef = v.get('linedef', 0)
        self.trace = v.get('trace')
        self.endgame = v.get('endgame', 0)
        self.centre = None
        self.centre_t = -100
        self.log = log
        self.stats = {'plans': 0, 'bombs': 0, 'bullets': 0, 'walls': 0, 'dash': 0, 'retreat': 0,
                      'attack': 0, 'evade': 0, 'wallkill': 0, 'bombkill': 0, 'block': 0}

    # ------------------------------------------------------------------
    def prime(self, rows, action):
        """Ingest frame 0 after `action` was already sent for it (see bot.py)."""
        self.w.update(rows, None)
        self.w.note_action(action)
        self.last_action = action

    def act(self, rows):
        t0 = perf_counter()
        w = self.w
        try:
            w.update(rows, self.last_action)
        except Exception as exc:  # keep going with whatever we have
            self._log('update error %r' % (exc,))
        t1 = perf_counter()
        try:
            action = self.decide(t0 + BUDGET)
        except Exception as exc:
            self._log('decide error %r' % (exc,))
            self.plan = None
            action = self.safe_move()
        t2 = perf_counter()
        if self.log and t2 - t0 > 0.035:
            self._log('slow t=%d update=%.1fms decide=%.1fms action=%s state=%s plan=%r' % (
                w.t, 1000 * (t1 - t0), 1000 * (t2 - t1), action, self.state, self.plan))
        action = self.sanitize(action)
        if self.trace and self.trace[0] <= w.t <= self.trace[1]:
            self._log('T t=%d pos=(%d,%d) act=%s area=%d c=[d%d b%d g%d w%d] lost=%d\n  %s' % (
                w.t, w.x, w.y, action, popcount(w.mine), w.dash.c, w.bomb.c, w.gun.c, w.build.c, w.lost_track,
                                                                '\n  '.join(rows)))
        try:
            w.note_action(action)
        except Exception:
            pass
        self.last_action = action
        if self.log and w.t % 100 == 0:
            self._log('t=%d pos=(%d,%d) area=%d state=%s plan=%r c=[d%d b%d g%d w%d] %.1fms %s' % (
                w.t, w.x, w.y, popcount(w.mine), self.state, self.plan,
                w.dash.c, w.bomb.c, w.gun.c, w.build.c, 1000 * (perf_counter() - t0), self.stats))
        return action

    def _log(self, msg):
        if self.log:
            sys.stderr.write(msg + '\n')
            sys.stderr.flush()

    # ------------------------------------------------------------------
    def decide(self, deadline):
        w = self.w
        b = w.b
        bit = b.bit
        h = w.head
        hb = bit[h]
        area = popcount(w.mine)
        in_home = bool(hb & w.mine)
        if in_home or area - self.prev_area > 3 or not self.base:
            self.base = w.mine
        self.prev_area = area
        # A move that silently failed twice (head-to-head contention): route around.
        la = self.last_action
        if la and la[0] in 'WASD' and not w.moved:
            self.fails += 1
            tgt = b.nbr[h][KEYS.index(la[0])]
            if self.fails >= 2 and tgt >= 0:
                self.avoid[tgt] = w.t + 8
                self.plan = None
        else:
            self.fails = 0
        self.avoid = {c: u for c, u in self.avoid.items() if u > w.t}
        self._advance_plan()

        planner = Planner(w, deadline, extra_block=b.mask(self.avoid), rng=self.rng, opts=self.variant)
        tac = Tactics(w, planner, avoid=b.mask(self.avoid))
        discount = self.plan.capture if self.plan else 0

        # ---- 1. dodge enemy bombs that would cut our head off ----------------
        act = tac.evade(self._preview())
        if act:
            self.plan = None
            self.state = RETREAT
            self.stats['evade'] += 1
            return act
        # ---- 1b. stop an enemy bullet that would slice our land off ----------
        act = tac.block_bullets()
        if act:
            self.stats['block'] += 1
            return act
        # ---- 1c. stand where a visible shooter's line cannot cut off our bulk --
        if self.opt_linedef and in_home:
            act = tac.dodge_lines(self._preview())
            if act:
                self.plan = None
                self.stats['dodge'] = self.stats.get('dodge', 0) + 1
                return act
        # ---- 2. instant kill: wall the last own tile behind an enemy head ----
        act = tac.wall_kill()
        if act:
            self.state = ATTACK
            self.stats['wallkill'] += 1
            return act
        # ---- 3. bomb that isolates an enemy head when it blows ------------------
        act = tac.bomb_kill()
        if act:
            self.state = ATTACK
            self.stats['bombkill'] += 1
            return act
        # ---- 4. enemy close and we hang by a thread: get into thick land -------
        ne = tac.nearest_enemy()
        if ne is not None and ne[0] <= 7:
            self.alert = w.t
            if tac.thin() or (self.plan is not None and self.plan.kind == 'loop'):
                act = tac.retreat_step()
                if act:
                    self.plan = None
                    self.state = RETREAT
                    self.stats['retreat'] += 1
                    return act

        # ---- danger: an enemy head near our open trail -------------------
        trail = w.mine & ~self.base
        threat = self._threat(trail) if (trail and not in_home) else None
        if threat is not None:
            self.state = RETREAT
            act = self._retreat(planner)
            if act:
                self.stats['retreat'] += 1
                return act

        # ---- ability: finish the loop with a bullet ----------------------
        p = self.plan
        if p is not None and p.bullet_at is not None and self.pi >= p.bullet_at:
            if w.gun.ready(w.t):
                first = b.nbr[h][p.bullet_dir]
                if first >= 0 and not (bit[first] & (w.wall | w.brk | w.objs)):
                    self.plan = None
                    self.bullet_block = (first, w.t + 2)
                    self.stats['bullets'] += 1
                    return 'G' + KEYS[p.bullet_dir]
            p.bullet_at = None  # cannot shoot: walk the rest

        # ---- abilities: bombs, bullets, wall cuts -----------------------------
        if w.bomb.ready(w.t):
            bb = planner.best_bomb(discount)
            if bb and bb[0] >= 7:
                self.stats['bombs'] += 1
                return 'B %d %d' % (bb[1], bb[2])
        if w.build.ready(w.t) and planner.enemy_all & w.vis:
            cut = planner.best_wall_cut()
            if cut and cut[0] >= 6:
                self.stats['walls'] += 1
                return 'C %d %d' % (cut[1], cut[2])
        if w.gun.ready(w.t) and perf_counter() < deadline:
            g = planner.best_bullet(discount)
            next_dir = self._next_dir()
            thr = 9 if w.gun.c >= w.gun.max else 16
            if g and g[0] >= thr and g[1] != next_dir:
                self.bullet_block = (b.nbr[h][g[1]], w.t + 2)
                self.stats['bullets'] += 1
                return 'G' + KEYS[g[1]]

        # ---- endgame: park the head where a cut leaves us the most --------------
        if self.endgame and w.t >= self.endgame and in_home and area >= 300:
            act = self._endgame_hold(tac)
            if act is not None:
                return act

        # ---- keep the head on the heavy side of our necks -----------------------
        if self.opt_heavy and in_home:
            act = self._relocate(planner)
            if act is not None:
                return act

        # ---- attack an exposed enemy trail in view ------------------------------
        atk = self._attack(planner)
        if atk is not None:
            self.state = ATTACK
            self.stats['attack'] += 1
            self.plan = atk
            self.pi = 0

        # ---- plan --------------------------------------------------------------
        if self.plan is None:
            self.state = EXPAND
            self.plan = self._new_plan(planner)
            self.pi = 0
            self.stats['plans'] += 1
        if self.plan is None:
            return self._hold(tac)
        return self._step()

    def _shape(self):
        w = self.w
        if self.shape is None or w.t - self.shape_t >= 4:
            self.shape = analyse(w.b, w.mine, w.b.bit[w.head])
            self.shape_t = w.t
        return self.shape

    def _heavy_region(self):
        sh = self.shape
        if sh is None or sh.heavy is None or self.w.t - self.shape_t > 12:
            return 0
        mass, region, _ = sh.blobs[sh.heavy]
        return region if mass >= 0.4 * sh.area else 0

    def _relocate(self, planner):
        """Walk into the heaviest blob when a single neck cut would cost us most of our land."""
        w = self.w
        b = w.b
        p = self.plan
        if p is not None and (p.kind == 'reloc' or (p.kind == 'loop' and self.pi > 0)):
            return None
        sh = self._shape()
        risk = sh.at_risk()
        if risk < max(self.reloc_min, self.reloc_frac * sh.area):
            return None
        core = sh.blobs[sh.heavy][2]
        safe = w.mine & ~(w.wall | w.brk | w.objs | planner.block)
        path = bfs_path(b, w.head, core, safe)
        if path is None:
            path = bfs_path(b, w.head, core, safe | planner.passable)
        if not path:
            return None
        self.plan = Plan(path, risk, len(path), 0, kind='reloc')
        self.pi = 0
        self.reloc_t = w.t
        self.stats['reloc'] = self.stats.get('reloc', 0) + 1
        return self._step()

    def _endgame_hold(self, tac):
        w = self.w
        b = w.b
        bit = b.bit
        p = self.plan
        if p is not None and p.kind == 'loop' and self.pi > 0:
            return None
        c = self.centre
        if c is None or w.t - self.centre_t >= 30 or not bit[c] & w.mine:
            c = central_cell(b, w.mine, c if c is not None else w.head)
            self.centre, self.centre_t = c, w.t
        if c is None:
            return None
        if c == w.head or (abs(c % b.w - w.x) + abs(c // b.w - w.y) <= 1 and bit[w.head] & w.mine):
            self.plan = None
            return self._hold(tac)
        if p is not None and p.kind == 'centre' and p.cells and p.cells[-1] == c:
            return self._step()
        safe = w.mine & ~(w.wall | w.brk | w.objs)
        path = bfs_path(b, w.head, bit[c], safe | bit[c])
        if not path:
            return None
        self.plan = Plan(path, 0, len(path), 0, kind='centre')
        self.pi = 0
        self.stats['centre'] = self.stats.get('centre', 0) + 1
        return self._step()

    def _hold(self, tac):
        """No safe excursion: stay inside our land, keep away from enemy heads."""
        w = self.w
        b = w.b
        bit = b.bit
        h = w.head
        if not w.mine:
            return self.safe_move()
        ne = tac.nearest_enemy()

        def key(cell):
            own = len(tac.own_neighbours(cell, w.mine | bit[h]))
            far = 0
            if ne is not None:
                far = min(8, max(abs(cell % b.w - ne[2] % b.w), abs(cell // b.w - ne[2] // b.w)))
            return (own >= 3, far, own)

        best = (key(h), 'I')
        for d, n in enumerate(b.nbr[h]):
            if n < 0 or bit[n] & tac.move_block or not (bit[n] & w.mine):
                continue
            k = key(n)
            if k > best[0]:
                best = (k, KEYS[d])
        if best[1] == 'I' and self.fails >= 2:
            return self.safe_move()
        return best[1]

    # ------------------------------------------------------------------
    def _advance_plan(self):
        p = self.plan
        if p is None:
            return
        h = self.w.head
        cells = p.cells
        for k in range(self.pi, min(self.pi + 4, len(cells))):
            if cells[k] == h:
                self.pi = k + 1
                break
        else:
            if self.pi > 0 and cells[self.pi - 1] != h and h not in cells[max(0, self.pi - 2):self.pi]:
                self.plan = None  # knocked off course
                return
        if self.pi >= len(cells):
            self.plan = None

    def _preview(self):
        """The plain move our plan would make now (for comparing with evasions)."""
        d = self._next_dir()
        return KEYS[d] if d is not None else 'I'

    def _next_dir(self):
        p = self.plan
        if p is None or self.pi >= len(p.cells):
            return None
        return self._dir(self.w.head, p.cells[self.pi])

    def _dir(self, a, c):
        for d, nb in enumerate(self.w.b.nbr[a]):
            if nb == c:
                return d
        return None

    def _step(self):
        """Follow the plan one move (dash when three straight free cells ahead)."""
        w = self.w
        b = w.b
        bit = b.bit
        p = self.plan
        h = w.head
        nxt = p.cells[self.pi]
        d = self._dir(h, nxt)
        if d is None:
            self.plan = None
            return self.safe_move()
        if self.bullet_block and w.t <= self.bullet_block[1] and nxt == self.bullet_block[0]:
            return 'I'
        if bit[nxt] & w.brk:
            return 'X' + KEYS[d]
        if bit[nxt] & (w.wall | w.objs):
            self.blocked_wait += 1
            if self.blocked_wait > 2 or bit[nxt] & w.wall:
                self.plan = None
                self.blocked_wait = 0
            return 'I'
        self.blocked_wait = 0
        cells = p.cells
        if w.dash.ready(w.t) and self.pi + 2 < len(cells) and \
                (p.bullet_at is None or self.pi + 3 <= p.bullet_at):
            c1, c2 = cells[self.pi + 1], cells[self.pi + 2]
            if self._dir(nxt, c1) == d and self._dir(c1, c2) == d and \
                    not (bit[c1] & (w.wall | w.brk | w.objs)) and not (bit[c2] & (w.wall | w.brk | w.objs)):
                after = b.nbr[c2][d]
                # A dash stops only at obstacles: never overshoot past the plan.
                if self.pi + 3 >= len(cells) and after >= 0 and not (bit[after] & (w.wall | w.brk | w.objs)):
                    pass
                elif self.pi + 3 < len(cells) and self._dir(c2, cells[self.pi + 3]) != d and \
                        after >= 0 and not (bit[after] & (w.wall | w.brk | w.objs)):
                    pass
                else:
                    self.stats['dash'] += 1
                    return 'J' + KEYS[d]
        return KEYS[d]

    # ------------------------------------------------------------------
    def _new_plan(self, planner):
        w = self.w
        if w.mine and w.t - self.alert < 12:
            return None  # enemy just around: no fresh excursions, hold thick land
        risky = self._enemy_near(25, 60)
        area = popcount(w.mine)
        # The bigger we are, the more a cut of our open trail would cost: shrink loops.
        big = self.variant.get('max_leg', 40)
        if area > 2500:
            big = min(big, 10)
        elif area > 1200:
            big = min(big, 18)
        max_leg = 12 if risky else (big if w.t > 30 else 14)
        if w.t > 1880 and area > 400:
            max_leg = min(max_leg, 5)
        plan = planner.plan_loops(max_leg=max_leg)
        if plan is not None and plan.rate >= 0.8:
            return plan
        far = self._frontier(planner)
        if far is not None and (plan is None or far.rate > plan.rate):
            return far
        return plan

    def _frontier(self, planner):
        """Walk (through our land) to the boundary cell with most claimable land nearby."""
        w = self.w
        b = w.b
        bit = b.bit
        M = w.mine | bit[w.head]
        passable = planner.passable | w.mine
        dist = b.distance_field(bit[w.head], passable, limit=90)
        claim = b.full & ~w.mine & ~w.wall
        boundary = M & b.dilate(claim & planner.passable)
        best = None
        cells = b.cells(boundary)
        if len(cells) > 300:
            cells = cells[::len(cells) // 300 + 1]
        heavy = b.dilate(self._heavy_region()) if self.opt_heavy else 0
        for c in cells:
            dd = dist[c]
            if dd >= INF or dd == 0:
                continue
            region = b.disk(c, 49) & claim
            score = popcount(region) / (dd + 12.0)
            if bit[c] & heavy:
                score *= self.heavy_bonus
            if best is None or score > best[0]:
                best = (score, c)
        if best is None:
            return None
        path = [best[1]]
        c = best[1]
        while dist[c] > 1:
            for nb in b.nbr[c]:
                if nb >= 0 and dist[nb] == dist[c] - 1:
                    c = nb
                    break
            else:
                return None
            path.append(c)
        path.reverse()
        plan = Plan(path, best[0], len(path), 0, kind='goto')
        plan.rate = 0.5
        return plan

    def _enemy_near(self, radius, age):
        w = self.w
        b = w.b
        for lab, (cell, ts) in w.heads.items():
            if w.t - ts <= age and abs(cell % b.w - w.x) + abs(cell // b.w - w.y) <= radius:
                return True
        return False

    # ------------------------------------------------------------------
    def _threat(self, trail):
        """An enemy head that can reach our open trail before we can close it."""
        w = self.w
        b = w.b
        best = None
        tcells = b.cells(trail)
        if not tcells:
            return None
        remaining = (len(self.plan.cells) - self.pi) if self.plan else 6
        for lab, (cell, ts) in w.heads.items():
            if w.t - ts > 1:
                continue
            ex, ey = cell % b.w, cell // b.w
            de = min(abs(c % b.w - ex) + abs(c // b.w - ey) for c in tcells)
            if de <= min(remaining, 8) + 1:
                if best is None or de < best:
                    best = de
        return best

    def _retreat(self, planner):
        """Get our head back onto/next to the base by the shortest way (or shoot it)."""
        w = self.w
        b = w.b
        bit = b.bit
        h = w.head
        base = self.base & ~bit[h]
        if not base:
            return None
        # A straight bullet back to base seals the excursion at once.
        if w.gun.ready(w.t):
            for d in range(4):
                line = w.ray(h, d)
                if len(line) >= 2 and any(bit[c] & base for c in line[:12]):
                    first = line[0]
                    self.bullet_block = (first, w.t + 2)
                    self.plan = None
                    self.stats['bullets'] += 1
                    return 'G' + KEYS[d]
        passable = planner.passable | w.mine
        dist = b.distance_field(base, passable, limit=60)
        bestn = None
        for d, nb in enumerate(b.nbr[h]):
            if nb < 0 or not (bit[nb] & passable) or bit[nb] & w.objs:
                continue
            if bestn is None or dist[nb] < dist[bestn[1]]:
                bestn = (d, nb)
        if bestn is None or dist[bestn[1]] >= INF:
            return None
        self.plan = None
        return KEYS[bestn[0]]

    def _attack(self, planner):
        """Cross a visible enemy trail when it cuts a big chunk off its owner."""
        w = self.w
        b = w.b
        bit = b.bit
        if not (planner.enemy_all & w.vis):
            return None
        if self.plan is not None and self.plan.kind == 'attack':
            return None
        passable = planner.passable | w.mine
        dist = b.distance_field(bit[w.head], passable, limit=6)
        best = None
        for c in b.cells(planner.enemy_all & w.vis):
            dd = dist[c]
            if dd >= INF or dd == 0:
                continue
            steal = planner.steal_by(bit[c])
            if steal < 6:
                continue
            score = steal / (dd + 1.0)
            if best is None or score > best[0]:
                best = (score, c, steal)
        if best is None or best[0] < 3.0:
            return None
        c = best[1]
        path = [c]
        while dist[c] > 1:
            for nb in b.nbr[c]:
                if nb >= 0 and dist[nb] == dist[c] - 1:
                    c = nb
                    break
            else:
                return None
            path.append(c)
        path.reverse()
        plan = Plan(path, best[2], len(path), 0, kind='attack')
        return plan

    # ------------------------------------------------------------------
    def safe_move(self):
        """Any legal move, preferring our own land, then fresh ground."""
        w = self.w
        b = w.b
        bit = b.bit
        best = None
        avoid = self.avoid
        for d, nb in enumerate(b.nbr[w.head]):
            if nb < 0 or bit[nb] & (w.wall | w.brk | w.objs) or nb in avoid:
                continue
            score = (1 if bit[nb] & w.mine else 0, -d)
            if best is None or score > best[0]:
                best = (score, d)
        if best is None:
            # Boxed in (or every exit contested): break out through a breakable wall.
            for d, nb in enumerate(b.nbr[w.head]):
                if nb >= 0 and bit[nb] & w.brk:
                    return 'X' + KEYS[d]
            return 'I'
        return KEYS[best[1]]

    @staticmethod
    def sanitize(a):
        if not isinstance(a, str) or not a:
            return 'I'
        k = a[0]
        if k in 'WASDI' and len(a) == 1:
            return a
        if k in 'JGX' and len(a) == 2 and a[1] in 'WASD':
            return a
        if k in 'BC':
            parts = a.split()
            if len(parts) == 3:
                try:
                    i, j = int(parts[1]), int(parts[2])
                    if 0 < i * i + j * j <= 16:
                        return '%s %d %d' % (k, i, j)
                except ValueError:
                    pass
        return 'I'
