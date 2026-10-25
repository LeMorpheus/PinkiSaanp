# PinkiSaanp: handoff for the Codewars "Agent Showdown" bot

Goal: **win** the hackathon. 4-player paper.io-like game, 100×100 map, 2000 moves, 11×11 view.
Score = painted tiles at the end. Language: Python 3 (judge image `python:3.12-slim`), 100 ms per move.

## Repo layout
| Path | What |
|---|---|
| `submission/PinkiSaanp/` | **The contest bot** (`manifest.json`, `bot.py`, `pinki/*.py`). Zip this folder's *contents*. |
| `PinkiSaanp_submission.zip` | Ready-to-upload archive (manifest.json at zip root). Rebuild after changes. |
| `baselines/PinkiV1/` | Original handed-over build (opponent for A/B tests; `variant.json` = seed 7). |
| `baselines/PinkiV2/` | Build after the wall-build fixes (+2883 tiles vs V1); the reference opponent for later A/Bs. |
| `baselines/PlainLoop/` | V2 with `noabil` (loops only, no bombs/bullets/walls): a stand-in for simple contest bots. |
| `Rules/map.txt` | Official contest map. Identical to `pinki/mapdata.py` / `probes/map_abs.txt` plus spawn digits. |
| `Rules/` | Official contest README + official test kit (`testkit` Linux binary, starter bots, web visualizer). |
| `tools/replay.py` | **Reverse-engineered `.pbrp` replay decoder**: full board for every tick. |
| `tools/arena.py` | Parallel testkit games: `--sync --lineup A,B,C,D --games 128 --rotate --seeded`; `--variant NAME=JSON` (copy of the submission with options), `--snap NAME=DIR`, `--src DIR` (snapshot to test). Prints avg/win%/TLE/errors and an A-vs-B head-to-head line. |
| `tools/opening.py` | Opening benchmark: our bot vs 3 idle bots, mean area at given ticks over seeds (`--noseed` = shipped config). ~5 s per config. |
| `tools/swings.py`, `losses.py`, `peek.py` | Replay analysis: big one-tick swings, loss mechanism classifier (bomb/bullet/wall/head), windows around a head. |
| `tools/build_zip.sh` | Rebuild `PinkiSaanp_submission.zip` (asserts manifest at root, no variant.json/pycache). |
| `probes/` | Scripted probe bots used to learn engine mechanics + `map_abs.txt` (the map, extracted from the binary). |
| `pinkisaanp/`, `sim/`, `tests/`, `main.py`, `STRATEGY.md` | **Legacy** bot for a different game (MiniAICups paper.io). Template only, not used. |

## Submission
The README says a submission is a directory with `manifest.json` (`{"run": ["python3", "bot.py"]}`), uploaded as a `.zip` / `.tar.gz`. Build it from inside the folder so `manifest.json` sits at the archive root:
```bash
cd submission/PinkiSaanp && rm -rf pinki/__pycache__ variant.json && zip -r ../../PinkiSaanp_submission.zip manifest.json bot.py pinki
```
Never ship `variant.json` (it is only for local A/B tests). Logging goes to stderr (allowed, captured by the judge). Turn it off with `PINKI_LOG=0`. Use `tools/build_zip.sh`.

The manifest runs `python3 -S bot.py`. The judge's clock includes interpreter start and module compilation (no bytecode is shipped) and all four bots start together, so `bot.py` plays a fixed 7-move opening (`OPENING`, the planner's own corner loop; nobody can reach us that early) while importing one module per move, then builds the brain, which replays the missed frames (`Brain.replay`). Cold start with 4 copies: every one of the first 10 moves < 19 ms.

## Running the official engine (Linux / cloud: no Docker needed)
```bash
cd Rules/agent-showdown-test-suite-main && chmod +x testkit
mkdir -p my_bots && cp -r ../../submission/PinkiSaanp my_bots/
./testkit -n 2000 my_bots/PinkiSaanp wall_hug random my_bots/PinkiSaanp      # P1..P4
./testkit -n 2000 -v -r out/replays/x.pbrp --log-dir runs/x my_bots/PinkiSaanp ...  # verbose + replay + logs
python3 ../../tools/replay.py out/replays/x.pbrp --scores                     # tiles per player every 50 ticks
```
Four identical copies play perfectly symmetric games, so use variants instead: copy the bot dir and add `variant.json` `{"seed": N, "max_leg": 30}`, which randomises tie-breaks. The web viewer is `python3 viewer_server.py 8000`; open `http://localhost:8000` and enter the replay id.

