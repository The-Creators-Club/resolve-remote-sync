#!/usr/bin/env python3
"""Step 3, part 2: gather every extract's items into one bundle per
capability (several for a large one), each with the knowledge-base lessons
of the same sub-topics, ready for the writers.

    python docs/rebuild-spec/tools/build_spec_bundles.py

Reads spec/_extracts/*.md and knowledge-base/<capability>.md and writes,
under the gitignored _raw/spec/:

    <capability>[-N].md       the items to write up, sub-topic by sub-topic,
                              each sub-topic followed by its lessons; then the
                              readers' questions about those items and the
                              points the inventory left unsettled
    <capability>[-N].questions  the ids of those questions and unsettled
                              points (for the count)
    <capability>[-N].ids      the item ids in the piece (for the count)
    <capability>[-N].lessons  the lesson ids in the piece (for the count)

An item filed under a heading the knowledge base does not have is placed
with the knowledge-base sub-topic it reads most like, so related things
reach the same writer; where nothing is alike it stays under its own
heading at the end. That placing only decides which writer sees it.

A reader's question goes to every piece that holds one of the items it
names, and says which other pieces also have it, so one writer answers for
it and the others point at it. A question naming no item, and every
unsettled line, goes to the piece it reads most like, among the pieces
holding items of the same inventory section.
Do not run again once a writer has started.
"""
from __future__ import annotations

import collections
import glob
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_extract as cx  # noqa: E402
import merged_lib as ml  # noqa: E402
from build_merge_bundles import STOP  # noqa: E402

OUT = os.path.join(ml.SPEC, "_raw", "spec")
PIECE = 150_000        # bytes of items one writer takes (its lessons come on top)
ALIKE = 0.10           # below this a stray heading keeps its own place


def toks(t: str):
    return [w for w in re.findall(r"[a-z][a-z0-9'-]{2,}", t.lower()) if w not in STOP]


def kb(cap: str):
    """-> [(sub-topic, [lesson lines])] in the file's order, and {sub-topic: text}"""
    path = os.path.join(ml.KB, cap + ".md")
    topics, cur, last = [], None, None
    if not os.path.exists(path):
        return topics
    for line in open(path, encoding="utf-8").read().split("\n"):
        if line.startswith("## "):
            cur = [line[3:].strip(), []]
            topics.append(cur)
        elif line.startswith("### ") and cur is not None:
            last = {"id": line[4:].split(":")[0], "title": line.split(":", 1)[1].strip()}
            cur[1].append(last)
        elif line.startswith("- Must:") and last is not None:
            last["must"] = line[7:].strip()
        elif line.startswith("- Kind:") and last is not None:
            last["kind"] = line[7:].strip()
    return topics


def render(it) -> str:
    f = it["fields"]
    out = [f"#### {it['id']}: {it['title']}", f"- Filed under: {f.get('Where', '')}",
           f"- What: {f.get('What', '')}"]
    for k in ("Flag", "Exact"):
        if f.get(k):
            out.append(f"- {k}: {f[k]}")
    return "\n".join(out) + "\n\n"


