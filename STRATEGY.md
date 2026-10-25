# PinkiSaanp: Architecture Blueprint

The bot runs four layers every tick:

1. **Threat analysis** builds bitboard influence maps.
2. **Candidate generation** proposes complete routes.
3. **Exact route simulation** replays each route under the real rules and scores it with an expected-value rate.
4. **A four-state FSM** picks the mode and the plan.

Then a move guard makes sure the answer is always legal. Everything is pure Python 3. Bitboards make a full-grid flood fill take about 9 µs, compared with about 550 µs for a Python BFS, so the bot can evaluate 100–1,000 complete routes per move inside a 120 ms budget.

The rules modelled are those of `References/paperio` (the MiniAICups Paper.io engine): `game_objects/game.py`, `player.py`, `territory.py` and `COLLISIONS.md`. Where an engine detail changes a decision, this document says so.

---

## 1. Architecture blueprint

```
             ┌──────────────┐   GameView (cells, our time units)
 engine ───▶ │   adapters   │───────────────────────────────────────┐
             └──────────────┘                                       ▼
                                   ┌──────────────────────────────────────────┐
                                   │ Analysis (once per tick, ~2-6 ms)         │
                                   │  • enemy reach tables R_e[T]  (threat map)│
                                   │  • threat[c], rammer contact map          │
                                   │  • dist_home[c] (A* heuristic), dist_me[c]│
                                   │  • enemy home times, pockets, exposure    │
                                   └──────────────────────────────────────────┘
                                                      │
                                                      ▼
   ┌────────────── Planner (time-boxed, best-first order) ───────────────────┐
   │ home   : safest A* home + shortest A* home     (survival first)         │
   │ attack : A* onto each reachable enemy trail cell, then home              │
   │ ram    : A* to meet a homeward enemy's head while our trail is shorter  │
   │ commit : remainder of last tick's plan (+12% hysteresis)                │
   │ expand : rectangle loops out-a / across-b / greedy-home, all 4 headings, │
   │          enumerated smallest perimeter first, capped by the greed limit  │
   │ defend : in-territory walks (no trail) maximising distance from heads    │
   │   every route → exact replay → Gain, Kills, P_survive, EV, Utility       │
   └──────────────────────────────────────────────────────────────────────────┘
                                                      │
                                                      ▼
                        StateMachine.select → (state, route) → move guard → direction
```

### How the state evaluator chooses a state

The evaluator does not use ad-hoc triggers. Every candidate route already carries its survival probability, gain, kill value and utility rate. The FSM reads a few summary signals from those routes:

| Signal | Definition | Used for |
|---|---|---|
| `outside` | we carry a trail | splits the transition table |
| `home_margin` | best safety margin among the routes straight home | RETREATING trigger |
| `best_attack.U` | best utility among routes that cut a trail before its owner gets home | ATTACKING |
| `best_expand.U`, `best_expand.EV` | best capture loop | EXPANDING_SAFELY vs DEFENDING |
| `best_defend` | an in-territory walk exists | DEFENDING is possible |

Transition table (priority top to bottom; `fsm.py`):

| Where we are | Condition | State | Plan |
|---|---|---|---|
| outside | `home_margin < 1.0`, or already RETREATING | **RETREATING** (sticky until home) | route with max `P_survive`; among equally survivable ones, max `U`. A counter-attack is allowed only if it is as survivable. |
| outside | best route kills | **ATTACKING** | that route |
| outside | otherwise | **EXPANDING_SAFELY** | best `U` (continue or extend the loop, or close now) |
| home | best kill route `U ≥ 0.10` and beats the best loop | **ATTACKING** | kill route |
| home | best loop `U > 0.05` (×2 when currently DEFENDING) and `EV > 0` | **EXPANDING_SAFELY** | best loop |
| home | otherwise | **DEFENDING** | safest in-territory walk |

There is hysteresis in three places:

- RETREATING only ends at home.
- Leaving home from DEFENDING needs twice the usual utility.
- The plan being executed gets a 12% bonus, so the bot doesn't flip-flop between equivalent loops while its trail is exposed.

---

## 2. The heuristic math

Notation: `t` counts **our** moves from now. A route visits cells `c_1 … c_T`, where `c_T` is the first cell back on our land (the loop closes at `T`). `L` is the set of trail cells at closing time: the existing trail plus planned cells.

