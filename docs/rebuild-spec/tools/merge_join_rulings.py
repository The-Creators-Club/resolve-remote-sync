#!/usr/bin/env python3
"""Joins: make spec/_trace/_joins/RULINGS.txt from the settlers' files.

    python docs/rebuild-spec/tools/merge_join_rulings.py          write RULINGS.txt
    python docs/rebuild-spec/tools/merge_join_rulings.py --cross  also list rulings that name a
                                                                  finding of another batch

Reads every spec/_trace/_joins/_rulings/<batch>.md (one settler each, written
under spec/_trace/JOINS_SETTLE_BRIEF.md) and then _rulings/_lead.txt, the
lead's own lines in the same shape, which replace a settler's line for the
same finding. Checks that every finding of every batch has exactly one
ruling. build_join_bundles.py --fixes then reads RULINGS.txt.
"""
from __future__ import annotations

import collections
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_join_bundles as bj  # noqa: E402
import merged_lib as ml  # noqa: E402

RUL = os.path.join(bj.ANSWERS, "_rulings")
LINE = re.compile(r"^(\S+ F\d+)\s*\|\s*([a-z]+(?: [^|]*)?)\s*(?:\|\s*(.*))?$")
REF = re.compile(r"\b([a-z][a-z0-9-]+) (F\d+)\b")


def read(path, only_section=True):
    out, part = {}, ""
    for l in open(path, encoding="utf-8"):
        l = l.rstrip("\r\n")
        if l.startswith("## "):
            part = l[3:].strip().lower()
            continue
        if l.startswith("#") or not l.strip() or (only_section and part != "rulings"):
            continue
        m = LINE.match(l)
        if m and m.group(2).split()[0] in bj.VERDICTS:
            out[m.group(1)] = (m.group(2).strip(), (m.group(3) or "").strip())
    return out


def main():
    known = {f"{f['target']} {f['id']}" for f in bj.findings()}
    batch_of, rulings, problems = {}, {}, []
    for p in sorted(glob.glob(os.path.join(RUL, "*.md"))):
        b = os.path.basename(p)[:-3]
        if b.startswith("_"):
            continue
        got = read(p)
        for k, v in got.items():
            if k not in known:
                problems.append(f"{b}: no finding '{k}'")
            elif k in rulings:
                problems.append(f"{b}: {k} is also ruled in {batch_of[k]}")
            else:
                rulings[k], batch_of[k] = v, b
    lead_path = os.path.join(RUL, "_lead.txt")
    lead = read(lead_path, only_section=False) if os.path.exists(lead_path) else {}
    for k in lead:
        if k not in known:
            problems.append(f"_lead: no finding '{k}'")
    rulings.update(lead)
    missing = sorted(known - set(rulings))
    if missing:
        problems.append(f"{len(missing)} findings have no ruling: {', '.join(missing[:20])}")
    for k, (v, note) in rulings.items():
        if v.startswith("same"):
            t = v[5:].strip()
            if t not in known:
                problems.append(f"{k}: 'same {t}' names no finding")
            elif rulings.get(t, ("",))[0].startswith("same"):
                problems.append(f"{k}: 'same {t}', which is itself 'same'")
        if v.startswith("home") and v[5:].strip() not in bj.cs.pieces():
            problems.append(f"{k}: 'home {v[5:].strip()}' is not a piece")
    tally = collections.Counter(v.split()[0] for v, _ in rulings.values())
    if "--cross" in sys.argv:
        for k in sorted(rulings):
            v, note = rulings[k]
            for piece, fid in REF.findall(note):
                other = f"{piece} {fid}"
                if other in known and other != k and batch_of.get(other) != batch_of.get(k):
                    ov, on = rulings.get(other, ("?", ""))
                    print(f"{k} [{v.split()[0]}] names {other} [{ov}]")
    for p in problems:
        print("PROBLEM: " + p)
    if not problems:
        def order(k):
            return (k.split(" ")[0], int(k.split("F")[-1]))
        with open(bj.RULINGS, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Made by tools/merge_join_rulings.py from _rulings/*.md and _rulings/_lead.txt.\n"
                    "# Do not edit: change _rulings/_lead.txt and run it again.\n")
            for k in sorted(rulings, key=order):
                v, note = rulings[k]
                f.write(f"{k} | {v}" + (f" | {note}" if note else "") + "\n")
    print(f"{len(rulings)} rulings of {len(known)} findings ({len(lead)} the lead's): {dict(tally)}")
    print("OK" if not problems else "NOT OK")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
