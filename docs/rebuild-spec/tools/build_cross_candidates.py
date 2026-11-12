#!/usr/bin/env python3
"""Step 2, the pass across capabilities: find finished entries that may be
the same lesson filed in two places, and lay them side by side for a reader
to rule on.

    python docs/rebuild-spec/tools/build_cross_candidates.py

Each capability was merged by an agent that saw only that capability, so a
lesson filed under two of them is still in both. This script decides
nothing. It pairs entries from DIFFERENT merged files that either read
alike or were drawn from the same original report, groups the pairs, and
writes the groups in batches a reader can take whole:

    knowledge-base/_cross/batch-NN.md     the groups, entries in full
    knowledge-base/_cross/batch-NN.ids    the group numbers in the batch
    knowledge-base/_cross/moves.md        one group per entry a merger marked
                                          `Move to:`, with its likely twins
                                          in the target capability
    knowledge-base/_cross/moves.ids

The reader's rulings go in knowledge-base/_cross/batch-NN.rulings (the
brief is _parts/KB_CROSS_BRIEF.md); check_cross.py checks them and
assemble_kb.py applies them. Sealed entries are grouped among themselves.
"""
from __future__ import annotations

import collections
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merged_lib as ml  # noqa: E402
from build_merge_bundles import STOP  # noqa: E402

# Measured 2026-11-12 on 1,955 entries by reading samples: at 0.40 and above
# five pairs in six were one lesson; between 0.30 and 0.40 about two in six;
# below 0.25 almost none. Sharing an original report is a weak sign on its
# own (a wide review is cited by dozens of unrelated entries), so it only
# lowers the bar a little.
ALIKE = 0.28          # cosine at or above this: a candidate pair on wording alone
ALIKE_SHARED = 0.17   # ... when the two also come from the same original report
ALIKE_TITLE = 0.60    # ... or when what the person saw reads alike
GROUP_MAX = 8         # a group larger than this is split by tightening
BATCH = 120_000       # bytes of batch text one reader takes


def words(e) -> list[str]:
    f = e["fields"]
    t = " ".join([e["title"], f.get("What was going on", ""),
                  f.get("What the product must do", "")]).lower()
    return [w for w in re.findall(r"[a-z][a-z0-9'-]{2,}|\d+(?:\.\d+)?", t) if w not in STOP]


def render(e) -> str:
    f = e["fields"]
    lines = [f"### {e['id']} [{e['capability']} / {e['topic']}]: {e['title']}",
             f"- What was going on: {f.get('What was going on', '')}",
             f"- What the product must do: {f.get('What the product must do', '')}",
             f"- Kind: {f.get('Kind', '')}"]
    for k in ("Tool", "State", "Move to", "Check"):
        if f.get(k):
            lines.append(f"- {k}: {f[k]}")
    return "\n".join(lines) + "\n"


