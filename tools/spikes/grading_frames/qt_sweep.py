"""Read-only sweep of QuickTime/MP4 camera files that are NOT .braw: what would
a hollow copy need for each kind? Reads only atom headers and the index (moov).

usage: qt_sweep.py <file with one path per line> [--detail]

Per file it reports: container order, video codec, whether every frame stands
alone (no sync-sample table) or the file is long-GOP, the GOP length, B-frame
reordering (ctts), frames per chunk, frame sizes, and the other tracks.
"""
import collections
import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import braw_atoms as ba  # noqa: E402  (re-wraps stdout as utf-8)

CONT = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}


def walk(buf, found, path=b""):
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
        found.append((p, buf[pos + hl:pos + n]))
        if typ in CONT:
            walk(buf[pos + hl:pos + n], found, p)
        pos += n


def look(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        tops = ba.top_level(f, size)
        moov = [t for t in tops if t[0] == b"moov"]
        if not moov:
            return {"err": "no moov", "tops": [t[0] for t in tops][:6]}
        moov = moov[0]
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
    kinds = [t[0].decode("latin1") for t in tops]
    out = {"size": size, "tops": ",".join(kinds), "moov_len": moov[2],
           "moov_pos": "end" if moov[1] + moov[2] >= size - 64 else ("start" if moov[1] < 4096 else "middle"),
           "others": []}
    for t in traks:
        kind = t.get(b"/mdia/hdlr", b"")[8:12].decode("latin1")
        stsd = t.get(b"/mdia/minf/stbl/stsd", b"")
        fmt = stsd[12:16].decode("latin1") if len(stsd) >= 16 else "?"
        if kind != "vide" or "fmt" in out:
            out["others"].append(kind + ":" + fmt)
            continue
        out["fmt"] = fmt
        stsz = t.get(b"/mdia/minf/stbl/stsz", b"")
        uni, cnt = struct.unpack(">II", stsz[4:12])
        sizes = struct.unpack(f">{cnt}I", stsz[12:12 + 4 * cnt]) if not uni else [uni] * cnt
        co = t.get(b"/mdia/minf/stbl/co64")
        out["offs"] = "co64" if co is not None else "stco"
        if co is None:
            co = t.get(b"/mdia/minf/stbl/stco", b"\0" * 8)
        chunks = struct.unpack(">I", co[4:8])[0]
        stss = t.get(b"/mdia/minf/stbl/stss")
        out["frames"] = cnt
        out["chunks"] = chunks
        out["per_chunk"] = round(cnt / chunks, 1) if chunks else 0
        out["ctts"] = b"/mdia/minf/stbl/ctts" in t
        out["sdtp"] = b"/mdia/minf/stbl/sdtp" in t
        if stss is None:
            out["gop"] = 1
            out["intra"] = True
        else:
            k = struct.unpack(">I", stss[4:8])[0]
            keys = struct.unpack(f">{k}I", stss[8:8 + 4 * k])
            gaps = [b - a for a, b in zip(keys, keys[1:])] or [cnt]
            out["gop"] = max(gaps)
            out["intra"] = k == cnt
            if sizes and not out["intra"]:
                # bytes in the largest GOP: what one frame costs to fetch
                best = 0
                for a, b in zip(keys, list(keys[1:]) + [cnt + 1]):
                    best = max(best, sum(sizes[a - 1:b - 1]))
                out["gop_bytes"] = best
        out["mean_frame"] = sum(sizes) // cnt if cnt else 0
        out["max_frame"] = max(sizes) if sizes else 0
        mdhd = t.get(b"/mdia/mdhd", b"")
        if len(mdhd) >= 20 and cnt:
            ts, dur = struct.unpack(">II", mdhd[12:20])
            out["fps"] = round(cnt / (dur / ts), 2) if dur and ts else 0
        tk = t.get(b"/tkhd", b"")
        if len(tk) >= 84:
            out["wh"] = "%dx%d" % (struct.unpack(">I", tk[76:80])[0] >> 16, struct.unpack(">I", tk[80:84])[0] >> 16)
    return out


def group_of(path):
    b = os.path.basename(path)
    e = os.path.splitext(b)[1].lower()
    m = re.match(r"[A-Za-z]+", b)
    return e + ":" + (m.group(0)[:6] if m else "#num")


def main():
    paths = [l.rstrip("\n") for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    detail = "--detail" in sys.argv
    t0 = time.time()
    groups = collections.defaultdict(list)
    errs = []
    for p in paths:
        try:
            r = look(p)
        except Exception as e:  # noqa: BLE001
            errs.append((p, repr(e)[:80]))
            continue
        if "err" in r or "fmt" not in r:
            errs.append((p, str(r)[:100]))
            continue
        groups[(group_of(p), r["fmt"])].append((p, r))
        if detail:
            print(os.path.basename(p), {k: v for k, v in r.items() if k != "size"}, "%.2f GB" % (r["size"] / 1e9))
    print(f"looked at {sum(len(v) for v in groups.values())} files in {time.time() - t0:.0f} s, {len(errs)} unreadable")
    for (g, fmt), rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        rs = [r for _, r in rows]
        c = lambda k: dict(collections.Counter(r.get(k) for r in rs))  # noqa: E731
        med = lambda k: sorted(r.get(k, 0) for r in rs)[len(rs) // 2]  # noqa: E731
        print(f"\n{g}  codec {fmt}  n={len(rs)}  e.g. {os.path.basename(rows[0][0])}")
        print("   order", c("tops"))
        print("   moov", c("moov_pos"), "offsets", c("offs"), "intra", c("intra"), "ctts", c("ctts"))
        print("   size", c("wh"), "fps", c("fps"))
        print("   GOP frames (max in file):", c("gop"), "| frames per chunk", c("per_chunk"))
        print("   mean frame MB median %.2f | largest GOP MB median %.2f max %.2f | index MB median %.2f max %.2f | file GB median %.2f max %.2f" % (
            med("mean_frame") / 1e6, med("gop_bytes") / 1e6, max(r.get("gop_bytes", 0) for r in rs) / 1e6,
            med("moov_len") / 1e6, max(r["moov_len"] for r in rs) / 1e6, med("size") / 1e9, max(r["size"] for r in rs) / 1e9))
        print("   other tracks", dict(collections.Counter(",".join(r["others"]) for r in rs)))
    for p, e in errs[:8]:
        print("ERR", os.path.basename(p), e)


if __name__ == "__main__":
    main()
