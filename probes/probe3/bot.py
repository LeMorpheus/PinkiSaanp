import sys

# Timing probe: spam each ability and record which attempts succeed.
#   moves   0- 79: 'G S' every move   (bullet init 0, recharge 20, cooldown 2, max 3)
#   moves  80-159: 'B 2 0' every move (bomb init 0, recharge 15, cooldown 15, max 1)
#   moves 160-230: dash alternating right/left (init 1, recharge 20, cooldown 5, max 2)


def cmd_for(t):
    if t < 80:
        return 'GS'
    if t < 160:
        return 'B 2 0'
    return 'JD' if (t // 1) % 2 == 0 else 'JA'


def main():
    t = 0
    prev = None
    while True:
        rows = []
        for _ in range(11):
            line = sys.stdin.readline()
            if not line:
                return
            rows.append(line.rstrip('\n'))
        me = rows[5][5]
        below = rows[6][5]
        right2 = rows[5][7]
        # head position change is visible through the walls: count '#' columns to our left on row 5
        left_wall = rows[5].find('#')
        sys.stderr.write('t=%d me=%s below=%s right2=%s wallcol=%d row5=%s\n'
                         % (t, me, below, right2, left_wall, rows[5]))
        sys.stderr.flush()
        print(cmd_for(t), flush=True)
        t += 1


main()