## Verified engine facts (probes + replays)
These **differ from or extend the README**:
1. **Labels are not relabelled to '1'.** The view is in our own frame (we spawn top-left at (3,3), x right, y down), but our head char can be any of `1234`. Learn it from the centre char on frame 0. Paint = `ABCD`[k], bomb = `!@$%`[k], bullet = one of `GHJKL` (learn it when we fire). The map is symmetric (both mirrors and the diagonal), so every frame matches `pinki/mapdata.py`.
2. **Tile left behind = our paint immediately.** No death mechanic. The head tile counts as part of the boundary for enclosures.
3. **Enclosure:** holes of (our area + head) are filled, including enemy paint and breakable walls. Unbreakable walls stay walls. **Walls do NOT act as fences:** the region between our trail and the border wall does not fill.
4. **Connectivity, the decisive rule.** Our area = the component 4-connected to our head.
   - If *we* disconnect our own tiles (e.g. building a wall on our own paint), they turn to **air**.
   - If an *enemy* causes it, the **entire disconnected part goes to that enemy**, e.g. 6087 tiles stolen in one tick by a single bullet crossing our thin trail.
   - Head-isolation kills:
     - a wall on the only own tile next to a head;
     - a bomb whose r²≤9 disk covers all 4 neighbours of a head (head within the diamond |dx|+|dy|≤2 of the bomb centre);
     - a bullet or another player crossing a 1-wide trail between a head and its base.
   - Self-play games are a chain of whole-territory steals; the last big steal wins.
5. **Dash:** paints all crossed tiles (3 per move).
6. **Bomb:** appears next frame and explodes 3 frames after the throw. It paints the r²≤9 disk (29 tiles) if connected to our area, otherwise air. It cannot be placed on `*`/walls/objects.
7. **Bullet:** sits on the adjacent tile for 1 frame, then flies 3 tiles/frame, painting what it crosses (including over enemy paint, which cuts). It stops at objects. Walls block bullets.
8. **Charges:** +1 every R moves while below max, with the timer running continuously. Cooldown C = C moves strictly between uses.

   | Ability | First available | Spacing between uses |
   |---|---|---|
   | Bullet | move 20 | 20 |
   | Bomb | move 15 | 16 (cooldown 15) |
   | Dash | start (charge 1) | 6 (cooldown 5) |

   Failed ability = idle; the cost is not deducted except a blocked dash.
9. Moving into a wall/object = idle. Two bots targeting the same tile both idle, which can deadlock forever (handled by failed-move detection).
10. **Frames and spawns.** In the replay frame P1 starts top-left, P2 top-right, P3 bottom-left, P4 bottom-right (`Rules/map.txt` is the same, y-flipped). Each player's view is a pure mirror (P2 mirrors x, P3 y, P4 both). So in our own frame the enemy with index k^1 started top-right, k^2 bottom-left, k^3 bottom-right. View bullet chars are `GHKL` = players 1..4 (absolute labels); a flying bullet leaves its owner's paint behind it (used to infer heading).
11. **Bullet lanes:** wall-free row/column segments are at most 39 cells long (median 13), so a bullet can only cut us along such a lane, fired from a free cell of it.
12. **Building:** line of sight is blocked by objects on any tile the centre-to-centre segment touches, including both tiles at a corner pass (`board.LOS_TABLE`). Walls on enemy paint work; a wall that cuts enemy land can be swallowed by the resulting fill (target shows our paint, charge spent). A bomb exploding as air (not connected to its thrower) still cuts: the victim's cut-off part becomes air.
13. **Replay format** (`tools/replay.py`):
    - Header: `PBRP` u8 ver, u8 w, u8 h, u8 ?, u32 ticks, 8 bytes, u16 n, then n×[type,x1,y1,x2,y2] map rectangles (y flipped).
    - Per tick: u32 tick, u16 n, n × 5-byte rect diffs.
    - Type → char `~.#*1234ABCDHJKLUIOPQWER6789!@$%`. Replay labels are absolute (P1 = `1`/`A`).

## Bot architecture (`submission/PinkiSaanp/pinki/`)
- `board.py`: bitboards (Python ints, stride 101). Flood fill ~0.1–0.3 ms on 100×100. Includes `holes()`, `distance_field()` and cached disks.
- `world.py`:
  - **Localisation**: candidate positions after our action; static-wall mismatches (hard) decide "lost" (then a radius-7 search), tile changes (soft) only rank candidates.
  - Map memory, our area belief (predicts own fills, bullet lines and bomb disks beyond view, then enforces head connectivity), enemy paint masks.
  - Enemy heads and headings, foreign bombs, foreign bullets with headings.
  - The ability-charge model, with verification of whether our ability actually fired (failed builds back off `no_build` and resync the charge).
  - `cut_off()`: credible enemy pieces cut off by a removal (used by `planner.steal_by`).
