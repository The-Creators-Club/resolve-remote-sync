#!/usr/bin/env python3
"""The count for step 3, part 1 (REBUILD_PLAN.md, "Step 3 in detail").

    python docs/rebuild-spec/tools/check_extract.py 03 --headings   list the section's headings
    python docs/rebuild-spec/tools/check_extract.py 03              check one extract
    python docs/rebuild-spec/tools/check_extract.py                 check every extract

An extract is spec/_extracts/<NN>.md, written from inventory section <NN>
under spec/_extracts/EXTRACT_BRIEF.md. Every `##` and `###` heading of the
inventory section must be accounted for in the extract's Coverage list,
either by the items drawn from it or by a reason it was left behind. Also
checks the fields, the capability names and the giveaway words.
"""
from __future__ import annotations

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.abspath(os.path.join(HERE, ".."))
INV = os.path.abspath(os.path.join(SPEC, "..", "feature-inventory"))
EXTRACTS = os.path.join(SPEC, "spec", "_extracts")
SKIP = {"44"}            # Story Deck: cut by the owner, a record only

sys.path.insert(0, HERE)
from lint_parts import RX  # noqa: E402
from merged_lib import NAMES  # noqa: E402

FLAGS = ("several ways in", "built twice", "differs", "dormant", "dev only", "unreachable",
         "undetermined")
QKINDS = ("several ways in", "built twice", "dormant", "either-or", "other")


def section_path(nn: str):
    hits = glob.glob(os.path.join(INV, nn + "-*.md"))
    return hits[0] if hits else None


def headings(nn: str):
    """-> [(line number, heading text)] for every ## and ### of the section."""
    out, fence = [], False
    for n, line in enumerate(open(section_path(nn), encoding="utf-8", errors="replace"), 1):
        if line.startswith("```"):
            fence = not fence
        if not fence and re.match(r"^#{2,3} ", line):
            out.append((n, line.strip()))
    return out


def sections():
    return sorted(os.path.basename(p)[:2] for p in glob.glob(os.path.join(INV, "[0-9][0-9]-*.md"))
                  if os.path.basename(p)[:2] not in SKIP)


def parse(nn: str):
    """-> (items, questions, old data lines, unsettled lines, coverage{line: text})"""
    path = os.path.join(EXTRACTS, nn + ".md")
    text = open(path, encoding="utf-8", errors="replace").read().replace("\r\n", "\n")
    part, cur, field = "", None, None
    items, questions, old, unsettled, cover = [], [], [], [], {}
    for line in text.split("\n"):
        if line.startswith("## "):
            part, cur, field = line[3:].strip().lower(), None, None
            continue
        if part == "items":
            m = re.match(r"^###\s+(\S+?):\s*(.*)$", line)
            if m:
                cur = {"id": m.group(1), "title": m.group(2).strip(), "fields": {}}
                items.append(cur)
                field = None
                continue
            m = re.match(r"^- (Where|What|Flag|Exact):\s*(.*)$", line)
            if m and cur is not None:
                field = m.group(1)
                cur["fields"][field] = m.group(2).strip()
            elif cur is not None and field and line.strip():
                cur["fields"][field] += "\n" + line          # a What may run over lines
        elif line.startswith("- "):
            if part.startswith("questions"):
                questions.append(line[2:])
            elif part.startswith("old data"):
                old.append(line[2:])
            elif part.startswith("unsettled"):
                unsettled.append(line[2:])
            elif part == "coverage":
                m = re.match(r"^- L(\d+)\s*\|\s*(.*)$", line)
                if m:
                    cover[int(m.group(1))] = m.group(2).strip()
                else:
                    cover[-len(cover) - 1] = line
    return items, questions, old, unsettled, cover


