# PinkiSaanp

A Paper.io bot for head-to-head hackathon play. It uses a finite state machine on top of risk-aware A\*, bitboard threat maps and exact loop simulation. It is pure Python 3 with no dependencies.

```
EXPANDING_SAFELY ──▶ ATTACKING ──▶ RETREATING ──▶ DEFENDING
      (all four re-evaluated every tick; see STRATEGY.md)
```

## Run it

```bash
python -u main.py
```

That command speaks the MiniAICups protocol (`References/paperio`). For a generic grid engine, use:

```bash
python -u main.py --protocol generic --objective territory
```

In generic mode the bot reads one JSON state per line and answers `UP` / `DOWN` / `LEFT` / `RIGHT`. Add `--y-down` when UP decreases `y` (screen coordinates). Add `--budget 0.05` to tighten the per-move search time. Missing headings are inferred from the previous tick. The schema is documented in `pinkisaanp/adapters.py`. From Python:

```python
from pinkisaanp import PinkiSaanp, GenericAdapter, BotConfig
bot, adapter = PinkiSaanp(BotConfig.territory()), GenericAdapter(y_down=True)
move = adapter.command(bot.decide(adapter.view(state_dict)).direction)   # "UP"
```

## Test and benchmark

```bash
python -m unittest tests.test_core
```

The tournament runs a 6-bot free-for-all against the baseline bots:

```bash
python -m sim.tournament -v -j 6 --games 24 --lineup pinki,greedy,cautious,hunter,hunter,cautious
```

To write a replay (pink & white viewer) for one game:

```bash
python -m sim.tournament --games 1 --html replays/demo.html
```

To play in the official reference engine, first install its dependencies with `pip install "pyglet<2" networkx`, then run:

```bash
python sim/reference_match.py --games 4 --lineup pinki,hunter,cautious,greedy,simple_bot,hunter
```

## Layout

| Path | What it is |
|---|---|
| `pinkisaanp/geometry.py` | Bitboard grid: dilation, flood fill, capture, BFS layers |
| `pinkisaanp/analysis.py` | Per-tick threat/influence maps, enemy home times, pockets, rammer map |
| `pinkisaanp/pathfinding.py` | Direction-aware, risk-weighted A\* with hard termination bounds |
| `pinkisaanp/planner.py` | Candidate routes (home / trail-cut / ram / rectangle loops / defend) and exact evaluation |
| `pinkisaanp/fsm.py` | The four-state machine with hysteresis |
| `pinkisaanp/bot.py` | Decision loop, time budget, fallback survival move |
| `pinkisaanp/adapters.py` | MiniAICups and generic protocol adapters |
| `pinkisaanp/config.py` | Every weight and threshold |
| `sim/` | Local engine (reference rules), baseline opponents, tournament, viewer |
| `STRATEGY.md` | Blueprint, math, FSM, edge cases, benchmark numbers |
