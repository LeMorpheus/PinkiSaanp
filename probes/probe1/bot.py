import sys

# Experiment script (absolute frame: we spawn at (3,3) 0-indexed, walls at row/col 0).
# 1) Walk an L from spawn up to the top wall, right, down, left to the left wall:
#    does the corner region between our paint and the border walls fill?
# 2) Wait for charges, then dash, bomb, bullet, build, break.
SCRIPT = (['W', 'W'] + ['D'] * 5 + ['S'] * 6 + ['A'] * 7 +
          ['I'] * 2 +
          ['JD', 'I', 'I'] +
          ['B 3 0', 'I', 'I', 'I', 'I'] +
          ['I'] * 8 + ['GD', 'I', 'I', 'I', 'I', 'I', 'I'] +
          ['C 0 -2', 'I', 'XW', 'I', 'C 1 0', 'XD', 'I'] +
          # 3) open-air square loop 4x4 back to its start
          ['S', 'S', 'S', 'D', 'D', 'D', 'D', 'S', 'S', 'S', 'A', 'A', 'A', 'W', 'W', 'W', 'D', 'I', 'I'])


def main():
    t = 0
    while True:
        rows = []
        for _ in range(11):
            line = sys.stdin.readline()
            if not line:
                return
            rows.append(line.rstrip('\n'))
        cmd = SCRIPT[t] if t < len(SCRIPT) else 'I'
        sys.stderr.write('== move %d  (about to send %r)\n%s\n' % (t, cmd, '\n'.join(rows)))
        sys.stderr.flush()
        print(cmd, flush=True)
        t += 1


main()
