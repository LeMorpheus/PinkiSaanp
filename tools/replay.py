"""Decoder for Codewars .pbrp replays (reverse-engineered).

Layout: 'PBRP' u8 version, u8 w, u8 h, u8 ?, u32 ticks, u32 ?, u32 ?,
u16 n + n * [type, x1, y1, x2, y2]   initial map (inclusive rectangles, y flipped),
then per tick: u32 tick, u16 n, n * [type, x1, y1, x2, y2]   changed rectangles.
Type index -> char: '~.#*1234ABCDHJKLUIOPQWER6789!@$%'.

    python tools/replay.py file.pbrp 509 510          # print boards
    python tools/replay.py file.pbrp --scores         # area per player per 50 ticks
"""

import struct
import sys

ALPHABET = '~.#*1234ABCDHJKLUIOPQWER6789!@$%'


def load(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'PBRP', 'not a pbrp file'
    w, h = d[5], d[6]
    ticks = struct.unpack_from('<I', d, 8)[0]
    n = struct.unpack_from('<H', d, 20)[0]
    off = 22
    grid = [['~'] * w for _ in range(h)]

    def apply(off, n):
        for _ in range(n):
            t, x1, y1, x2, y2 = d[off:off + 5]
            off += 5
            ch = ALPHABET[t] if t < len(ALPHABET) else '?'
            for y in range(min(y1, y2), max(y1, y2) + 1):
                row = grid[h - 1 - y]
                for x in range(min(x1, x2), max(x1, x2) + 1):
                    row[x] = ch
        return off

    off = apply(off, n)
    frames = [[r[:] for r in grid]]
    while off + 6 <= len(d):
        tick = struct.unpack_from('<I', d, off)[0]
        n = struct.unpack_from('<H', d, off + 4)[0]
        off = apply(off + 6, n)
        frames.append([r[:] for r in grid])
    return frames, ticks


def scores(frame):
    out = {}
    for row in frame:
        for ch in row:
            if ch in 'ABCD':
                out[ch] = out.get(ch, 0) + 1
    return out


def show(frame, x0=0, y0=0, x1=100, y1=100):
    return '\n'.join(''.join(r[x0:x1]) for r in frame[y0:y1])


if __name__ == '__main__':
    frames, ticks = load(sys.argv[1])
    if '--scores' in sys.argv:
        for t in range(0, len(frames), 50):
            print(t, scores(frames[t]))
        print(len(frames) - 1, scores(frames[-1]))
    else:
        args = [int(a) for a in sys.argv[2:]]
        for t in args:
            print('--- tick', t, scores(frames[t]))
            print(show(frames[t]))