def check(nn: str):
    problems = []
    if not section_path(nn):
        return [f"no inventory section {nn}"], 0
    path = os.path.join(EXTRACTS, nn + ".md")
    if not os.path.exists(path):
        return [f"{nn}: not written yet"], 0
    items, questions, old, unsettled, cover = parse(nn)
    ids = [i["id"] for i in items]
    for n, i in enumerate(ids, 1):
        if i != f"{nn}-{n:03d}":
            problems.append(f"item {n} is '{i}', expected {nn}-{n:03d}")
            break
    for it in items:
        f = it["fields"]
        where = f.get("Where", "")
        cap = where.split("/")[0].strip().strip("`")
        if cap not in NAMES:
            problems.append(f"{it['id']}: Where must start with a capability name, got '{where[:50]}'")
        elif "/" not in where or not where.split("/", 1)[1].strip():
            problems.append(f"{it['id']}: Where needs a sub-topic after the capability")
        if not it["title"]:
            problems.append(f"{it['id']}: no title")
        if len(f.get("What", "").split()) < 4:
            problems.append(f"{it['id']}: no What")
        flag = f.get("Flag", "")
        if flag and not flag.lower().startswith(FLAGS):
            problems.append(f"{it['id']}: Flag must start with one of {FLAGS}")
        if f.get("Exact", "").lower().startswith("yes"):
            continue
        for label, t in (("title", it["title"]), ("What", f.get("What", ""))):
            hits = sorted({h.group(0).lower() for h in RX.finditer(t)})
            if hits:
                problems.append(f"{it['id']} [{label}] names: {', '.join(hits[:8])}")
    for q in questions:
        cols = [c.strip() for c in q.split("|")]
        if len(cols) < 3 or not re.match(rf"^{nn}-Q\d+$", cols[0]) or not cols[1].startswith(QKINDS):
            problems.append(f"question line must be `{nn}-Q<n> | <kind> | <question>`: {q[:70]}")
        else:
            hits = sorted({h.group(0).lower() for h in RX.finditer(" ".join(cols[2:]))})
            if hits:
                problems.append(f"{cols[0]} names: {', '.join(hits[:8])}")
    want = dict(headings(nn))
    used = set()
    for n, textv in cover.items():
        if n not in want:
            problems.append(f"coverage: L{n} is not a heading line of section {nn}"
                            if n > 0 else f"coverage: cannot read '{textv[:60]}'")
            continue
        got = re.findall(rf"\b{nn}-\d{{3}}\b", textv)
        for i in got:
            if i not in ids:
                problems.append(f"coverage L{n}: no item {i}")
        used.update(got)
        if not got and not textv.lower().startswith("left behind:"):
            problems.append(f"coverage L{n}: give item ids or `left behind: <why>`")
    missing = [n for n in want if n not in cover]
    if missing:
        problems.append(f"{len(missing)} of {len(want)} headings not accounted for: "
                        + ", ".join(f"L{n}" for n in missing[:40]))
    orphans = [i for i in ids if i not in used]
    if orphans:
        problems.append(f"{len(orphans)} items are in no coverage line: {', '.join(orphans[:20])}")
    return problems, len(items)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--headings" in sys.argv:
        for n, h in headings(args[0]):
            print(f"L{n} | {h}")
        return
    whole = not args
    names = args or sections()
    bad = done = total = 0
    for nn in names:
        problems, n = check(nn)
        total += n
        if problems:
            bad += 1
            if not (whole and problems[0].endswith("not written yet")):
                print(f"== {nn}")
                for p in problems[:60]:
                    print("  " + p)
                if len(problems) > 60:
                    print(f"  ... and {len(problems) - 60} more")
        else:
            done += 1
    if whole:
        todo = [nn for nn in names if not os.path.exists(os.path.join(EXTRACTS, nn + ".md"))]
        print(f"{done} of {len(names)} extracts written and passing, {total} items"
              + (f"; not written: {' '.join(todo)}" if todo else ""))
    print("OK" if not bad else f"NOT OK: {bad} with problems")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