def main():
    entries, _ = ml.merged()
    parts = ml.parts()
    n = len(entries)
    bags = [set(words(e)) for e in entries]
    df = collections.Counter()
    for b in bags:
        df.update(b)
    vecs = []
    for b in bags:
        v = {w: math.log(n / df[w]) for w in b if df[w] > 1}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({w: x / norm for w, x in v.items()})
    index = collections.defaultdict(list)
    for i, v in enumerate(vecs):
        for w in v:
            index[w].append(i)
    tvecs = []
    for e in entries:
        tw = {w for w in re.findall(r"[a-z][a-z0-9'-]{2,}|\d+(?:\.\d+)?", e["title"].lower())
              if w not in STOP and df[w] > 1}
        v = {w: math.log(n / df[w]) for w in tw}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        tvecs.append({w: x / norm for w, x in v.items()})
    srcs = []
    for e in entries:
        s = set()
        for pid in e["from"]:
            s.update(parts.get(pid, {}).get("sources", []))
        srcs.append(s)
    by_src = collections.defaultdict(list)
    for i, s in enumerate(srcs):
        for x in s:
            by_src[x].append(i)

    pairs = {}
    for i in range(n):
        score = collections.Counter()
        for w, x in vecs[i].items():
            for j in index[w]:
                if j > i:
                    score[j] += x * vecs[j][w]
        shared = set()
        for x in srcs[i]:
            shared.update(j for j in by_src[x] if j > i)
        for j, s in score.items():
            a, b = entries[i], entries[j]
            if a["bundle"] == b["bundle"] or a["sealed"] != b["sealed"]:
                continue
            if s >= ALIKE or (j in shared and s >= ALIKE_SHARED):
                pairs[(i, j)] = s
            elif s >= 0.12 and len(tvecs[i]) > 2:
                t = sum(x * tvecs[j].get(w, 0.0) for w, x in tvecs[i].items())
                if t >= ALIKE_TITLE:
                    pairs[(i, j)] = max(s, ALIKE)

    def components(edges, floor):
        parent = {}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for (i, j), s in edges.items():
            if s >= floor:
                parent[find(i)] = find(j)
        comp = collections.defaultdict(list)
        for x in list(parent):
            comp[find(x)].append(x)
        return [sorted(c) for c in comp.values() if len(c) > 1]

    # Split an over-large group by raising the floor inside it, so a chain of
    # "a like b like c ..." does not become one group of forty.
    groups, todo = [], [(components(pairs, 0.0), 0.0)]
    while todo:
        comps, floor = todo.pop()
        for c in comps:
            if len(c) <= GROUP_MAX or floor >= 0.9:
                groups.append(c)
                continue
            inside = {k: v for k, v in pairs.items() if k[0] in c and k[1] in c}
            todo.append((components(inside, floor + 0.08), floor + 0.08))
    groups.sort(key=lambda c: (entries[c[0]]["capability"], c[0]))

    os.makedirs(ml.CROSS, exist_ok=True)
    for f in os.listdir(ml.CROSS):
        if re.match(r"batch-\d+\.(md|ids)$", f) or f in ("moves.md", "moves.ids"):
            os.remove(os.path.join(ml.CROSS, f))
    batches, cur, size = [], [], 0
    for g, c in enumerate(groups, 1):
        text = f"## Group {g}\n\n" + "\n".join(render(entries[i]) for i in c) + "\n"
        b = len(text.encode("utf-8"))
        if cur and size + b > BATCH:
            batches.append(cur)
            cur, size = [], 0
        cur.append((g, text))
        size += b
    if cur:
        batches.append(cur)
    for k, batch in enumerate(batches, 1):
        with open(os.path.join(ml.CROSS, f"batch-{k:02d}.md"), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(f"# Entries that may be one lesson filed twice: batch {k} of "
                    f"{len(batches)} ({len(batch)} groups)\n\n")
            for _, text in batch:
                f.write(text)
        with open(os.path.join(ml.CROSS, f"batch-{k:02d}.ids"), "w", encoding="utf-8",
                  newline="\n") as f:
            for g, text in batch:
                ids = re.findall(r"^### (\S+?) \[", text, re.M)
                f.write(f"{g}\t{' '.join(ids)}\n")

    # Entries a merger marked `Move to:`. Each becomes a group of its own: the
    # entry, the five entries of the target capability that read most like it
    # (it may already be there), and the target's sub-topics to choose from.
    moves = [i for i, e in enumerate(entries) if e["fields"].get("Move to")]
    topics = collections.defaultdict(list)
    for e in entries:
        if not e["sealed"] and e["topic"] not in topics[e["capability"]]:
            topics[e["capability"]].append(e["topic"])
    nl = "\n"
    with open(os.path.join(ml.CROSS, "moves.md"), "w", encoding="utf-8", newline=nl) as f, \
            open(os.path.join(ml.CROSS, "moves.ids"), "w", encoding="utf-8", newline=nl) as g:
        f.write(f"# Entries a merger marked for another capability ({len(moves)} groups)" + nl * 2)
        for k, i in enumerate(moves, 1):
            e = entries[i]
            target = e["fields"]["Move to"].strip().strip("`.")
            score = collections.Counter()
            for w, x in vecs[i].items():
                for j in index[w]:
                    if entries[j]["capability"] == target and entries[j]["sealed"] == e["sealed"]:
                        score[j] += x * vecs[j][w]
            near = [j for j, _ in score.most_common(5)]
            f.write(f"## Group M{k}" + nl * 2 + f"Marked to move to `{target}`:" + nl * 2
                    + render(e) + nl)
            f.write(f"The entries of `{target}` that read most like it:" + nl * 2)
            f.write(nl.join(render(entries[j]) for j in near) + nl)
            f.write(f"Sub-topics of `{target}`: " + "; ".join(topics.get(target, [])) + nl * 2)
            g.write(f"M{k}\t{e['id']} " + " ".join(entries[j]["id"] for j in near) + nl)

    in_groups = sum(len(c) for c in groups)
    sizes = collections.Counter(len(c) for c in groups)
    print(f"{n} entries; {len(pairs)} candidate pairs; {len(groups)} groups holding "
          f"{in_groups} entries; {len(batches)} batch(es); {len(moves)} marked to move")
    print("group sizes:", dict(sorted(sizes.items())))


if __name__ == "__main__":
    main()