### 2.1 Threat (influence) map

For each enemy `e`, with speed ratio `v_e` (cells per one of our moves) and lag `λ_e` (time to reach the cell it is entering):

```
R_e[0]   = {head_e}
R_e[1]   = head_e ∪ {non-reverse neighbours}            (no-reverse rule on move 1)
R_e[k+1] = R_e[k] ∪ (dilate(R_e[k]) ∩ ¬trail_e)          (walls and its own trail block it)
Danger_e(T) = R_e[ floor((T − λ_e) · v_e) ]               (cells e can occupy within T of our moves)
arrival_e(S) = min{ T : Danger_e(T) ∩ S ≠ ∅ }             (binary search, ~7 big-int ANDs)
threat[c]    = min_e arrival_e({c})
```

The no-reverse rule is enforced only on the first enemy move, and enemies are treated as able to pass through any territory. Both choices over-approximate enemy reach, which keeps the model conservative.

### 2.2 What a loop gains

```
New = capture(Territory, L)   = L ∪ {free cells not 4-connected to the map edge}   (bitboard flood)
G   = w_n · |New ∩ neutral| + w_e · |New ∩ enemy land| + Σ bonus weights
```

Defaults: `w_n = 1`, `w_e = 5`. MiniAICups pays 5 points per stolen cell. In territory mode `w_e = 2`, because a stolen cell is +1 for us and −1 for them.

### 2.3 Safety margins (the core inequality)

A trail laid now is cut if any enemy reaches any cell of `L` before we close:

```
m_e = arrival_e(L) − T
```

The reference engine resolves the capture (and clears the trail) **before** it checks trail crossings. So an enemy arriving exactly at `T` does not kill us, and `m_e ≥ 0` means a perfect hunter cannot cut this loop.

For a route that kills enemy `e` at step `t_k`, the deadline is `t_k + 1`: a simultaneous cut is mutual death. The mask used is the trail laid up to `t_k`.

### 2.4 Death probability

```
p_e        = σ( (m_mid − m_e) / s )            m_mid = −1.0, s = 0.55
P_cut      = 1 − Π_e (1 − p_e)
p_ram      = 0.55 · σ( (0 − m_ram) / s )        m_ram = min_{t≥3, trail>0} (ram_contact[c_t] − t)
p_headon   = 0.65 if an exact sub-step contact on move 1 loses (0.26 on move 2)
p_pocket   = 0.9  if we are still inside an enemy's closing pocket when it can close
P_survive  = (1 − P_cut)(1 − p_ram)(1 − p_headon1)(1 − p_headon2)(1 − p_pocket)
```

Sample values: `m = 0 → p = 0.14`, `m = 1 → 0.026`, `m = 2 → 0.004`, `m = −1 → 0.5`, `m = −2 → 0.86`.

The **rammer map** fills a gap that the cut test leaves open. An enemy whose trail has at most 2 cells (usually one sitting at home) wins every head-on against us while we carry a trail. Squares touch one cell early (diagonal approach), and they also touch on the closing cell itself. So `ram_contact` is that enemy reach, dilated by one cell.

An enemy that is still outside counts as a rammer **from its `home_time` onward**. One that is a step from closing its own loop is a rammer next tick; the duel seed 412 death was exactly this case.

### 2.5 Value of staying alive

```
V_life = max( 30,  α · |our land|  +  β · rate · steps_left )
```

- MiniAICups mode: `α = 0.35`, `β = 0.5`. Points are banked, so death only stops future income.
- Territory mode: `α = 1.0`, `β = 0.35`. Death forfeits all land.
- `rate` is an EMA of the land we actually gained per move.

`V_life` shrinks as the game runs down, so the bot becomes **more ruthless in the endgame** automatically.

### 2.6 Exposure (wall hugging)

```
E = w_x · Σ_{c ∈ new trail} (open_sides(c) − 2) · exp(−threat[c] / τ)      w_x = 0.30, τ = 7
```

`open_sides` is 4 in open field, 3 along a wall and 2 in a corner. Trail cells along a wall have one less flank to attack from, and the penalty only bites when enemies are near. The reach model already scores this exactly against visible enemies; this term adds a prior against future threats.

