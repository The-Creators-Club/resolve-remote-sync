"""Build a HOLLOW copy of any QuickTime/MP4 camera file (Sony XAVC S, DJI,
Nikon, iPhone, ProRes), for the second-build spike (docs/GRADING_FRAMES.md).

What is kept: everything that is not picture or sound payload (every atom but
the inside of `mdat`, wherever the index sits), the first group of pictures,
and for each frame asked for the whole group of pictures it needs. A frame is
given in DISPLAY order, 0-based, as an editor counts them. On a long-GOP file
that means: find the sample shown N-th (B-frames are stored out of order),
take its group from the keyframe before it to the next keyframe, and the group
before as well when the sample is shown before its own keyframe (open GOP).

Reads the source read-only, and only the ranges it copies. Windows + NTFS.

usage: make_hollow_qt.py <source> <dest dir> <display frame> [...] [--no-marker]
"""
import json
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import braw_atoms as ba  # noqa: E402
from qt_sweep import walk  # noqa: E402


def tables(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        tops = ba.top_level(f, size)
        moov = [t for t in tops if t[0] == b"moov"][0]
        f.seek(moov[1] + moov[3])
        mbuf = f.read(moov[2] - moov[3])
    found = []
    walk(mbuf, found, b"/moov")
    cur, traks = None, []
    for p, body in found:
        if p == b"/moov/trak":
            cur = {}
            traks.append(cur)
        elif cur is not None and p.startswith(b"/moov/trak/"):
            cur[p[len(b"/moov/trak"):]] = body
    return size, tops, traks


def sample_offsets(t):
    """(offset, size) of every sample of one track, in stored (decode) order."""
    S = b"/mdia/minf/stbl/"
    stsz = t[S + b"stsz"]
    uni, cnt = struct.unpack(">II", stsz[4:12])
    sizes = list(struct.unpack(f">{cnt}I", stsz[12:12 + 4 * cnt])) if not uni else [uni] * cnt
    co = t.get(S + b"co64")
    if co is not None:
        n = struct.unpack(">I", co[4:8])[0]
        chunk_off = struct.unpack(f">{n}Q", co[8:8 + 8 * n])
    else:
        co = t[S + b"stco"]
        n = struct.unpack(">I", co[4:8])[0]
        chunk_off = struct.unpack(f">{n}I", co[8:8 + 4 * n])
    stsc = t[S + b"stsc"]
    e = struct.unpack(">I", stsc[4:8])[0]
    runs = [struct.unpack(">III", stsc[8 + 12 * i:20 + 12 * i]) for i in range(e)]
    out, si = [], 0
    for ri, (first, per, _) in enumerate(runs):
        last = runs[ri + 1][0] - 1 if ri + 1 < len(runs) else len(chunk_off)
        for ch in range(first, last + 1):
            off = chunk_off[ch - 1]
            for _ in range(per):
                if si >= cnt:
                    break
                out.append((off, sizes[si]))
                off += sizes[si]
                si += 1
    return out


def video_plan(t, frames):
    S = b"/mdia/minf/stbl/"
    samples = sample_offsets(t)
    cnt = len(samples)
    stss = t.get(S + b"stss")
    if stss is None:
        keys = list(range(cnt))                      # every frame stands alone
    else:
        k = struct.unpack(">I", stss[4:8])[0]
        keys = [x - 1 for x in struct.unpack(f">{k}I", stss[8:8 + 4 * k])]
    # decode time of each sample (stts), then display time (ctts)
    stts = t[S + b"stts"]
    e = struct.unpack(">I", stts[4:8])[0]
    dts, tcur = [], 0
    for i in range(e):
        c, d = struct.unpack(">II", stts[8 + 8 * i:16 + 8 * i])
        for _ in range(c):
            dts.append(tcur)
            tcur += d
    ctts = t.get(S + b"ctts")
    cts = list(dts)
    if ctts is not None:
        e = struct.unpack(">I", ctts[4:8])[0]
        i = 0
        for j in range(e):
            c, o = struct.unpack(">Ii", ctts[8 + 8 * j:16 + 8 * j])
            for _ in range(c):
                if i < cnt:
                    cts[i] = dts[i] + o
                i += 1
    order = sorted(range(cnt), key=lambda i: cts[i])  # order[n] = stored index of the n-th frame shown
    import bisect
    groups = set()
    for fr in [0] + list(frames):
        s = order[fr]
        gi = bisect.bisect_right(keys, s) - 1
        groups.add(gi)
        if cts[s] < cts[keys[gi]] and gi > 0:        # shown before its own keyframe
            groups.add(gi - 1)
    ranges = []
    for gi in sorted(groups):
        a = keys[gi]
        b = keys[gi + 1] if gi + 1 < len(keys) else cnt
        lo = min(samples[i][0] for i in range(a, b))
        hi = max(samples[i][0] + samples[i][1] for i in range(a, b))
        ranges.append((lo, hi - lo, a, b))
    return ranges, samples, len(keys), cnt


def main():
    args = sys.argv[1:]
    marker = "--no-marker" not in args
    args = [a for a in args if a != "--no-marker"]
    src, dest_dir = args[0], args[1]
    frames = [int(x) for x in args[2:]]
    size, tops, traks = tables(src)
    vid = [t for t in traks if t.get(b"/mdia/hdlr", b"")[8:12] == b"vide"][0]
    groups, samples, nkeys, cnt = video_plan(vid, frames)
    ranges = []
    for typ, pos, n, hl in tops:                     # every atom whole, except the inside of mdat
        ranges.append((pos, hl if typ == b"mdat" else n))
    ranges += [(lo, n) for lo, n, _, _ in groups]
    ranges.sort()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src))
    with open(dest, "wb"):
        pass
    subprocess.run(["fsutil", "sparse", "setflag", dest], check=True, capture_output=True)
    total = 0
    with open(src, "rb") as s, open(dest, "r+b") as d:
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
        if os.path.getsize(dest) < size:             # index was not last: pin the length with one byte
            s.seek(size - 1)
            d.seek(size - 1)
            d.write(s.read(1))
        if marker:
            body = json.dumps({"ccsync": "hollow", "v": 1, "real_size": size, "frames": frames}).encode()
            d.seek(size)
            d.write(struct.pack(">I4s", 8 + len(body), b"free") + body)
    print("dest", dest)
    print("length", os.path.getsize(dest), "original", size, "marker", marker)
    print("video samples", cnt, "keyframes", nkeys, "| groups kept:", [(a, b) for _, _, a, b in groups])
    print("bytes copied", total, f"({total / 1e6:.2f} MB) of {size / 1e9:.2f} GB, frames asked", frames)


if __name__ == "__main__":
    main()
