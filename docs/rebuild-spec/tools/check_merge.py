#!/usr/bin/env python3
"""The merge count (REBUILD_PLAN.md, step 2, part 3).

    python docs/rebuild-spec/tools/check_merge.py sync          one bundle
    python docs/rebuild-spec/tools/check_merge.py               every bundle

A merger's output is knowledge-base/_merged/<bundle>.md. Every entry id of
the bundle (_raw/merge/<bundle>.ids) must be in exactly one `From:` line or
one `Removed` line. Also checks fields, length and giveaway words.
"""
from __future__ import annotations

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.abspath(os.path.join(HERE, ".."))
BUNDLES = os.path.join(SPEC, "_raw", "merge")
MERGED = os.path.join(SPEC, "knowledge-base", "_merged")

sys.path.insert(0, HERE)
from lint_parts import RX  # noqa: E402  the same giveaway-word net

KINDS = {"1a", "1b", "2", "3"}
STATES = {"still open", "outcome not found", "fixed, never shipped"}
REASONS = ("superseded by ", "no longer applies: ", "old build only", "not a lesson")
PART_ID = re.compile(r"\b[PLGHDMC]\d\d-\d{3}\b")


def check(name: str):
    problems = []
    ids_path = os.path.join(BUNDLES, name + ".ids")
    if not os.path.exists(ids_path):
        return [f"no such bundle: {name}"], 0, 0, 0, 0
    want = [l.strip() for l in open(ids_path, encoding="utf-8") if l.strip()]
    path = os.path.join(MERGED, name + ".md")
    if not os.path.exists(path):
        return [f"{name}: not merged yet ({len(want)} entries)"], len(want), 0, 0, 0
    text = open(path, encoding="utf-8", errors="replace").read().replace("\r\n", "\n")
    section = ""
    placed: dict[str, int] = {}
    moved: set[str] = set()
    entry = None
    finished = sealed = removed = 0
    seen_ids = set()

    def close(e):
        if e is None:
            return
        f = e["fields"]
        for need in ("What was going on", "What the product must do", "Kind", "From"):
            if not f.get(need):
                problems.append(f"{e['id']}: missing '{need}'")
        k = f.get("Kind", "")
        if k and k not in KINDS:
            problems.append(f"{e['id']}: Kind '{k}'")
        if e["sealed"]:
            if k and k != "1b":
                problems.append(f"{e['id']}: under Sealed but Kind {k}")
            if not f.get("Tool"):
                problems.append(f"{e['id']}: a sealed entry needs a Tool line")
        elif k == "1b":
            problems.append(f"{e['id']}: Kind 1b belongs under '## Sealed'")
        if f.get("State") and f["State"] not in STATES:
            problems.append(f"{e['id']}: State '{f['State']}' (write State only when it is "
                            "still open, outcome not found, or fixed, never shipped)")
        got = PART_ID.findall(f.get("From", ""))
        if f.get("From") and not got:
            problems.append(f"{e['id']}: no entry id in From")
        for i in got:
            # A second lesson split off for another capability carries the same
            # source id with a `Move to:` line: that is allowed (the brief).
            if f.get("Move to"):
                moved.add(i)
            else:
                placed[i] = placed.get(i, 0) + 1
        for field, limit in (("title", 15), ("What was going on", 34),
                             ("What the product must do", 34)):
            t = e["title"] if field == "title" else f.get(field, "")
            if len(t.split()) > limit:
                problems.append(f"{e['id']} [{field}] is {len(t.split())} words")
            hits = sorted({h.group(0).lower() for h in RX.finditer(t)})
            if hits:
                problems.append(f"{e['id']} [{field}] names: {', '.join(hits)}")

    for line in text.split("\n"):
        if line.startswith("## "):
            close(entry)
            entry = None
            section = line[3:].strip().lower()
            continue
        if section == "removed":
            if not line.startswith("- "):
                continue
            cols = [c.strip() for c in line[2:].split("|", 1)]
            got = PART_ID.findall(cols[0])
            if not got:
                problems.append(f"removed: no id in line: {line[:80]}")
                continue
            if len(cols) < 2 or not cols[1].startswith(REASONS):
                problems.append(f"removed: reason must start with one of {REASONS}: {line[:90]}")
            for i in got:
                placed[i] = placed.get(i, 0) + 1
                removed += 1
            continue
        m = re.match(r"^###\s+(\S+?):\s*(.*)$", line)
        if m:
            close(entry)
            eid = m.group(1)
            if eid in seen_ids:
                problems.append(f"{eid}: used twice as a finished id")
            seen_ids.add(eid)
            entry = {"id": eid, "title": m.group(2).strip(), "fields": {},
                     "sealed": section == "sealed"}
            if entry["sealed"]:
                sealed += 1
            else:
                finished += 1
            if not entry["title"]:
                problems.append(f"{eid}: no title")
            continue
        m = re.match(r"^-\s+([A-Za-z ]+?):\s*(.*)$", line)
        if m and entry is not None:
            entry["fields"][m.group(1).strip()] = m.group(2).strip()
    close(entry)

    for i, n in placed.items():
        if n > 1:
            problems.append(f"{i} is placed {n} times")
        if i not in want:
            problems.append(f"{i} is not in this bundle")
    for i in moved:
        if i not in want:
            problems.append(f"{i} is not in this bundle")
    missing = [i for i in want if i not in placed and i not in moved]
    if missing:
        show = ", ".join(missing[:40]) + (" ..." if len(missing) > 40 else "")
        problems.append(f"{len(missing)} of {len(want)} bundle entries not placed: {show}")
    return problems, len(want), finished, sealed, removed


def main():
    names = sys.argv[1:]
    whole = not names
    if whole:
        names = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(BUNDLES, "*.ids")))
    bad = 0
    tw = tf = ts = tr = done = 0
    for name in names:
        problems, w, f, s, r = check(name)
        tw += w
        tf += f
        ts += s
        tr += r
        if problems:
            bad += 1
            print(f"== {name}")
            for p in problems[:80]:
                print("  " + p)
            if len(problems) > 80:
                print(f"  ... and {len(problems) - 80} more")
        else:
            done += 1
    if whole:
        print(f"{done} of {len(names)} bundles merged: {tw} entries in, "
              f"{tf} finished, {ts} sealed, {tr} removed")
    print("OK" if not bad else f"NOT OK: {bad} bundle(s) with problems")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
