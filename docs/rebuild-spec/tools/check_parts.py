#!/usr/bin/env python3
"""The count (REBUILD_PLAN.md, step 2, part 4).

    python docs/rebuild-spec/tools/check_parts.py P08      one part
    python docs/rebuild-spec/tools/check_parts.py          every slice

Checks that every id in the register is accounted for: in the Sources of an
entry, in "Stays behind", or in "No entry" with a reason (a part file), or in
the script-made auto_no_entry.tsv. Step 2 is finished when a run with no
arguments prints OK. Also checks each entry's fields.
"""
from __future__ import annotations

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.abspath(os.path.join(HERE, ".."))
RAW = os.path.join(SPEC, "_raw")
PARTS = os.path.join(SPEC, "knowledge-base", "_parts")

KINDS = {"1a", "1b", "2", "3"}
FOUND = {"real use", "reading the code", "a test"}
STATES = {"fixed and live", "fixed, never shipped", "still open",
          "declined by the owner", "outcome not found", "a standing rule"}
CAPS = {"sync", "proxies-and-file-moves", "resolve-on-the-editors-computer",
        "editor-app", "dashboard", "server-install-and-running",
        "releases-and-updates", "broll", "music", "youtube", "cards-editor",
        "cards-to-resolve-and-exports", "cards-footage-in", "cards-board",
        "footage-sorter-and-camera-cards", "fleet-jobs",
        "accounts-privacy-legal", "whole-product"}
ID = r"[PLGHDMC]-[A-Za-z0-9_.\-]+"
RANGE = re.compile(r"^([PL])-(\d+)\.\.([PL])-(\d+)$")


def expand(token: str):
    token = token.strip().strip("`").rstrip(".,;")
    m = RANGE.match(token)
    if m and m.group(1) == m.group(3):
        a, b = int(m.group(2)), int(m.group(4))
        width = len(m.group(2))
        if b < a or b - a > 5000:
            return [token]
        return [f"{m.group(1)}-{n:0{width}d}" for n in range(a, b + 1)]
    return [token] if re.fullmatch(ID, token) else []


def ids_in(text: str):
    out = []
    for tok in re.split(r"[,\s]+", text):
        out.extend(expand(tok))
    return out


def check(slice_name: str):
    problems = []
    want_path = os.path.join(RAW, "slices", slice_name + ".ids")
    if not os.path.exists(want_path):
        return [f"no such slice: {slice_name}"], 0, 0
    want = [l.strip() for l in open(want_path, encoding="utf-8") if l.strip()]
    part = os.path.join(PARTS, slice_name + ".md")
    if not os.path.exists(part):
        return [f"{slice_name}: part file not written ({len(want)} ids)"], len(want), 0
    text = open(part, encoding="utf-8", errors="replace").read().replace("\r\n", "\n")
    section = ""
    seen_lists: dict[str, int] = {}
    seen_sources: set[str] = set()
    entry = None
    entries = 0

    def close(e):
        if e is None:
            return
        f = e["fields"]
        for need in ("What was going on", "What the product must do", "Kind",
                     "Capability", "Found by", "State", "Sources"):
            if not f.get(need):
                problems.append(f"{e['id']}: missing field '{need}'")
        k = f.get("Kind", "")
        if k and k not in KINDS:
            problems.append(f"{e['id']}: Kind '{k}' (an entry is 1a, 1b, 2 or 3; "
                            "kinds 4 and 5 go under 'Stays behind')")
        if k == "1b" and not f.get("Tool"):
            problems.append(f"{e['id']}: kind 1b needs a Tool line")
        if f.get("Capability") and f["Capability"] not in CAPS:
            problems.append(f"{e['id']}: Capability '{f['Capability']}' is not in the list")
        if f.get("Found by") and f["Found by"] not in FOUND:
            problems.append(f"{e['id']}: Found by '{f['Found by']}'")
        if f.get("State") and f["State"] not in STATES:
            problems.append(f"{e['id']}: State '{f['State']}'")
        src = ids_in(f.get("Sources", ""))
        if f.get("Sources") and not src:
            problems.append(f"{e['id']}: no register id in Sources")
        seen_sources.update(src)

    for line in text.split("\n"):
        if line.startswith("## "):
            close(entry)
            entry = None
            section = line[3:].strip().lower()
            continue
        if section == "entries":
            m = re.match(r"^###\s+(\S+?):\s*(.*)$", line)
            if m:
                close(entry)
                entries += 1
                entry = {"id": m.group(1), "fields": {}}
                if not m.group(2).strip():
                    problems.append(f"{m.group(1)}: no title")
                continue
            m = re.match(r"^-\s+([A-Za-z ]+?):\s*(.*)$", line)
            if m and entry is not None:
                entry["fields"][m.group(1).strip()] = m.group(2).strip()
        elif section in ("stays behind", "no entry"):
            if not line.startswith("- "):
                continue
            cols = [c.strip() for c in line[2:].split("|")]
            got = ids_in(cols[0])
            if not got:
                problems.append(f"{section}: no id in line: {line[:80]}")
                continue
            if section == "stays behind" and (len(cols) < 3 or cols[1] not in ("kind 4", "kind 5")):
                problems.append(f"stays behind: wants 'ids | kind 4 | what it was': {line[:80]}")
            if section == "no entry" and (len(cols) < 2 or not cols[1]):
                problems.append(f"no entry: no reason: {line[:80]}")
            for i in got:
                seen_lists[i] = seen_lists.get(i, 0) + 1
    close(entry)

    for i, n in seen_lists.items():
        if n > 1:
            problems.append(f"{i} is listed {n} times in the two lists")
    accounted = seen_sources | set(seen_lists)
    missing = [i for i in want if i not in accounted]
    if missing:
        show = ", ".join(missing[:40]) + (" ..." if len(missing) > 40 else "")
        problems.append(f"{len(missing)} of {len(want)} ids not accounted for: {show}")
    return problems, len(want), entries


def main():
    names = sys.argv[1:]
    whole = not names
    if whole:
        names = sorted(os.path.basename(p)[:-4]
                       for p in glob.glob(os.path.join(RAW, "slices", "*.ids")))
    bad = 0
    total = entries = done = 0
    for name in names:
        problems, n, e = check(name)
        total += n
        entries += e
        if problems:
            bad += 1
            print(f"== {name}")
            for p in problems[:60]:
                print("  " + p)
            if len(problems) > 60:
                print(f"  ... and {len(problems) - 60} more")
        else:
            done += 1
    if whole:
        print(f"{done} of {len(names)} parts complete, {entries} entries, {total} ids in the slices")
    print("OK" if not bad else f"NOT OK: {bad} part(s) with problems")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
