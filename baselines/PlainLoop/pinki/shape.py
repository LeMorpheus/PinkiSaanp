"""Territory shape: which part of our land a single cut could take away.

A cut (bomb disk, wall, bullet line, enemy step) always leaves us the part
still connected to our head and hands the rest to the cutter.  Necks narrower
than a bomb disk (7 cells) vanish when the land is eroded by 3, so the
components of that core are the blobs one bomb cannot split.  Keeping the
head in (and growing) the heaviest blob means a cut costs the light side.
"""

from .board import popcount


def erode(b, m):
    s = b.stride
    return m & (m << 1) & (m >> 1) & (m << s) & (m >> s)


def dilate_in(b, m, k, within):
    for _ in range(k):
        m = b.dilate(m) & within
    return m


class Shape:
    __slots__ = ('blobs', 'heavy', 'head_blob', 'area')

    def __init__(self, blobs, heavy, head_blob, area):
        self.blobs = blobs              # list of (mass, region, core)
        self.heavy = heavy              # index of the heaviest blob or None
        self.head_blob = head_blob      # index of the blob the head hangs on, or None
        self.area = area

    def at_risk(self):
        """Mass we would lose if the head's link to the heavy blob were cut."""
        if self.heavy is None or self.head_blob == self.heavy:
            return 0
        hm = self.blobs[self.head_blob][0] if self.head_blob is not None else 0
        return self.blobs[self.heavy][0] - hm


def analyse(b, mine, head_bit, k=3, min_core=6, max_blobs=10, reach=40):
    M = mine | head_bit
    area = popcount(mine)
    core = M
    for _ in range(k):
        core = erode(b, core)
    blobs = []
    rest = core
    guard = 0
    while rest and guard < 40 and len(blobs) < max_blobs:
        guard += 1
        low = rest & -rest
        comp = b.flood(low, rest)
        rest &= ~comp
        if popcount(comp) < min_core:
            continue
        region = dilate_in(b, comp, k, M)
        blobs.append((popcount(region & mine), region, comp))
    if not blobs:
        return Shape([], None, None, area)
    heavy = max(range(len(blobs)), key=lambda i: blobs[i][0])
    head_blob = None
    for i, (_, region, _) in enumerate(blobs):
        if region & head_bit:
            head_blob = i
            break
    if head_blob is None:
        # Head on a thin strip: the first blob reached through our land.
        front = head_bit
        for _ in range(reach):
            front = b.dilate(front) & M
            hit = [i for i, bl in enumerate(blobs) if bl[1] & front]
            if hit:
                head_blob = max(hit, key=lambda i: blobs[i][0])
                break
    return Shape(blobs, heavy, head_blob, area)


def bfs_path(b, src, targets, passable, limit=150):
    """Shortest 4-path (cells, excluding src) from cell src into the target mask."""
    bit = b.bit
    sb = bit[src]
    if sb & targets:
        return []
    layers = [sb]
    seen = sb
    cur = sb
    hit = 0
    for _ in range(limit):
        nxt = b.dilate(cur) & passable & ~seen
        if not nxt:
            return None
        seen |= nxt
        layers.append(nxt)
        cur = nxt
        hit = nxt & targets
        if hit:
            break
    if not hit:
        return None
    c = b.cells(hit & -hit)[0]
    path = [c]
    nbr = b.nbr
    for k in range(len(layers) - 2, 0, -1):
        lay = layers[k]
        for n in nbr[c]:
            if n >= 0 and bit[n] & lay:
                c = n
                break
        else:
            return None
        path.append(c)
    path.reverse()
    return path


def dist_sum(b, src_bit, M, cap=160):
    """Sum of 4-path distances from src to every cell of M (unreached cells cost cap)."""
    seen = cur = src_bit & M
    if not cur:
        return None
    total = 0
    k = 0
    while cur and k < cap:
        k += 1
        cur = b.dilate(cur) & M & ~seen
        seen |= cur
        total += k * popcount(cur)
    return total + cap * popcount(M & ~seen)


def central_cell(b, M, start, rounds=6):
    """Approximate graph median of M (where a random cut leaves us the most), by local search."""
    bit = b.bit
    w = b.w
    if not M:
        return None
    best = start if bit[start] & M else b.cells(M & -M)[0]
    best_v = dist_sum(b, bit[best], M)
    step = 8
    for _ in range(rounds):
        x, y = best % w, best // w
        improved = False
        for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < b.h):
                continue
            c = ny * w + nx
            if not bit[c] & M:
                continue
            v = dist_sum(b, bit[c], M)
            if v is not None and v < best_v:
                best, best_v, improved = c, v, True
        if not improved:
            if step == 1:
                break
            step = max(1, step // 2)
    return best


def neck_cut(b, M, head_bit, narrow=4, max_layers=150, min_far=150):
    """BFS layers from the head through M are vertex cuts.  Find the narrow layer (<= narrow
    cells) leaving the most mass beyond it compared with the head's side.

    Returns (excess, depth, layers) or None; layers[k] is the mask at distance k + 1.
    """
    layers = []
    sizes = []
    seen = cur = head_bit
    while len(layers) < max_layers:
        cur = b.dilate(cur) & M & ~seen
        if not cur:
            break
        seen |= cur
        layers.append(cur)
        sizes.append(popcount(cur))
    total = sum(sizes)
    before = 0
    best = None
    for d, n in enumerate(sizes):
        after = total - before - n
        if n <= narrow and after >= min_far and after > before + n:
            excess = after - before - n
            if best is None or excess > best[0]:
                best = (excess, d)
        before += n
    if best is None:
        return None
    return best[0], best[1], layers


def path_down_layers(b, layers, target_depth, head):
    """Walk from a cell of layers[target_depth] back to the head along decreasing depth."""
    bit = b.bit
    nbr = b.nbr
    lay = layers[target_depth]
    c = b.cells(lay & -lay)[0]
    path = [c]
    for k in range(target_depth - 1, -1, -1):
        for n in nbr[c]:
            if n >= 0 and bit[n] & layers[k]:
                c = n
                break
        else:
            return None
        path.append(c)
    path.reverse()
    if head not in nbr[path[0]]:
        return None
    return path
