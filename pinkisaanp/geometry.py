"""Bitboard grid geometry for PinkiSaanp.

Every set of cells (territory, trail, reach region, ...) is a Python int used
as a bitboard.  Row ``y`` occupies bits ``[y*S, y*S + W)`` where the stride
``S = W + 1`` leaves one always-zero guard column per row, so horizontal
shifts never wrap into the neighbouring row.  A full-grid flood fill is ~9us
with this layout versus ~550us with a Python-level BFS, which is what lets the
planner score hundreds of candidate loops every tick.

Internal coordinates: ``x`` grows RIGHT, ``y`` grows UP (the reference
MiniAICups convention).  Adapters flip ``y`` for screen-style engines.
"""

UP, RIGHT, DOWN, LEFT = 0, 1, 2, 3
DIRS = (UP, RIGHT, DOWN, LEFT)
DIR_NAMES = ('up', 'right', 'down', 'left')
DX = (0, 1, 0, -1)
DY = (1, 0, -1, 0)
INF = 1 << 30

try:
    popcount = int.bit_count  # Python >= 3.10
except AttributeError:  # pragma: no cover - older interpreters
    def popcount(m):
        return bin(m).count('1')


def reverse(d):
    return None if d is None else (d + 2) & 3


_ALLOWED = {None: DIRS}
for _d in DIRS:
    _ALLOWED[_d] = tuple(x for x in DIRS if x != (_d + 2) & 3)


def allowed_dirs(d):
    """Directions the engine accepts next tick (reversal is ignored by servers)."""
    return _ALLOWED[d]


class Board:
    __slots__ = ('w', 'h', 'n', 'stride', 'bit', 'pos2idx', 'full', 'border',
                 'nbr', 'open_sides')

    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.n = n = w * h
        self.stride = s = w + 1
        self.bit = [1 << ((i // w) * s + (i % w)) for i in range(n)]
        self.pos2idx = [-1] * (s * h)
        full = 0
        border = 0
        for i in range(n):
            x, y = i % w, i // w
            self.pos2idx[y * s + x] = i
            full |= self.bit[i]
            if x == 0 or y == 0 or x == w - 1 or y == h - 1:
                border |= self.bit[i]
        self.full = full
        self.border = border
        nbr = []
        open_sides = []
        for i in range(n):
            x, y = i % w, i // w
            row = []
            for d in DIRS:
                nx, ny = x + DX[d], y + DY[d]
                row.append(ny * w + nx if 0 <= nx < w and 0 <= ny < h else -1)
            nbr.append(tuple(row))
            open_sides.append(sum(1 for c in row if c >= 0))
        self.nbr = nbr
        # Number of non-wall sides of a cell: the wall-hugging signal.
        self.open_sides = open_sides

    # -- coordinates -----------------------------------------------------
    def idx(self, x, y):
        return y * self.w + x

    def xy(self, i):
        return i % self.w, i // self.w

    def inside(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def manhattan(self, a, b):
        w = self.w
        return abs(a % w - b % w) + abs(a // w - b // w)

    # -- bitboard primitives ---------------------------------------------
    def mask(self, cells):
        bit = self.bit
        m = 0
        for c in cells:
            m |= bit[c]
        return m

    def cells(self, m):
        """Decode a bitboard into a list of cell indices (fast for dense masks)."""
        if not m:
            return []
        p2i = self.pos2idx
        s = bin(m)[:1:-1]  # LSB first, without the '0b' prefix
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

    def flood(self, seed, passable):
        """All cells of ``passable`` 4-connected to ``seed`` (seed clipped to passable)."""
        s = self.stride
        cur = seed & passable
        while True:
            nxt = (cur | (cur << 1) | (cur >> 1) | (cur << s) | (cur >> s)) & passable
            if nxt == cur:
                return cur
            cur = nxt

    def distance_field(self, seed, passable, limit=INF):
        """Multi-source BFS distances (list, INF where unreachable)."""
        dist = [INF] * self.n
        s = self.stride
        cur = seed
        frontier = seed
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

    def reach_layers(self, head, direction, passable, kmax):
        """Cumulative reach sets: ``layers[k]`` = cells reachable within k moves.

        The first move honours the no-reverse rule; later moves are relaxed
        to plain dilation, which over-approximates reach (conservative when
        the layers model an opponent's threat).
        """
        bit = self.bit
        s = self.stride
        l0 = bit[head]
        first = 0
        for d in allowed_dirs(direction):
            c = self.nbr[head][d]
            if c >= 0 and bit[c] & passable:
                first |= bit[c]
        cur = l0 | first
        layers = [l0, cur]
        for _ in range(2, kmax + 1):
            nxt = ((cur | (cur << 1) | (cur >> 1) | (cur << s) | (cur >> s)) & passable) | cur
            if nxt == cur:
                break
            layers.append(nxt)
            cur = nxt
        return layers

    def capture(self, terr, trail, wall_encloses=False):
        """Cells gained when ``trail`` closes onto ``terr``: trail + enclosed pockets.

        Standard Paper.io semantics: a free region is enclosed when it is not
        4-connected to the map edge.  With ``wall_encloses`` the arena edge
        counts as a fence and every free component except the largest is taken.
        """
        free = self.full & ~(terr | trail)
        if not wall_encloses:
            outside = self.flood(self.border & free, free)
            return (trail | (free & ~outside)) & ~terr
        enclosed = 0
        biggest = 0
        rest = free
        while rest:
            low = rest & -rest
            comp = self.flood(low, rest)
            rest &= ~comp
            if popcount(comp) > popcount(biggest):
                enclosed |= biggest
                biggest = comp
            else:
                enclosed |= comp
        return (trail | enclosed) & ~terr
