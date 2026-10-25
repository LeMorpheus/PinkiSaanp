# Codewars Test Kit

Run your bot against others in the same sandbox and game binary the judge uses.

## Requirements
Docker. That's it.

## Quick start
```bash
docker build -t codewars-testkit .
mkdir -p my_bots && cp -r path/to/your_bot my_bots/
./play.sh your_bot                     # 4 copies of your bot
./play.sh your_bot random_walk         # your bot vs a built-in bot (cycled to 4 players)
./play.sh your_bot bot_b bot_c bot_d   # explicit lineup: P1..P4
```
Bots resolve from `./my_bots` first, then the built-in bots.

## Submission format
A directory with a `manifest.json`:
```json
{
  "build": ["g++", "-O2", "-o", "bot", "bot.cpp"],
  "run": ["./bot"]
}
```
- `build` is optional. It may use multiple processes. Its stdout goes to stderr, so don't rely on it.
- `run` is the command executed per player. The game talks to your bot over **stdin/stdout**.
- `run` can also be `{"argv": [...], "processes": true}` if you need child processes.
- Symlinks are rejected.
- Available toolchains: g++, Python 3, Java 17, Node.js.

# The Game
Now that you have the debugging environment set up, we can dive into the rules and mechanics of the game itself. The game involves [paper.io-like](https://paper.io) mechanics of expanding your territory by growing out your area using paint, and there are five abilities and special actions which you can use: [dash](#dash), [bombs](#bombs), [bullets](#bullets), [building](#building), and [breaking](#breaking). Your task is to occupy the maximum area you can on the map at the end of the game, where each game lasts for $2000$ individual moves. Turns are parallel, and all four [players](#players) in a match perform one [action](#actions) simultaneously in one move.
## Map
The map is basically the board you are playing the game on. The map consists of a $100 \times 100$ grid of tiles. The initial state of these tiles is known to you at the start of the game itself, and can be found at `map.txt` in this repository, in the format of the [input](#input), but for all $100 \times 100$ tiles.
### Field of View
Inside the $100 \times 100$ tile grid, you are only given an $11 \times 11$ tile grid as the [input](#input) every move surrounding your player at the center. This input will contain [void](#void) tiles to depict regions which are outside the map, if you are close to the boundary. This means that throughout the game, you are unaware of the activities of other players outside this sub-grid, but you can intelligently predict their behavior using probabilistic models and remember tiles in your path as your player navigates the map throughout the game.
### Players
From your perspective, your player is always Player 1, represented with the character `1`, with your area having the [paint](#painting) color represented by the character `A`.

Your three opponents are Player 2, Player 3, and Player 4, having the characters `2`, `3`, and `4`, and their [paints](#painting) being of the characters `B`, `C`, and `D`, respectively.

> [!NOTE]
> In your replays, it may not be the case that you actually are Player 1. The game shifts the characters for your perspective such that you are Player 1 with the tile character `A` and the others are not. This is done for your convenience so that you do not have to deal with specific cases for each of the four scenarios.
### Spawn-points
Four players begin, in other words, spawn, near each of the corners of the grid, where your player is on the top-left corner. Precisely, from the top-left corner, including the [wall](#walls) but not including the [void](#void), your player is on the $4^\text{th}$ horizontal and $4^\text{th}$ vertical tile. This is your spawn-point.

So for the $100 \times 100$ grid, if the top-most and left-most tile has a coordinate of $(1,1)$ and tiles are represented by $(i,j) \mid (1 \leq i,j \leq 100)$ where $i$ increases rightwards along the x-axis and $j$ increases downwards along the y-axis, your player spawns at $(4,4)$.

> [!NOTE]
> Just like before, the game process internally flips your output and input for you so that from your perspective you always start on the top-left corner, although on the replay you may not actually be on that corner.

As you can see in `map.txt`, the initial positions for all the players are as follows, even in your perspective:
- **Player 1:** Top Left
- **Player 2:** Top Right
- **Player 3:** Bottom Left
- **Player 4:** Bottom Right
### Walls
Walls are tiles that you cannot pass through. You cannot pass through walls by [movement](#movement) nor can you do so by [dashing](#dash). Your [bullets](#bullets) will break once they reach a point where they cannot cross a wall, inducing no harm to the wall. However, your [bombs](#bombs) can be placed across walls. 

There are two kinds of walls:
- **Unbreakable Walls:** These walls are a part of the map and cannot be placed or broken by players. Covering these walls with paint in [Area Fills](#area-fills) does not break them, and they remain inside the area.
- **Breakable Walls:** These walls can be both a part of the map or placed by a player. They can be both placed and broken by players. Covering these walls with paint in [Area Fills](#area-fills) breaks them, so it can be an effective way of breaking these walls if possible.

The map starts off with some walls of both kinds already placed initially. This initial distribution is reflection-symmetric, i.e., the map is symmetrical along the x-axis, y-axis, and both diagonals. This ensures fairness across players.

Unbreakable walls are represented by the `#` character and breakable walls are represented by the `*` character in the [input](#input).
### Air
Air is essentially a tile which hasn't been painted by anyone and is not a part of anyone's area. These tiles allow [movement](#movement), [dashing](#dash), placement of [bombs](#bombs), traversal of [bullets](#bullets), and [placing walls](#building). Most of the map starts out as air. Air is represented with the 'dot' character `.` in the [input](#input).
### Void
Void represents the tiles outside the map. These tiles are inaccessible, and you cannot build or place bombs there. They are represented by the `~` character in the [input](#input).
## Painting
Paint consists of the tiles which are a part of your area. It is ultimately the number of tiles which have your paint (i.e., your area) at the end of the game which decides your standing in the game. All the [actions](#actions) you can perform on air tiles can be done on paint tiles as well. Air and paint tiles are not considered objects, whereas all other tiles are considered objects.
### Area Fills
Your player leaves a trail of paint whenever they move, and larger areas of paint can be formed by closing loops. In principle, your area is always simply connected, i.e., throughout the game, the topology of the area owned by you is such that there are no holes. So, if you enclose an area such that there are holes inside it, those enclosed regions get filled up with your paint, acting as a way for you to gain area more quickly. You can also use [bullets](#bullets) and [bombs](#bombs) to assist yourself with this. 

> [!TIP]
> Taking a larger excursion to enclose an area can give you significantly more territory, but it also makes you more vulnerable to cuts causing your area to get stolen.
### Cutting
Your area is also always connected to you. Any part of your area that gets disconnected due to the actions of other players (through movement, bombs, placing walls, bullets, etc.) is removed from you and instantly reclaimed by the player responsible for this breakage. Therefore, stealing your foe's area by cutting it is a very effective method to increase your own area. Walls and bombs also contribute to cuts.

> [!TIP]
> This mechanic exists to promote aggressive (and interesting) play. This also means that it is a good idea to place walls and take other measures to protect your territory from being stolen.
## Actions
Actions are what your player does. Every move, your player performs one action. Some actions have specific properties which the agent needs to keep track of through resource management. There are seven types of actions that your player can perform: [idling](#idle), [moving](#movement), [dashing](#dash), [bombing](#bombs), [shooting](#bullets), [building](#building), and [breaking](#breaking).
### Idle
Idling is an action which makes the player stay where they currently are without placing any objects in that turn, essentially doing nothing. In some specific scenarios, your best move of choice may be to idle.

Idling is also the default fallback action selected in case of an invalid or illegal [output](#output) or when exceeding the time limit. In case two or more players try to occupy the same tile, none of their actions take place and they all idle. In an attempt to place a bomb or wall over a tile which does not support placing it, the fallback action is also idle. Idling also occurs when your player tries to move into a wall.

To idle for your turn, your [output](#output) should be either `I` or `i`, and then you must flush your output stream.
### Movement
For most of your moves, your player will be moving. Movement is simply the process of shifting your player by one tile in one of the four cardinal directions: up, left, down, or right.

In other words, for the $100 \times 100$ grid, if the top-most and left-most tile has a coordinate of $(1,1)$ and your current player coordinate is $(i,j) \mid (1 \leq i,j \leq 100)$ where $i$ increases rightwards along the x-axis and $j$ increases downwards along the y-axis, then:

- **Moving up** shifts your player to $(i, j - 1)$ if possible without any collisions.
- **Moving left** shifts your player to $(i - 1, j)$ if possible without any collisions.
- **Moving down** shifts your player to $(i, j + 1)$ if possible without any collisions.
- **Moving right** shifts your player to $(i + 1, j)$ if possible without any collisions.

Here, a collision is the condition that occurs when more than one object contends for the same tile. Walls always contend for the tiles they are placed on.

> [!NOTE]
> In case your movement results in a collision with another object, you fall back to [idle](#idle).

Moving your player also leaves a trail of paint of their area color behind. So if a player is currently on tile $(i,j)$, and successfully moves on the next turn, the tile $(i,j)$ becomes painted with the player's area color and becomes part of the player's area (unless something else also happens to change that tile in that turn).

To move upwards, leftwards, downwards, or rightwards for your turn, your [output](#output) should be one of `W` or `w`, `A` or `a`, `S` or `s`, or `D` or `d`, respectively. After this one character, you must flush your output stream.
### Abilities
Abilities are unique actions that have special attributes to limit their usage per player. There are five common attributes to all abilities: maximum charge, initial charge, ability cost, cooldown time, and recharge time. At every stage of the game, your player holds a non-negative integer quantity called *charge* for each of the abilities. You must track your available charge for your abilities in your code to know when you can use them.

- **Maximum charge:** The maximum, fixed number of charges your player can recharge to and store at a time for an ability.
- **Initial charge:** The moment your player spawns, they start off with this number of charges already available for them to use.
- **Ability cost:** The amount deducted from your *charge* when using the ability. Note that your charge for an ability can never be less than zero. In case you try to perform an action whose ability cost exceeds your available charge, your output is ignored and you [idle](#idle) for that turn.
- **Cooldown time:** Two consecutive uses of the same ability must have at least $C$ other moves between them, where $C$ is the cooldown time. In case you attempt to use the ability while it is on cooldown, no cost is deducted and you simply [idle](#idle) for that turn.
- **Recharge time:** If not already at maximum charge, your ability charge passively increases by $1$ every $R$ moves, where $R$ is the recharge time. This means that there are $R - 1$ moves between recharges during which you do not gain charge.

Your charge for the next turn is the net result after all of these effects.
### Dash
Dashing (or jumping) is an [ability](#abilities). A dash makes your player go straight in a particular direction by a maximum of $3$ tiles. In case of a collision along those $3$ tiles, the player stops right before the first tile where such a collision would occur. A player can dash only up, left, down, or right.

In other words, a dash changes the current coordinate of the player $(x,y)$ by either $\Delta x = \pm d$ along the x-axis or $\Delta y = \pm d$ along the y-axis in one move, where $0 \leq d \leq 3$ is the largest integer such that for every intermediate step $k \mid 1 \leq k \leq d$, the corresponding tile has no collisions or contention with other objects (i.e., it remains as air or paint).

Just like [movement](#movement), dashing leaves a trail of paint behind the player across all tiles traversed. The attributes for the dash ability are listed below:

**Dash Attributes**

| Attribute | Value |
| :--- | :---: |
| Maximum Charge | $2$ |
| Initial Charge | $1$ |
| Ability Cost | $1$ |
| Cooldown Time | $5$ |
| Recharge Time | $20$ |
| Dash Distance | $3$ |

To dash on your turn, your [output](#output) must begin with `J` or `j`, followed by a character indicating the direction you wish to dash in: `W` or `w`, `A` or `a`, `S` or `s`, or `D` or `d`. For example, the output for a rightward dash is `JD`. After these two characters, you must flush your output stream. Note that if your output is valid but you cannot move any tiles due to an immediate collision ($d = 0$), your ability cost is still deducted.
### Bombs
Bombing is another [ability](#abilities). Bombs are objects that can be placed on tiles by your player within a throw radius of $4$ tiles around the player. After staying on the map for $2$ moves, these bombs explode and cover the surrounding area in a circle of paint of blast radius $3$, provided that after the explosion the painted region is connected to the player's existing area. Otherwise, it explodes to form a circle of air.

Precisely, if your player is currently at $(x,y)$, then you can place your bomb at any tile $(x+i,y+j)$ which satisfies all of the following criteria:
1. $0 < i^2 + j^2 \leq 4^2$
2. $(x+i, y+j)$ does not collide with any objects (e.g., it is not attempted to be placed on a wall or another player).

The bomb then remains placed for the next $2$ moves, after which it explodes. For a bomb placed at $(p, q)$, the explosion covers all tiles $(p + h, q + k)$ such that $h^2 + k^2 \leq 3^2$, and replaces all non-object tiles as well as breakable walls with either:
- Painted tiles of the color of the player who placed the bomb, if after the explosion there exists a connection between this newly painted region and the current area of that player.
- Air tiles, if such a connection is not possible.

> [!TIP]
> An important aspect of bombs is that they can be thrown across walls. This makes them useful for offense in cases where you are walled off by other players or the map. They are also a great resource to break breakable walls quickly.


**Bomb Attributes**

| Attribute      | Value |
| :------------- | :---: |
| Maximum Charge |  $1$  |
| Initial Charge |  $0$  |
| Ability Cost   |  $1$  |
| Cooldown Time  | $15$  |
| Recharge Time  | $15$  |
| Throw Radius   |  $4$  |
| Ignition Time  |  $2$  |
| Blast Radius   |  $3$  |
In your [Field of View](#field-of-view), placed bombs are represented according to the player who threw them (in your relative perspective):
- **Player 1:** `!`
- **Player 2:**`@`
- **Player 3:**`$`
- **Player 4:**`%`

To throw a bomb on your turn, your [output](#output) must begin with `B` or `b`, followed by two whitespace-separated signed integers determining the offset $(i, j)$ from the player's position at which you wish to place the bomb.
For example, a valid output to place a bomb is `B -2 3`. After this, you must flush your output stream. In case of an invalid or illegal output which does not meet the criteria, no cost will be deducted and your player will just [idle](#idle).
### Bullets
Bullets (or gunning) can be fired by players and are also an [ability](#abilities). Bullets traverse the map on their own in the direction you set while leaving a trail of paint behind, until they collide with an object and break. Bullets move at a speed of $3$ tiles per move.

A player can place a bullet one tile above, below, or to their left or right. The direction in which it is placed determines where the bullet will move: if placed on the left, it travels leftwards; if placed above, it travels upwards, and so on.

In other words, a player at $(x,y)$ can do one of the following:

- **Shoot Up:** Place a bullet at $(x, y - 1)$ which stays there for the next $1$ move, and then advances to $(x, y - 1 - 3k)$ on the $k^\text{th}$ move after the one-move wait, until it reaches $(x, m)$, where $m$ is the minimum y-coordinate the bullet can reach without colliding (where $m$ need not be a part of the arithmetic progression).
- **Shoot Left:** Place a bullet at $(x - 1, y)$ which stays there for the next $1$ move, and then advances to $(x - 1 - 3k, y)$ on the $k^\text{th}$ move after the one-move wait, until it reaches $(m, y)$, where $m$ is the minimum x-coordinate the bullet can reach without colliding (where $m$ need not be a part of the arithmetic progression).
- **Shoot Down:** Place a bullet at $(x, y + 1)$ which stays there for the next $1$ move, and then advances to $(x, y + 1 + 3k)$ on the $k^\text{th}$ move after the one-move wait, until it reaches $(x, M)$, where $M$ is the maximum y-coordinate the bullet can reach without colliding (where $M$ need not be a part of the arithmetic progression).
- **Shoot Right:** Place a bullet at $(x + 1, y)$ which stays there for the next $1$ move, and then advances to $(x + 1 + 3k, y)$ on the $k^\text{th}$ move after the one-move wait, until it reaches $(M, y)$, where $M$ is the maximum x-coordinate the bullet can reach without colliding (where $M$ need not be a part of the arithmetic progression).

Note that the trajectory of the bullet is such that, if at the present move the bullet is at position $(p,q)$ moving rightwards (for example), then the bullet moves to a position $(p + d, q)$, where $0 < d \leq 3$, and $d$ is the largest possible integer such that there are no collisions on the tiles $(p+i,q) \ \forall \ i \mid 0 < i \leq d$. All of these traversed tiles except the last one (which holds the bullet itself) are replaced with the paint of the player who fired the bullet. This is similar to how [dashing](#dash) works.

**Bullet Attributes**

| Attribute | Value |
| :--- | :---: |
| Maximum Charge | $3$ |
| Initial Charge | $0$ |
| Ability Cost | $1$ |
| Cooldown Time | $2$ |
| Recharge Time | $20$ |
| Bullet Speed | $3$ |

In case a bullet and a player contend for the same tile in a move, the player occupies that tile and the bullet breaks.

> [!TIP]
> Bullets are very useful for long-range gameplay and can be used to make quick and easy [cuts](#cutting) into your opponents' territory.

In your [Field of View](#field-of-view), active bullets are represented by a single character per player regardless of the direction they are traveling: `G` for Player 1 (your bullets), `H` for Player 2, `K` for Player 3, and `L` for Player 4. Because the character itself does not encode the bullet's orientation, your agent must infer a bullet's direction of travel by observing its position and paint trail across moves.

To shoot a bullet on your turn, your [output](#output) must begin with `G` or `g`, followed by a character indicating the direction you wish to shoot it in: `W` or `w`, `A` or `a`, `S` or `s`, or `D` or `d` for upwards, leftwards, downwards, and rightwards, respectively. For example, the output for an upward shot is `GW`. After these two characters, you must flush your output stream. Note that if your output is valid but the bullet cannot be placed on the initial adjacent tile due to a collision, your ability cost is not deducted and you [idle](#idle).
### Building
Building (or constructing) is the [ability](#abilities) of placing breakable walls. You can place breakable walls inside your build radius, as long as they are not behind other objects, which means you cannot build through walls, bombs, other players, etc.

Precisely, if your player is currently at $(x,y)$, then you can place a breakable wall at any tile $(x+i,y+j)$ which satisfies all of the following criteria:
1. $0 < i^2 + j^2 \leq 4^2$
2. $(x+i, y+j)$ does not collide with any objects (e.g., it is not attempted to be placed on another wall or player).
3. None of the tiles intersected by the line segment joining the midpoint of tile $(x,y)$ and the midpoint of tile $(x + i, y + j)$ contain objects.

Breakable walls do not belong to any particular player.

**Building Attributes**

| Attribute | Value |
| :--- | :---: |
| Maximum Charge | $30$ |
| Initial Charge | $5$ |
| Ability Cost | $1$ |
| Cooldown Time | $0$ |
| Recharge Time | $5$ |
| Build Radius | $4$ |

> [!TIP]
> Walls can be used to block off other players from certain areas and defend your territory from other players and their bullets.

To place a wall on your turn, your [output](#output) must begin with `C` or `c`, followed by two whitespace-separated signed integers determining the offset $(i, j)$ from the player's position at which you wish to place the wall.
For example, `C 3 -1`. After this, you must flush your output stream. In case of an invalid or illegal output which does not meet the criteria, no cost will be deducted and your player will just [idle](#idle).
### Breaking
Breaking is the act of destroying adjacent breakable walls directly, which is different from breaking them by surrounding them with your paint via [Area Fills](#area-fills). You need to be orthogonally adjacent to a breakable wall to break it, and there is no charge limit, cost, or cooldown restriction (i.e., the cost and cooldown are $0$).

In other words, if your player is at tile $(x,y)$, then you can break a breakable wall located at $(x+1,y)$, $(x,y+1)$, $(x-1,y)$, or $(x,y-1)$. Upon breaking it, the wall tile is replaced with paint of your color.

To break a wall on your turn, your [output](#output) must begin with `X` or `x`, followed by a character indicating the direction of the wall you wish to break: `W` or `w`, `A` or `a`, `S` or `s`, or `D` or `d` for just above you, on your left, just below you, and on your right, respectively. For example, the output for a downward break is `XS`. After these two characters, you must flush your output stream. Note that if your output is valid but there is no breakable wall at that adjacent tile, your player [idles](#idle).
## Input
I/O in Agent Showdown works like an interactive competitive programming problem where your agent reads the current state of its [Field of View](#field-of-view) from standard input (`stdin`) at the beginning of each move and responds with an [action](#actions) via standard [output](#output) (`stdout`). 

**Movement**

| Action                  |  Keybind  | Format | Coordinate Change | Description                             |
| :---------------------- | :-------: | :----: | :---------------: | :-------------------------------------- |
| [Idle](#idle)           | `I` / `i` |  `I`   |     $(0, 0)$      | Stay on the current tile and do nothing |
| [Move Up](#movement)    | `W` / `w` |  `W`   |     $(0, -1)$     | Move $1$ tile upwards                   |
| [Move Left](#movement)  | `A` / `a` |  `A`   |     $(-1, 0)$     | Move $1$ tile leftwards                 |
| [Move Down](#movement)  | `S` / `s` |  `S`   |     $(0, +1)$     | Move $1$ tile downwards                 |
| [Move Right](#movement) | `D` / `d` |  `D`   |     $(+1, 0)$     | Move $1$ tile rightwards                |

**Directional Abilities**

| Action                   | Action Keybind | Direction Keybind  | Format  | Example | Description                                              |
| :----------------------- | :------------: | :----------------: | :-----: | :-----: | :------------------------------------------------------- |
| [Dash](#dash)            |   `J` / `j`    | `W`, `A`, `S`, `D` | `J dir` |  `JD`   | Dash up to $3$ tiles in the chosen direction             |
| [Shoot Bullet](#bullets) |   `G` / `g`    | `W`, `A`, `S`, `D` | `G dir` |  `GW`   | Fire a bullet $1$ tile away in the chosen direction      |
| [Break Wall](#breaking)  |   `X` / `x`    | `W`, `A`, `S`, `D` | `X dir` |  `XS`   | Break an adjacent breakable wall in the chosen direction |

**Targeted Offset Abilities**

| Action                  | Action Keybind | Offset Parameters | Format  |     Range Constraint     | Example  | Description                                                  |
| :---------------------- | :------------: | :---------------: | :-----: | :----------------------: | :------: | :----------------------------------------------------------- |
| [Throw Bomb](#bombs)    |   `B` / `b`    |      $i, j$       | `B i j` | $0 < i^2 + j^2 \leq 4^2$ | `B -2 3` | Throw a bomb at offset $(i, j)$ from $(x, y)$                |
| [Build Wall](#building) |   `C` / `c`    |      $i, j$       | `C i j` | $0 < i^2 + j^2 \leq 4^2$ | `C 3 -1` | Build a breakable wall at offset $(i, j)$ with line of sight |

## Output
At the start of the game and after each of your parsed action requests across all $2000$ moves, the game outputs an $11 \times 11$ grid of characters (as $11$ lines of $11$ characters each) representing your player's centered [Field of View](#field-of-view) (as well as the full $100 \times 100$ initial grid in `map.txt`), using the following character mappings:

**Player Related Mappings**

| Entity   | Player Character | Paint Character | Bomb Character | Bullet Character | Perspective Role                                                 |
| :------- | :--------------: | :-------------: | :------------: | :--------------: | :--------------------------------------------------------------- |
| Player 1 |       `1`        |       `A`       |      `!`       |       `G`        | Your agent, your painted territory, and your projectiles         |
| Player 2 |       `2`        |       `B`       |      `@`       |       `H`        | Opponent (Top Right spawn in relative view) and their objects    |
| Player 3 |       `3`        |       `C`       |      `$`       |       `K`        | Opponent (Bottom Left spawn in relative view) and their objects  |
| Player 4 |       `4`        |       `D`       |      `%`       |       `L`        | Opponent (Bottom Right spawn in relative view) and their objects |

**Ability Object Properties**

| Object Type         | Characters (`P1` / `P2` / `P3` / `P4`) | Considered an Object | Passable | Destructible | Description                                                                                      |
| :------------------ | :------------------------------------: | :------------------: | :------: | :----------: | :----------------------------------------------------------------------------------------------- |
| [Bombs](#bombs)     |         `!` / `@` / `$` / `%`          |         Yes          |    No    |      No      | Explodes after $2$ moves in a radius of $3$; blocks movement, dashes, bullets, and line of sight |
| [Bullets](#bullets) |         `G` / `H` / `K` / `L`          |         Yes          |   Yes*   |     Yes      | Travels $3$ tiles/move after a $1$-move delay; direction is not shown and must be observed       |

*\*Note: If a player and a bullet contend for the same tile on a move, the player occupies the tile and the bullet breaks.*

**Terrain & Wall Character Mappings**

| Tile Type                  | Character | Considered an Object | Passable | Destructible | Description                                           |
| :------------------------- | :-------: | :------------------: | :------: | :----------: | :---------------------------------------------------- |
| [Air](#air)                |    `.`    |          No          |   Yes    |     N/A      | Neutral unpainted tile                                |
| [Unbreakable Wall](#walls) |    `#`    |         Yes          |    No    |      No      | Permanent wall on the map                             |
| [Breakable Wall](#walls)   |    `*`    |         Yes          |    No    |     Yes      | Wall that can be built or destroyed                   |
| [Void](#void)              |    `~`    |         Yes          |    No    |      No      | Out-of-bounds region outside the $100 \times 100$ map |

## Constants

**Game & Map**

| Name          | Value  | Description                                                    |
| :------------ | :----: | :------------------------------------------------------------- |
| `MAX_MOVES`   | $2000$ | Total number of moves in a single match                        |
| `NUM_PLAYERS` |  $4$   | Number of players competing in a match                         |
| `MAP_WIDTH`   | $100$  | Width of the full map grid in tiles                            |
| `MAP_HEIGHT`  | $100$  | Height of the full map grid in tiles                           |
| `FOV_SIZE`    |  $11$  | Side length of the $11 \times 11$ Field of View grid           |
| `FOV_RADIUS`  |  $5$   | Visibility radius around the player in each cardinal direction |
| `SPAWN_X`     |  $4$   | Initial x-coordinate of Player 1 from the top-left corner      |
| `SPAWN_Y`     |  $4$   | Initial y-coordinate of Player 1 from the top-left corner      |

**Ability Economy**

| Ability               |        Max Charge         |       Initial Charge       |        Cost         |        Cooldown         |         Recharge         |
| :-------------------- | :-----------------------: | :------------------------: | :-----------------: | :---------------------: | :----------------------: |
| [Dash](#dash)         |  `DASH_MAX_CHARGE` $= 2$  |  `DASH_INIT_CHARGE` $= 1$  |  `DASH_COST` $= 1$  |  `DASH_COOLDOWN` $= 5$  |  `DASH_RECHARGE` $= 20$  |
| [Bombs](#bombs)       |  `BOMB_MAX_CHARGE` $= 1$  |  `BOMB_INIT_CHARGE` $= 0$  |  `BOMB_COST` $= 1$  | `BOMB_COOLDOWN` $= 15$  |  `BOMB_RECHARGE` $= 15$  |
| [Bullets](#bullets)   | `BULLET_MAX_CHARGE` $= 3$ | `BULLET_INIT_CHARGE` $= 0$ | `BULLET_COST` $= 1$ | `BULLET_COOLDOWN` $= 2$ | `BULLET_RECHARGE` $= 20$ |
| [Building](#building) | `BUILD_MAX_CHARGE` $= 30$ | `BUILD_INIT_CHARGE` $= 5$  | `BUILD_COST` $= 1$  | `BUILD_COOLDOWN` $= 0$  |  `BUILD_RECHARGE` $= 5$  |
| [Breaking](#breaking) |            N/A            |            N/A             | `BREAK_COST` $= 0$  | `BREAK_COOLDOWN` $= 0$  |           N/A            |

**Miscellaneous**

| Constant Name        | Ability               | Value | Description                                                             |
| :------------------- | :-------------------- | :---: | :---------------------------------------------------------------------- |
| `DASH_DISTANCE`      | [Dash](#dash)         |  $3$  | Maximum number of tiles traversed in a single dash                      |
| `BOMB_THROW_RADIUS`  | [Bombs](#bombs)       |  $4$  | Maximum radius ($\sqrt{i^2 + j^2} \leq 4$) for placing a bomb           |
| `BOMB_IGNITION_TIME` | [Bombs](#bombs)       |  $2$  | Number of moves a bomb stays on the map before exploding                |
| `BOMB_BLAST_RADIUS`  | [Bombs](#bombs)       |  $3$  | Radius ($\sqrt{h^2 + k^2} \leq 3$) covered by a bomb explosion          |
| `BULLET_SPEED`       | [Bullets](#bullets)   |  $3$  | Number of tiles a bullet advances per move after its $1$-move wait      |
| `BULLET_SPAWN_DELAY` | [Bullets](#bullets)   |  $1$  | Number of moves a newly placed bullet waits before advancing            |
| `BUILD_RADIUS`       | [Building](#building) |  $4$  | Maximum radius ($\sqrt{i^2 + j^2} \leq 4$) for placing a breakable wall |
| `BREAK_DISTANCE`     | [Breaking](#breaking) |  $1$  | Distance required to break a breakable wall                             |


## Bot I/O protocol

Communication is **line-oriented text** on stdin/stdout. Use **stderr** for debug logs (it is captured in `logs/player*.log` and never parsed by the game).

### Turn loop

1. The match runs for **2000 rounds**. Each round, all four players act once in order P1 → P2 → P3 → P4.
2. When it is your turn, the game writes **11 lines** (your local view) to your stdin, then waits for **one line** on stdout.
3. Reply with a single command, **flush stdout**, and repeat until stdin closes (match over).
4. Default **100 ms** wall time per command (`-t` / `--time-limit`). Timeout, disconnect, or malformed input is treated as **`I` (idle)** for that turn.

Example bots: `bots/random_walk/` (random moves + abilities) and `bots/wall_hug/` (simple movement).

### Your coordinate frame

The engine rotates and mirrors the map so that **you are always Player 1**:

- Your head is **`1`** at the **center** of the 11×11 grid (line 6, column 6, 1-based).
- **`W` / `A` / `S` / `D`** mean up / left / down / right **in this view** (toward the top / left / bottom / right of the text grid).
- Other players appear as **`2`–`4`**; their paint is **`B`–`D`**. Your paint is **`A`**.
- Off-map cells and void are **`~`**. Empty floor is **`.`**.

You never need to un-flip coordinates: send moves and `(i, j)` offsets in this same frame.

### View characters

| Char | Meaning |
|------|---------|
| `.` | Air (walkable) |
| `#` | Unbreakable wall |
| `*` | Breakable wall |
| `1`–`4` | Player heads (you are always `1`) |
| `A`–`D` | Painted territory (yours is `A`) |
| `G`–`L` | Bullet belonging to relative players 1–4 (direction is hidden) |
| `!` `@` `$` `%` | Bomb belonging to relative players 1–4 |
| `~` | Out of bounds / void |

Air and paint are passable. Walls, heads, bombs, and bullets block movement. Bullets break on contact with anything except air or paint.

### Commands

Send **one line** per turn. Spaces separate tokens. Letters are case-insensitive.

| Command | Description |
|---------|-------------|
| `W` `A` `S` `D` | Move one tile, leaving paint on the tile you leave |
| `I` | Idle |
| `J` `<dir>` | Dash up to 3 tiles in `<dir>` (`W`/`A`/`S`/`D`) |
| `G` `<dir>` | Fire a bullet in `<dir>` |
| `X` `<dir>` | Break an adjacent breakable wall (`*`) in `<dir>`, turning it into your paint |
| `B` `i` `j` | Place a bomb at offset `(i, j)` from your head |
| `C` `i` `j` | Place a breakable wall at offset `(i, j)` |

For **`B`** and **`C`**, `(i, j)` are tile offsets in your view: **`i`** is horizontal (+ right, same as `D`), **`j`** is vertical (+ down, same as `S`). The target must satisfy `0 < i² + j² ≤ 16` (disk of radius 4, excluding your own tile).

Examples: `D`, `I`, `G W`, `B 2 -1`, `C 0 3`.

Invalid or unavailable actions (wrong syntax, on cooldown, out of range, blocked) do nothing for that turn, same as idle. Ability costs, cooldowns, and recharge rates are fixed in the judge binary (`game/config.h` in this repo).

## Output
Written to `./out/`:
- `replays/{id}.pbrp`: load into the visualizer
- `logs/player{1..4}.log`: build output, stderr, and isolate messages for each bot

Options (after the bot names): `-w SECONDS` wall limit, `-m KB` memory limit,
`--build-wall`, `--build-memory`, `--timeout`.

## Visualizing

Setup and run the visualizer using

```bash
docker build -f Dockerfile.viewer -t codewars-viewer .
./play.sh wall_hug random_walk
./view.sh
```

Then open `http://localhost:8000` and enter the id of the replay you want to visualize.


## Troubleshooting
- `isolate ... failed`: the container needs `--privileged` (`play.sh` does this).
- Two matches at once: pass a different `--box-base` (e.g. `--box-base 10`).
- Bot "killed after game end" is harmless. It means your bot didn't exit on stdin EOF.
