"""Decision loop: FSM (EXPAND / RETREAT / ATTACK) over the loop planner + abilities."""

import random
import sys
from time import perf_counter

from .board import DX, DY, INF, KEYS, popcount
from .planner import Plan, Planner
from .tactics import Tactics
from .world import World

BUDGET = 0.028          # seconds of planning per move (judge limit is 100 ms; keep worst case < 50)
WATCHDOG = 0.040        # past this, skip every optional stage and just make a safe move
GUARD_AGE = 8           # sightings this recent still count as a threat to our trail
STYLE_MARGIN = {'aggr': 3, 'neutral': 1, 'timid': -1}
EXPAND, RETREAT, ATTACK, ROAM = 'EXPAND', 'RETREAT', 'ATTACK', 'ROAM'


class Brain:
    def __init__(self, log=False, variant=None):
        self.variant = variant or {}
        self.rng = random.Random(self.variant['seed']) if 'seed' in self.variant else None
        self.w = World()
        # Belief fixes (all measured neutral-to-worse in win rate / placement; off):
        self.w.objkeep = bool(self.variant.get('objkeep', 0))
        self.w.book = bool(self.variant.get('book', 0))
        self.w.freshcut = bool(self.variant.get('freshcut', 0))
        self.w.staleprop = bool(self.variant.get('staleprop', 0))
        self.w.restore = bool(self.variant.get('restore', 0))
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
        v = self.variant
        self.frontier_skipped = False
        self.atk_min = v.get('atk_min', 6)         # smallest credible steal worth walking for
        self.atk_score = v.get('atk_score', 3.0)
        self.atk_radius = v.get('atk_radius', 6)   # how far we walk to cross an enemy trail
        self.opt_guard = v.get('guard', 0)         # race-based tail guard (vs reckless bots)
        self.opt_fp = v.get('fp', 0)               # opponent fingerprints widen/narrow its margin
        self.opt_wkdodge = v.get('wkdodge', 0)     # keep >= 2 own neighbours near enemy heads
        self.late = v.get('late', 0)               # from this tick on: no new loops once we hold land
        self.alert_ticks = v.get('alert_ticks', 12)  # no new loops this long after an enemy came close
        self.opt_trap = v.get('trap', 0)           # wall in enemy heads with a single free neighbour
        self.opt_bblock2 = v.get('bblock2', 0)     # stop bullets fired inside our land early
        holy = v.get('holy', 0)                    # opponent model: bomb at once, steal-aware, centre-bound
        self.bomb_min = v.get('bomb_min', 7)        # least gain for an expansion bomb
        self.centre_bias = v.get('centre_bias', 1.0 if holy else 0)
        self.opt_bombtimer = v.get('bombtimer', 0)   # keep off enemies whose bomb may be ready
        self.endavoid = v.get('endavoid', 0)         # from this tick: keep 8 off every enemy head
        self.rank_from = v.get('rank', 0)            # from this tick: hold when clearly 1st
        self.holding = False
        self.trace = v.get('trace')                # debug: [t0, t1] dump views
        self.tracepos = v.get('tracepos', 0)       # debug: log position every tick
        self.log = log
        self.stats = {'plans': 0, 'bombs': 0, 'bullets': 0, 'walls': 0, 'dash': 0, 'retreat': 0,
                      'attack': 0, 'evade': 0, 'wallkill': 0, 'bombkill': 0, 'block': 0}

    # ------------------------------------------------------------------
    def replay(self, frames, actions):
        """Catch up on frames already answered by the scripted opening (see bot.py)."""
        w = self.w
        for k, rows in enumerate(frames):
            w.update(rows, actions[k - 1] if k else None)
            w.note_action(actions[k])
        self.last_action = actions[len(frames) - 1]

    def act(self, rows, clock_start=None):
        """One move.  clock_start: when this move's time limit started, if earlier than now."""
        t0 = perf_counter() if clock_start is None else clock_start
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
        if self.tracepos:
            self._log('P %d %d %d %s %d %d' % (w.t, w.x, w.y, action, w.lost_track, popcount(w.mine)))
        if self.trace and self.trace[0] <= w.t <= self.trace[1]:
            self._log('T t=%d pos=(%d,%d) act=%s area=%d c=[d%d b%d g%d w%d] lost=%d\n  %s' % (
                w.t, w.x, w.y, action, popcount(w.mine), w.dash.c, w.bomb.c, w.gun.c, w.build.c, w.lost_track,
                                                                '\n  '.join(rows)))
        try:
            w.note_action(action)
        except Exception:
            pass
        self.last_action = action
        if self.log and w.t == 1999:
            self._log('audit %r' % (sorted(w.audit.items()),))
        if self.log and w.t % 100 == 0:
            self._log('t=%d pos=(%d,%d) area=%d state=%s plan=%r c=[d%d b%d g%d w%d] %.1fms %s' % (
                w.t, w.x, w.y, popcount(w.mine), self.state, self.plan,
                w.dash.c, w.bomb.c, w.gun.c, w.build.c, 1000 * (perf_counter() - t0), self.stats))
        return action

    def _count(self, key):
        self.stats[key] = self.stats.get(key, 0) + 1

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
        # Endgame, clearly 1st: protect the lead (no open trails, keep off enemy heads).
        self.holding = bool(self.rank_from and w.t >= self.rank_from and area > 400 and w.clearly_first())
        if self.holding:
            self._count('holding')

        start = deadline - BUDGET
        planner = Planner(w, deadline, extra_block=b.mask(self.avoid), rng=self.rng, opts=self.variant)
        tac = Tactics(w, planner, avoid=b.mask(self.avoid))
        tac.short_crack = self.opt_bblock2
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
        # ---- 1d. never hang on one own tile with an enemy head in wall range ----
        if self.opt_wkdodge and w.mine:
            act = tac.wallkill_dodge(self._preview(), self.base if not in_home else w.mine)
            if act:
                self.plan = None if act != self._preview() else self.plan
                self._count('wkdodge')
                return act
        # ---- 2. instant kill: wall the last own tile behind an enemy head ----
        act = tac.wall_kill()
        if act:
            self.state = ATTACK
            self.stats['wallkill'] += 1
            return act
        if self.opt_trap:
            act = tac.trap()
            if act:
                self.state = ATTACK
                self._count('trap')
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
            if (tac.thin() or (self.plan is not None and self.plan.kind == 'loop')) and \
                    not (self.opt_guard and not in_home):
                act = tac.retreat_step()
                if act:
                    self.plan = None
                    self.state = RETREAT
                    self.stats['retreat'] += 1
                    return act

        # ---- danger: an enemy head near our open trail -------------------
        trail = w.mine & ~self.base
        if self.opt_guard:
            if trail and not in_home:
                act = self._guard(planner, trail)
                if act:
                    self.state = RETREAT
                    self._count('guard')
                    return act
            threat = None
        else:
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

        if perf_counter() - start > WATCHDOG:
            return self._fallback(tac)

        # ---- abilities: bombs, bullets, wall cuts -----------------------------
        if w.bomb.ready(w.t):
            bb = planner.best_bomb(discount)
            if bb and bb[0] >= self.bomb_min:
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

        if perf_counter() - start > WATCHDOG:
            return self._fallback(tac)

        # ---- stay out of bomb-kill reach of enemies whose bomb may be ready -------
        if (self.opt_bombtimer or self.holding or (self.endavoid and w.t >= self.endavoid)) and in_home:
            act = self._keep_off(tac)
            if act is not None:
                return act

        # ---- attack an exposed enemy trail in view ------------------------------
        atk = None if self.holding else self._attack(planner)
        if atk is not None:
            self.state = ATTACK
            self.stats['attack'] += 1
            self.plan = atk
            self.pi = 0

        # ---- plan --------------------------------------------------------------
        if self.plan is None and perf_counter() - start > WATCHDOG:
            return self._fallback(tac)
        if self.plan is None:
            self.state = EXPAND
            self.plan = self._new_plan(planner)
            self.pi = 0
            self.stats['plans'] += 1
        if self.plan is None:
            return self._hold(tac)
        return self._step()

    def _fallback(self, tac):
        """Watchdog: no time left for optional work. Keep following the plan (it returns
        to our land), else head straight for our land, else stay put inside it."""
        self._count('watchdog')
        if self.plan is not None and self.pi < len(self.plan.cells):
            return self._step()
        w = self.w
        if not (w.b.bit[w.head] & w.mine) and self.base:
            path = w.b.path_to(w.head, self.base, tac.p.passable | w.mine, limit=40)
            if path:
                self.plan = Plan(path, 0, len(path), 0, kind='retreat')
                self.pi = 0
                return self._step()
        return 'I' if w.b.bit[w.head] & w.mine else self.safe_move()

    def _guard(self, planner, trail):
        """Tail guard against reckless bots.

        Any enemy seen in the last GUARD_AGE ticks is assumed to come straight for our
        open trail (one cell per tick unseen, plus a style margin), or to shoot along a
        clear line onto it.  If it can get there before we can close, close by the
        fastest way: a bullet back to our land when that seals sooner, else the shortest
        path home (dashing on straights).  Otherwise keep the plan.
        """
        w = self.w
        b = w.b
        bit = b.bit
        h = w.head
        base = self.base & ~bit[h]
        if not base:
            return None
        foes = [(lab, cell, w.t - ts) for lab, (cell, ts) in w.heads.items() if w.t - ts <= GUARD_AGE]
        if not foes:
            return None
        passable = planner.passable | w.mine
        p = self.plan
        remaining = len(p.cells) - self.pi if p is not None and p.kind in ('loop', 'retreat') else None
        path = None
        if p is not None and p.kind == 'retreat':
            path = p.cells[self.pi:]
        if not path:
            path = b.path_to(h, base, passable, limit=60)
        if not path:
            return None
        close = len(path) - (2 if w.dash.ready(w.t) and len(path) >= 3 else 0)
        seal = None
        if w.gun.ready(w.t):
            for d in range(4):
                line = w.ray(h, d)
                k = next((i for i, c in enumerate(line[:12]) if bit[c] & base), None)
                if k is not None and k >= 1:
                    tt = 2 + k // 3
                    if seal is None or tt < seal[0]:
                        seal = (tt, d, line[0])
        t_close = min(close, seal[0]) if seal else close
        # Race: distance from each recent sighting to the trail, grown by its age.
        threat = False
        reach = trail
        far = {}
        todo = {lab: (cell, age) for lab, cell, age in foes}
        for k in range(0, 25):
            for lab, (cell, age) in list(todo.items()):
                if bit[cell] & reach:
                    far[lab] = k
                    del todo[lab]
            if not todo:
                break
            reach = b.dilate(reach)
        for lab, cell, age in foes:
            margin = STYLE_MARGIN[w.enemy_style(lab)] if self.opt_fp else 1
            d = far.get(lab)
            if d is not None and d - age <= t_close + margin:
                threat = True
                break
            if age <= 2 and (not self.opt_fp or w.enemy_style(lab) != 'timid'):
                # a bullet along a clear row/column onto our trail
                for dd in range(4):
                    if any(bit[c] & trail for c in w.ray(cell, dd)[:10]):
                        threat = True
                        break
                if threat:
                    break
        if not threat:
            return None
        if remaining is not None and p.kind == 'loop' and remaining <= t_close:
            return None                     # the plan itself closes as fast: keep it
        if seal is not None and seal[0] <= close:
            self.plan = None
            self.bullet_block = (seal[2], w.t + 2)
            self.stats['bullets'] += 1
            return 'G' + KEYS[seal[1]]
        if p is None or p.kind != 'retreat':
            self.plan = Plan(path, 0, len(path), 0, kind='retreat')
            self.pi = 0
        return self._step()

    def _keep_off(self, tac):
        """Step (inside our land) away from close enemy heads that could bomb us now.

        A bomb kills a head within the diamond |dx|+|dy| <= 2 of its centre and is thrown
        up to 4 away, so an enemy within 6 with its bomb off cooldown is a threat.  In the
        endgame every enemy head within 8 counts."""
        w = self.w
        b = w.b
        bit = b.bit
        late = self.holding or (self.endavoid and w.t >= self.endavoid)
        radius = 8 if late else 6
        foes = [c for lab, c in tac.heads.items()
                if (late or w.enemy_bomb_ready(lab)) and
                max(abs(c % b.w - w.x), abs(c // b.w - w.y)) <= radius]
        if not foes:
            return None

        def gap(cell):
            return min(max(abs(cell % b.w - c % b.w), abs(cell // b.w - c // b.w)) for c in foes)

        here = gap(w.head)
        best = None
        for d, n in enumerate(b.nbr[w.head]):
            if n < 0 or bit[n] & tac.move_block or not bit[n] & w.mine:
                continue
            k = (gap(n), len(tac.own_neighbours(n, w.mine | bit[w.head])) >= 3)
            if k[0] > here and (best is None or k > best[0]):
                best = (k, d)
        if best is None:
            return None
        self.plan = None
        self._count('keepoff')
        return KEYS[best[1]]

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
        self._count('hold_' + ('alert' if w.t - self.alert < 12 else 'noplan') + ('_I' if best[1] == 'I' else ''))
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
        self._count('step_' + p.kind)
        if d is None:
            self.plan = None
            return self.safe_move()
        if self.bullet_block and w.t <= self.bullet_block[1] and nxt == self.bullet_block[0]:
            self._count('idle_bullet')
            return 'I'
        if bit[nxt] & w.brk:
            return 'X' + KEYS[d]
        if bit[nxt] & (w.wall | w.objs):
            self.blocked_wait += 1
            if self.blocked_wait > 2 or bit[nxt] & w.wall:
                self.plan = None
                self.blocked_wait = 0
            self._count('idle_blocked')
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
        if w.mine and w.t - self.alert < self.alert_ticks:
            return None  # enemy just around: no fresh excursions, hold thick land
        risky = self._enemy_near(25, 60)
        area = popcount(w.mine)
        if (self.late and w.t >= self.late and area > 400) or self.holding:
            return None     # endgame: an open trail risks everything for a few tiles; hold thick land
        # The bigger we are, the more a cut of our open trail would cost: shrink loops.
        big = self.variant.get('max_leg', 40)
        if area > 2500:
            big = min(big, 10)
        elif area > 1200:
            big = min(big, 18)
        max_leg = 12 if risky else (big if w.t > 30 else 14)
        if w.t > 1880 and area > 400:
            max_leg = min(max_leg, 5)
        plan = planner.plan_loops(max_leg=max_leg, top=self.variant.get("top", 100))
        if plan is not None and plan.rate >= 0.8:
            return plan
        if perf_counter() > planner.deadline + 0.008 and not self.frontier_skipped:
            self.frontier_skipped = True
            return plan             # out of time: the frontier walk can wait one tick
        self.frontier_skipped = False
        far = self._frontier(planner)
        if far is not None and (plan is None or far.rate > plan.rate):
            return far
        return plan

    def _frontier(self, planner):
        """Walk (through our land) to the boundary cell with most claimable land nearby.

        Bitboard BFS from the head, scoring boundary cells layer by layer; stops once no
        farther cell can beat the best (a radius-7 disk holds at most 149 cells).
        """
        w = self.w
        b = w.b
        bit = b.bit
        hb = bit[w.head]
        M = w.mine | hb
        passable = planner.passable | w.mine
        claim = b.full & ~w.mine & ~w.wall
        boundary = M & b.dilate(claim & planner.passable)
        layers = [hb]
        seen = cur = hb
        best = None
        for k in range(1, 91):
            cur = b.dilate(cur) & passable & ~seen
            if not cur:
                break
            seen |= cur
            layers.append(cur)
            cand = cur & boundary
            if cand:
                cells = b.cells(cand)
                if len(cells) > 40:
                    cells = cells[::len(cells) // 40 + 1]
                for c in cells:
                    score = popcount(b.disk(c, 49) & claim) / (k + 12.0)
                    if self.centre_bias:
                        score *= 1.0 + self.centre_bias * (100 - abs(c % b.w - 50) - abs(c // b.w - 50)) / 100.0
                    if best is None or score > best[0]:
                        best = (score, c, k)
            if best is not None and 149.0 / (k + 13.0) <= best[0]:
                break
        if best is None:
            return None
        c = best[1]
        path = [c]
        nbr = b.nbr
        for k in range(best[2] - 1, 0, -1):
            lay = layers[k]
            for n in nbr[c]:
                if n >= 0 and bit[n] & lay:
                    c = n
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
        dist = b.distance_field(bit[w.head], passable, limit=self.atk_radius)
        best = None
        for c in b.cells(planner.enemy_all & w.vis):
            dd = dist[c]
            if dd >= INF or dd == 0:
                continue
            if planner.out_of_time(-0.010):
                break           # each check floods enemy land: never run far past the budget
            steal = planner.steal_by(bit[c])
            if steal < self.atk_min:
                continue
            score = steal / (dd + 1.0)
            if best is None or score > best[0]:
                best = (score, c, steal)
        if best is None or best[0] < self.atk_score:
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
