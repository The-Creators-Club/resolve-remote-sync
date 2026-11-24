#!/usr/bin/env python3
"""The count for step 3, part 2 (REBUILD_PLAN.md, "Step 3 as it is being done").

    python docs/rebuild-spec/tools/check_spec.py music            check one piece
    python docs/rebuild-spec/tools/check_spec.py                  check every piece
    python docs/rebuild-spec/tools/check_spec.py music --build    also write the built text

A piece is spec/<piece>.md (the text that crosses) with spec/_trace/<piece>.md
(stays behind), written from the bundle _raw/spec/<piece>.md under
spec/_trace/WRITER_BRIEF.md. Checks that every item, lesson, reader's
question and unsettled point of the bundle is accounted for, that the trace
names headings the text really has, and that the text gives nothing away:
no giveaway word, no word that admits a past, no long dash, no stray id.

A line `{{31-044}}` in the text stands for that item's own words, carried
across exactly; --build writes the text with those lines filled in, under
the gitignored _raw/spec-built/.
"""
from __future__ import annotations

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_extract as cx  # noqa: E402
import merged_lib as ml  # noqa: E402
from lint_parts import RX  # noqa: E402

RAW = os.path.join(ml.SPEC, "_raw", "spec")
BUILT = os.path.join(ml.SPEC, "_raw", "spec-built")
TEXT = os.path.join(ml.SPEC, "spec")
TRACE = os.path.join(TEXT, "_trace")

ITEM = re.compile(r"\b\d\d[a-d]?-\d{3}\b")
RQ = re.compile(r"\b(?:\d\d[a-d]?-Q\d+|U-\d\d[a-d]?-\d+)\b")
INCLUDE = re.compile(r"^\{\{(\d\d[a-d]?-\d{3})\}\}$")
# Words that admit the product had a past, or exists in more than one form.
PAST = re.compile(r"\b(today|currently|at present|present build|old build|legacy|the inventory|"
                  r"originally|previously|built twice|two forms|the reader)\b", re.I)
QKINDS = ("several ways in", "built twice", "differs", "dormant", "unreachable", "dev only",
          "either-or", "other")
QFIELDS = ("Kind", "Today", "Options", "Recommend", "Changes for a person", "Text assumes", "Items")

_items = {}


def item(iid: str):
    nn = iid.split("-")[0]
    if nn not in _items:
        path = os.path.join(cx.EXTRACTS, nn + ".md")
        _items[nn] = {i["id"]: i for i in cx.parse(nn)[0]} if os.path.exists(path) else {}
    return _items[nn].get(iid)


def lines_of(path):
    return open(path, encoding="utf-8", errors="replace").read().replace("\r\n", "\n").split("\n")


def ids_in(path):
    return [l.strip() for l in lines_of(path) if l.strip()] if os.path.exists(path) else []


def pieces():
    return sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(RAW, "*.ids")))


def unquoted(line: str) -> str:
    """The line without what is inside double quotes: wording a person is shown."""
    return re.sub(r'"[^"]*"|“[^”]*”', '""', line)


def read_text(piece: str):
    """-> (problems, built lines, {### heading}, [## headings], counts)"""
    problems, built, heads, subs = [], [], {}, []
    counts = {"behaviours": 0, "settings": 0, "pending": 0, "included": 0}
    pending, included = [], []
    raw = lines_of(os.path.join(TEXT, piece + ".md"))
    # Which ### sections are marked exact: the word nets are skipped inside them.
    exact, cur, fence = set(), None, False
    for n, line in enumerate(raw):
        if line.startswith("```"):
            fence = not fence
        if fence:
            continue
        if re.match(r"^#{1,3} ", line):
            cur = n if line.startswith("### ") else None
        elif cur is not None and line.strip().lower().startswith("- exact: yes"):
            exact.add(cur)
    cur, fence = None, False
    for n, line in enumerate(raw):
        if line.startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            subs.append(line[3:].strip())
            cur = None
        elif not fence and line.startswith("### "):
            h = line[4:].strip()
            cur = n
            counts["behaviours"] += 1
            if h in heads:
                problems.append(f"text L{n + 1}: the heading '{h[:60]}' is used twice")
            if "|" in h or ";" in h:
                problems.append(f"text L{n + 1}: a heading must not contain | or ;")
            heads[h] = n
        m = INCLUDE.match(line.strip())
        if m:
            it = item(m.group(1))
            if not it:
                problems.append(f"text L{n + 1}: no item {m.group(1)}")
            elif not it["fields"].get("Exact", "").lower().startswith("yes"):
                problems.append(f"text L{n + 1}: {m.group(1)} is not an Exact item; write it out")
            elif cur not in exact:
                problems.append(f"text L{n + 1}: {m.group(1)} is carried exactly, so its heading "
                                f"needs `- Exact: yes`")
            else:
                body = it["fields"].get("What", "")
                if ITEM.search(body) or RQ.search(body):
                    problems.append(f"text L{n + 1}: {m.group(1)}'s own words name another id; "
                                    f"copy it by hand and repair it")
                built.extend(body.split("\n"))
                included.append(m.group(1))
            continue
        built.append(line)
        if line.startswith("- Setting:"):
            counts["settings"] += 1
            for part in ("Does:", "Default:", "Who:", "Applies to:", "Search words:"):
                if part not in line and part not in " ".join(raw[n:n + 8]):
                    problems.append(f"text L{n + 1}: a Setting line needs '{part}'")
                    break
        if line.startswith("- Pending:"):
            counts["pending"] += 1
            pending.extend(re.findall(rf"{re.escape(piece)}-[QU]\d+", line))
            if not re.search(rf"{re.escape(piece)}-[QU]\d+", line):
                problems.append(f"text L{n + 1}: Pending needs an id like {piece}-Q1 or {piece}-U1")
            continue
        if fence:
            continue
        for m2 in ITEM.finditer(line):
            problems.append(f"text L{n + 1}: an item id ({m2.group(0)}) outside double braces")
        for m2 in RQ.finditer(line):
            problems.append(f"text L{n + 1}: a reader's id ({m2.group(0)}) in the text")
        if "—" in line or "–" in line:
            problems.append(f"text L{n + 1}: a long dash")
        if cur in exact or line.startswith(("#### Lessons", "- Met:", "- Not yet met",
                                            "- Tied to an arrangement")):
            continue
        hits = sorted({h.group(0).lower() for h in RX.finditer(line)})
        if hits:
            problems.append(f"text L{n + 1} names: {', '.join(hits[:8])}")
        hits = sorted({h.group(0).lower() for h in PAST.finditer(unquoted(line))})
        if hits:
            problems.append(f"text L{n + 1} admits a past: {', '.join(hits)}")
    counts["included"] = len(included)
    return problems, built, heads, subs, counts, pending, included


