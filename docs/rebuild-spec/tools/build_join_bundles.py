#!/usr/bin/env python3
"""Step 3, "After the writers": the joins between pieces.

    python docs/rebuild-spec/tools/build_join_bundles.py           write the bundles
    python docs/rebuild-spec/tools/build_join_bundles.py --check   check the readers' answers
    python docs/rebuild-spec/tools/build_join_bundles.py --fixes   per piece, the findings it must change for

Every piece's trace ends with "Joins with other capabilities": one line per
place where a behaviour of that piece leans on a sub-topic written by another
piece,

    - <capability> / <sub-topic> | <heading of the leaning behaviour> | <what it leans on>

Each writer saw only their own piece, so nobody has checked that the piece
leaned ON says what the leaning piece assumes. This gathers, per TARGET piece
(the one leaned on), every join aimed at it with the full text of the leaning
behaviour, into the gitignored _raw/joins/<target>.md. One reader per bundle
follows spec/_trace/JOINS_BRIEF.md and writes spec/_trace/_joins/<target>.md
(stays behind): every join either `fine` or a numbered finding.

A join aimed at a piece of its own capability (the editor's five parts, sync's
two) is checked like any other.
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

OUT = os.path.join(ml.SPEC, "_raw", "joins")
ANSWERS = os.path.join(cs.TRACE, "_joins")


def behaviours(piece):
    """-> {### heading: its text}, [## sub-topics]"""
    heads, subs, cur = {}, [], None
    for l in cs.lines_of(os.path.join(cs.TEXT, piece + ".md")):
        if l.startswith("## "):
            subs.append(l[3:].strip())
            cur = None
        elif l.startswith("### "):
            cur = l[4:].strip()
            heads[cur] = []
        elif l.startswith("#### "):
            cur = None
        elif cur is not None:
            heads[cur].append(l)
    return {h: "\n".join(b).strip() for h, b in heads.items()}, subs


def gather():
    """-> ({target piece: [join]}, [joins that could not be placed])"""
    pieces = cs.pieces()
    text = {p: behaviours(p) for p in pieces}
    names = {v.lower(): k for k, v in ml.NAMES.items()}
    where = {}                                   # (capability, sub-topic lower) -> piece
    for p in pieces:
        for s in text[p][1]:
            where[(ml.capability_of(p), s.lower())] = p
    by_target, unplaced = collections.defaultdict(list), []
    for p in pieces:
        part = ""
        for l in cs.lines_of(os.path.join(cs.TRACE, p + ".md")):
            if l.startswith("## "):
                part = l[3:].strip().lower()
                continue
            if not (part.startswith("joins with") and l.startswith("- ")):
                continue
            cols = [c.strip() for c in l[2:].split("|")]
            target = cols[0]
            j = {"from": p, "target": target, "heading": cols[1] if len(cols) > 1 else "",
                 "leans": " | ".join(cols[2:]) if len(cols) > 2 else ""}
            if "/" in target:
                cap, sub = [x.strip() for x in target.split("/", 1)]
            else:                                # leans on a whole capability
                cap, sub = target, ""
            cap = re.sub(r"\s*\(part \d+\)$|,\s*part \d+$", "", cap, flags=re.I)
            key = names.get(cap.lower(), cap.lower())
            key = key if key in ml.NAMES else ml.capability_of(key)
            # One join may name several sub-topics ("a; b"); each is looked up.
            tps = []
            for one in ([x.strip() for x in sub.split(";")] if sub else []):
                t = where.get((key, one.lower()))
                if t and t not in tps:
                    tps.append(t)
            if not sub:
                tps = [q for q in pieces if ml.capability_of(q) == key][:1]
                sub = "(the capability as a whole)"
            if not tps:
                unplaced.append((j, "no written piece has that sub-topic"))
                continue
            tp = tps[0]
            j["sub"] = sub
            # The leaning behaviour's own words. A join may name several
            # headings, or paraphrase one; give what can be found.
            found = [h for h in [x.strip() for x in j["heading"].split(" ; ")] if h in text[p][0]]
            j["bodies"] = [(h, text[p][0][h]) for h in found]
            for tp in tps:
                by_target[tp].append(j)
    return by_target, unplaced


def write():
    by_target, unplaced = gather()
    os.makedirs(OUT, exist_ok=True)
    total = 0
    for tp in sorted(by_target):
        out = [f"# Joins aimed at the piece `{tp}`", "",
               f"{len(by_target[tp])} places where a behaviour of ANOTHER piece leans on something "
               f"`spec/{tp}.md` is said to hold. Check each against that piece's text.", ""]
        for n, j in enumerate(by_target[tp], 1):
            out += [f"## J{n}: from `{j['from']}`, leaning on the sub-topic \"{j['sub']}\"", "",
                    f"- Leaning behaviour: {j['heading']}",
                    f"- What it says it leans on: {j['leans']}", ""]
            if not j["bodies"]:
                out += ["(The join names no heading that `spec/" + j["from"] + ".md` has word for "
                        "word. Find the behaviour in that file by its sense.)", ""]
            for h, body in j["bodies"]:
                out += [f"The leaning behaviour's text (`spec/{j['from']}.md`, \"{h}\"):", ""]
                out += ["> " + b if b.strip() else ">" for b in body.split("\n")]
                out.append("")
        with open(os.path.join(OUT, tp + ".md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out).rstrip() + "\n")
        with open(os.path.join(OUT, tp + ".ids"), "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(f"J{n}\n" for n in range(1, len(by_target[tp]) + 1)))
        total += len(by_target[tp])
        print(f"{tp}: {len(by_target[tp])} joins, "
              f"{os.path.getsize(os.path.join(OUT, tp + '.md')) // 1024} KB")
    if unplaced:
        with open(os.path.join(OUT, "_unplaced.md"), "w", encoding="utf-8", newline="\n") as f:
            for j, why in unplaced:
                f.write(f"- {j['from']} -> {j['target']} | {j['heading']} | {why}\n")
    print(f"{total} joins in {len(by_target)} bundles; {len(unplaced)} could not be placed"
          + (" (see _raw/joins/_unplaced.md)" if unplaced else ""))


FKINDS = ("contradiction", "missing", "differs", "said twice")


def check():
    names = sorted(f[:-4] for f in os.listdir(OUT) if f.endswith(".ids")) if os.path.isdir(OUT) else []
    bad = done = findings = 0
    tally = collections.Counter()
    for tp in names:
        path = os.path.join(ANSWERS, tp + ".md")
        if not os.path.exists(path):
            print(f"{tp}: not checked yet")
            continue
        want = cs.ids_in(os.path.join(OUT, tp + ".ids"))
        part, seen, found, cur, problems = "", {}, {}, None, []
        for l in cs.lines_of(path):
            if l.startswith("## "):
                part, cur = l[3:].strip().lower(), None
            elif part == "checked" and l.startswith("- "):
                m = re.match(r"^- (J\d+)\s*\|\s*(.*)$", l)
                if not m:
                    problems.append(f"checked: cannot read '{l[:60]}'")
                else:
                    seen[m.group(1)] = m.group(2).strip()
            elif part == "findings":
                m = re.match(r"^### (F\d+):\s*(.*)$", l)
                if m:
                    cur = {"title": m.group(2)}
                    found[m.group(1)] = cur
                else:
                    m = re.match(r"^- ([A-Z][A-Za-z ]+?):\s*(.*)$", l)
                    if m and cur is not None:
                        cur[m.group(1)] = m.group(2).strip()
        missing = [j for j in want if j not in seen]
        if missing:
            problems.append(f"{len(missing)} of {len(want)} joins not accounted for: "
                            + ", ".join(missing[:20]))
        for j, what in seen.items():
            if what != "fine" and not all(f in found for f in re.findall(r"F\d+", what)) \
                    or (what != "fine" and not re.findall(r"F\d+", what)):
                problems.append(f"{j}: must be `fine` or name findings that exist ({what[:40]})")
        for fid, f in found.items():
            for k in ("Kind", "From", "Here", "From says", "Here says", "Settled by", "Fix"):
                if not f.get(k):
                    problems.append(f"{fid}: no '{k}:' line")
            if f.get("Kind") and not f["Kind"].lower().startswith(FKINDS):
                problems.append(f"{fid}: Kind must start with one of {FKINDS}")
            else:
                tally[f.get("Kind", "").split()[0].lower() if f.get("Kind") else "?"] += 1
        if problems:
            bad += 1
            print(f"{tp}: {len(problems)} problem(s)")
            for p in problems[:30]:
                print("   " + p)
        else:
            done += 1
            findings += len(found)
    print(f"{done} of {len(names)} bundles checked and passing; {findings} findings "
          + str(dict(tally)))
    print("OK" if names and done == len(names) else "NOT OK")
    sys.exit(0 if not bad else 1)


RULINGS = os.path.join(ANSWERS, "RULINGS.txt")
FIXES = os.path.join(ml.SPEC, "_raw", "join-fixes")
VERDICTS = ("apply", "instead", "home", "owner", "code", "drop", "same")


def findings():
    """-> [finding] across every reader's answer: target, id, title and the
    seven lines, plus which joins named it."""
    out = []
    if not os.path.isdir(ANSWERS):
        return out
    for f in sorted(os.listdir(ANSWERS)):
        if not f.endswith(".md"):
            continue
        tp, part, cur = f[:-3], "", None
        for l in cs.lines_of(os.path.join(ANSWERS, f)):
            if l.startswith("## "):
                part, cur = l[3:].strip().lower(), None
            elif part == "findings":
                m = re.match(r"^### (F\d+):\s*(.*)$", l)
                if m:
                    cur = {"target": tp, "id": m.group(1), "title": m.group(2).strip()}
                    out.append(cur)
                else:
                    m = re.match(r"^- ([A-Z][A-Za-z ]+?):\s*(.*)$", l)
                    if m and cur is not None:
                        cur[m.group(1)] = m.group(2).strip()
    return out


def rulings():
    """-> ({(target, F id): (verdict, note)}, problems). The lead's word on a
    finding; a finding with no line is applied as its reader wrote it."""
    out, problems = {}, []
    if not os.path.exists(RULINGS):
        return out, problems
    for n, line in enumerate(open(RULINGS, encoding="utf-8"), 1):
        line = line.rstrip("\r\n")
        if not line.strip() or line.startswith("#"):
            continue
        cols = [c.strip() for c in line.split("|", 2)]
        m = re.match(r"^(\S+)\s+(F\d+)$", cols[0])
        if not m or len(cols) < 2 or cols[1].split()[0] not in VERDICTS:
            problems.append(f"RULINGS L{n}: cannot read '{line[:70]}'")
            continue
        out[(m.group(1), m.group(2))] = (cols[1], cols[2] if len(cols) > 2 else "")
    return out, problems


def fixes():
    """Write, per piece, the findings it may have to change for."""
    pieces = cs.pieces()
    rl, problems = rulings()
    fs = findings()
    known = {(f["target"], f["id"]) for f in fs}
    for k in rl:
        if k not in known:
            problems.append(f"RULINGS: no finding {k[0]} {k[1]}")
    for p in problems:
        print("PROBLEM: " + p)
    if problems:
        sys.exit(1)
    os.makedirs(FIXES, exist_ok=True)
    per = collections.defaultdict(list)
    held = collections.Counter()
    for f in fs:
        verdict, note = rl.get((f["target"], f["id"]), ("apply", ""))
        word = verdict.split()[0]
        if word in ("owner", "code", "drop", "same"):
            held[word] += 1
            continue
        # every piece the finding names may be the one that changes
        blob = " ".join([f.get("From", ""), f.get("Fix", ""), note, f["title"]])
        named = {p for p in pieces if re.search(r"(?<![\w-])" + re.escape(p) + r"(?![\w-])", blob)}
        named.add(f["target"])
        for p in sorted(named):
            per[p].append((f, verdict, note))
    for p in pieces:
        path = os.path.join(FIXES, p + ".md")
        if not per.get(p):
            if os.path.exists(path):
                os.remove(path)
            continue
        out = [f"# Disagreements between pieces that name `{p}`", "",
               f"{len(per[p])} findings. Each says which piece changes. Change `{p}` only where "
               "a finding says this piece changes.", ""]
        for f, verdict, note in per[p]:
            out += [f"## {f['target']} {f['id']}: {f['title']}", ""]
            out += [f"- {k}: {f.get(k, '')}" for k in
                    ("Kind", "From", "Here", "From says", "Here says", "Settled by", "Fix")]
            out.append(f"- (\"Here\" is the piece `{f['target']}`.)")
            if verdict != "apply":
                out.append(f"- THE LEAD'S RULING, which outranks the Fix line: {verdict}"
                           + (f": {note}" if note else ""))
            elif note:
                # An `apply` with a note: the reader had left the choice open
                # ("the owner must say", "if the owner says ...") and the
                # settler found what decides it. Without this line a fixer
                # reads the finding as still waiting for the owner.
                out.append("- THE LEAD'S RULING: this is SETTLED, it does not wait for the owner. "
                           "Apply the Fix; where the Fix gives a choice or a condition, this "
                           f"decides it: {note}")
            out.append("")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(out))
        print(f"{p}: {len(per[p])} findings")
    print(f"{len(fs)} findings; held back: {dict(held)}")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--fixes" in sys.argv:
        fixes()
    else:
        write()