### 2.7 Expected value and utility rate

```
EV = P_survive · (G + KillValue) − (1 − P_survive) · V_life − E
U  = EV / (T + 1.5)
KillValue = 50 + 0.15 · |victim land|          (territory mode: 25 + 0.6 · |victim land|)
```

Maximising **gain per move** rather than gain per loop is what produces *small incremental loops*. A big loop has a better area-to-perimeter ratio, but its trail stays exposed longer and its margins shrink, so `P_survive` falls quickly. The optimum is the largest loop whose margin is still about 1 or more. With `V_life = 200` and `G = 15`, a loop is only taken when `p < G/(G+V_life) ≈ 7%`, i.e. `m ≳ 1`.

**Greed cap.** The planned trail may not exceed

```
L_max = clamp(6 + 2.2 · nearest_threat, 6, 46)
```

where `nearest_threat` is the earliest enemy arrival at our head, trail or border.

### 2.8 Attack feasibility (trail hunting)

Trail cell `c` of enemy `e` is a target when:

```
dist_me(c) < home_time_e        (home_time_e = λ_e + BFS(head_e → land_e avoiding own trail) / v_e)
```

Ties go to the victim, because it closes and clears its trail first. The kill must also survive its own deadline (§2.3), and the rest of the route must get home with an acceptable `P_survive`. A rectangle loop that happens to cross a vulnerable trail is also counted as an attack, which is often the best attack of all: kill plus capture.

### 2.8b Head-hunting (ram attacks)

Trail cutting cannot catch an enemy that is running *toward* us. Its nearest trail cell is always behind its head. The head-on rule can: the longer trail dies, and inside our own land our trail is 0.

```
pred_e      = [head_e] + shortest path home        (only when e is aligned and at speed 1)
contact at t: exact sub-step test of (c_{t−1} → c_t) vs (pred_e[t−1] → pred_e[t])
win         : our trail < theirs at that moment (pre-move lengths before the centre)
p_kill(t)   = 0.7 · 0.8^(t−1),   t ≤ 4
KillValue  += p_kill · (w_kill + w_kill_territory · |land_e|)
p_cut_e    *= (1 − p_kill)        (if the ram works, that enemy never reaches our trail)
```

Ramming from inside our territory is free: no trail, no risk. It also blocks the enemy's return path, which is what stops it from enclosing ("painting") us.

### 2.9 Risk-aware A\*

The search state is `(cell, heading)`. The heuristic `h = dist_home` (BFS ignoring risk) is admissible and consistent. The cost of stepping onto `c` at time `t` outside our land is:

```
cost = 1 + 6 · max(0, t + dist_home(c) − threat(c) + 1) + 0.25 · expo(c)
```

`t + dist_home(c)` is the earliest we could close after laying `c`, so the risk term charges every cell an enemy could reach before we are safely home. Inside our land the cost is exactly 1.

### Default weights

| Field | Default | Why |
|---|---|---|
| `w_enemy` | 5 | MiniAICups stolen-cell value (2 in territory mode) |
| `w_kill` | 50 | MiniAICups trail-cut bonus |
| `margin_mid`, `margin_scale` | −1.0, 0.55 | `m ≥ 1` ≈ 97% safe even against a perfect hunter |
| `ram_p` | 0.55 | Tuned: 0.5 scored best in mixed 6-bot fields (879 vs 843 at 0.85); 0.25 was worse |
| `life_*` | 0.35 / 0.5 | Death cost ≈ 150–400 early game, falling to ~30 at the end |
| `loop_len_*` | 6 / 46 / 2.2 | "Don't be greedy" as a hard cap |
| `commit_bonus` | 0.12 | Anti-dither |
| `time_budget` | 0.12 s | Stops the candidate search; analysis and the final pick take a few ms more |

---

## 3. Core code structure

### Decision loop (`bot.py`)

```python
def decide(view):
    deadline = now() + cfg.time_budget
    try:
        an = Analysis(view, cfg)                         # threat maps
        P  = Planner(an, cfg, rate, deadline)
        routes  = P.home_routes()                         # survival first
        routes += P.attack_routes()                       # then kills: trail cuts
        routes += P.ram_routes()                          #             and head-ons
        routes += [P.continue_route(prev_plan)]           # then the current plan
        routes += P.rectangle_routes()                    # then new loops (small first)
        routes += P.defend_routes()                       # then staying home
        state, route = fsm.select(an, routes)
        move = first step of route, if legal, else survival_move()
    except Exception:
        move = survival_move()                            # never crash
    return move
```

