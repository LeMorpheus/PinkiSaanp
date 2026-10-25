"""Head-isolation tactics: the decisive mechanic of this game.

Our area is whatever stays 4-connected to our head; everything else is lost
(to whoever caused it).  So a single breakable wall on the only own tile next
to a head, or a bomb whose radius-3 disk covers all four neighbours of a head,
wipes out a whole territory.  This module both exploits and evades that.
"""

from .board import DX, DY, INF, KEYS, popcount

# Head offsets (relative to a bomb centre) whose four neighbours all lie in the
# radius-3 blast: the diamond |dx|+|dy| <= 2.
KILL_ZONE = [(dx, dy) for dx in range(-2, 3) for dy in range(-2, 3) if abs(dx) + abs(dy) <= 2]
ENEMY_BOMBS = None


class Tactics:
    def __init__(self, world, planner, avoid=0):
        self.w = world
        self.b = world.b
        self.p = planner
        w = world
        b = self.b
        self.block = w.wall | w.brk | w.objs
        self.move_block = self.block | avoid     # also tiles where our moves keep failing
        self.heads = {}
        for lab, (cell, ts) in w.heads.items():
            if ts == w.t:
                self.heads[lab] = cell

    # ------------------------------------------------------------------
    def own_neighbours(self, cell, mask):
        bit = self.b.bit
        return [n for n in self.b.nbr[cell] if n >= 0 and bit[n] & mask]

    def los(self, x0, y0, x1, y1):
        """Build line of sight: no object on tiles crossed between tile centres."""
        return self.b.los(x0, y0, x1, y1, self.block)

    def can_build(self, cell):
        w = self.w
        b = self.b
        x, y = cell % b.w, cell // b.w
        i, j = x - w.x, y - w.y
        if not (0 < i * i + j * j <= 16):
            return None
        if b.bit[cell] & self.block or w.no_build.get(cell, -1) >= w.t:
            return None
        if not self.los(w.x, w.y, x, y):
            return None
        return i, j

    # ------------------------------------------------------------------
    def wall_kill(self):
        """Wall the only own tile next to a visible enemy head: it loses everything."""
        w = self.w
        if not w.build.ready(w.t):
            return None
        best = None
        for lab, h in self.heads.items():
            E = w.enemy.get(lab, 0)
            nb = self.own_neighbours(h, E)
            if len(nb) != 1:
                continue
            cell = nb[0]
            if self.b.bit[cell] & w.mine:
                continue
            ij = self.can_build(cell)
            if ij is None:
                continue
            value = popcount(E) + 50
            if best is None or value > best[0]:
                best = (value, ij)
        if best is None:
            return None
        return 'C %d %d' % best[1]

    def bomb_kill(self):
        """Bomb that will cover every neighbour of an enemy head when it blows."""
        w = self.w
        b = self.b
        if not w.bomb.ready(w.t):
            return None
        best = None
        hb = b.bit[w.head]
        for lab, h in self.heads.items():
            hx, hy = h % b.w, h // b.w
            d = w.head_dirs.get(lab)
            preds = [(h, 0.25)]
            if d is not None:
                c = h
                for k, p in ((1, 0.2), (2, 0.25), (3, 0.3)):
                    c2 = b.nbr[c][d]
                    if c2 < 0 or b.bit[c2] & self.block:
                        break
                    c = c2
                    preds.append((c, p))
            for j in range(-4, 5):
                for i in range(-4, 5):
                    if not (0 < i * i + j * j <= 16):
                        continue
                    cx, cy = w.x + i, w.y + j
                    if not (0 <= cx < b.w and 0 <= cy < b.h):
                        continue
                    c = cy * b.w + cx
                    if b.bit[c] & self.block:
                        continue
                    # never trap ourselves: our own neighbours must survive
                    if abs(cx - w.x) + abs(cy - w.y) <= 2 and not self._disk_connected(c):
                        continue
                    score = 0.0
                    for p, pr in preds:
                        px, py = p % b.w, p // b.w
                        if (px, py) != (cx, cy) and abs(px - cx) + abs(py - cy) <= 2:
                            score += pr
                    if score >= 0.45 and (best is None or score > best[0]):
                        best = (score, i, j)
        if best is None:
            return None
        return 'B %d %d' % (best[1], best[2])

    def _disk_connected(self, c):
        w = self.w
        b = self.b
        disk = b.disk(c, 9) & ~w.wall & ~w.objs
        return bool(disk & b.dilate(w.mine))

    def block_bullets(self):
        """Build a wall in front of an enemy bullet whose path would cut our land."""
        w = self.w
        b = self.b
        M = w.mine
        if not M or not w.fbullet_dirs:
            return None
        can_wall = w.build.ready(w.t)
        hb = b.bit[w.head]
        total = popcount(M)
        best = None
        for c, d in w.fbullet_dirs.items():
            path = w.ray(c, d, stop=w.wall | w.brk | (w.objs & ~b.bit[c]))
            first = next((k for k, p in enumerate(path) if b.bit[p] & M), None)
            if first is None:
                continue
            A2 = M & ~b.mask(path)
            kept = b.flood(b.dilate(hb) & A2, A2)
            loss = total - popcount(kept)
            if loss < 25:
                continue
            placed = False
            for k in range(first - 1, 0, -1) if can_wall else ():
                ij = self.can_build(path[k])
                if ij is not None:
                    if best is None or loss > best[0]:
                        best = (loss, 'C %d %d' % ij)
                    placed = True
                    break
            if not placed:
                # Body-block: a head on the bullet's next tiles breaks it.
                for d, n in enumerate(b.nbr[w.head]):
                    if n >= 0 and n in path[:3] and not (b.bit[n] & self.move_block):
                        if best is None or loss > best[0]:
                            best = (loss, KEYS[d])
                        break
        if best is None:
            return None
        return best[1]

    # ------------------------------------------------------------------
    def kept_after(self, head_cell, area, removed, cap=80):
        """Size of our part still attached to head_cell once `removed` is gone (capped flood)."""
        b = self.b
        s = b.stride
        A = area & ~removed
        cur = b.dilate(b.bit[head_cell]) & A
        for _ in range(cap):
            nxt = (cur | (cur << 1) | (cur >> 1) | (cur << s) | (cur >> s)) & A
            if nxt == cur:
                return popcount(cur)
            cur = nxt
        return popcount(A)     # still growing after cap steps: treat as the big side

    def enemy_rays(self):
        """Bullet paths visible enemy heads could fire now (weight 1) or after one step (0.5)."""
        w = self.w
        b = self.b
        bit = b.bit
        out = []
        for lab, e in self.heads.items():
            starts = [(e, 1.0)]
            for n in b.nbr[e]:
                if n >= 0 and not (bit[n] & self.block):
                    starts.append((n, 0.5))
            for s, wt in starts:
                for d in range(4):
                    first = b.nbr[s][d]
                    if first < 0 or bit[first] & self.block:
                        continue
                    path = w.ray(s, d)
                    if path:
                        out.append((path, b.mask(path), wt))
        return out

    def dodge_lines(self, preferred):
        """Step so a bullet from a visible enemy head cannot cut us off from our bulk."""
        w = self.w
        b = self.b
        bit = b.bit
        M = w.mine
        if not M or not self.heads:
            return None
        h = w.head
        area = popcount(M)
        rays = [ray for ray in self.enemy_rays() if ray[1] & M]
        if not rays:
            return None
        options = [('I', h, M)]
        for d in range(4):
            n = b.nbr[h][d]
            if n >= 0 and not (bit[n] & self.move_block):
                options.append((KEYS[d], n, M | bit[h]))

        def risk(cell, A):
            worst = 0.0
            for path, r, wt in rays:
                if bit[cell] & r:     # our head stops the bullet: only the stretch before us paints
                    r = b.mask(path[:path.index(cell)])
                    if not r & A:
                        continue
                loss = (popcount(A) - self.kept_after(cell, A, r)) * wt
                if loss > worst:
                    worst = loss
            return worst

        cur = next((o for o in options if o[0] == preferred), options[0])
        base = risk(cur[1], cur[2])
        if base < max(120, 0.15 * area):
            return None
        best = (base, cur[0])
        for act, cell, A in options:
            if act == cur[0]:
                continue
            r = risk(cell, A)
            if r < best[0] - 1:
                best = (r, act)
        if best[1] == cur[0] or base - best[0] < max(80, 0.1 * area):
            return None
        return best[1]

    # ------------------------------------------------------------------
    def lane_plug(self, radius=6, min_loss=150, frac=0.15, avoid=0):
        """Wall off a bullet lane that could cut our land, where it leaves our land.

        Bullets fly along wall-free row/column segments ("lanes", at most 39 long on
        this map) and are fired from a free cell of the same lane.  A lane whose
        cells inside our land would split it, and which has open cells outside our
        land, is plugged with a wall on the outside cell next to our land.
        """
        w = self.w
        b = self.b
        bit = b.bit
        M = w.mine
        if not M:
            return None
        n = b.w
        hx, hy = w.x, w.y
        stop = w.wall | w.brk
        area = popcount(M)
        need = max(min_loss, frac * area)
        best = None
        lines = [(0, y) for y in range(max(0, hy - radius), min(n, hy + radius + 1))] + \
                [(1, x) for x in range(max(0, hx - radius), min(n, hx + radius + 1))]
        for axis, k in lines:
            cells = [k * n + i for i in range(n)] if axis == 0 else [i * n + k for i in range(n)]
            seg = []
            for c in cells + [-1]:
                if c >= 0 and not (bit[c] & stop):
                    seg.append(c)
                    continue
                if len(seg) >= 3:
                    best = self._plug_segment(seg, M, area, need, best, avoid)
                seg = []
        if best is None:
            return None
        return 'C %d %d' % best[1]

    def _plug_segment(self, seg, M, area, need, best, avoid):
        b = self.b
        bit = b.bit
        inside = [i for i, c in enumerate(seg) if bit[c] & M]
        if not inside or len(inside) == len(seg):
            return best
        lane = b.mask(seg[inside[0]:inside[-1] + 1]) & M
        loss = area - self.kept_after(self.w.head, M, lane, cap=60)
        if loss < need or (best is not None and loss <= best[0]):
            return best
        # Plug spots: the open lane cells just outside our first and last run.
        spots = []
        if inside[0] > 0:
            spots.append(seg[inside[0] - 1])
        if inside[-1] < len(seg) - 1:
            spots.append(seg[inside[-1] + 1])
        for c in spots:
            if bit[c] & (M | avoid):
                continue
            ij = self.can_build(c)
            if ij is not None:
                return (loss, ij)
        return best

    # ------------------------------------------------------------------
    def enemy_bombs(self):
        """Visible enemy bombs as (cell, first_seen_t)."""
        return [(c, t0) for c, t0 in self.w.foreign_bombs.items()]

    def retained_after(self, head_cell, area, blasts):
        """Our area still connected to `head_cell` after the given blast disks."""
        b = self.b
        A = area
        for disk in blasts:
            A &= ~disk
        hb = b.bit[head_cell]
        comp = b.flood(b.dilate(hb) & A, A)
        return popcount(comp)

    def dodge_split(self, preferred):
        """A visible enemy bomb will split our land: walk (<= 2 cells, through our land) to the big side."""
        w = self.w
        b = self.b
        bit = b.bit
        M = w.mine
        bombs = self.enemy_bombs()
        if not bombs or not M:
            return None
        blast = 0
        for c, _ in bombs:
            blast |= b.disk(c, 9) & ~w.wall
        if not blast & M:
            return None
        area = popcount(M)
        h = w.head
        here = self.kept_after(h, M, blast)
        if area - here < max(150, 0.15 * area):
            return None
        # Cells within two steps through our land (outside the blast), first step remembered.
        best = (here, None)
        seen = {h}
        frontier = []
        for d, n in enumerate(b.nbr[h]):
            if n >= 0 and bit[n] & M and not bit[n] & (self.move_block | blast):
                frontier.append((n, d))
                seen.add(n)
        for depth in range(2):
            nxt = []
            for c, d0 in frontier:
                k = self.kept_after(c, M | bit[h], blast)
                if k > best[0] + 50:
                    best = (k, d0)
                if depth == 0:
                    for n in b.nbr[c]:
                        if n >= 0 and n not in seen and bit[n] & M and not bit[n] & (self.move_block | blast):
                            seen.add(n)
                            nxt.append((n, d0))
            frontier = nxt
        if best[1] is None:
            return None
        return KEYS[best[1]]

    def evade(self, preferred):
        """If enemy bombs threaten to isolate us, pick the move keeping most area."""
        w = self.w
        b = self.b
        bombs = self.enemy_bombs()
        if not bombs:
            return None
        blasts = [b.disk(c, 9) & ~w.wall for c, _ in bombs]
        near = 0
        for disk in blasts:
            near |= disk
        if not (b.dilate(b.bit[w.head]) & near):
            return None
        area = w.mine
        options = [('I', w.head, area)]
        for d in range(4):
            n = b.nbr[w.head][d]
            if n >= 0 and not (b.bit[n] & self.move_block):
                options.append((KEYS[d], n, area | b.bit[w.head]))
            if w.dash.ready(w.t):
                c = w.head
                trail = b.bit[w.head]
                for _ in range(3):
                    c2 = b.nbr[c][d]
                    if c2 < 0 or b.bit[c2] & self.block:
                        break
                    trail |= b.bit[c]
                    c = c2
                if c != w.head:
                    options.append(('J' + KEYS[d], c, area | trail))
        scored = []
        for act, cell, A in options:
            r = self.retained_after(cell, A, blasts)
            scored.append((r, act == preferred, act))
        scored.sort(reverse=True)
        best = scored[0]
        current = next((s for s in scored if s[2] == preferred), None)
        if current is not None and current[0] >= best[0] - 2:
            return None
        return best[2]

    # ------------------------------------------------------------------
    def nearest_enemy(self):
        w = self.w
        b = self.b
        best = None
        for lab, (cell, ts) in w.heads.items():
            age = w.t - ts
            if age > 6:
                continue
            dist = max(abs(cell % b.w - w.x), abs(cell // b.w - w.y)) - age
            if best is None or dist < best[0]:
                best = (dist, lab, cell)
        return best

    def thin(self):
        """Our head hangs on at most one own tile (a single wall would wipe us)."""
        return len(self.own_neighbours(self.w.head, self.w.mine)) <= 1

    def retreat_step(self):
        """Step toward thick territory (>= 3 own neighbours), away from enemies."""
        w = self.w
        b = self.b
        bit = b.bit
        M = w.mine
        if not M:
            return None
        thick = M & b.dilate(M) & ~b.ring(M)
        # cells of M whose 4 neighbours are mostly ours: erode once
        s = b.stride
        core = M & (M << 1) & (M >> 1) & (M << s) & (M >> s) & b.full
        target = core if core else thick
        if not target:
            target = M
        passable = (b.full & ~self.block) | M
        dist = b.distance_field(target, passable, limit=60)
        best = None
        for d, n in enumerate(b.nbr[w.head]):
            if n < 0 or bit[n] & self.move_block:
                continue
            dd = dist[n]
            if dd >= INF:
                continue
            own = len(self.own_neighbours(n, M | bit[w.head]))
            key = (dd, -own)
            if best is None or key < best[0]:
                best = (key, d)
        if best is None:
            return None
        return KEYS[best[1]]
