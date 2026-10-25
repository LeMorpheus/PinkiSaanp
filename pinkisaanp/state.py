"""Engine-agnostic snapshot of one decision tick (built by adapters.py)."""

from .geometry import Board


class PlayerView:
    """One player, in cell coordinates and in *our* time units.

    ``speed`` is cells moved per one of our moves (1.0 when equally fast) and
    ``lag`` is how many of our moves the player still needs to reach ``head``
    (non-zero when the engine reports it between two cell centres).
    """

    __slots__ = ('pid', 'head', 'dir', 'trail', 'trail_mask', 'terr', 'speed',
                 'lag', 'score', 'alive', 'is_me', 'bonuses')

    def __init__(self, pid, head, direction, trail, terr_mask, board,
                 speed=1.0, lag=0.0, score=0, is_me=False, bonuses=None):
        self.pid = pid
        self.head = head
        self.dir = direction
        self.trail = list(trail)
        self.trail_mask = board.mask(self.trail)
        self.terr = terr_mask
        self.speed = speed if speed > 0 else 1.0
        self.lag = lag
        self.score = score
        self.alive = True
        self.is_me = is_me
        self.bonuses = bonuses or {}

    @property
    def outside(self):
        return bool(self.trail_mask)


class GameView:
    __slots__ = ('board', 'me', 'enemies', 'tick', 'steps_left', 'bonuses')

    def __init__(self, board, me, enemies, tick=0, steps_left=None, bonuses=None):
        assert isinstance(board, Board)
        self.board = board
        self.me = me
        self.enemies = [e for e in enemies if e.alive]
        self.tick = tick
        self.steps_left = steps_left
        self.bonuses = bonuses or []  # list of (cell, kind)
