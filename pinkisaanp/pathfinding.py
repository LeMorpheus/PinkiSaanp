"""Risk-aware, direction-aware A* over (cell, heading) states.

Cost of stepping onto cell ``c`` at time ``t`` (outside our territory):

    cost = 1 + W_RISK * max(0, t + h(c) - threat(c) + 1)
             + W_FLANK * flanks(c) * exp(-threat(c) / tau)

``t + h(c)`` is the earliest we could close the loop after laying ``c``
(``h`` = BFS distance home), so the risk term charges every step that leaves a
trail cell an enemy can reach before we are home.  Cells inside our territory
cost exactly 1.  ``h`` is admissible because it ignores trails and risk, so the
time component of the path is optimal and the risk component is minimised
among near-optimal paths.

Termination guarantees (the "no infinite loop" contract):
  * closed set keyed on (cell, heading): each state is expanded at most once;
  * hard cap ``max_nodes`` on expansions and an optional wall-clock deadline;
  * the no-reverse rule is enforced, and our own trail is a hard obstacle.
"""

import heapq
from time import perf_counter

from .geometry import INF, allowed_dirs

W_RISK = 6.0
W_FLANK = 0.25


def astar(an, start, start_dir, goal_mask, blocked, heuristic, t0=0,
          max_nodes=6000, deadline=None, risk=True, terr=None):
    """Return the list of cells after ``start`` ending in ``goal_mask``, or None.

    heuristic: list indexed by cell (admissible lower bound on steps to goal)
    blocked:   bitboard of hard obstacles (our trail, planned trail, ...)
    """
    b = an.board
    bit = b.bit
    nbr = b.nbr
    threat = an.threat
    dist_home = an.dist_home
    expo = an.expo
    if terr is None:
        terr = an.me.terr

    h0 = heuristic[start]
    if h0 >= INF:
        return None
    counter = 0
    heap = [(h0, 0, 0.0, t0, start, start_dir)]
    best = {(start, start_dir): 0.0}
    parent = {}
    expanded = 0
    while heap:
        f, _, g, t, cell, d = heapq.heappop(heap)
        key = (cell, d)
        if g > best.get(key, INF):
            continue
        if t > t0 and bit[cell] & goal_mask:
            path = []
            while key in parent:
                path.append(key[0])
                key = parent[key]
            path.reverse()
            return path
        expanded += 1
        if expanded > max_nodes:
            return None
        if deadline is not None and (expanded & 63) == 0 and perf_counter() > deadline:
            return None
        nt = t + 1
        for nd in allowed_dirs(d):
            nc = nbr[cell][nd]
            if nc < 0:
                continue
            bc = bit[nc]
            if bc & blocked:
                continue
            hn = heuristic[nc]
            if hn >= INF:
                continue
            step = 1.0
            if risk and not (bc & terr):
                th = threat[nc]
                if th < INF:
                    deficit = nt + dist_home[nc] - th + 1
                    if deficit > 0:
                        step += W_RISK * deficit
                    step += W_FLANK * expo[nc]
            ng = g + step
            nkey = (nc, nd)
            if ng < best.get(nkey, INF):
                best[nkey] = ng
                parent[nkey] = key
                counter += 1
                heapq.heappush(heap, (ng + hn, counter, ng, nt, nc, nd))
    return None


def manhattan_field(board, target):
    """Heuristic list for a single target cell."""
    w = board.w
    tx, ty = target % w, target // w
    return [abs(i % w - tx) + abs(i // w - ty) for i in range(board.n)]
