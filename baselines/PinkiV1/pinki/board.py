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


class Board:
    __slots__ = ('w', 'h', 'n', 'stride', 'bit', 'p2i', 'full', 'border', 'nbr', '_disk')

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.n = n = w * h
        self.stride = s = w + 1
        self.bit = [1 << ((i // w) * s + i % w) for i in range(n)]
        self.p2i = [-1] * (s * h)
        full = border = 0
        nbr = []
        for i in range(n):
            x, y = i % w, i // w
            self.p2i[y * s + x] = i
            b = self.bit[i]
            full |= b
            if x == 0 or y == 0 or x == w - 1 or y == h - 1:
                border |= b
            nbr.append(tuple((y + DY[d]) * w + x + DX[d]
                             if 0 <= x + DX[d] < w and 0 <= y + DY[d] < h else -1
                             for d in range(4)))
        self.full, self.border, self.nbr = full, border, nbr
        self._disk = {}

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
