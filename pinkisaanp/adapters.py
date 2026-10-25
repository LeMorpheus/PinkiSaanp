"""Translate engine messages into a GameView (and directions back).

Two adapters are provided:

* ``AiCupsAdapter``: the MiniAICups Paper.io protocol from References/paperio
  (pixel coordinates, cell width, sub-cell motion, nitro/slowdown/saw).
* ``GenericAdapter``: a plain grid schema for hackathon clones::

      {"width": W, "height": H, "tick": t, "max_ticks": M, "me": "p1",
       "players": [{"id": "p1", "position": [x, y], "direction": "UP",
                    "territory": [[x, y], ...], "trail": [[x, y], ...]}, ...]}

  ``players`` may also be a dict ``{id: {...}}``; ``grid``/``grid_size`` keys,
  ``{"x":..,"y":..}`` points and ``alive`` flags are accepted; a missing
  ``direction`` is inferred from the previous tick.  Set ``y_down=True`` for
  screen-style coordinates where UP decreases ``y``.
"""

import math

from .geometry import Board, DIR_NAMES
from .state import GameView, PlayerView

_DIR_LOOKUP = {'up': 0, 'u': 0, 'north': 0, 'n': 0,
               'right': 1, 'r': 1, 'east': 1, 'e': 1,
               'down': 2, 'd': 2, 'south': 2, 's': 2,
               'left': 3, 'l': 3, 'west': 3, 'w': 3}


