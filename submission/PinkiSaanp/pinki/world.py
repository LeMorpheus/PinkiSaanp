"""World model: localisation, map memory, territory beliefs, ability charges.

Facts measured against the judge binary (probes/):
  * the view is in our own frame (spawn top-left at (3,3)); our head is the
    centre char, whose label is NOT necessarily '1' -> learn it on frame 0;
  * leaving a tile paints it; area = 4-connected component of our head;
    parts we disconnect ourselves revert to air;
  * enclosures: (area + head) holes are filled; walls do NOT fence;
  * bombs show up next frame and explode 3 frames after the throw (r^2<=9);
  * bullets sit next to us one frame, then fly 3 tiles/frame painting;
  * charges: +1 every R moves while below max; cooldown C means C moves
    strictly between uses.
"""

from .board import Board, DX, DY, KEYS, popcount
from .mapdata import ROWS

LABELS = '1234'
PAINTS = 'ABCD'
BOMBS = '!@$%'
BULLET_CHARS = set('GHJKL')
BULLET_OWNER = {'G': 0, 'H': 1, 'K': 2, 'L': 3}     # view char -> player index
FREE_CHARS = set('.ABCD')
STABLE = set('.ABCD*')
N = 100
_WALL_TABLE = bytes(1 if c == ord('#') else 0 for c in range(256))


def _mask_of(rows, ch):
    """Bitboard (stride N + 1) of the cells holding `ch`, built via int(str, 2)."""
    tr = str.maketrans({c: '0' for c in set(''.join(rows)) if c != ch} | {ch: '1'})
    bits = '0'.join(r.translate(tr) for r in rows)
    return int(bits[::-1], 2)


class Ability:
    __slots__ = ('c', 'max', 'cd', 'r', 'last', 'timer', 'prev_last')

    def __init__(self, maxc, init, cd, r):
        self.c, self.max, self.cd, self.r = init, maxc, cd, r
        self.last = self.prev_last = -10 ** 6
        self.timer = 0

    def ready(self, t):
        return self.c >= 1 and t - self.last > self.cd

    def use(self, t):
        self.c -= 1
        self.prev_last, self.last = self.last, t

    def refund(self):
        self.c += 1
        self.last = self.prev_last

    def tick(self):
        if self.c < self.max:
            self.timer += 1
            if self.timer >= self.r:
                self.c += 1
                self.timer = 0
        else:
            self.timer = 0


