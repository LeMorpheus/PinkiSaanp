#!/usr/bin/env python3
"""Starter Bot for Codewars.

Protocol Overview:
- Each turn, the game sends an 11x11 grid (11 lines of 11 characters each).
- Your bot is ALWAYS centered at row 5, col 5 (index [5][5]) and represented as '1'.
- You must reply with EXACTLY ONE line specifying your action, and then FLUSH stdout.
- Time limit per move: 100 milliseconds. If you exceed this or don't flush, TLE occurs!

Grid Tile Legend:
  '.' - Empty floor
  '#' - Indestructible wall
  '*' - Destructible wall / block
  '~' - Void / deadly hazard
  '!' - Active bomb
  '1' - You (center: [5][5])
  '2', '3', '4' - Opponents
  '@', '$', '%' - Paint / territory tiles

Basic Actions:
  'W' - Move Up
  'A' - Move Left
  'S' - Move Down
  'D' - Move Right
  'I' - Idle / Stay in place

Abilities (when off cooldown):
  'J<dir>' - Jump (e.g. 'JD')
  'G<dir>' - Gun / shoot (e.g. 'GW')
  'X<dir>' - Shield / dash (e.g. 'XS')
  'B <dx> <dy>' - Place Bomb (e.g. 'B 1 0')
  'C <dx> <dy>' - Paint / Color burst
"""
from __future__ import annotations

import random
import sys

VIEW_SIZE = 11
CENTER = VIEW_SIZE // 2  # Index 5 is your bot's position

# Obstacles you generally should not walk into
OBSTACLES = set("#*~!234")

# Cardinal directions: (Action name, row_delta, col_delta)
DIRECTIONS = [
    ("W", -1, 0),  # Up
    ("A", 0, -1),  # Left
    ("S", 1, 0),   # Down
    ("D", 0, 1),   # Right
]


def read_grid() -> list[str] | None:
    """Reads 11 lines representing the local vision grid around your bot."""
    grid = []
    for _ in range(VIEW_SIZE):
        line = sys.stdin.readline()
        if not line:
            return None  # Game over / EOF
        grid.append(line.rstrip("\r\n"))
    return grid


def choose_action(grid: list[str], turn: int) -> str:
    """Determine the next move given the 11x11 vision grid."""
    safe_moves = []

    for action, dr, dc in DIRECTIONS:
        target_row = CENTER + dr
        target_col = CENTER + dc

        if 0 <= target_row < VIEW_SIZE and 0 <= target_col < VIEW_SIZE:
            tile = grid[target_row][target_col]
            if tile not in OBSTACLES:
                safe_moves.append(action)

    if safe_moves:
        # Move safely towards free spaces
        return random.choice(safe_moves)

    # Fallback to Idle if trapped
    return "I"


def main():
    turn = 0
    while True:
        grid = read_grid()
        if grid is None:
            break  # End of match

        action = choose_action(grid, turn)

        # IMPORTANT: Always flush stdout immediately!
        print(action, flush=True)

        turn += 1


if __name__ == "__main__":
    main()