### State machine (`fsm.py`)

See the transition table in §1.

### Route replay (`planner.py: Planner.evaluate`)

For every step, the replay:

- rejects the route if it crosses our own trail;
- records a kill if the cell is a vulnerable enemy trail and `t < home_time`, plus expected ram kills for the first 4 moves;
- tracks rammer contact and pocket membership;
- on re-entering our land with a trail, closes the loop: exact capture, then margins.

### A\* (`pathfinding.py`)

- Heap entries are `(f, tiebreak, g, t, cell, heading)`.
- The closed set is keyed on `(cell, heading)`.
- Expansion caps and a deadline bound the search.

---

## 4. Edge cases

### Head-on collisions and ties

The engine rule (`game.check_loss`) is that if two squares overlap, the player with the **longer or equal** trail dies, so equal lengths kill both. Squares move in 6 sub-steps and touch when `|dx| < 1` and `|dy| < 1`. Trail lengths only change at cell centres, so most contacts compare the lengths **before** the move. That includes the case where we are stepping home to close a loop.

The bot handles this in five ways:

1. **Exact sub-step contact test** for our first two moves against every enemy's possible moves (`Planner.headon_risk`). It uses pre-move lengths for contacts before the centre and post-move lengths at the centre. A losing or tied contact multiplies `P_survive` by 0.35 on move 1 and by 0.74 on move 2.
2. **Rammer contact map** (§2.4) for later steps and for the closing cell.
3. **Two bots at home both have trail 0**, so a touch is a tie and both die. The exact test treats ties as losses, so DEFENDING walks keep away from enemy heads, and their tie-break also maximises distance from those heads.
4. **Symmetry breaking.** Moves are chosen deterministically by utility, and the plan-commitment bonus makes the bot follow through. Two copies of the bot don't keep mirroring each other into a contested cell. In 4-way self-play there were no head-on deaths.
5. **Offence.** The same contact model powers ram attacks (§2.8b). When we are guaranteed the shorter trail, a head-on is a kill, not a risk.

### Infinite loops in pathfinding

- **A\*:** the closed set on `(cell, heading)` means each state is expanded at most once (at most `4·W·H`). There is also a hard `max_nodes` cap and a wall-clock deadline check every 64 expansions. Returning `None` is a normal outcome.
- **Greedy home descent:** at most `dist_home + 6` steps, and it falls back to A\* or drops the candidate.
- **Defend DFS:** depth-limited to 7, with no revisits, and it stops after the first full-depth continuation per subtree.
- **Reach and distance layers:** these stop when a dilation adds nothing new (fixpoint) or at the horizon (96).
- **Behavioural loops:** sticky RETREATING, the doubled leave-home threshold and the plan-commitment bonus prevent peeking out and back in. A pure in-territory walk has utility near 0, so any safe loop with positive EV beats circling forever.

### Other engine details the bot respects

