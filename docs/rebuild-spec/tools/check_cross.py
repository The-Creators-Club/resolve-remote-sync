#!/usr/bin/env python3
"""Check the rulings of the pass across capabilities (KB_CROSS_BRIEF.md).

    python docs/rebuild-spec/tools/check_cross.py batch-01     one batch
    python docs/rebuild-spec/tools/check_cross.py              every batch

A batch is knowledge-base/_cross/<name>.md with its groups listed in
<name>.ids; its rulings are <name>.rulings. Every group needs a ruling, a
ruling may name only entries of its own group, and nothing may be dropped
twice. `rulings()` is what assemble_kb.py reads.
"""
from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merged_lib as ml  # noqa: E402

ID = re.compile(r"^[A-Z0-9]{2,4}-S?\d{2,3}$")


def groups_of(name: str):
    out = {}
    for line in open(os.path.join(ml.CROSS, name + ".ids"), encoding="utf-8"):
        if line.strip():
            g, ids = line.rstrip("\n").split("\t")
            out[g] = ids.split()
    return out


def rulings(name: str, entries_by_id=None):
    """-> (rulings, problems). A ruling: group, verb, and keep/drop/topic/question."""
    problems, out = [], []
    groups = groups_of(name)
    path = os.path.join(ml.CROSS, name + ".rulings")
    if not os.path.exists(path):
        return [], [f"{name}: no rulings yet ({len(groups)} groups)"]
    if entries_by_id is None:
        entries_by_id = {e["id"]: e for e in ml.merged()[0]}
    topics = {}
    for e in entries_by_id.values():
        if not e["sealed"]:
            topics.setdefault(e["capability"], set()).add(e["topic"])
    ruled, dropped = set(), {}
    for n, raw in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = [c.strip() for c in line.split("|")]
        g = cols[0]
        where = f"{name} line {n}"
        if g not in groups:
            problems.append(f"{where}: no group '{g}' in this batch")
            continue
        members = groups[g]
        verb = cols[1] if len(cols) > 1 else ""
        is_move = g.startswith("M")
        ruled.add(g)
        if verb == "distinct" and not is_move:
            out.append({"group": g, "verb": verb})
        elif verb == "stay" and is_move:
            out.append({"group": g, "verb": verb, "id": members[0]})
        elif verb == "move" and is_move:
            e = entries_by_id[members[0]]
            target = e["fields"]["Move to"].strip().strip("`.")
            topic = "|".join(cols[2:]).strip() if len(cols) > 2 else ""
            if topic not in topics.get(target, ()):
                problems.append(f"{where}: '{topic}' is not a sub-topic of {target}")
            out.append({"group": g, "verb": verb, "id": members[0], "target": target,
                        "topic": topic})
        elif verb == "same" and len(cols) == 4:
            keep = cols[2]
            drops = [d.strip() for d in cols[3].split(",") if d.strip()]
            for i in [keep] + drops:
                if i not in members:
                    problems.append(f"{where}: {i} is not in group {g}")
            if is_move and (drops != [members[0]] or keep == members[0]):
                problems.append(f"{where}: in a move group it is "
                                f"`same | <target entry> | {members[0]}`")
            if keep in drops:
                problems.append(f"{where}: {keep} is both kept and dropped")
            for d in drops:
                if d in dropped:
                    problems.append(f"{where}: {d} is already dropped ({dropped[d]})")
                dropped[d] = where
            out.append({"group": g, "verb": verb, "keep": keep, "drop": drops})
        elif verb == "conflict" and len(cols) >= 5 and not is_move:
            a, b = cols[2], cols[3]
            for i in (a, b):
                if i not in members:
                    problems.append(f"{where}: {i} is not in group {g}")
            q = "|".join(cols[4:]).strip()
            if len(q.split()) < 4:
                problems.append(f"{where}: the conflict needs its question")
            out.append({"group": g, "verb": verb, "ids": [a, b], "question": q})
        else:
            problems.append(f"{where}: cannot read '{line[:90]}'")
    missing = [g for g in groups if g not in ruled]
    if missing:
        problems.append(f"{name}: {len(missing)} of {len(groups)} groups have no ruling: "
                        + ", ".join(missing[:40]) + (" ..." if len(missing) > 40 else ""))
    for r in out:
        if r["verb"] == "same" and r["keep"] in dropped:
            problems.append(f"{name}: {r['keep']} is kept in group {r['group']} but dropped "
                            f"at {dropped[r['keep']]}")
    return out, problems


def batch_names():
    return sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(ml.CROSS, "*.ids")))


def main():
    names = sys.argv[1:] or batch_names()
    by_id = {e["id"]: e for e in ml.merged()[0]}
    bad = 0
    tally = {}
    for name in names:
        rs, problems = rulings(name, by_id)
        for r in rs:
            tally[r["verb"]] = tally.get(r["verb"], 0) + 1
        if problems:
            bad += 1
            print(f"== {name}")
            for p in problems[:60]:
                print("  " + p)
    print("rulings:", ", ".join(f"{v} {k}" for k, v in sorted(tally.items())) or "none")
    print("OK" if not bad else f"NOT OK: {bad} batch(es) with problems")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
