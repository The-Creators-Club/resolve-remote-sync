#!/usr/bin/env python3
"""Step 2, part 3: gather every reader's entries into one bundle per
capability, ready for the mergers.

    python docs/rebuild-spec/tools/build_merge_bundles.py

Reads knowledge-base/_parts/*.md and writes, under the gitignored
_raw/merge/:

    <capability>[-N].md   the entries of one capability, like lessons placed
                          side by side, in pieces a merger can read whole
    <capability>[-N].ids  the entry ids in that piece (for the merge count)
    stats.json

Inside a capability, entries are ordered so that lessons about the same
thing sit together: each entry is placed next to the one it shares the most
uncommon words with. That is only an ordering, to help the merger see
repeats; it decides nothing.
"""
from __future__ import annotations

import collections
import glob
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.abspath(os.path.join(HERE, ".."))
PARTS = os.path.join(SPEC, "knowledge-base", "_parts")
OUT = os.path.join(SPEC, "_raw", "merge")
PIECE = 165_000          # bytes of bundle text one merger reads

STOP = set("""a an the and or of to in on for with from by at as is are was were be been it its
this that these those not no never must may can could should would will when while if then than
so but into out over under after before any every each all one two only also still which who
what how why where there their them they he his she her we our you your i did do does done had
has have about without within until once per more most less same other another new old own
product person people editor editors computer computers file files""".split())


def parse(path: str):
    name = os.path.basename(path)[:-3]
    text = open(path, encoding="utf-8", errors="replace").read().replace("\r\n", "\n")
    section = ""
    cur = None
    out = []
    for line in text.split("\n"):
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if section != "entries":
            continue
        m = re.match(r"^###\s+(\S+?):\s*(.*)$", line)
        if m:
            cur = {"id": m.group(1), "title": m.group(2).strip(), "part": name}
            out.append(cur)
            continue
        m = re.match(r"^-\s+([A-Za-z ]+?):\s*(.*)$", line)
        if m and cur is not None:
            cur[m.group(1).strip()] = m.group(2).strip()
    return out


def words(e) -> list[str]:
    t = " ".join([e.get("title", ""), e.get("What was going on", ""),
                  e.get("What the product must do", "")]).lower()
    return [w for w in re.findall(r"[a-z][a-z0-9'-]{2,}|\d+(?:\.\d+)?", t) if w not in STOP]


def order(entries):
    """Greedy chain: start from the entry with the rarest vocabulary, then
    keep stepping to the unplaced entry most alike. O(n^2), fine for a few
    thousand."""
    if len(entries) < 3:
        return entries
    df = collections.Counter()
    bags = []
    for e in entries:
        b = set(words(e))
        bags.append(b)
        df.update(b)
    n = len(entries)
    idf = {w: math.log(n / c) for w, c in df.items()}
    vecs = []
    for b in bags:
        v = {w: idf[w] for w in b if df[w] > 1}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({w: x / norm for w, x in v.items()})
    index = collections.defaultdict(list)
    for i, v in enumerate(vecs):
        for w in v:
            index[w].append(i)
    left = set(range(n))
    cur = 0
    chain = [cur]
    left.discard(cur)
    while left:
        score = collections.Counter()
        for w, x in vecs[cur].items():
            for j in index[w]:
                if j in left:
                    score[j] += x * vecs[j][w]
        if score:
            nxt = max(score.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        else:
            nxt = min(left)
        chain.append(nxt)
        left.discard(nxt)
        cur = nxt
    return [entries[i] for i in chain]


def render(e) -> str:
    lines = [f"### {e['id']}: {e.get('title', '')}",
             f"- What was going on: {e.get('What was going on', '')}",
             f"- What the product must do: {e.get('What the product must do', '')}",
             f"- Kind: {e.get('Kind', '')}"]
    if e.get("Tool"):
        lines.append(f"- Tool: {e['Tool']}")
    lines.append(f"- Found by: {e.get('Found by', '')} | Date: {e.get('Date', '')} | "
                 f"State: {e.get('State', '')}")
    return "\n".join(lines) + "\n\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in glob.glob(os.path.join(OUT, "*")):
        os.remove(f)
    entries = []
    for p in sorted(glob.glob(os.path.join(PARTS, "*.md"))):
        if os.path.basename(p) in ("KB_BRIEF.md", "KB_MERGE_BRIEF.md"):
            continue
        entries.extend(parse(p))
    by_cap = collections.defaultdict(list)
    for e in entries:
        by_cap[e.get("Capability", "unfiled")].append(e)
    stats = {"entries": len(entries), "capabilities": {}}
    kinds = collections.Counter(e.get("Kind", "?") for e in entries)
    states = collections.Counter(e.get("State", "?") for e in entries)
    stats["kinds"] = dict(kinds)
    stats["states"] = dict(states)
    for cap, es in sorted(by_cap.items()):
        es = order(es)
        pieces, cur, size = [], [], 0
        for e in es:
            b = len(render(e).encode("utf-8"))
            if cur and size + b > PIECE:
                pieces.append(cur)
                cur, size = [], 0
            cur.append(e)
            size += b
        if cur:
            pieces.append(cur)
        names = []
        for k, piece in enumerate(pieces, 1):
            name = cap if len(pieces) == 1 else f"{cap}-{k}"
            names.append(name)
            with open(os.path.join(OUT, name + ".md"), "w", encoding="utf-8", newline="\n") as f:
                f.write(f"# Entries to merge: {cap}"
                        + (f", piece {k} of {len(pieces)}" if len(pieces) > 1 else "")
                        + f" ({len(piece)} entries)\n\n")
                for e in piece:
                    f.write(render(e))
            with open(os.path.join(OUT, name + ".ids"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(e["id"] for e in piece) + "\n")
        stats["capabilities"][cap] = {
            "entries": len(es), "pieces": names,
            "by kind": dict(collections.Counter(e.get("Kind", "?") for e in es))}
    with open(os.path.join(OUT, "stats.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(stats, f, indent=1)
    print(f"{len(entries)} entries; kinds {dict(kinds)}")
    print("states", dict(states))
    for cap, s in stats["capabilities"].items():
        print(f"{s['entries']:5d}  {len(s['pieces'])} piece(s)  {cap}  {s['by kind']}")


if __name__ == "__main__":
    main()
