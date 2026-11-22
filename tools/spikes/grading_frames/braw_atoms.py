"""Read-only look at a .braw's QuickTime layout: where the index sits, how big
each frame is, and which byte ranges one frame needs. Reads only atom headers
and the moov box; never the picture data."""
import io
import os
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"udta", b"dinf"}


def top_level(f, size):
    out = []
    pos = 0
    while pos < size:
        f.seek(pos)
        hdr = f.read(16)
        if len(hdr) < 8:
            break
        n, typ = struct.unpack(">I4s", hdr[:8])
        hl = 8
        if n == 1:
            n = struct.unpack(">Q", hdr[8:16])[0]
            hl = 16
        elif n == 0:
            n = size - pos
        out.append((typ, pos, n, hl))
        if n < 8:
            break
        pos += n
    return out


def walk(buf, base, depth, found, path=b""):
    pos = 0
    while pos + 8 <= len(buf):
        n, typ = struct.unpack(">I4s", buf[pos:pos + 8])
        hl = 8
        if n == 1:
            n = struct.unpack(">Q", buf[pos + 8:pos + 16])[0]
            hl = 16
        if n < 8 or pos + n > len(buf):
            break
        p = path + b"/" + typ
        found.append((p, base + pos, n, buf[pos + hl:pos + n]))
        if typ in CONTAINERS:
            walk(buf[pos + hl:pos + n], base + pos + hl, depth + 1, found, p)
        pos += n


def main(path):
    size = os.path.getsize(path)
    print("file", path)
    print("size", size, f"({size / 1e9:.2f} GB)")
    with open(path, "rb") as f:
        tops = top_level(f, size)
        for typ, pos, n, hl in tops:
            print(f"  top {typ!r:8} at {pos:>14} len {n:>14}")
        moov = [t for t in tops if t[0] == b"moov"][0]
        f.seek(moov[1] + moov[3])
        mbuf = f.read(moov[2] - moov[3])
    found = []
    walk(mbuf, moov[1] + moov[3], 0, found, b"/moov")
    # split per trak
    traks = []
    for p, pos, n, body in found:
        if p == b"/moov/trak":
            traks.append({"pos": pos, "len": n, "atoms": {}})
        elif p.startswith(b"/moov/trak/") and traks:
            traks[-1]["atoms"][p[len(b"/moov/trak"):]] = body
    other = sorted({p for p, *_ in found if not p.startswith(b"/moov/trak/")})
    print("moov children outside traks:", [o.decode() for o in other])
    for p, pos, n, body in found:
        if p in (b"/moov/udta", b"/moov/meta"):
            print("  ", p.decode(), "len", n)
    for i, t in enumerate(traks):
        a = t["atoms"]
        hdlr = a.get(b"/mdia/hdlr", b"")
        kind = hdlr[8:12]
        stsd = a.get(b"/mdia/minf/stbl/stsd", b"")
        fmt = stsd[12:16] if len(stsd) >= 16 else b""
        stsz = a.get(b"/mdia/minf/stbl/stsz", b"")
        stco = a.get(b"/mdia/minf/stbl/stco")
        co64 = a.get(b"/mdia/minf/stbl/co64")
        stsc = a.get(b"/mdia/minf/stbl/stsc", b"")
        stts = a.get(b"/mdia/minf/stbl/stts", b"")
        mdhd = a.get(b"/mdia/mdhd", b"")
        print(f"trak {i}: handler {kind!r} format {fmt!r} keys {sorted(k.decode() for k in a)}")
        if len(mdhd) >= 20:
            ts, dur = struct.unpack(">II", mdhd[12:20])
            print(f"   timescale {ts} duration {dur} ({dur / ts if ts else 0:.2f} s)")
        uni, cnt = struct.unpack(">II", stsz[4:12]) if len(stsz) >= 12 else (0, 0)
        sizes = None
        if cnt and not uni:
            sizes = struct.unpack(f">{cnt}I", stsz[12:12 + 4 * cnt])
            print(f"   samples {cnt} sizes min {min(sizes)} max {max(sizes)} mean {sum(sizes) // cnt}")
        else:
            print(f"   samples {cnt} uniform size {uni}")
        offs = None
        if stco is not None:
            c = struct.unpack(">I", stco[4:8])[0]
            offs = struct.unpack(f">{c}I", stco[8:8 + 4 * c])
            print(f"   stco chunks {c} first {offs[:3]} last {offs[-1] if offs else None}")
        if co64 is not None:
            c = struct.unpack(">I", co64[4:8])[0]
            offs = struct.unpack(f">{c}Q", co64[8:8 + 8 * c])
            print(f"   co64 chunks {c} first {offs[:3]} last {offs[-1] if offs else None}")
        if len(stsc) >= 8:
            c = struct.unpack(">I", stsc[4:8])[0]
            ent = [struct.unpack(">III", stsc[8 + 12 * j:20 + 12 * j]) for j in range(min(c, 4))]
            print(f"   stsc entries {c} first {ent}")
        if len(stts) >= 8:
            c = struct.unpack(">I", stts[4:8])[0]
            ent = [struct.unpack(">II", stts[8 + 8 * j:16 + 8 * j]) for j in range(min(c, 3))]
            print(f"   stts entries {c} first {ent}")
        if kind == b"vide" and sizes and offs and len(offs) == len(sizes):
            mid = len(sizes) // 2
            print(f"   frame {mid}: bytes {offs[mid]}..{offs[mid] + sizes[mid]} ({sizes[mid] / 1e6:.2f} MB)")
            gaps = [offs[k + 1] - (offs[k] + sizes[k]) for k in range(min(len(offs) - 1, 2000))]
            print(f"   gap between consecutive frames: min {min(gaps)} max {max(gaps)}")
    need = moov[2] + sum(n for typ, pos, n, hl in tops if typ not in (b"mdat", b"moov"))
    print(f"index + other non-mdat atoms: {need} bytes ({need / 1e6:.2f} MB)")


if __name__ == "__main__":
    main(sys.argv[1])
