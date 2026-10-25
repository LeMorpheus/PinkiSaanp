import json
import os
import random
import sys
import unittest
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinkisaanp import AiCupsAdapter, BotConfig, GenericAdapter, PinkiSaanp  # noqa: E402
from pinkisaanp.analysis import Analysis  # noqa: E402
from pinkisaanp.fsm import ATTACKING, RETREATING  # noqa: E402
from pinkisaanp.geometry import DOWN, LEFT, RIGHT, UP, Board, allowed_dirs, popcount  # noqa: E402
from pinkisaanp.pathfinding import astar  # noqa: E402
from pinkisaanp.state import GameView, PlayerView  # noqa: E402


def naive_capture(b, terr_cells, trail_cells):
    walls = set(terr_cells) | set(trail_cells)
    outside = set()
    q = deque(c for c in range(b.n) if b.bit[c] & b.border and c not in walls)
    outside.update(q)
    while q:
        c = q.popleft()
        for n in b.nbr[c]:
            if n >= 0 and n not in walls and n not in outside:
                outside.add(n)
                q.append(n)
    enclosed = {c for c in range(b.n) if c not in walls and c not in outside}
    return (enclosed | set(trail_cells)) - set(terr_cells)


def rect(b, x0, y0, x1, y1):
    return [b.idx(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def player(b, pid, head, d, terr_cells, trail_cells=(), is_me=False):
    return PlayerView(pid, head, d, list(trail_cells), b.mask(terr_cells), b, is_me=is_me)


class GeometryTests(unittest.TestCase):
    def test_cells_roundtrip(self):
        b = Board(17, 11)
        rng = random.Random(3)
        for _ in range(50):
            cs = sorted(rng.sample(range(b.n), rng.randint(0, b.n)))
            self.assertEqual(sorted(b.cells(b.mask(cs))), cs)

    def test_capture_matches_naive_flood(self):
        rng = random.Random(11)
        for _ in range(300):
            w, h = rng.randint(4, 14), rng.randint(4, 14)
            b = Board(w, h)
            terr = rng.sample(range(b.n), rng.randint(1, b.n // 3))
            rest = [c for c in range(b.n) if c not in set(terr)]
            trail = rng.sample(rest, rng.randint(0, len(rest) // 2))
            got = set(b.cells(b.capture(b.mask(terr), b.mask(trail))))
            self.assertEqual(got, naive_capture(b, terr, trail))

    def test_rectangle_loop_capture(self):
        b = Board(10, 10)
        terr = rect(b, 0, 0, 9, 2)  # bottom strip
        trail = [b.idx(2, y) for y in range(3, 7)] + [b.idx(x, 6) for x in range(3, 7)] + \
                [b.idx(6, y) for y in range(3, 6)]
        cap = b.capture(b.mask(terr), b.mask(trail))
        self.assertEqual(popcount(cap), 5 * 4)  # 5x4 rectangle incl. its border trail

    def test_distance_field(self):
        b = Board(9, 7)
        wall = b.mask([b.idx(4, y) for y in range(0, 6)])
        dist = b.distance_field(b.bit[b.idx(0, 0)], b.full & ~wall)
        self.assertEqual(dist[b.idx(8, 0)], 8 + 6 + 6)

    def test_no_reverse(self):
        self.assertNotIn(DOWN, allowed_dirs(UP))
        self.assertEqual(len(allowed_dirs(None)), 4)


class PathTests(unittest.TestCase):
    def _view(self, b, me, enemies=()):
        return GameView(b, me, list(enemies), steps_left=200)

    def test_astar_avoids_own_trail_and_reverse(self):
        b = Board(12, 12)
        terr = rect(b, 0, 0, 11, 1)
        trail = [b.idx(5, y) for y in range(2, 8)] + [b.idx(6, 7), b.idx(7, 7)]
        head = trail[-1]
        me = player(b, 'me', head, RIGHT, terr, trail, is_me=True)
        an = Analysis(self._view(b, me), BotConfig())
        path = astar(an, head, RIGHT, me.terr, an.my_block, an.dist_home)
        self.assertIsNotNone(path)
        self.assertTrue(b.bit[path[-1]] & me.terr)
        self.assertFalse(any(b.bit[c] & me.trail_mask for c in path))
        self.assertNotEqual(path[0], b.idx(6, 7))  # no reversal

    def test_astar_terminates_when_sealed(self):
        b = Board(8, 8)
        terr = rect(b, 0, 0, 1, 1)
        box = [c for c in rect(b, 4, 5, 6, 7) if c != b.idx(5, 6)]
        head = b.idx(5, 6)
        me = player(b, 'me', head, RIGHT, terr, box + [head], is_me=True)
        an = Analysis(self._view(b, me), BotConfig())
        self.assertIsNone(astar(an, head, RIGHT, me.terr, an.my_block, an.dist_home))


class BehaviourTests(unittest.TestCase):
    def test_retreats_when_hunter_is_near_trail(self):
        b = Board(20, 20)
        terr = rect(b, 0, 0, 19, 2)
        trail = [b.idx(10, y) for y in range(3, 10)]
        head = trail[-1]
        me = player(b, 'me', head, UP, terr, trail, is_me=True)
        hunter = player(b, 'e', b.idx(15, 7), LEFT, rect(b, 15, 5, 18, 9))
        bot = PinkiSaanp(strict=True)
        dec = bot.decide(GameView(b, me, [hunter], steps_left=200))
        self.assertEqual(dec.state, RETREATING)
        n = b.nbr[head][dec.direction]
        an = Analysis(GameView(b, me, [hunter], steps_left=200), BotConfig())
        self.assertLess(an.dist_home[n], an.dist_home[head] + 1)

    def test_attacks_exposed_trail(self):
        b = Board(20, 20)
        my_terr = rect(b, 0, 0, 6, 6)
        me = player(b, 'me', b.idx(6, 4), RIGHT, my_terr, is_me=True)
        enemy_trail = [b.idx(x, 9) for x in range(8, 16)]
        enemy = player(b, 'e', b.idx(16, 9), RIGHT, rect(b, 3, 15, 6, 18), enemy_trail + [b.idx(16, 9)])
        bot = PinkiSaanp(strict=True)
        dec = bot.decide(GameView(b, me, [enemy], steps_left=200))
        self.assertEqual(dec.state, ATTACKING)
        self.assertTrue(dec.route.kills)

    def test_rams_raider_crossing_our_land(self):
        # An enemy cuts down through our territory toward its land at the
        # bottom.  We stay inside (empty trail), so meeting its head on its way
        # home kills it at no risk: the longer trail loses a head-on.
        b = Board(18, 18)
        my_terr = rect(b, 6, 3, 13, 10)
        me = player(b, 'me', b.idx(12, 6), LEFT, my_terr, is_me=True)
        trail = [b.idx(10, y) for y in range(16, 9, -1)]
        enemy = player(b, 'e', b.idx(10, 9), DOWN, rect(b, 4, 0, 15, 1), trail + [b.idx(10, 9)])
        view = GameView(b, me, [enemy], steps_left=200)
        from time import perf_counter
        from pinkisaanp.planner import Planner
        an = Analysis(view, BotConfig())
        rams = Planner(an, BotConfig(), 1.5, perf_counter() + 1).ram_routes()
        self.assertTrue(any('e' in r.kills and r.p_survive > 0.95 for r in rams))
        dec = PinkiSaanp(strict=True).decide(view)
        self.assertEqual(dec.state, ATTACKING)
        self.assertIn('e', dec.route.kills)

    def test_avoids_head_on_tie(self):
        # Both at home with empty trails, heads two cells apart, facing each other:
        # stepping into the gap would kill both of us.
        b = Board(12, 12)
        me = player(b, 'me', b.idx(4, 5), RIGHT, rect(b, 1, 3, 4, 7), is_me=True)
        enemy = player(b, 'e', b.idx(6, 5), LEFT, rect(b, 6, 3, 9, 7))
        bot = PinkiSaanp(strict=True)
        dec = bot.decide(GameView(b, me, [enemy], steps_left=200))
        self.assertNotEqual(b.nbr[me.head][dec.direction], b.idx(5, 5))

    def test_never_reverses_or_suicides_fuzz(self):
        from sim.engine import Engine
        from sim.opponents import PinkiAgent, REGISTRY

        class Checked(PinkiAgent):
            def act(self, view):
                d = super().act(view)
                me = view.me
                legal = [x for x in allowed_dirs(me.dir)
                         if view.board.nbr[me.head][x] >= 0
                         and not (view.board.bit[view.board.nbr[me.head][x]] & me.trail_mask)]
                if legal:
                    assert d in legal, (d, legal)
                return d

        for seed in range(2):
            agents = [('pinki', Checked(BotConfig(time_budget=0.03)))] + \
                     [(n, REGISTRY[n](seed)) for n in ('hunter', 'greedy', 'random')]
            eng = Engine(16, 16, agents, max_steps=80, seed=seed)
            eng.run()


class AdapterTests(unittest.TestCase):
    def test_aicups_mid_cell_enemy(self):
        ad = AiCupsAdapter()
        ad.start({'x_cells_count': 31, 'y_cells_count': 31, 'speed': 5, 'width': 30})
        msg = {'players': {
            'i': {'score': 0, 'direction': 'up', 'position': [135, 165],
                  'territory': [[135, 165], [105, 165]], 'lines': [], 'bonuses': []},
            '2': {'score': 0, 'direction': 'left', 'position': [400, 165],
                  'territory': [[465, 165]], 'lines': [[435, 165]], 'bonuses': []}},
            'bonuses': [], 'tick_num': 12}
        view = ad.view(msg)
        self.assertEqual(view.board.xy(view.me.head), (4, 5))
        e = view.enemies[0]
        self.assertEqual(view.board.xy(e.head), (12, 5))  # heading left from x=12.83
        self.assertAlmostEqual(e.lag, 5 / 6.0, places=6)
        self.assertEqual(ad.command(LEFT), 'left')

    def test_generic_y_down(self):
        ad = GenericAdapter(y_down=True)
        state = {'width': 10, 'height': 8, 'me': 'a', 'tick': 3, 'max_ticks': 100,
                 'players': {'a': {'position': [2, 1], 'direction': 'UP',
                                   'territory': [[2, 1], [2, 2]], 'trail': []},
                             'b': {'position': {'x': 7, 'y': 6}, 'direction': 'down',
                                   'territory': [[7, 6]], 'trail': [[7, 5]]}}}
        view = ad.view(state)
        self.assertEqual(view.board.xy(view.me.head), (2, 6))  # flipped
        self.assertEqual(view.steps_left, 97)
        bot = PinkiSaanp(BotConfig(time_budget=0.05), strict=True)
        self.assertIn(ad.command(bot.decide(view).direction), ('UP', 'DOWN', 'LEFT', 'RIGHT'))

    def test_generic_infers_missing_heading(self):
        ad = GenericAdapter(y_down=True)
        base = {'width': 8, 'height': 8, 'me': 'a'}
        p0 = {'position': [3, 4], 'territory': [[3, 4], [3, 5]], 'trail': []}
        ad.view(dict(base, players={'a': p0}))
        p1 = {'position': [3, 3], 'territory': [[3, 4], [3, 5]], 'trail': []}  # moved up (y-1)
        view = ad.view(dict(base, players={'a': p1}))
        self.assertEqual(view.me.dir, UP)
        self.assertNotIn(DOWN, allowed_dirs(view.me.dir))

    def test_main_generic_protocol_roundtrip(self):
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        state = {'width': 6, 'height': 6, 'me': 1, 'players': [
            {'id': 1, 'position': [1, 1], 'direction': None, 'territory': [[1, 1]], 'trail': []}]}
        out = subprocess.run([sys.executable, '-u', os.path.join(root, 'main.py'), '--protocol', 'generic'],
                             input=json.dumps(state) + '\n', capture_output=True, text=True, timeout=60)
        self.assertIn(out.stdout.strip(), ('UP', 'DOWN', 'LEFT', 'RIGHT'))
        self.assertEqual(out.stderr, '')


if __name__ == '__main__':
    unittest.main()
