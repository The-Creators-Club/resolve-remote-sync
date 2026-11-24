#!/usr/bin/env python3
"""Step 3, part 3: what only shows once every piece is written.

    python docs/rebuild-spec/tools/check_seams.py

Reads every spec/_trace/<piece>.md and spec/<piece>.md and reports, without
changing anything:

  1. A reader's question one piece handed to another ("with <piece>") that
     the other piece did not write up or account for.
  2. A reader's question or unsettled point nobody wrote up at all.
  3. A lesson one piece lists as "not yet met" that no other piece of the
     same capability meets either.
  4. The lessons listed as tied to an arrangement (to be taken out of what
     crosses), by capability.
  5. Joins: every "<capability> / <sub-topic>" a piece says it leans on, with
     whether that sub-topic exists in a written piece.
  6. Totals: behaviours, settings, questions, pending marks, still unsettled.
"""
from __future__ import annotations

import collections
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_spec as cs  # noqa: E402
import merged_lib as ml  # noqa: E402

LESSON = re.compile(r"\b[A-Z][A-Z0-9]{2}-\d{3}\b")


def main():
    pieces = cs.pieces()
    written = [p for p in pieces if os.path.exists(os.path.join(cs.TEXT, p + ".md"))
               and os.path.exists(os.path.join(cs.TRACE, p + ".md"))]
    print(f"{len(written)} of {len(pieces)} pieces written"
          + (f"; not yet: {' '.join(p for p in pieces if p not in written)}" if len(written) < len(pieces) else ""))
    readers, covers, owner_q, unsettled = {}, {}, {}, {}
    met, not_met, tied = collections.defaultdict(set), collections.defaultdict(set), collections.defaultdict(set)
    subs, joins = {}, []
    tot = collections.Counter()
    for p in written:
        _pr, cover, questions, rd, uns = cs.read_trace(p)
        readers[p], owner_q[p], unsettled[p] = rd, questions, uns
        covers[p] = set()
        for q in questions.values():
            covers[p].update(re.findall(r"\b(?:\d\d[a-d]?-Q\d+|U-\d\d[a-d]?-\d+)\b", q.get("Covers", "")))
        cap = ml.capability_of(p)
        text = cs.lines_of(os.path.join(cs.TEXT, p + ".md"))
        subs[p] = [l[3:].strip() for l in text if l.startswith("## ")]
        for l in text:
            if l.startswith("- Met"):
                met[cap].update(LESSON.findall(l))
            elif l.startswith("- Not yet met"):
                not_met[cap].update(LESSON.findall(l))
            elif l.startswith("- Tied to an arrangement"):
                tied[cap].update(LESSON.findall(l))
            elif l.startswith("### "):
                tot["behaviours"] += 1
            elif l.startswith("- Setting:"):
                tot["settings"] += 1
            elif l.startswith("- Pending:"):
                tot["pending marks"] += 1
        tot["questions for the owner"] += len(questions)
        tot["still unsettled"] += len(uns)
        part = ""
        for l in cs.lines_of(os.path.join(cs.TRACE, p + ".md")):
            if l.startswith("## "):
                part = l[3:].strip().lower()
            elif part.startswith("joins") and l.startswith("- "):
                joins.append((p, l[2:].split("|")[0].strip()))

    print("\n1. Handed to another piece and not picked up there:")
    n = 0
    for p in written:
        for q, what in readers[p].items():
            m = re.match(r"^with\s+(\S+)", what)
            if not m:
                continue
            other = m.group(1).rstrip(".,;")
            if other not in pieces:
                print(f"   {p}: {q} handed to '{other}', which is not a piece")
                n += 1
            elif other in written and q not in readers[other]:
                print(f"   {p}: {q} handed to {other}, which does not list it")
                n += 1
            elif other in written and re.match(r"^with\s", readers[other].get(q, "")):
                print(f"   {p}: {q} handed to {other}, which hands it on again ({readers[other][q]})")
                n += 1
    print("   none" if not n else f"   {n} in all")

    # A piece that meets another piece's lesson lists it "Met for another
    # part", and it may belong to another capability (the hand-over to
    # Resolve meets three of the editor's).
    met_anywhere = set().union(*met.values()) if met else set()
    print("\n2. Lessons 'not yet met' in one piece and met in no piece at all:")
    n = 0
    for cap in sorted(not_met):
        left = sorted(not_met[cap] - met_anywhere)
        if left:
            n += len(left)
            print(f"   {cap}: {', '.join(left)}")
    print("   none" if not n else f"   {n} in all")

    print("\n3. Lessons tied to an arrangement (to come out of what crosses):")
    for cap in sorted(tied):
        print(f"   {cap} ({len(tied[cap])}): {', '.join(sorted(tied[cap]))}")
    print(f"   {sum(len(v) for v in tied.values())} in all")

    print("\n4. Joins that name a sub-topic no written piece has:")
    all_subs = {(ml.capability_of(p), s.lower()) for p in written for s in subs[p]}
    names = {v.lower(): k for k, v in ml.NAMES.items()}
    n = 0
    for p, target in joins:
        if "/" not in target:
            continue
        cap, sub = [x.strip() for x in target.split("/", 1)]
        cap_key = names.get(cap.lower(), cap.lower())
        if cap_key in ml.NAMES and (cap_key, sub.lower()) not in all_subs \
                and any(ml.capability_of(w) == cap_key for w in written):
            n += 1
            print(f"   {p} -> {target}")
    print("   none" if not n else f"   {n} in all (of {len(joins)} joins)")

    print("\n5. Totals: " + ", ".join(f"{v} {k}" for k, v in tot.items()))


if __name__ == "__main__":
    main()
