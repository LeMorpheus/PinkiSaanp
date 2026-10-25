"""Bitboard grid (PinkiSaanp core, y-down frame of the Codewars view).

Cell sets are Python ints.  Row y occupies bits [y*S, y*S + W) with stride
S = W + 1; the always-zero guard column stops horizontal shifts from wrapping.
"""

W, A, S, D = 0, 1, 2, 3          # up, left, down, right (view frame)
DX = (0, -1, 0, 1)
DY = (-1, 0, 1, 0)
KEYS = 'WASD'
OPP = (2, 3, 0, 1)
INF = 1 << 30

try:
    popcount = int.bit_count
except AttributeError:  # pragma: no cover
    def popcount(m):
        return bin(m).count('1')


def _los_table(r=4):
    """Tiles strictly between our tile and offset (i, j) that the centre-to-centre segment
    touches (closed squares: a pass through a corner counts both side tiles)."""
    table = {}
    for j in range(-r, r + 1):
        for i in range(-r, r + 1):
            if not 0 < i * i + j * j <= r * r:
                continue
            cells = []
            for cy in range(min(0, j), max(0, j) + 1):
                for cx in range(min(0, i), max(0, i) + 1):
                    if (cx, cy) in ((0, 0), (i, j)):
                        continue
                    s = [2 * i * (2 * cy + ey) - 2 * j * (2 * cx + ex) for ex in (-1, 1) for ey in (-1, 1)]
                    if all(v > 0 for v in s) or all(v < 0 for v in s):
                        continue
                    cells.append((cx, cy))
            table[(i, j)] = tuple(cells)
    return table


LOS_TABLE = _los_table()


class Board:
    __slots__ = ('w', 'h', 'n', 'stride', 'bit', 'p2i', 'full', 'border', 'nbr', '_disk')

    def __init__(self, w, h):
        # Startup time counts against the first move: keep this to a few ms.
        self.w, self.h = w, h
        self.n = n = w * h
        self.stride = s = w + 1
        self.bit = [1 << p for y in range(0, s * h, s) for p in range(y, y + w)]
        p2i = [-1] * (s * h)
        for y in range(h):
            p2i[y * s:y * s + w] = range(y * w, y * w + w)
        self.p2i = p2i
        row = (1 << w) - 1
        edges = 1 | (1 << (w - 1))
        full = border = 0
        for y in range(h):
            full |= row << (y * s)
            border |= (row if y == 0 or y == h - 1 else edges) << (y * s)
        up = [i - w for i in range(n)]
        up[:w] = [-1] * w
        down = [i + w for i in range(n)]
        down[n - w:] = [-1] * w
        left = [i - 1 for i in range(n)]
        left[::w] = [-1] * h
        right = [i + 1 for i in range(n)]
        right[w - 1::w] = [-1] * h
        self.full, self.border = full, border
        self.nbr = list(zip(up, left, down, right))
        self._disk = {}

    def los(self, x0, y0, x1, y1, stop):
        """Build/throw line of sight from tile (x0, y0) to (x1, y1): no `stop` tile in between."""
        cells = LOS_TABLE.get((x1 - x0, y1 - y0))
        if cells is None:
            return False
        w, h, bit = self.w, self.h, self.bit
        for dx, dy in cells:
            x, y = x0 + dx, y0 + dy
            if not (0 <= x < w and 0 <= y < h) or bit[y * w + x] & stop:
                return False
        return True

    def idx(self, x, y):
        return y * self.w + x

    def inside(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def mask(self, cells):
        bit = self.bit
        m = 0
        for c in cells:
            m |= bit[c]
        return m

    def cells(self, m):
        if not m:
            return []
        p2i = self.p2i
        s = bin(m)[:1:-1]
        out = []
        find = s.find
        i = find('1')
        while i != -1:
            out.append(p2i[i])
            i = find('1', i + 1)
        return out

    def dilate(self, m):
        s = self.stride
        return (m | (m << 1) | (m >> 1) | (m << s) | (m >> s)) & self.full

    def ring(self, m):
        """4-neighbours of m that are not in m."""
        return self.dilate(m) & ~m

    def flood(self, seed, passable):
        s = self.stride
        cur = seed & passable
        while True:
            nxt = (cur | (cur << 1) | (cur >> 1) | (cur << s) | (cur >> s)) & passable
            if nxt == cur:
                return cur
            cur = nxt

    def holes(self, area):
        """Cells the engine fills when `area` (incl. head) encloses them."""
        free = self.full & ~area
        return free & ~self.flood(self.border & free, free)

    def distance_field(self, seed, passable, limit=INF):
        dist = [INF] * self.n
        s = self.stride
        cur = frontier = seed
        k = 0
        cells = self.cells
        while frontier and k <= limit:
            for i in cells(frontier):
                dist[i] = k
            nxt = (cur | (cur << 1) | (cur >> 1) | (cur << s) | (cur >> s)) & passable
            frontier = nxt & ~cur
            cur |= nxt
            k += 1
        return dist

    def disk(self, c, r2):
        key = (c, r2)
        m = self._disk.get(key)
        if m is None:
            w, h = self.w, self.h
            x0, y0 = c % w, c // w
            m = 0
            r = int(r2 ** 0.5)
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if dx * dx + dy * dy <= r2 and 0 <= x0 + dx < w and 0 <= y0 + dy < h:
                        m |= self.bit[(y0 + dy) * w + x0 + dx]
            self._disk[key] = m
        return m
