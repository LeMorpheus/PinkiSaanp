# PinkiSaanp: handoff for the Codewars "Agent Showdown" bot

Goal: **win** the hackathon. 4-player paper.io-like game, 100×100 map, 2000 moves, 11×11 view.
Score = painted tiles at the end. Language: Python 3 (judge image `python:3.12-slim`), 100 ms per move.

## Repo layout
| Path | What |
|---|---|
| `submission/PinkiSaanp/` | **The contest bot** (`manifest.json`, `bot.py`, `pinki/*.py`). Zip this folder's *contents*. |
| `PinkiSaanp_submission.zip` | Ready-to-upload archive (manifest.json at zip root). Rebuild after changes. |
| `baselines/PinkiV1/` | Frozen earlier build (opponent for A/B tests; `variant.json` = seed 7). |
| `Rules/` | Official contest README + official test kit (`testkit` Linux binary, starter bots, web visualizer). |
| `tools/replay.py` | **Reverse-engineered `.pbrp` replay decoder**: full board for every tick. |
| `tools/arena.py`, `tools/*.sh` | Run many testkit games in parallel and aggregate scores (written for WSL paths; adapt `SRC`/`KIT`). |
| `probes/` | Scripted probe bots used to learn engine mechanics + `map_abs.txt` (the map, extracted from the binary). |
| `pinkisaanp/`, `sim/`, `tests/`, `main.py`, `STRATEGY.md` | **Legacy** bot for a different game (MiniAICups paper.io). Template only, not used. |

## Submission
The README says a submission is a directory with `manifest.json` (`{"run": ["python3", "bot.py"]}`), uploaded as a `.zip` / `.tar.gz`. Build it from inside the folder so `manifest.json` sits at the archive root:
```bash
cd submission/PinkiSaanp && rm -rf pinki/__pycache__ variant.json && zip -r ../../PinkiSaanp_submission.zip manifest.json bot.py pinki
```
Never ship `variant.json` (it is only for local A/B tests). Logging goes to stderr (allowed, captured by the judge). Turn it off with `PINKI_LOG=0`.

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
10. **Replay format** (`tools/replay.py`):
    - Header: `PBRP` u8 ver, u8 w, u8 h, u8 ?, u32 ticks, 8 bytes, u16 n, then n×[type,x1,y1,x2,y2] map rectangles (y flipped).
    - Per tick: u32 tick, u16 n, n × 5-byte rect diffs.
    - Type → char `~.#*1234ABCDHJKLUIOPQWER6789!@$%`. Replay labels are absolute (P1 = `1`/`A`).

## Bot architecture (`submission/PinkiSaanp/pinki/`)
- `board.py`: bitboards (Python ints, stride 101). Flood fill ~0.1–0.3 ms on 100×100. Includes `holes()`, `distance_field()` and cached disks.
- `world.py`:
  - **Localisation**: candidate positions after our action, scored against static walls and the previous frame.
  - Map memory, our area belief (predicts own fills, bullet lines and bomb disks beyond view, then enforces head connectivity), enemy paint masks.
  - Enemy heads and headings, foreign bombs, foreign bullets with headings.
  - The ability-charge model, with verification of whether our ability actually fired.
- `planner.py`:
  - Loop candidates: start = head or nearby boundary cell, leg1 a cells, leg2 b cells, return straight then greedy to our area.
  - Ranked with 2D prefix sums, then the top ~24 are evaluated exactly via `holes()`. Score = gain/cost minus a cut-risk penalty that grows with our area.
  - Bullet-return variant (shoot the last straight leg).
  - Bomb/bullet expansion evaluators, plus `steal_by()` (enemy cells cut off from their head).
- `tactics.py`: `evade` (enemy bomb blast simulation), `block_bullets` (wall in front of an enemy bullet that would cut us), `wall_kill`, `bomb_kill`, `retreat_step` to thick land, `thin()`.
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

  Also failed-move detection (avoid contested tiles), dash on straight runs, and a 50 ms budget.

## Results so far (official testkit)
- vs `wall_hug`/`random`: 6870 and 2433 tiles; baselines near 0. Avg ~1–2 ms/move, max 83 ms once (planning spike).
- 4-way self-play with variants: chaotic. Whole territories change hands (bullets through thin trails; bombs next to heads). The original PinkiSaanp copy scored 0 in two games, while a variant got 6739.
- The **latest edits are UNTESTED**: `block_bullets`, enemy bullet tracking, area-scaled loop sizes, `RISK_K` 1/40000, endgame caution. Run the arena first; fix any exceptions (they're caught and logged as `decide error` in stderr logs).

## Highest-value next steps
1. **Startup timeout risk.** One TLE was seen, probably the first move including Python import + `Board` init (10k big-int bits, neighbour tables). Measure the startup cost and make it lazy/faster (e.g. build `bit` via `1 << pos` on demand, precompute less). The 100 ms limit applies per move. Also keep worst-case moves < ~50 ms (log lines `slow t=`).
2. **Defence against cuts** (the main way to lose everything):
   - Keep the head in thick land (≥3 own neighbours) whenever enemies are near.
   - Shorten exposure (trail length × time) as area grows.
   - Block enemy bullets with walls.
   - Consider walling the perimeter facing enemies (walls stop bullets; up to 30 charges, +1 per 5 moves; break our own walls with `X`).
   - Dodge bombs (`tactics.evade`, single-step lookahead).
3. **Offence.** Steals transfer whole territories:
   - Snipe with bullets through enemy land/trails (`best_bullet` includes `steal_by`; it is conservative when the enemy head is unseen).
   - Wall-kill heads hanging on one own tile.
   - Bomb heads (aim at a predicted position 2–3 moves ahead; a bomb in their path also blocks them).
   - Late-game steals are decisive, so prioritise the leader and the endgame.
4. Validate in A/B matches vs `baselines/PinkiV1` + `wall_hug` + `random` (rotate seats); compare average tiles and win%.
5. Keep `PINKI_LOG` stderr light (the judge captures it; it's fine but don't spam).
