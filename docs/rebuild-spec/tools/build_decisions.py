#!/usr/bin/env python3
"""Step 4: the writers' questions for the owner, gathered into pages.

    python docs/rebuild-spec/tools/build_decisions.py            write the pages
    python docs/rebuild-spec/tools/build_decisions.py --check    only say what would be written

Reads "Questions for the owner" from every spec/_trace/<piece>.md and writes
one page per piece under docs/rebuild-spec/decisions/, numbered from page 3
(pages 1 and 2 are in DECISIONS.md). A page puts the real choices first, in
full, then the tidy-ups (several ways in, the same job built twice, dormant,
unreachable and builders' tools) as a short table, each with the
recommendation. The owner answers a page by naming the numbers he disagrees
with; anything not named is the recommendation.

A page that already holds answers (a line starting "ANSWERED") is never
written over: answers are typed into the page by hand, under its last
heading, and the specification is then changed to match.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_spec as cs  # noqa: E402
import merged_lib as ml  # noqa: E402

OUT = os.path.join(ml.SPEC, "decisions")
FIRST_PAGE = 3
# The order the pages are put to him in: what shapes everything else first.
ORDER = ["whole-product", "sync-1", "sync-2", "dashboard-1", "dashboard-2", "editor-app",
         "accounts-privacy-legal", "releases-and-updates", "server-install-and-running-1",
         "server-install-and-running-2", "fleet-jobs", "proxies-and-file-moves",
         "resolve-on-the-editors-computer", "broll", "music", "youtube",
         "footage-sorter-and-camera-cards-1", "footage-sorter-and-camera-cards-2",
         "footage-sorter-and-camera-cards-3", "cards-footage-in", "cards-board",
         "cards-editor-1", "cards-editor-2", "cards-editor-3", "cards-editor-4",
         "cards-editor-5", "cards-to-resolve-and-exports"]
TIDY = ("several ways in", "built twice", "dormant", "unreachable", "dev only")


def title_of(piece: str) -> str:
    cap = ml.capability_of(piece)
    name = ml.NAMES.get(cap, cap)
    m = re.search(r"-(\d+)$", piece)
    return name + (f", part {m.group(1)}" if m else "")


def cell(s: str) -> str:
    return s.replace("|", "/").replace("\n", " ").strip()


def page(n: int, piece: str, questions: dict) -> str:
    real = [(qid, q) for qid, q in questions.items()
            if not q.get("Kind", "").lower().startswith(TIDY)]
    tidy = [(qid, q) for qid, q in questions.items()
            if q.get("Kind", "").lower().startswith(TIDY)]
    out = [f"# Decision list, page {n}: {title_of(piece)}", "",
           "Stays behind: never shown to the session that rebuilds the product.", "",
           f"{len(questions)} questions. Each has what exists today, the options, my "
           "recommendation and what you would notice. The specification is already written "
           "to the recommendation (or, where I recommend cutting something, still holds it, "
           "ready to delete). **Reply with the numbers you disagree with; anything you do "
           "not mention is taken as the recommendation.**", ""]
    k = 0
    if real:
        out += ["## Choices", ""]
        for qid, q in real:
            k += 1
            out += [f"### {n}.{k} {q['title']}", "",
                    f"- **Today:** {q.get('Today', '')}",
                    f"- **Options:** {q.get('Options', '')}",
                    f"- **Recommended:** {q.get('Recommend', '')}",
                    f"- **What you would notice:** {q.get('Changes for a person', '')}",
                    f"- ({qid})", ""]
    if tidy:
        out += ["## Tidy-ups", "",
                "One thing that can be done from several places, the same job existing twice, "
                "things switched off for everyone, things nobody can reach, and tools only the "
                "builders use.", "",
                "| # | Question | Today | Recommended |", "|---|---|---|---|"]
        for qid, q in tidy:
            k += 1
            out.append(f"| {n}.{k} | {cell(q['title'])} | {cell(q.get('Today', ''))} | "
                       f"{cell(q.get('Recommend', ''))} ({qid}) |")
        out.append("")
    out += ["## Your answers", "", "Not yet answered.", ""]
    return "\n".join(out)


def main():
    check = "--check" in sys.argv
    pieces = [p for p in ORDER if os.path.exists(os.path.join(cs.TRACE, p + ".md"))]
    missing = [p for p in cs.pieces() if p not in ORDER]
    if missing:
        sys.exit(f"not in ORDER: {missing}")
    os.makedirs(OUT, exist_ok=True)
    index, total, n = [], 0, FIRST_PAGE
    for piece in ORDER:
        if piece not in pieces:
            print(f"   (page {n}: {piece} is not written yet)")
            n += 1
            continue
        _pr, _cover, questions, _rd, _uns = cs.read_trace(piece)
        path = os.path.join(OUT, f"page-{n:02d}-{piece}.md")
        total += len(questions)
        state = "written"
        if os.path.exists(path) and re.search(r"^ANSWERED", open(path, encoding="utf-8").read(), re.M):
            state = "kept (it holds answers)"
        elif not check:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(page(n, piece, questions))
        tidy = sum(1 for q in questions.values() if q.get("Kind", "").lower().startswith(TIDY))
        index.append(f"| {n} | [{title_of(piece)}](decisions/page-{n:02d}-{piece}.md) | "
                     f"{len(questions) - tidy} | {tidy} | not yet answered |")
        print(f"page {n}: {piece}, {len(questions)} questions ({tidy} tidy-ups), {state}")
        n += 1
    print(f"{total} questions on {len(index)} pages")
    print("\nFor DECISIONS.md:\n")
    print("| Page | About | Choices | Tidy-ups | State |\n|---|---|---|---|---|")
    print("\n".join(index))


if __name__ == "__main__":
    main()