def read_trace(piece: str):
    part, cover, questions, readers, unsettled, cur = "", {}, {}, {}, {}, None
    problems = []
    for line in lines_of(os.path.join(TRACE, piece + ".md")):
        if line.startswith("## "):
            part, cur = line[3:].strip().lower(), None
            continue
        if part == "coverage" and line.startswith("- "):
            m = re.match(r"^- (\d\d[a-d]?-\d{3})\s*\|\s*(.*)$", line)
            if not m:
                problems.append(f"coverage: cannot read '{line[:60]}'")
            elif m.group(1) in cover:
                problems.append(f"coverage: {m.group(1)} is listed twice")
            else:
                cover[m.group(1)] = m.group(2).strip()
        elif part.startswith("questions for the owner"):
            m = re.match(r"^### (\S+?):\s*(.*)$", line)
            if m:
                cur = {"title": m.group(2).strip()}
                questions[m.group(1)] = cur
            else:
                m = re.match(r"^- ([A-Z][A-Za-z ]+?):\s*(.*)$", line)
                if m and cur is not None:
                    cur[m.group(1)] = m.group(2).strip()
        elif part.startswith("readers' questions") and line.startswith("- "):
            m = re.match(r"^- (\S+)\s*\|\s*(.*)$", line)
            if m:
                readers[m.group(1)] = m.group(2).strip()
            else:
                problems.append(f"readers' questions: cannot read '{line[:60]}'")
        elif part.startswith("still unsettled") and line.startswith("- "):
            m = re.match(r"^- (\S+)\s*\|\s*(.*)$", line)
            if m:
                unsettled[m.group(1)] = m.group(2).strip()
    return problems, cover, questions, readers, unsettled


