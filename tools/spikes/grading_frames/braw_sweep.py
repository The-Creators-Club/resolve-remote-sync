"""Read-only sweep: does every .braw in a sample share the layout the hollow
method relies on? Reads only the first 64 KB and the index of each file."""
import collections
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import braw_atoms as ba  # noqa: E402  (re-wraps stdout as utf-8)


def look(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        tops = ba.top_level(f, size)
        kinds = [t[0] for t in tops]
        moov = [t for t in tops if t[0] == b"moov"]
        if not moov:
            return {"err": "no moov", "tops": kinds}
        moov = moov[0]
        f.seek(moov[1] + moov[3])
        mbuf = f.read(moov[2] - moov[3])
        f.seek(0)
        head = f.read(65536)
    found = []
    ba.walk(mbuf, moov[1] + moov[3], 0, found, b"/moov")
    cur, traks = None, []
    for p, pos, n, body in found:
        if p == b"/moov/trak":
            cur = {}
            traks.append(cur)
        elif cur is not None and p.startswith(b"/moov/trak/"):
            cur[p[len(b"/moov/trak"):]] = body
    out = {"size": size, "tops": b",".join(kinds).decode("latin1"), "moov_len": moov[2],
           "moov_last": moov[1] + moov[2] == size, "tracks": len(traks)}
    for t in traks:
        if t.get(b"/mdia/hdlr", b"")[8:12] != b"vide":
            continue
        stsd = t.get(b"/mdia/minf/stbl/stsd", b"")
        out["fmt"] = stsd[12:16].decode("latin1")
        stsz = t[b"/mdia/minf/stbl/stsz"]
        cnt = struct.unpack(">I", stsz[8:12])[0]
        sizes = struct.unpack(f">{cnt}I", stsz[12:12 + 4 * cnt])
        co = t.get(b"/mdia/minf/stbl/co64")
        if co is not None:
            c = struct.unpack(">I", co[4:8])[0]
            offs = struct.unpack(f">{c}Q", co[8:8 + 8 * c])
            out["offs"] = "co64"
        else:
            co = t[b"/mdia/minf/stbl/stco"]
            c = struct.unpack(">I", co[4:8])[0]
            offs = struct.unpack(f">{c}I", co[8:8 + 4 * c])
            out["offs"] = "stco"
        out["frames"] = cnt
        out["one_per_chunk"] = c == cnt
        out["has_stss"] = b"/mdia/minf/stbl/stss" in t
        out["max_frame"] = max(sizes) if sizes else 0
        out["mean_frame"] = sum(sizes) // cnt if cnt else 0
        first = offs[0] if offs else 0
        out["first_frame_at"] = first
        out["bmdf"] = first + 8 <= len(head) and head[first + 4:first + 8] == b"bmdf"
        break
    return out


def main(listfile):
    paths = [l.rstrip("\n") for l in open(listfile, encoding="utf-8") if l.strip()]
    t0 = time.time()
    rows, errs = [], []
    for p in paths:
        try:
            r = look(p)
        except Exception as e:  # noqa: BLE001
            errs.append((p, repr(e)))
            continue
        if "err" in r:
            errs.append((p, r))
        else:
            rows.append((p, r))
    print(f"looked at {len(rows)} clips in {time.time() - t0:.0f} s, {len(errs)} unreadable")
    for key in ("tops", "fmt", "offs", "moov_last", "one_per_chunk", "has_stss", "bmdf", "tracks"):
        print(f"  {key}:", dict(collections.Counter(r.get(key) for _, r in rows)))
    sizes = sorted(r["size"] for _, r in rows)
    print("  file size GB: min %.2f median %.2f max %.2f; over 4 GB: %d" % (
        sizes[0] / 1e9, sizes[len(sizes) // 2] / 1e9, sizes[-1] / 1e9, sum(1 for s in sizes if s > 2 ** 32)))
    mf = sorted(r["mean_frame"] for _, r in rows)
    print("  mean frame MB: min %.2f median %.2f max %.2f; largest single frame %.2f MB" % (
        mf[0] / 1e6, mf[len(mf) // 2] / 1e6, mf[-1] / 1e6, max(r["max_frame"] for _, r in rows) / 1e6))
    ml = sorted(r["moov_len"] for _, r in rows)
    print("  index bytes: min %d median %d max %d" % (ml[0], ml[len(ml) // 2], ml[-1]))
    fa = collections.Counter(r["first_frame_at"] for _, r in rows)
    print("  first frame offset:", dict(fa.most_common(5)))
    for p, e in errs[:5]:
        print("  ERR", p, e)


if __name__ == "__main__":
    main(sys.argv[1])