class World:
    def __init__(self):
        self.b = b = Board(N, N)
        bit = b.bit
        self.t = 0
        self.label = None
        self.paint = None
        self.bomb_ch = None
        self.bullet_ch = None
        self.x, self.y = 3, 3
        flat = ''.join(ROWS)
        self.wall = _mask_of(ROWS, '#')     # unbreakable (static)
        self.brk = _mask_of(ROWS, '*')      # breakable walls (belief)
        self.static_wall = bytearray(flat.encode().translate(_WALL_TABLE))
        self.mem = bytearray(flat.encode())
        self.seen = [-1] * (N * N)
        self.mine = 0
        self.enemy = {}                 # label -> paint mask (belief)
        self.heads = {}                 # label -> (cell, t_seen)
        self.head_dirs = {}             # label -> last observed heading
        self.foreign_bombs = {}         # cell -> first frame seen
        self.fbullets = {}              # cell -> char (enemy bullets in view)
        self.fbullet_dirs = {}          # cell -> heading when inferable
        self.objs = 0                   # bombs / bullets / heads in the latest view
        self.vis = 0
        self.seen_ever = 0
        self.dash = Ability(2, 1, 5, 20)
        self.bomb = Ability(1, 0, 15, 15)
        self.gun = Ability(3, 0, 2, 20)
        self.build = Ability(30, 5, 0, 5)
        self.last_action = None
        self.no_build = {}              # cell -> tick until which building there is pointless
        self.build_fail_t = -100
        self.audit = {}                 # action letter -> count, 'failX' -> failed count
        self.book_steals = False        # add credible steals beyond the view to our land belief
        self.head_age = 1               # ticks a sighting still pins an enemy head's side of a cut
        self.debug_build = None
        self.prev_rows = None
        self.moved = True
        self.my_bullets = []            # [path cells, fired_t]
        self.my_bombs = []              # [centre, fired_t]
        self.lost_track = 0
        self.area_hist = []

    # ------------------------------------------------------------------
    @property
    def head(self):
        return self.y * N + self.x

    def passable_char(self, ch):
        return ch in FREE_CHARS

    def blocked_mask(self):
        """Cells we cannot step into right now (walls, breakables, live objects)."""
        return self.wall | self.brk | self.objs

    # ------------------------------------------------------------------
    def update(self, rows, action):
        """Ingest one 11x11 frame (taken after `action` resolved)."""
        rows = [(r + '~' * 11)[:11] for r in rows]
        if self.label is None:
            self._learn_label(rows[5][5])
        else:
            self.t += 1
            self._localize(rows, action)
            self._verify(rows, action)
            for ab in (self.dash, self.bomb, self.gun, self.build):
                ab.tick()
        before = dict(self.enemy) if self.book_steals else None
        self._observe(rows)
        self.prev_rows = rows
        self._predict_effects()
        if before is not None:
            self._resolve_steals(before)
        self._enforce_connectivity()
        self.area_hist.append(popcount(self.mine))

    def _learn_label(self, ch):
        if ch not in LABELS:
            ch = '1'
        self.label = ch
        k = LABELS.index(ch)
        self.paint = PAINTS[k]
        self.bomb_ch = BOMBS[k]
        self.enemy_paints = {PAINTS[j]: LABELS[j] for j in range(4) if j != k}
        for j in range(4):
            if j != k:
                self.enemy[LABELS[j]] = 0

    # ------------------------------------------------------------------
    def _evidence(self, rows, x, y, hard_limit):
        """(hard, soft) disagreement between a frame and the map if our head were at (x, y).

        Hard: static walls / off-map cells that do not match (they never change).
        Soft: tiles seen on the previous frame that changed.  Soft evidence only ranks
        candidates: our own bomb blasts and fills legitimately change dozens of tiles.
        """
        sw = self.static_wall
        mem = self.mem
        seen = self.seen
        prev = self.t - 1
        hard = soft = 0
        for r in range(11):
            wy = y + r - 5
            row = rows[r]
            inside_y = 0 <= wy < N
            for c in range(11):
                if r == 5 and c == 5:
                    continue
                ch = row[c]
                wx = x + c - 5
                if not inside_y or wx < 0 or wx >= N:
                    if ch != '~':
                        hard += 1
                    continue
                i = wy * N + wx
                if sw[i]:
                    if ch != '#':
                        hard += 1
                elif ch == '#' or ch == '~':
                    hard += 1
                elif seen[i] == prev and ch in STABLE and mem[i] != ord(ch):
                    soft += 1
            if hard > hard_limit:
                return hard, soft
        return hard, soft

    def _localize(self, rows, action):
        d = None
        steps = 0
        if action and action[0] in 'WASD':
            d, steps = KEYS.index(action[0]), 1
        elif action and action[0] == 'J' and len(action) > 1 and action[1] in 'WASD':
            d, steps = KEYS.index(action[1]), 3
        cands = []
        if d is not None:
            for k in range(steps, -1, -1):
                cands.append((self.x + DX[d] * k, self.y + DY[d] * k, 0.0 if k == steps else 0.4 + 0.1 * k))
        else:
            cands.append((self.x, self.y, 0.0))
        best = None
        for (x, y, prior) in cands:
            if not (0 <= x < N and 0 <= y < N):
                continue
            hard, soft = self._evidence(rows, x, y, 1 << 30)
            score = 2 * hard + 0.25 * soft + prior
            # Moving leaves our paint behind us; idling does not.
            if d is not None and (x, y) != (self.x, self.y):
                bx, by = 5 - DX[d], 5 - DY[d]
                if rows[by][bx] == self.paint:
                    score -= 0.5
            if best is None or score < best[0]:
                best = (score, x, y, hard)
        if best[3] > 0:
            # Static walls contradict every expected position: we are lost.  Search
            # nearby for the position the walls agree with best.
            top = None
            for dy in range(-7, 8):
                for dx in range(-7, 8):
                    x, y = self.x + dx, self.y + dy
                    if not (0 <= x < N and 0 <= y < N):
                        continue
                    hard, soft = self._evidence(rows, x, y, best[3] if top is None else top[1])
                    key = (hard, 0.25 * min(soft, 24) + 0.05 * (abs(dx) + abs(dy)))
                    if top is None or key < (top[1], top[2]):
                        top = (None, hard, key[1], x, y)
            if top is not None and top[1] < best[3]:
                best = (0.0, top[3], top[4], top[1])
            self.lost_track += 1
        self.moved = (best[1], best[2]) != (self.x, self.y)
        self.x, self.y = best[1], best[2]

    def _verify(self, rows, action):
        """Check whether last tick's ability actually fired; fix charge beliefs."""
        if not action:
            return
        k = action[0]
        a = self.audit
        a[k] = a.get(k, 0) + 1
        if k in 'WASDJ' and not self.moved:
            a['fail' + k] = a.get('fail' + k, 0) + 1
        if k == 'G':
            d = KEYS.index(action[1])
            ch = rows[5 + DY[d]][5 + DX[d]]
            if ch in BULLET_CHARS:
                if self.bullet_ch is None:
                    self.bullet_ch = ch
            else:
                a['failG'] = a.get('failG', 0) + 1
                self.gun.refund()
                self.gun.c = 0
                if self.my_bullets and self.my_bullets[-1][1] == self.t - 1:
                    self.my_bullets.pop()
        elif k == 'B':
            i, j = (int(v) for v in action[1:].split())
            ch = rows[5 + j][5 + i] if 0 <= 5 + j < 11 and 0 <= 5 + i < 11 else '?'
            if ch != self.bomb_ch:
                a['failB'] = a.get('failB', 0) + 1
                self.bomb.refund()
                self.bomb.c = 0
                if self.my_bombs and self.my_bombs[-1][1] == self.t - 1:
                    self.my_bombs.pop()
        elif k == 'C':
            i, j = (int(v) for v in action[1:].split())
            ch = rows[5 + j][5 + i] if 0 <= 5 + j < 11 and 0 <= 5 + i < 11 else '?'
            # A wall that cuts enemy land off can be swallowed by the fill at once:
            # our own paint on the target still means the charge was spent.
            if ch != '*' and ch != self.paint:
                a['failC'] = a.get('failC', 0) + 1
                if self.debug_build is not None:
                    self.debug_build.append((self.t, action, ch, self.build.c, list(rows), self.prev_rows))
                self.build.refund()
                # Usually a head stepping onto the same tile: retrying just deadlocks both.
                self.no_build[self.b.idx(self.x + i, self.y + j)] = self.t + 6
                if self.t - self.build_fail_t <= 3:
                    self.build.c = 0      # charge belief has drifted: resync from zero
                self.build_fail_t = self.t
        elif k == 'J':
            if not self.moved:
                self.dash.c = 0

    # ------------------------------------------------------------------
    def _observe(self, rows):
        b = self.b
        bit = b.bit
        t = self.t
        x0, y0 = self.x - 5, self.y - 5
        vis = mine_v = brk_v = obj_v = 0
        en_v = {k: 0 for k in self.enemy}
        bombs = {}
        bullets = {}
        paints = self.enemy_paints
        mem = self.mem
        seen = self.seen
        my = self.paint
        center = (self.y * N + self.x)
        for r in range(11):
            wy = y0 + r
            if wy < 0 or wy >= N:
                continue
            row = rows[r]
            base = wy * N
            for c in range(11):
                wx = x0 + c
                if wx < 0 or wx >= N:
                    continue
                i = base + wx
                ch = row[c]
                if i == center:
                    continue
                bi = bit[i]
                vis |= bi
                seen[i] = t
                if ch == my:
                    mine_v |= bi
                    mem[i] = ord(ch)
                elif ch in paints:
                    en_v[paints[ch]] |= bi
                    mem[i] = ord(ch)
                elif ch == '.':
                    mem[i] = 46
                elif ch == '*':
                    brk_v |= bi
                    mem[i] = 42
                elif ch == '#' or ch == '~':
                    mem[i] = ord(ch)
                else:
                    obj_v |= bi
                    if ch in LABELS:
                        prev = self.heads.get(ch)
                        if prev is not None and prev[1] == t - 1 and prev[0] != i:
                            for d, nb in enumerate(b.nbr[prev[0]]):
                                if nb == i:
                                    self.head_dirs[ch] = d
                                    break
                            else:
                                self.head_dirs.pop(ch, None)
                        elif prev is not None and prev[0] == i:
                            self.head_dirs.pop(ch, None)
                        self.heads[ch] = (i, t)
                    elif ch in BOMBS and ch != self.bomb_ch:
                        bombs[i] = self.foreign_bombs.get(i, t)
                    elif ch in BULLET_CHARS and ch != self.bullet_ch:
                        bullets[i] = ch
        self.foreign_bombs = bombs
        self._track_bullets(bullets)
        self.vis = vis
        self.seen_ever |= vis
        self.mine = (self.mine & ~vis) | mine_v
        for k in self.enemy:
            self.enemy[k] = (self.enemy[k] & ~vis) | en_v[k]
        self.brk = (self.brk & ~vis) | brk_v
        self.objs = obj_v

    def _track_bullets(self, bullets):
        """Foreign bullets with their heading (3-tile jumps or fresh next to a head)."""
        b = self.b
        w = b.w
        prev = self.fbullets
        dirs = {}
        for c, ch in bullets.items():
            cx, cy = c % w, c // w
            found = None
            for p, pch in prev.items():
                px, py = p % w, p // w
                if pch != ch:
                    continue
                if px == cx and 0 < abs(py - cy) <= 3:
                    found = 2 if cy > py else 0
                elif py == cy and 0 < abs(px - cx) <= 3:
                    found = 3 if cx > px else 1
                if found is not None:
                    break
            if found is None:
                for lab, (hc, ts) in self.heads.items():
                    if ts == self.t:
                        for d, nb in enumerate(b.nbr[hc]):
                            if nb == c:
                                found = d
            if found is None and ch in BULLET_OWNER:
                # A flying bullet paints its owner's colour behind it: owner paint on
                # exactly one side (and not ahead) gives the heading.
                paint = ord(PAINTS[BULLET_OWNER[ch]])
                mem = self.mem
                cands = []
                for d in range(4):
                    back = b.nbr[c][(d + 2) & 3]
                    ahead = b.nbr[c][d]
                    if back >= 0 and mem[back] == paint and (ahead < 0 or mem[ahead] != paint):
                        cands.append(d)
                if len(cands) == 1:
                    found = cands[0]
            if found is not None:
                dirs[c] = found
        self.fbullets = bullets
        self.fbullet_dirs = dirs

    def _predict_effects(self):
        """Our own paint that lands outside the view: bullet lines, bombs, fills."""
        b = self.b
        t = self.t
        add = 0
        keep = []
        for path, t0 in self.my_bullets:
            k = t - t0
            n = min(len(path), max(0, 3 * (k - 1)))
            for c in path[:n]:
                add |= b.bit[c]
            if 3 * (k - 1) < len(path) + 3:
                keep.append((path, t0))
        self.my_bullets = keep
        keepb = []
        for c, t0 in self.my_bombs:
            if t - t0 >= 3:
                disk = b.disk(c, 9) & ~self.wall & ~self.objs
                if disk & b.dilate(self.mine | b.bit[self.head]):
                    add |= disk
                self.brk &= ~disk
            else:
                keepb.append((c, t0))
        self.my_bombs = keepb
        add &= ~self.vis
        if add:
            self.mine |= add
            for k in self.enemy:
                self.enemy[k] &= ~add
        hb = b.bit[self.head]
        filled = b.holes(self.mine | hb) & ~self.wall & ~hb
        if filled:
            self.mine |= filled
            self.brk &= ~filled
            for k in self.enemy:
                self.enemy[k] &= ~filled

    def cut_off(self, lab, E2, removed=0):
        """Credible part of enemy land E2 that is no longer attached to its owner.

        The owner keeps its head's component (head seen within a tick) or else its
        largest known piece.  A piece only counts when sealed by tiles we have seen,
        otherwise it may still connect through land we never saw.
        """
        b = self.b
        if not E2:
            return 0
        known = self.seen_ever | removed
        head = self.heads.get(lab)
        if head and self.t - head[1] <= self.head_age:
            hb = b.bit[head[0]]
            near = b.dilate(hb)
            for _ in range(min(3, self.t - head[1] - 1)):
                near = b.dilate(near)          # it may have moved a step or three since
            kept = b.flood(near & E2, E2)
            if b.ring(kept | hb) & ~known:
                return 0
            return E2 & ~kept
        comps = []
        rest = E2
        while rest and len(comps) < 12:
            low = rest & -rest
            comp = b.flood(low, rest)
            rest &= ~comp
            comps.append(comp)
        if rest:
            comps.append(rest)
        big = max(comps, key=popcount)
        out = 0
        for comp in comps:
            if comp is not big and not (b.ring(comp) & ~known):
                out |= comp
        return out

    def _resolve_steals(self, before):
        """Enemy land we just took a bite of: book the credible cut-off pieces our land touches."""
        b = self.b
        for lab, E in self.enemy.items():
            if not E or not (before.get(lab, 0) & self.mine):
                continue
            stolen = self.cut_off(lab, E)
            if not stolen:
                continue
            ours = b.flood(stolen & b.dilate(self.mine), stolen)
            if ours:
                self.mine |= ours
                self.enemy[lab] = E & ~ours

    def _enforce_connectivity(self):
        b = self.b
        hb = b.bit[self.head]
        comp = b.flood(hb, self.mine | hb)
        self.mine &= comp

    # ------------------------------------------------------------------
    def note_action(self, action):
        """Book-keeping when we send `action` for tick self.t."""
        self.last_action = action
        k = action[0]
        if k == 'J':
            self.dash.use(self.t)
        elif k == 'B':
            self.bomb.use(self.t)
            i, j = (int(v) for v in action[1:].split())
            self.my_bombs.append((self.b.idx(self.x + i, self.y + j), self.t))
        elif k == 'G':
            self.gun.use(self.t)
            d = KEYS.index(action[1])
            self.my_bullets.append((self.ray(self.head, d), self.t))
        elif k == 'C':
            self.build.use(self.t)

    def ray(self, start, d, stop=None, limit=N):
        """Cells a bullet / dash from `start` heading d would cross (until blocked)."""
        b = self.b
        bit = b.bit
        if stop is None:
            stop = self.wall | self.brk | self.objs
        out = []
        c = start
        for _ in range(limit):
            c = b.nbr[c][d]
            if c < 0 or bit[c] & stop:
                break
            out.append(c)
        return out
