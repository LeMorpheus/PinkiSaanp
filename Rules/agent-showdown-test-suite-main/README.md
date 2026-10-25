# Codewars Player Testkit & Visualizer

A self-contained testing suite and visualizer for developing and benchmarking bots for Codewars.

Supports **Linux**, **macOS** (Intel & Apple Silicon), and **Windows** (Docker Desktop / WSL2).

---

## ⚡ Quick Start

### 1. Requirements
- **Docker** (recommended for all platforms: [Docker Desktop](https://www.docker.com/products/docker-desktop/))
  *Note: On Linux, you can also run `./testkit` directly without Docker if you have Python 3 installed.*

### 2. Run your first match
In your terminal / command prompt, run:

- **Linux / macOS:**
  ```bash
  ./play.sh starter_bot random_walk
  ```
- **Windows (CMD / PowerShell):**
  ```cmd
  play.bat starter_bot random_walk
  ```

*(The first run will automatically build the lightweight Docker image in a few seconds).*

You will see the match play out and output something like:
```text
======================================================
                  MATCH RESULTS
======================================================
Player 1 (starter_bot): Moves: 2000, TLEs: 0, Avg: 1.2ms, Max: 6.4ms
Player 2 (random_walk): Moves: 2000, TLEs: 0, Avg: 1.1ms, Max: 5.8ms
...
Replay ID: 1
Saved replay to: out/replays/1.pbrp
======================================================
```

### 3. Watch the replay in the visualizer
Start the web visualizer:

- **Linux / macOS:**
  ```bash
  ./view.sh
  ```
- **Windows:**
  ```cmd
  view.bat
  ```

Then open your browser at **[http://localhost:8000](http://localhost:8000)**.
Enter the **Replay ID** (e.g. `1`) and click **Load Replay**!
Use the timeline scrubber, playback speed controls, and music toggle.

---

## 🤖 Writing Your Bot

All participant bots live inside the `my_bots/` directory.

Each bot is a folder containing:
1. Your source code / script.
2. A `manifest.json` telling the engine how to build and run your bot.

### Starter Bots Included:
- `my_bots/starter_bot/`: Python starter template.
- `my_bots/starter_bot_cpp/`: C++ starter template.

### Example: Python Bot (`my_bots/my_python_bot/manifest.json`)
```json
{
  "run": ["python3", "bot.py"]
}
```

### Example: C++ Bot (`my_bots/my_cpp_bot/manifest.json`)
```json
{
  "build": ["make"],
  "run": ["./bot"]
}
```
*(The testkit will automatically run your build command before the match if the binary is missing).*

### Example: Java Bot (`my_bots/my_java_bot/manifest.json`)
```json
{
  "build": ["javac", "Bot.java"],
  "run": ["java", "Bot"]
}
```

### Example: Node.js Bot (`my_bots/my_js_bot/manifest.json`)
```json
{
  "run": ["node", "bot.js"]
}
```

---

## 📜 Game Protocol & Rules

### Turn Loop
At each tick of the match:
1. The game sends an **11x11 grid** (11 lines of 11 characters) over standard input (`stdin`).
2. Your bot is **ALWAYS centered** at row 5, col 5 (`grid[5][5]`) and represented by `'1'`.
3. Your bot must compute an action and write **EXACTLY ONE line** to standard output (`stdout`), followed by an immediate **FLUSH**.
4. Time limit: **100 milliseconds** per move.

> ⚠️ **CRITICAL:** Always flush stdout after printing your move!
> - In Python: `print(action, flush=True)` or `sys.stdout.flush()`
> - In C++: `std::cout << action << "\n" << std::flush;`
> - In Java: `System.out.println(action); System.out.flush();`
> - In Node.js: `console.log(action);`

If your bot takes longer than 100ms or fails to flush, a **Time Limit Exceeded (TLE)** is recorded and your move defaults to Idle (`I`).

### Vision Grid Tiles
| Symbol | Meaning |
|---|---|
| `.` | Empty passable floor |
| `#` | Indestructible wall |
| `*` | Destructible block |
| `~` | Void / hazard (falling into this kills you) |
| `!` | Active bomb |
| `1` | You (always in the center: `grid[5][5]`) |
| `2`, `3`, `4` | Opponent bots |
| `@`, `$`, `%` | Paint / territory markers |

### Actions
- **Movement:**
  - `W` - Move Up
  - `A` - Move Left
  - `S` - Move Down
  - `D` - Move Right
  - `I` - Idle / Stay in place
- **Abilities:**
  - `J<dir>` - Jump (e.g. `JD`)
  - `G<dir>` - Gun / shoot projectile (e.g. `GW`)
  - `X<dir>` - Shield / dash (e.g. `XS`)
  - `B <dx> <dy>` - Drop bomb at relative coordinate (e.g. `B 1 0`)
  - `C <dx> <dy>` - Paint blast at relative coordinate (e.g. `C 0 -1`)

---

## ⚙️ Advanced CLI Options

You can pass standard flags through `./play.sh` or `play.bat`:

```bash
# Test with 4 distinct bots
./play.sh starter_bot wall_hug random_walk starter_bot_cpp

# Change per-move time limit to 150ms
./play.sh -t 150 starter_bot random_walk

# Play a 500-move match
./play.sh -n 500 starter_bot random_walk

# Enable verbose move-by-move tracing to stderr
./play.sh -v starter_bot random_walk
```

### Checking Bot Error Logs
Stderr output from your bots is automatically saved to:
`out/logs/p1_<name>.log`, `out/logs/p2_<name>.log`, etc.
Check these files if your bot crashes or outputs debug statements.

---

## 🐳 Docker Compose Alternative

If you prefer `docker compose`:

```bash
# Start the visualizer
docker compose up visualizer

# In another terminal, run a match
docker compose run --rm play starter_bot random_walk
```
