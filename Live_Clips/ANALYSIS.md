# Live clips: opponent intel (contest field, collected 2026-10-25)

Viewer colours: P1 red, P2 brown, P3 yellow, P4 green. Some screenshots are cropped or hand-marked (the green circle in 5.jpeg marks a cut point).

## the_holy_one (confirmed opponent)
- 10.jpeg: as P1 vs wall_hug + 2× aggro_wall_hug it scored **6462** (the others 0/0/93).
- 11.jpeg: as P4 vs 3× random_walk it scored **5105** (the others 320/530/152).
- It is very likely the red P1 in 1.jpeg (replay 86, t=2000), where red owns almost the whole map.
- Images 3→9 (one game): brown dominated the top half. Red sliced it with long straight lines (bullet/dash lanes) and cut brown's territory near brown's head (7.jpeg → 8.jpeg: a short brown hook at bottom-left, then the whole brown region turns red). So it **steals whole territories via neck/head cuts** and then holds them.
- The contest field also contains `aggro_wall_hug` (a wall hugger that also attacks) and the built-in `wall_hug`/`random_walk`.

## Videos/76/76.pbrp (decode with `python3 tools/replay.py Live_Clips/Videos/76/76.pbrp --scores`)
Four players: three strong (P1/P2/P3) and P4 weak (dead by t≈385). Final: **P2 4303**, P3 812, P1 41.

| Tick | Territory (P1 / P2 / P3 / P4) |
|---|---|
| 300 | 902 / 1042 / 614 / 16 |
| 600 | P3 3938 |
| 1400 | P1 5323 |
| 1600 | P2 6663 |
| 2000 | P2 4303 |

- **Bombs are used at nearly the maximum rate:** P1 123, P2 110, P3 118 bombs (the cap is about 125 per game). Walls: 96 built in total.
- **Steal mechanisms** (18 swings of more than 700 tiles):
  - **13 coincide with a bomb explosion.** In those, the cutter's head is usually **16–28 cells from the victim's head**, so bombs cut territory *necks*, not just isolate heads.
  - 2 are wall cuts (t1332: two walls placed next to the victim's head, steal 2879; t1734).
  - The rest are bullets crossing lanes (t1009, t1266: steal 3235 from 64 cells away).
- **Endgame chain at the map centre:** at t1408, t1419 and t1420, three heads within 3–4 cells of each other trade bombs. Each steal is about 6300 tiles, and the last bomber wins.
- **Expansion speed:** these bots have about 900–1050 tiles at t=300. PinkiSaanp's opening reaches about 1355 at t=300, so we out-expand them early; games are decided by steals.