- **No reverse.** The server ignores a reverse command and keeps going straight, possibly into a wall. Every generator and the move guard only use `allowed_dirs(heading)`. The guard also rejects walls and our own trail.
- **First tick.** The heading is `None`, so all four moves are allowed.
- **Mid-cell enemies (MiniAICups).** An enemy between cells is placed at the cell it is entering, with `lag` = fraction remaining × speed ratio. Nitro and slowdown are reproduced exactly (speed steps to the next divisor of the cell width).
- **Capture beats trail-cut** (COLLISIONS.md #5 and #6). Closing on the tick an enemy reaches our trail saves us, which is why the margin `m ≥ 0` is safe. Stepping onto an enemy trail on the tick it closes is harmless unless our previous cell is inside its capture.
- **Being painted** (COLLISIONS.md #3 and #4). Each enemy's shortest return path defines a pocket. Routes still inside a pocket when it can close get `p_pocket`.
- **Contested captures.** Cells claimed by two players on the same tick go to nobody; the bot simply re-plans next tick.
- **Endgame.** Routes that cannot close before `steps_left` are dropped, so no trail is left unbanked. `V_life` falls toward its floor, which makes late loops bolder.
- **Timeouts.** There is a time budget per move, candidates are ordered best-first, and the bot never blocks on I/O. Answers go to stdout only, never stderr: the reference runner treats any stderr output as an error.
- **Exceptions.** Any planner exception triggers a survival move: a legal move that keeps the largest free area, prefers home and avoids enemy heads. Tests run in `strict` mode so bugs can't hide behind it.

---

## 5. Benchmarks

All numbers are from the final version (v5), with seats shuffled per game. An earlier build also won both of its official-engine games. The opponents were:

- **Hunter:** a cautious looper that dives at any trail it can reach before the owner gets home.
- **Cautious:** medium loops, retreats when an enemy can reach its trail.
- **Greedy:** big loops, no threat awareness.
- **simple_bot:** the reference runner's built-in bot.

| Arena | Games | PinkiSaanp win % (score) | Survival | Avg score (PinkiSaanp / best other) |
|---|---|---|---|---|
| **Official MiniAICups engine** (`sim/reference_match.py`, 31×31, 6 bots, 1500 ticks, bonuses on, seat rotated every game) | 6 | **100%** | **100%** | 732 / 365 |
| Local engine FFA 31×31, 6 bots (Pinki + Greedy + 2 Cautious + 2 Hunter) | 36 | **81%** (78% by land) | **100%** | 756 / 290 |
| Duel vs Hunter, 20×20 | 24 | **100%** | **100%** | 560 / 286 |
| Duel vs Cautious, 20×20 | 24 | **100%** | **100%** | 499 / 282 |
| Self-play 4× PinkiSaanp + 2 Hunters | 12 | 25% each (as expected) | **100%** (48 seats) | 887 / 356 |

Decision time (budget 0.12 s, measured with 6 games running in parallel):

| Board | avg | max |
|---|---|---|
| 31×31 | 23–37 ms | ~140 ms |
| 50×50 | 73 ms | 125 ms |
| 100×100 | 121 ms | 125 ms (anytime search caps it) |

The fixes that got here, each found by replaying a lost game (`sim/tournament.py -v` then the ASCII inspector):

1. **Head-on lengths are pre-move.** Contact happens mid-move, before trails update at the cell centre.
2. **An enemy about to close becomes a rammer** from its `home_time`.
3. **Ram attacks** stop raiders that cut through our land from enclosing us.
4. **Simulator fidelity.** "Painted" requires the previous cell to be inside the capture as well (`player.is_ate`).

Tuning evidence: four PinkiSaanp variants played in the same 6-bot arena, 30 games per tournament.

| Variant | Avg score | Wins |
|---|---|---|
| `ram_p` 0.5 | 879 | 40% |
| `w_enemy` 8 (raider) | 848 | 27% |
| default (`ram_p` 0.85) | 843 | 17% |
| bold (`margin_mid` −0.4) | 789 | 17% |
| greedy loops | 856 | 37% (1 death) |
| safe (`margin_mid` −1.6) | 799 | 17% (2 deaths) |

So `margin_mid = −1` sits at the optimum, and `ram_p` was lowered to 0.55.

---

## 6. Porting to your hackathon engine (checklist)

1. **Coordinates.** Is the origin at the top-left? If so, use `--y-down`. Does the state include our heading? If not, the adapter can infer it from the last two positions.
2. **Is the head part of the trail?** `GenericAdapter` normalises this to "head is the newest trail cell when outside".
3. **Capture semantics.** Flood fill from the map edge is the standard rule. If the arena edge counts as a fence, use `--wall-encloses`.
4. **Head-on rule.** If your engine kills both players on any head contact, raise `headon_lose_p` and `ram_p` to about 0.9. If it has no head-on rule, set them to 0.
5. **Ordering of trail cut vs capture.** If your engine checks cuts first, set `margin_mid = 0.0` so the bot demands one extra step of margin.
6. **Scoring.** `--objective territory` is for winner-by-final-land, and is the default for `--protocol generic`. `--objective score` is for banked points, and is the default for the MiniAICups protocol.
7. **Time limit.** Set `--budget` to roughly 40% of the per-move limit to absorb interpreter jitter.
