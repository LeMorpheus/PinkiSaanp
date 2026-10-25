import sys

# Local frame: spawn (3,3), border walls at row/col 0.
SCRIPT = (['D'] * 4 + ['S'] * 3 + ['A'] * 3 + ['W'] * 3 + ['I', 'I'] +      # 4x4 ring, interior 2x2
          ['D'] * 5 + ['S'] * 6 + ['D'] * 4 + ['S'] * 2 + ['A'] * 4 + ['W'] * 2 + ['I', 'I'] +  # ring around '*'
          ['GD', 'I', 'I'] + ['D'] * 6 + ['I'] +
          ['S', 'S', 'I'])


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