def main():
    items, questions, unsettled = [], [], []
    for nn in cx.sections():
        if os.path.exists(os.path.join(cx.EXTRACTS, nn + ".md")):
            its, qs, _old, uns, _cover = cx.parse(nn)
            items.extend(its)
            questions.extend((nn, q) for q in qs)
            unsettled.extend((nn, f"U-{nn}-{k}", u) for k, u in enumerate(uns, 1))
    by_cap = collections.defaultdict(list)
    for it in items:
        where = it["fields"].get("Where", "")
        cap = where.split("/")[0].strip().strip("`")
        it["sub"] = where.split("/", 1)[1].strip() if "/" in where else ""
        by_cap[cap].append(it)
    os.makedirs(OUT, exist_ok=True)
    for f in glob.glob(os.path.join(OUT, "*")):
        os.remove(f)
    report, held, strays_report = [], [], {}
    for cap in sorted(by_cap):
        topics = kb(cap)
        names = [t[0] for t in topics]
        low = {n.lower(): n for n in names}
        groups = collections.defaultdict(list)
        strays = []
        for it in by_cap[cap]:
            n = low.get(it["sub"].lower())
            (groups[n].append(it) if n else strays.append(it))
        # Place strays with the sub-topic they read most like.
        docs = {n: " ".join([n] + [l["title"] + " " + l.get("must", "") for l in ls]
                            + [i["title"] + " " + i["fields"].get("What", "") for i in groups[n]])
                for n, ls in topics}
        df = collections.Counter()
        bags = {n: collections.Counter(toks(t)) for n, t in docs.items()}
        for b in bags.values():
            df.update(set(b))
        N = max(len(bags), 1)

        def vec(counter):
            v = {w: (1 + math.log(c)) * math.log(1 + N / df[w]) for w, c in counter.items() if df[w]}
            norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
            return {w: x / norm for w, x in v.items()}
        tv = {n: vec(b) for n, b in bags.items()}
        other = collections.defaultdict(list)
        placed = 0
        for it in strays:
            v = vec(collections.Counter(toks(it["sub"] + " " + it["sub"] + " " + it["title"] + " "
                                             + it["fields"].get("What", ""))))
            best, score = None, 0.0
            for n, t in tv.items():
                s = sum(x * t.get(w, 0.0) for w, x in v.items())
                if s > score:
                    best, score = n, s
            if best and score >= ALIKE:
                groups[best].append(it)
                placed += 1
            else:
                other[it["sub"] or "Other"].append(it)
        order = [(n, groups[n], ls) for n, ls in topics] + \
                [(n, other[n], []) for n in sorted(other)]
        pieces, cur, size = [], [], 0
        for n, its, ls in order:
            if not its and not ls:
                continue
            b = sum(len(render(i).encode("utf-8")) for i in its)
            if cur and size + b > PIECE:
                pieces.append(cur)
                cur, size = [], 0
            cur.append((n, its, ls))
            size += b
        if cur:
            pieces.append(cur)
        for k, piece in enumerate(pieces, 1):
            held.append((cap if len(pieces) == 1 else f"{cap}-{k}", cap, k, pieces, piece))
        strays_report[cap] = (len(strays), placed)

    # Route the readers' questions and the unsettled lines to the pieces.
    home = {}                                   # item id -> piece name
    bag_of = {}                                 # piece name -> its words
    sections_in = collections.defaultdict(set)  # piece name -> inventory sections
    for name, cap, k, pieces, piece in held:
        words = []
        for n, its, ls in piece:
            words.append(n)
            for it in its:
                home[it["id"]] = name
                sections_in[name].add(it["id"].split("-")[0])
                words.append(it["title"] + " " + it["fields"].get("What", ""))
        bag_of[name] = collections.Counter(toks(" ".join(words)))
    dfp = collections.Counter()
    for b in bag_of.values():
        dfp.update(set(b))
    NP = max(len(bag_of), 1)

    def pvec(counter):
        v = {w: (1 + math.log(c)) * math.log(1 + NP / dfp[w]) for w, c in counter.items() if dfp[w]}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norm for w, x in v.items()}
    pv = {n: pvec(b) for n, b in bag_of.items()}

    def most_like(nn, text):
        v = pvec(collections.Counter(toks(text)))
        among = [n for n in pv if nn in sections_in[n]] or list(pv)
        return max(among, key=lambda n: sum(x * pv[n].get(w, 0.0) for w, x in v.items()))

    q_of = collections.defaultdict(list)        # piece name -> [(question id, line, other pieces)]
    u_of = collections.defaultdict(list)
    for nn, q in questions:
        cols = [c.strip() for c in q.split("|")]
        ids = re.findall(r"\b\d\d[a-d]?-\d{3}\b", " ".join(cols[3:]))
        where = sorted({home[i] for i in ids if i in home}) or [most_like(nn, " ".join(cols[2:]))]
        for name in where:
            q_of[name].append((cols[0], q, [w for w in where if w != name]))
    for nn, uid, u in unsettled:
        u_of[most_like(nn, u)].append((uid, u))

    for name, cap, k, pieces, piece in held:
        if True:
            n_items = sum(len(its) for _, its, _ in piece)
            n_less = sum(len(ls) for _, _, ls in piece)
            with open(os.path.join(OUT, name + ".md"), "w", encoding="utf-8", newline="\n") as f:
                f.write(f"# To write: {ml.NAMES.get(cap, cap)}"
                        + (f", piece {k} of {len(pieces)}" if len(pieces) > 1 else "")
                        + f" ({n_items} items, {n_less} lessons)\n\n")
                if len(pieces) > 1:
                    f.write("The whole capability's sub-topics, in order, with the piece each "
                            "is in:\n\n")
                    for j, p in enumerate(pieces, 1):
                        f.write(f"- piece {j}: " + "; ".join(n for n, _, _ in p) + "\n")
                    f.write("\n")
                for n, its, ls in piece:
                    f.write(f"## Sub-topic: {n}\n\n### Items ({len(its)})\n\n")
                    for it in sorted(its, key=lambda i: i["id"]):
                        f.write(render(it))
                    f.write(f"### Lessons this sub-topic must meet ({len(ls)})\n\n")
                    for l in ls:
                        f.write(f"- {l['id']} [{l.get('kind', '')}]: {l['title']} "
                                f"Must: {l.get('must', '')}\n")
                    f.write("\n")
                f.write("## Questions the readers raised about these items "
                        f"({len(q_of[name])})\n\n")
                for _qid, line, others in q_of[name]:
                    f.write(f"- {line}"
                            + (f" | ALSO WITH: {', '.join(others)}" if others else "") + "\n")
                f.write(f"\n## Left unsettled by the inventory ({len(u_of[name])})\n\n")
                for uid, u in u_of[name]:
                    f.write(f"- {uid} | {u}\n")
            with open(os.path.join(OUT, name + ".questions"), "w", encoding="utf-8",
                      newline="\n") as f:
                f.write("\n".join([qid for qid, _, _ in q_of[name]]
                                  + [uid for uid, _ in u_of[name]]) + "\n")
            with open(os.path.join(OUT, name + ".ids"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(i["id"] for _, its, _ in piece for i in its) + "\n")
            with open(os.path.join(OUT, name + ".lessons"), "w", encoding="utf-8",
                      newline="\n") as f:
                f.write("\n".join(l["id"] for _, _, ls in piece for l in ls) + "\n")
            kb_bytes = os.path.getsize(os.path.join(OUT, name + ".md")) // 1024
            report.append(f"{name}: {n_items} items, {n_less} lessons, {len(q_of[name])} questions, "
                          f"{len(u_of[name])} unsettled, {kb_bytes} KB")
    for cap, (n_strays, placed) in sorted(strays_report.items()):
        report.append(f"   ({cap}: {n_strays} items under headings of their own, "
                      f"{placed} placed with a knowledge-base sub-topic)")
    report.append(f"{len(questions)} questions and {len(unsettled)} unsettled lines routed")
    print(f"{len(items)} items in {len(by_cap)} capabilities")
    print("\n".join(report))


if __name__ == "__main__":
    main()