def parse_dir(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value & 3
    return _DIR_LOOKUP.get(str(value).strip().lower())


def _pt(p):
    if isinstance(p, dict):
        return p.get('x'), p.get('y')
    return p[0], p[1]


class AiCupsAdapter:
    def __init__(self, max_tick=1500):
        self.board = None
        self.width = 30
        self.speed = 5
        self.max_tick = max_tick

    def start(self, params):
        self.width = int(params.get('width', 30))
        self.speed = int(params.get('speed', 5))
        self.board = Board(int(params.get('x_cells_count', 31)), int(params.get('y_cells_count', 31)))

    def _speed(self, bonuses):
        """Replicates game_objects/bonuses.py speed stepping (must divide width)."""
        w = self.width
        s = self.speed
        kinds = {b.get('type') for b in bonuses or ()}
        if 'n' in kinds:
            while s < w:
                s += 1
                if w % s == 0:
                    break
        if 's' in kinds:
            while s > 1:
                s -= 1
                if w % s == 0:
                    break
        return s

    def _cell(self, v):
        return (v - self.width // 2) / float(self.width)

    def view(self, params):
        if self.board is None:
            self.start({})
        b = self.board
        players = params.get('players', {})
        me_raw = players.get('i')
        if me_raw is None:
            return None
        my_speed = self._speed(me_raw.get('bonuses'))
        views = []
        me_view = None
        for pid, raw in players.items():
            is_me = pid == 'i'
            px, py = raw['position']
            fx, fy = self._cell(px), self._cell(py)
            d = parse_dir(raw.get('direction'))
            spd = self._speed(raw.get('bonuses'))
            lag = 0.0
            if abs(fx - round(fx)) < 1e-9 and abs(fy - round(fy)) < 1e-9:
                hx, hy = int(round(fx)), int(round(fy))
            else:  # between cells: the head is the cell it is entering
                if d == 1:
                    hx, hy = math.ceil(fx), int(round(fy))
                elif d == 3:
                    hx, hy = math.floor(fx), int(round(fy))
                elif d == 0:
                    hx, hy = int(round(fx)), math.ceil(fy)
                else:
                    hx, hy = int(round(fx)), math.floor(fy)
                lag = (abs(hx - fx) + abs(hy - fy)) * my_speed / float(spd)
            hx = min(max(hx, 0), b.w - 1)
            hy = min(max(hy, 0), b.h - 1)
            terr = b.mask(self._idx(p) for p in raw.get('territory', ()))
            trail = [self._idx(p) for p in raw.get('lines', ())]
            pv = PlayerView(pid, b.idx(hx, hy), d, trail, terr, b,
                            speed=spd / float(my_speed), lag=lag,
                            score=raw.get('score', 0), is_me=is_me,
                            bonuses={x.get('type'): x.get('ticks') for x in raw.get('bonuses', ())})
            if is_me:
                me_view = pv
            else:
                views.append(pv)
        tick = int(params.get('tick_num', 0))
        steps_left = (self.max_tick - tick) * my_speed / float(self.width)
        bonuses = []
        for bo in params.get('bonuses', ()):
            x, y = bo['position']
            bonuses.append((self._idx((x, y)), bo.get('type')))
        return GameView(b, me_view, views, tick=tick, steps_left=steps_left, bonuses=bonuses)

    def _idx(self, p):
        x, y = _pt(p)
        w = self.width
        cx = int(round((x - w // 2) / float(w)))
        cy = int(round((y - w // 2) / float(w)))
        b = self.board
        return min(max(cy, 0), b.h - 1) * b.w + min(max(cx, 0), b.w - 1)

    @staticmethod
    def command(direction):
        return DIR_NAMES[direction]


class GenericAdapter:
    def __init__(self, y_down=False, upper=True):
        self.y_down = y_down
        self.upper = upper
        self.board = None
        self._last_heads = {}

    def _size(self, s):
        if 'width' in s and 'height' in s:
            return int(s['width']), int(s['height'])
        g = s.get('grid') or s.get('grid_size') or s.get('size')
        if isinstance(g, dict):
            return int(g.get('width', g.get('w'))), int(g.get('height', g.get('h')))
        return int(g[0]), int(g[1])

    def view(self, s):
        w, h = self._size(s)
        if self.board is None or self.board.w != w or self.board.h != h:
            self.board = Board(w, h)
        b = self.board
        me_id = next((s[k] for k in ('me', 'you', 'my_id', 'self', 'player_id') if k in s), None)
        raw_players = s.get('players', [])
        if isinstance(raw_players, dict):
            items = [(k, v) for k, v in raw_players.items()]
        else:
            items = [(p.get('id', p.get('name', i)), p) for i, p in enumerate(raw_players)]
        me_view = None
        others = []
        for pid, p in items:
            if p.get('alive', True) is False:
                continue
            pos = p.get('position', p.get('head', p.get('pos')))
            x, y = _pt(pos)
            head = self._idx(x, y)
            terr = b.mask(self._idx(*_pt(q)) for q in p.get('territory', ()))
            trail = [self._idx(*_pt(q)) for q in p.get('trail', p.get('lines', ()))]
            d = parse_dir(p.get('direction', p.get('dir')))  # names survive the y flip
            if d is None:  # engine does not report headings: infer from last tick
                prev = self._last_heads.get(str(pid))
                if prev is not None and prev != head:
                    d = next((k for k, n in enumerate(b.nbr[prev]) if n == head), None)
            self._last_heads[str(pid)] = head
            pv = PlayerView(pid, head, d, trail, terr, b, score=p.get('score', 0),
                            is_me=str(pid) == str(me_id))
            if pv.is_me:
                me_view = pv
            else:
                others.append(pv)
        if me_view is None:
            raise ValueError('state does not identify our player (key "me")')
        # Engines differ on whether the head is part of the trail; normalise to
        # "head is the newest trail cell whenever we are outside territory".
        for pv in [me_view] + others:
            if not (b.bit[pv.head] & pv.terr) and (not pv.trail or pv.trail[-1] != pv.head):
                pv.trail.append(pv.head)
                pv.trail_mask |= b.bit[pv.head]
        tick = int(s.get('tick', s.get('turn', 0)))
        max_ticks = s.get('max_ticks', s.get('max_turns'))
        steps_left = (int(max_ticks) - tick) if max_ticks is not None else None
        bonuses = []
        for bo in s.get('bonuses', ()):
            bx, by = _pt(bo.get('position', bo))
            bonuses.append((self._idx(bx, by), bo.get('type')))
        return GameView(b, me_view, others, tick=tick, steps_left=steps_left, bonuses=bonuses)

    def _idx(self, x, y):
        b = self.board
        x = int(x)
        y = int(y)
        if self.y_down:
            y = b.h - 1 - y
        return min(max(y, 0), b.h - 1) * b.w + min(max(x, 0), b.w - 1)

    def command(self, direction):
        name = DIR_NAMES[direction]
        return name.upper() if self.upper else name
