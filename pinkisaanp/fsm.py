"""Finite State Machine that turns scored candidate routes into a mode + plan.

States and transitions (priority order, evaluated every tick):

  RETREATING      outside AND (margin of the best way home < retreat_enter_margin
                  OR we were already retreating).  Sticky until we are home.
                  Plan = route with the highest survival probability; a
                  counter-attack is allowed only if it is at least as survivable.
  ATTACKING       a route that cuts an enemy trail before it can get home has
                  the best utility and clears attack_min_utility.
  EXPANDING_SAFELY  best loop/home route utility clears the threshold
                  (higher threshold to *leave* home than to keep going).
  DEFENDING       at home and nothing out there is worth the risk: patrol
                  inside the territory, as far from enemy heads as possible.
"""

EXPANDING_SAFELY = 'EXPANDING_SAFELY'
RETREATING = 'RETREATING'
ATTACKING = 'ATTACKING'
DEFENDING = 'DEFENDING'


class StateMachine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = DEFENDING
        self.ticks_in_state = 0
        self.history = []

    def _set(self, state):
        if state != self.state:
            self.history.append(state)
            if len(self.history) > 64:
                del self.history[:32]
            self.state = state
            self.ticks_in_state = 0
        else:
            self.ticks_in_state += 1

    def select(self, an, routes):
        """Pick (state, route) from the evaluated candidates (any may be missing)."""
        cfg = self.cfg
        outside = bool(an.me.trail_mask)
        # Any route that cuts a trail is an attack, whichever builder produced it
        # (a capture loop that also crosses an exposed trail is the best attack).
        attacks = [r for r in routes if r.kills]
        homes = [r for r in routes if r.kind == 'home' and not r.kills]
        expands = [r for r in routes if r.kind in ('expand', 'commit') and not r.kills]
        defends = [r for r in routes if r.kind == 'defend' and not r.kills]

        def best(rs):
            return max(rs, key=lambda r: r.utility) if rs else None

        def safest(rs):
            return max(rs, key=lambda r: (r.p_survive, r.utility)) if rs else None

        if outside:
            exits = homes + expands + attacks
            if not exits:
                return self._pick(RETREATING, None)
            home_margin = max((r.margin for r in homes), default=-1e9)
            if self.state == RETREATING or home_margin < cfg.retreat_enter_margin:
                pick = safest(exits)
                # Prefer a quicker/greedier exit only when it is just as survivable.
                good = [r for r in exits if r.p_survive >= pick.p_survive - 1e-3]
                pick = best(good)
                state = ATTACKING if pick.kills else RETREATING
                return self._pick(state, pick)
            pick = best(exits)
            if pick.kills:
                return self._pick(ATTACKING, pick)
            if pick.kind == 'home' and pick.p_survive < 0.97:
                return self._pick(RETREATING, pick)
            return self._pick(EXPANDING_SAFELY, pick)

        # ---- at home ----------------------------------------------------------
        a = best(attacks)
        e = best(expands)
        d = best(defends)
        if a and a.utility >= cfg.attack_min_utility and (e is None or a.utility >= e.utility):
            return self._pick(ATTACKING, a)
        threshold = cfg.expand_enter_utility
        if self.state == DEFENDING:
            threshold *= 2.0  # hysteresis: do not peek out and back every tick
        if e and e.utility > threshold and e.ev > 0:
            return self._pick(EXPANDING_SAFELY, e)
        if d:
            return self._pick(DEFENDING, d)
        # Cannot stay inside (tiny/thin territory): take the least bad way out.
        rest = [r for r in (e, a) if r]
        if rest:
            return self._pick(EXPANDING_SAFELY, safest(rest))
        return self._pick(DEFENDING, None)

    def _pick(self, state, route):
        self._set(state)
        return state, route