def check(piece: str, build=False):
    text_path = os.path.join(TEXT, piece + ".md")
    trace_path = os.path.join(TRACE, piece + ".md")
    if not os.path.exists(text_path):
        return [f"{piece}: not written yet"], None
    if not os.path.exists(trace_path):
        return [f"{piece}: the text is there but the trace is not"], None
    problems, built, heads, subs, counts, pending, included = read_text(piece)
    tp, cover, questions, readers, unsettled = read_trace(piece)
    problems += tp

    # The sub-topics are the bundle's, in order.
    want_subs = [l[len("## Sub-topic: "):].strip()
                 for l in lines_of(os.path.join(RAW, piece + ".md")) if l.startswith("## Sub-topic: ")]
    if subs != want_subs:
        missing = [s for s in want_subs if s not in subs]
        extra = [s for s in subs if s not in want_subs]
        problems.append("the ## headings must be the bundle's sub-topics, in order"
                        + (f"; missing: {missing[:6]}" if missing else "")
                        + (f"; not in the bundle: {extra[:6]}" if extra else ""))

    # Every item, once.
    want = ids_in(os.path.join(RAW, piece + ".ids"))
    missing = [i for i in want if i not in cover]
    if missing:
        problems.append(f"{len(missing)} of {len(want)} items are in no coverage line: "
                        + ", ".join(missing[:25]))
    for i in cover:
        if i not in want:
            problems.append(f"coverage: {i} is not an item of this bundle")
    left_out = 0
    for i, where in cover.items():
        if where.lower().startswith("left out:"):
            left_out += 1
            if len(where) < 14:
                problems.append(f"coverage {i}: say why it was left out")
            continue
        for h in [w.strip() for w in where.split(" ; ")]:
            if h not in heads:
                problems.append(f"coverage {i}: the text has no heading '{h[:70]}'")
    for i in included:
        if i not in want:
            problems.append(f"{{{{{i}}}}} is not an item of this bundle")

    # Every lesson.
    whole = "\n".join(built)
    lessons = ids_in(os.path.join(RAW, piece + ".lessons"))
    missing = [l for l in lessons if not re.search(rf"\b{re.escape(l)}\b", whole)]
    if missing:
        problems.append(f"{len(missing)} of {len(lessons)} lessons are in no Lessons line: "
                        + ", ".join(missing[:25]))
    not_met = len(re.findall(r"[A-Z][A-Z0-9]{2}-\d{3}", " ".join(
        l for l in built if l.startswith("- Not yet met"))))
    tied = len(re.findall(r"[A-Z][A-Z0-9]{2}-\d{3}", " ".join(
        l for l in built if l.startswith("- Tied to an arrangement"))))
    arranged = sum(1 for w in cover.values() if w.lower().startswith("left out: an arrangement"))

    # Every reader's question and unsettled point.
    asked = ids_in(os.path.join(RAW, piece + ".questions"))
    missing = [q for q in asked if q not in readers]
    if missing:
        problems.append(f"{len(missing)} of {len(asked)} readers' questions and unsettled points "
                        f"are not accounted for: " + ", ".join(missing[:25]))
    for q, what in readers.items():
        m = re.match(rf"^(open:\s*)?({re.escape(piece)}-[QU]\d+)\b", what)
        if m and m.group(2) not in questions and m.group(2) not in unsettled:
            problems.append(f"{q}: the trace has no {m.group(2)}")
        elif not m and not re.match(r"^(answered:|with |not a question:|settled:|behind the glass)",
                                    what):
            problems.append(f"{q}: say what became of it ({piece}-Q<n>, answered:, with <piece>, "
                            f"not a question:, settled:, open: {piece}-U<n>, behind the glass)")

    # The owner's questions are complete.
    for qid, q in questions.items():
        if not re.match(rf"^{re.escape(piece)}-Q\d+$", qid):
            problems.append(f"question id '{qid}' must be {piece}-Q<n>")
        for f in QFIELDS:
            if not q.get(f):
                problems.append(f"{qid}: no '{f}:' line")
        if q.get("Kind") and not q["Kind"].lower().startswith(QKINDS):
            problems.append(f"{qid}: Kind must start with one of {QKINDS}")
        for i in ITEM.findall(q.get("Items", "")):
            if i not in want:
                problems.append(f"{qid}: {i} is not an item of this bundle")
    for p in pending:
        if p not in questions and p not in unsettled:
            problems.append(f"the text has Pending: {p} but the trace has no such entry")

    if build:
        os.makedirs(BUILT, exist_ok=True)
        with open(os.path.join(BUILT, piece + ".md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(built))
    counts.update(items=len(want), left_out=left_out, lessons=len(lessons), not_met=not_met,
                  tied=tied, arranged=arranged,
                  questions=len(questions), unsettled=len(unsettled),
                  kb=len(whole.encode("utf-8")) // 1024)
    return problems, counts


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    build = "--build" in sys.argv
    names = args or pieces()
    bad = done = 0
    todo = []
    tot = {"behaviours": 0, "settings": 0, "pending": 0, "questions": 0, "unsettled": 0}
    for name in names:
        problems, counts = check(name, build)
        if counts is None:
            todo.append(name)
            if args:
                print(problems[0])
            continue
        if problems:
            bad += 1
            print(f"{name}: {len(problems)} problem(s)")
            for p in problems[:60]:
                print("   " + p)
        else:
            done += 1
        for k in tot:
            tot[k] += counts[k]
        if args:
            print(f"{name}: {counts['items']} items ({counts['left_out']} left out, "
                  f"{counts['arranged']} of those as arrangements; "
                  f"{counts['included']} carried exactly), {counts['behaviours']} behaviours, "
                  f"{counts['settings']} settings, {counts['lessons']} lessons "
                  f"({counts['not_met']} not yet met, {counts['tied']} tied to an arrangement), "
                  f"{counts['questions']} questions, "
                  f"{counts['pending']} pending marks, {counts['unsettled']} still unsettled, "
                  f"{counts['kb']} KB")
    if not args:
        print(f"{done} of {len(names)} pieces written and passing; "
              f"{tot['behaviours']} behaviours, {tot['settings']} settings, "
              f"{tot['questions']} questions, {tot['pending']} pending marks, "
              f"{tot['unsettled']} still unsettled"
              + (f"; not written: {' '.join(todo)}" if todo else ""))
    print("OK" if not bad and not (todo and not args) else f"NOT OK: {bad + len(todo)} with problems")
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
