"""Build a HOLLOW copy of a .braw by hand, for the Resolve half of the spike
(docs/GRADING_FRAMES.md section 6). Same name, the original's length plus a
marker, and only these bytes filled in: the head, the index (moov), the whole
first frame and the frames asked for. Everything else is a sparse hole.

Reads the source read-only, and only the ranges it copies. Windows + NTFS only
(it uses `fsutil sparse setflag`); the real feature must not shell out.

usage: make_hollow.py <source.braw> <dest dir> <frame index> [<frame index> ...]
       add --no-marker to leave the trailing marker atom off
"""
import json
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import braw_atoms as ba  # noqa: E402  (also re-wraps stdout as utf-8)


def video_table(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        tops = ba.top_level(f, size)
        moov = [t for t in tops if t[0] == b"moov"][0]
        f.seek(moov[1] + moov[3])
        mbuf = f.read(moov[2] - moov[3])
    found = []
    ba.walk(mbuf, moov[1] + moov[3], 0, found, b"/moov")
    cur, traks = None, []
    for p, pos, n, body in found:
        if p == b"/moov/trak":
            cur = {}
            traks.append(cur)
        elif cur is not None and p.startswith(b"/moov/trak/"):
            cur[p[len(b"/moov/trak"):]] = body
    for t in traks:
        if t.get(b"/mdia/hdlr", b"")[8:12] != b"vide":
            continue
        stsz = t[b"/mdia/minf/stbl/stsz"]
        cnt = struct.unpack(">I", stsz[8:12])[0]
        sizes = struct.unpack(f">{cnt}I", stsz[12:12 + 4 * cnt])
        co = t.get(b"/mdia/minf/stbl/co64")
        if co is not None:
            offs = struct.unpack(f">{cnt}Q", co[8:8 + 8 * cnt])
        else:
            co = t[b"/mdia/minf/stbl/stco"]
            offs = struct.unpack(f">{cnt}I", co[8:8 + 4 * cnt])
        return size, moov, offs, sizes
    raise SystemExit("no video track")


def main():
    args = sys.argv[1:]
    marker = "--no-marker" not in args
    args = [a for a in args if a != "--no-marker"]
    src, dest_dir = args[0], args[1]
    frames = sorted({0, *[int(x) for x in args[2:]]})   # frame 0 always: the decoder reads its header to open the clip
    size, moov, offs, sizes = video_table(src)
    ranges = [(0, min(offs))]                            # wide + mdat header + the timecode sample
    ranges += [(offs[fr], sizes[fr]) for fr in frames]
    ranges.append((moov[1], size - moov[1]))             # the index; written LAST, it sets the length
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src))
    with open(dest, "wb"):
        pass
    subprocess.run(["fsutil", "sparse", "setflag", dest], check=True, capture_output=True)
    total = 0
    with open(src, "rb") as s, open(dest, "r+b") as d:
        # Never truncate() to extend: the C runtime zero-fills, which fills the
        # holes (measured: 1.9 GB allocated for a 3 GB clip). Seeking past the
        # end and writing leaves a hole on a sparse file.
        for off, n in ranges:
            s.seek(off)
            d.seek(off)
            left = n
            while left:
                b = s.read(min(left, 4 << 20))
                if not b:
                    raise SystemExit(f"short read at {off}")
                d.write(b)
                left -= len(b)
            total += n
        if marker:
            body = json.dumps({"ccsync": "hollow", "v": 1, "real_size": size, "frames": frames}).encode()
            d.seek(size)
            d.write(struct.pack(">I4s", 8 + len(body), b"free") + body)
    print("dest", dest)
    print("length", os.path.getsize(dest), "original", size, "marker", marker)
    print("bytes copied", total, f"({total / 1e6:.2f} MB), frames", frames)
    out = subprocess.run(["fsutil", "sparse", "queryrange", dest], capture_output=True, text=True)
    print(out.stdout.strip()[:800])


if __name__ == "__main__":
    main()
