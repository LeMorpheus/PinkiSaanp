"""Every tunable number of PinkiSaanp lives here (see STRATEGY.md for the math)."""


class BotConfig:
    # ---- objective: value of what a closed loop gains ----------------------
    w_neutral = 1.0          # neutral cell captured
    w_enemy = 5.0            # enemy-owned cell captured (MiniAICups pays 5x)
    w_kill = 50.0            # cutting an enemy trail
    w_kill_territory = 0.15  # per cell of the victim's land (it becomes free)
    w_bonus = {'n': 6.0, 'saw': 10.0, 's': -12.0}  # nitro / saw / slowdown pickups

    # ---- risk model: p_death = sigmoid((margin_mid - margin) / margin_scale) -
    margin_mid = -1.0        # margin where an optimal hunter kills us 50% of the time
    margin_scale = 0.55
    expand_min_margin = 0.0  # hard floor: never start a loop an enemy can provably cut
    headon_lose_p = 0.65     # chance an adjacent enemy actually takes a contested cell
    pocket_p = 0.9           # chance we die if caught inside an enemy's closing loop
    ram_trail_len = 2        # enemies with trails this short win head-ons against us
    ram_margin_mid = 0.0     # rammer contact margin where we die 50% (x ram_p)
    ram_p = 0.55             # chance a rammer that *can* reach our head actually does

    # ---- value of staying alive (what death costs) --------------------------
    life_territory_weight = 0.35  # per owned cell (1.0 when death erases territory)
    life_future_weight = 0.5      # x expected gain-rate x steps left
    life_min = 30.0
    rate_prior = 1.5              # initial estimate of gain per step
    rate_ema = 0.05

    # ---- exposure / wall hugging ---------------------------------------------
    w_exposure = 0.30        # penalty per open flank of a trail cell, scaled by threat
    exposure_tau = 7.0       # threat distance (steps) at which flank cost decays by e

    # ---- planner ------------------------------------------------------------
    max_leg = 13             # longest straight leg of a rectangle loop
    loop_len_min = 6         # greed cap on planned trail length ...
    loop_len_max = 46        # ... interpolated by distance to the nearest threat
    loop_len_per_threat = 2.2
    time_overhead = 1.5      # steps added to each route's duration in the rate
    commit_bonus = 0.12      # utility bonus for sticking with the previous plan
    max_attack_targets = 5   # trail cells probed per vulnerable enemy
    ram_horizon = 4          # moves ahead we try to meet a homeward enemy head-on
    ram_kill_p = 0.7         # chance it really follows its shortest path home
    ram_kill_decay = 0.8     # confidence lost per extra move of lookahead
    kill_buffer = 0.0        # extra steps we demand before the victim reaches home
    horizon = 96             # longest route / threat table considered (steps)
    defend_lookahead = 7     # in-territory walk depth for DEFENDING

    # ---- FSM thresholds (hysteresis) -----------------------------------------
    retreat_enter_margin = 1.0   # outside + home-now margin below this -> RETREATING
    expand_enter_utility = 0.05  # leave home only if best loop beats this rate
    attack_min_utility = 0.10

    # ---- engine semantics -------------------------------------------------------
    wall_encloses = False    # does the arena edge count as a fence when capturing?
    default_max_steps = 250  # decision steps per game when the engine doesn't say
    time_budget = 0.12       # seconds of search per decision (hard stop)

    def __init__(self, **overrides):
        self.w_bonus = dict(self.w_bonus)
        for k, v in overrides.items():
            if not hasattr(self, k):
                raise AttributeError('unknown BotConfig field: %s' % k)
            setattr(self, k, v)

    @classmethod
    def aicups(cls, **kw):
        """MiniAICups Paper.io scoring: points are banked, death only stops income."""
        return cls(**kw)

    @classmethod
    def territory(cls, **kw):
        """Winner = largest territory at the end; dying forfeits everything."""
        base = dict(w_enemy=2.0, w_kill=25.0, w_kill_territory=0.6,
                    life_territory_weight=1.0, life_future_weight=0.35)
        base.update(kw)
        return cls(**base)