- `planner.py`:
  - Loop candidates: start = head or nearby boundary cell, leg1 a cells, leg2 b cells, return straight then greedy to our area.
  - Ranked with 2D prefix sums, then up to 100 are evaluated exactly via `holes()` until the planning deadline (minus 6 ms for the frontier walk). Score = gain/cost minus a cut-risk penalty that grows with our area.
  - Bullet-return variant (shoot the last straight leg).
  - Bomb/bullet expansion evaluators, plus `steal_by()` (enemy cells cut off from their head).
- `tactics.py`: `evade` (enemy bomb blast simulation), `block_bullets` (wall in front of / body-block an enemy bullet that would cut us; heading from trailing paint), `wall_kill`, `bomb_kill`, `retreat_step` to thick land, `thin()`. Movement routines respect `move_block` (tiles where our moves keep failing).
- `brain.py`, in priority order each move:
  1. Evade bombs.
  2. Block bullets.
  3. Wall-kill.
  4. Bomb-kill.
  5. Retreat if an enemy head is within 7 and we're thin or looping.
  6. Old trail-threat retreat.
  7. Bullet loop-finish.
  8. Expansion bombs, wall-cuts, bullets.
  9. Attack visible trails.
  10. Plan loops (no new loops for 12 moves after an enemy is seen close; smaller loops as area grows; tiny loops after t=1880).
  11. `_hold` (stay inside, away from enemies).

  Also failed-move detection (avoid contested tiles; boxed in -> break a `*`), dash on straight runs, and a 28 ms planning budget. Debug options via `variant.json`: `trace` [t0,t1], `tracepos`, `nodeadline`, `top`, `risk_mult`, `atk_min`/`atk_score`.

## Results (official testkit, A/B = 128 games, seats rotated, per-game seeds, `tools/arena.py`)
Head-to-head standard error is ~400 tiles per 128 games: outcomes are near-binary steal chains, so only big effects show.

| Change | Result |
|---|---|
| Startup: answer move 1 before imports, fast `Board`/`World` init, `-S`, `gc.freeze` | move 1 86 ms -> 14 ms (cold), no TLE |
| Wall builds: exact LOS table, *credible* steals (cut piece must be sealed by tiles we have seen), fill-swallowed walls count as built, retry back-off, move/build deadlock breaking | **vs PinkiV1: 4470 vs 1587 avg, 93-35, +2883 +- 393** (V1 wasted ~400 moves/game on failing walls) |
| Bullet heading from trailing paint, body-blocking, 32 ms planning budget | vs V2 +195 +- 393 |
| Localisation: only static walls may declare us lost (own bomb blasts used to trip it) | lost ticks 73 -> 1 per game; vs V2 +89 +- 385 |
| `top=100` exact loop evaluations (until deadline, 6 ms reserved for the frontier walk) | opening +23% area (t=300/450/600: 1355/1880/2390 vs 1000/1374/1946); vs V2 +601 +- 425; vs PlainLoop field 4093 vs 3488 avg |
| Frontier walk as layered bitboard BFS with early stop; planning budget 28 ms; staged loading | opening t=600/800: 2533/3197 (unseeded); idle-machine worst move ~27 ms (one 60 ms OS spike), cold first moves < 19 ms |
| **Final build vs PinkiV1 + wall_hug + random (128 games)** | **4854 vs 1620 avg, win 73% vs 20%, h2h 100-28, +3233 +- 400, 0 TLE** |
| **Final build vs PinkiV2 + wall_hug + random (256 games)** | **3447 vs 2890 avg, win 51% vs 43%, h2h 140-116, +558 +- 295** |

Tried and dropped (vs V2, +-~400 each): heavy-blob relocation -226, BFS-neck crossing w2 -178 / w5 -4435, perimeter term +282/-304, visible-shooter line dodge +68, endgame centre hold +82, small loops on alert +49, bomb steal-awareness +380/+461 alone but -115 +- 278 on top of top=100 (256 games), lane plugs -150, cut-before-bomb ordering -115, head_age 4 -29, steal booking -88 (slow), risk x4 -147, snipe +117, bomb-split dodge -169, attack thresholds 30 +362 / off -316 (attacks are worth it). Code for these is in git history (commit a095ac3).

## Contest sprint (field: us + HolyLike + PinkiV2/PinkiShip + wall_hug, 64 games, seeded, rotated)
- **Shipped (final):** branch code at defaults = the previous build plus a decide watchdog (past 40 ms: just follow the plan / go home) and time bounds on the attack and wall-cut steal scans; every new feature below is an option, off. Freeze A/B vs the previous zip (64 games, HolyLike + RandChaos field): win 37.5% vs 25.0%, place 2.31 vs 2.52, last 25% vs 27%, tiles 2312 vs 1956, 0 TLE/errors; pooled with the wall_hug-field run (128 games): win +13.3 +- 6.8 pts, place -0.38 +- 0.16 (better). Idle-machine worst move 24 ms.
- `baselines/HolyLike` (centre-biased, steal-aware bombing) stands in for the_holy_one; `baselines/PinkiShip` is the previously shipped zip.
- Tried as a bundle (options, off by default): `bomb_min` 0 (any positive expansion bomb), `widen` 1.0 (bomb gain counts tiles that thicken 1-wide necks), `bombtimer` 1 (per-enemy bomb cooldown from seen throws; keep 6+ away from an enemy whose bomb may be ready). vs HolyLike looked +658 ± 513, but the freeze A/B vs the shipped build lost: 30-34, −699 ± 476 (64 games, 0 TLE, 0 errors). Not shipped.
- `baselines/RandChaos`: random walker that fires every ability as soon as it has charge (stand-in for the contest's random_walker). The shipped build won only 52% of games in a RandChaos×2 + random field.
- **Own-area belief was badly wrong** (replay check: `bsim` re-runs `World` on a replay with the logged actions, `tracepos` logs area per tick). Fixed in `world.py`: (1) a bullet/bomb on a tile hides but keeps its paint (our own bullet on the trail tile behind us used to "cut" our head off: belief 2600 -> 0); (2) detached own land is dropped only next to a cut seen happening in view (stale tiles coming into view used to wipe thousands of believed tiles); (3) steals by our bullets/bombs (credible `cut_off`) and bomb kills are booked. Still open: big steals we never see (belief can't know) and thefts out of view (`staleprop` option tried: helps some games, wrecks others; off).
- But shipping them did not pay: with fixes (1)-(3) win rate was flat (mixed field 29% vs 27%, but mean place 2.51 vs 2.36, last 29% vs 18%); adding `restore` (take back dropped land when it shows up as ours) lost badly (9% vs 34% wins). All are options, off by default (`objkeep`, `freshcut`, `book`, `restore`, `staleprop`).
- Scoring is by 1st places (maybe OpenSkill later): judge A/Bs with `tools/ranks.py` (win rate with ties split, mean placement, last-place rate, tiles; `--pair` for two runs on the same seeds).
- Rank-aware endgame (`rank` tick: hold when "clearly 1st") is wrong-footed by what we cannot see: in the 18 games it held, it was really 1st in only 4 (vs base on the same seeds: win -4.7 +- 7.9 pts, place +0.24 worse). Off. `rankw` (steal worth 1.3x when it changes placements): vs base on the same seeds win -6.3 +- 8.9 pts, place +0.23 worse. Off.
- Standard-bot field (`HLoop`, `HAggro`, kit `random`, 48 games, same seeds): shipped build wins 62.5%, place 1.77, last 12.5%; losses are mostly HAggro walls/bullets/trail crossings while we are on an excursion, with HLoop then winning. Tweaks vs that base: `atk_radius` 10 + `atk_min` 4: 35% wins (much worse); `risk_mult` 0.6: -4 +- 9 pts; `trap`+`wkdodge`: -6 +- 11 pts; `guard`+`fp`: -12.5 +- 8 pts; `chaos` 1.0: -14.6 +- 8 pts. All off: against standard bots the plain build is best. Vs kit `random` (random_walk) x2 + HLoop (48 games): 89.6% wins, place 1.17, last 2.1%, 4592 tiles vs random's 426.
- A/A check (branch at defaults vs the shipped build, 64 games) came out 35.9% vs 21.9% wins: 64-game A/Bs swing by 10-15 win-% points on noise alone.
- Off-by-default options (`guard`, `fp`, `trap`, `late`, `endavoid`, `chaos`, `bombtimer`, `widen`, `bomb_min` 0) all lost or were flat.

## Highest-value next steps
1. Losses are dominated by bullets and bombs cutting necks out of view (77% of cutters are >10 cells from our head); the head is usually on the light side of a cut. No structural defence tried so far beat the noise.
2. Expansion speed is the most reliable lever (deterministic, transfers to any field): `tools/opening.py` measures it in seconds. Better loop pre-ranking or cheaper exact evaluation should pay off.
3. Our land belief drifts (steals out of view are not booked; robberies out of view are not seen). Booking credible steals was too slow as implemented.
4. Keep `PINKI_LOG` stderr light (the judge captures it; it's fine but don't spam).
