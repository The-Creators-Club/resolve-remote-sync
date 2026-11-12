#!/usr/bin/env python3
"""Step 2, the last part: turn the merged bundles into the finished
knowledge base.

    python docs/rebuild-spec/tools/assemble_kb.py           write everything
    python docs/rebuild-spec/tools/assemble_kb.py --check   write nothing, report

Reads knowledge-base/_merged/*.md (the mergers' output), the rulings of the
pass across capabilities (knowledge-base/_cross/*.rulings) and, for the
Timeline Cards editor, which was merged in three pieces, the map of their
sub-topics onto one list (knowledge-base/_cross/topics.tsv). Writes:

    knowledge-base/<capability>.md      THE TEXT THAT CROSSES to the rebuild:
                                        each lesson once, no sources, no
                                        states, nothing of the old build
    sealed/<tool>.md                    the sealed notes, one file per tool
                                        (or per set of tools an entry names),
                                        released only when the rebuild's own
                                        design names that tool
    knowledge-base/_trace/trace.tsv     STAYS BEHIND: finished id -> merged
                                        ids -> readers' entries -> register ids
    knowledge-base/_trace/removed.tsv   STAYS BEHIND: what the mergers removed
                                        and why
    knowledge-base/_owner/QUESTIONS.md  STAYS BEHIND: lessons still open, with
                                        no outcome found, or never shipped;
                                        the mergers' `Check:` questions; and
                                        the conflicts the cross pass found

An id is never renumbered: a lesson keeps the id its merger gave it, even
when it is moved to another capability, so a question already put to the
owner still points at the same lesson.
"""
from __future__ import annotations

import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merged_lib as ml  # noqa: E402
import check_cross  # noqa: E402
import check_merge  # noqa: E402
from lint_parts import RX  # noqa: E402

SEALED_DIR = os.path.join(ml.SPEC, "sealed")
TRACE = os.path.join(ml.KB, "_trace")
OWNER = os.path.join(ml.KB, "_owner")
KIND_WORD = {"1a": "given", "2": "ruling", "3": "situation"}
KIND_RANK = {"1a": 0, "2": 1, "3": 2, "1b": 3}

# A sealed entry is filed by every tool its `Tool:` line names, so that
# releasing one tool's notes never tells the rebuild about another. First
# column: a word to look for (lower case); second: the file it belongs to.
FAMILIES = [
    ("yt-dlp", "yt-dlp"), ("bgutil", "yt-dlp"),
    ("rclone", "rclone"),
    ("syncthing", "syncthing"),
    ("whisper", "whisper"), ("ctranslate", "whisper"),
    ("pyannote", "pyannote"),
    ("ffmpeg", "ffmpeg"), ("ffprobe", "ffmpeg"), ("nvenc", "ffmpeg"),
    ("project librar", "resolve-project-library-direct"),
    ("project database", "resolve-project-library-direct"),
    ("keystroke", "resolve-keystrokes"), ("autohotkey", "resolve-keystrokes"),
    ("preference file", "resolve-preference-files"),
    ("claude code", "claude-code-cli"),
    ("github", "github"),
    ("tkinter", "tkinter"), ("tcl", "tkinter"),
    ("pyinstaller", "pyinstaller"),
    ("htmx", "htmx"),
    ("qwen", "local-vision-model"),
    ("jieba", "chinese-word-segmenters"), ("stanza", "chinese-word-segmenters"),
    ("tailscale", "tailscale"),
    ("docker", "docker"),
    ("sqlite", "sqlite"),
    ("truenas", "truenas"),
    ("zfs", "zfs"),
    ("cloudflare", "cloudflare"),
    ("anthropic", "anthropic-api-and-models"), ("claude haiku", "anthropic-api-and-models"),
    ("claude as", "anthropic-api-and-models"), ("claude fable", "anthropic-api-and-models"),
    ("hugging face", "hugging-face"),
    ("opencc", "opencc"),
    ("clap", "clap-audio-embeddings"),
    ("tk on", "tkinter"),
    ("python", "python-standard-library"),
    ("trusted web activity", "android-web-app-wrapper"), ("bubblewrap", "android-web-app-wrapper"),
    ("hetzner", "offsite-storage-providers"), ("backblaze", "offsite-storage-providers"),
    ("powershell", "windows-powershell"),
    ("browser", "browser-features"),
]


def family(tool: str) -> str:
    low = tool.lower()
    hit = []
    for word, fam in FAMILIES:
        if re.search(r"(?<![a-z])" + re.escape(word), low) and fam not in hit:
            hit.append(fam)
    if hit:
        return "+".join(sorted(hit))
    slug = re.sub(r"[^a-z0-9]+", "-", re.split(r"[(,;:]", low)[0]).strip("-")
    return slug[:60] or "unnamed"


def read_topics():
    """-> {(bundle, old heading): new heading}, [new headings in order]"""
    path = os.path.join(ml.CROSS, "topics.tsv")
    mapping, order = {}, []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            bundle, old, new = line.split("\t")
            mapping[(bundle, old)] = new
            if new not in order:
                order.append(new)
    return mapping, order


def main():
    write = "--check" not in sys.argv
    problems, notes = [], []

    # 1. The merge count must close before anything is assembled.
    for name in sorted(os.path.basename(p)[:-4] for p in
                       __import__("glob").glob(os.path.join(check_merge.BUNDLES, "*.ids"))):
        probs = check_merge.check(name)[0]
        if probs:
            problems.append(f"merge count: {name}: {probs[0]}")

    entries, removed = ml.merged()
    by_id = {e["id"]: e for e in entries}
    if len(by_id) != len(entries):
        dup = [i for i, c in collections.Counter(e["id"] for e in entries).items() if c > 1]
        problems.append(f"finished ids used twice across bundles: {dup[:10]}")
    parts = ml.parts()
    topic_map, topic_order = read_topics()

    # 2. The rulings.
    drop_to, moved, conflicts = {}, {}, []
    for name in check_cross.batch_names():
        rs, probs = check_cross.rulings(name, by_id)
        problems.extend(f"cross pass: {p}" for p in probs)
        for r in rs:
            if r["verb"] == "same":
                for d in r["drop"]:
                    drop_to[d] = r["keep"]
            elif r["verb"] == "move":
                moved[r["id"]] = (r["target"], r["topic"])
            elif r["verb"] == "conflict":
                conflicts.append(r)

    def keeper(i):
        seen = set()
        while i in drop_to:
            if i in seen:
                problems.append(f"cross pass: {i} is dropped in a circle")
                break
            seen.add(i)
            i = drop_to[i]
        return i

    def place(e):
        """-> (capability, sub-topic) the entry ends up under."""
        if e["id"] in moved:
            cap, topic = moved[e["id"]]
            for (bundle, old), new in topic_map.items():
                if ml.capability_of(bundle) == cap and old == topic:
                    return cap, new
            return cap, topic
        return e["capability"], topic_map.get((e["bundle"], e["topic"]), e["topic"])

    for e in entries:
        if e["fields"].get("Move to") and e["id"] not in moved and e["id"] not in drop_to:
            stay = any(r for n in check_cross.batch_names() if os.path.exists(
                os.path.join(ml.CROSS, n + ".rulings"))
                for r in check_cross.rulings(n, by_id)[0]
                if r["verb"] == "stay" and r["id"] == e["id"])
            if not stay:
                notes.append(f"{e['id']} is marked `Move to: {e['fields']['Move to']}` "
                             "and has no ruling; left where it is")

    # 3. What each finished entry is made of.
    absorbed = collections.defaultdict(list)          # keeper -> merged ids dropped into it
    for d in drop_to:
        absorbed[keeper(d)].append(d)
    final = [e for e in entries if e["id"] not in drop_to]
    caps = collections.defaultdict(lambda: collections.defaultdict(list))
    sealed = collections.defaultdict(list)
    for e in final:
        k = e["fields"].get("Kind", "")
        if e["sealed"]:
            sealed[family(e["fields"].get("Tool", ""))].append(e)
        else:
            cap, topic = place(e)
            caps[cap][topic].append(e)
    see_also = collections.defaultdict(lambda: collections.defaultdict(list))
    for d, _ in drop_to.items():
        de, ke = by_id[d], by_id[keeper(d)]
        if de["sealed"]:
            continue
        dcap, dtopic = place(de)
        kcap, _ = place(ke)
        if dcap != kcap and ke["id"] not in see_also[dcap][dtopic]:
            see_also[dcap][dtopic].append(ke["id"])

    # 4. The purge net, once more, over what crosses.
    for e in final:
        f = e["fields"]
        for label, t in (("title", e["title"]), ("why", f.get("What was going on", "")),
                         ("must", f.get("What the product must do", ""))):
            hits = sorted({h.group(0).lower() for h in RX.finditer(t)})
            if hits:
                problems.append(f"purge: {e['id']} [{label}] names {', '.join(hits)}")

    def topics_of(cap):
        seen = [t for t in topic_order if t in caps[cap] or t in see_also[cap]]
        for e in sorted((x for ts in caps[cap].values() for x in ts), key=lambda x: x["order"]):
            t = place(e)[1]
            if t not in seen:
                seen.append(t)
        for t in see_also[cap]:
            if t not in seen:
                seen.append(t)
        return seen

    files = {}
    for cap in sorted(caps):
        name = ml.NAMES.get(cap, cap)
        n = sum(len(v) for v in caps[cap].values())
        out = [f"# {name}: what real use taught", "",
               f"{n} lessons. Each is one rule the product can be tested against: what a "
               "person saw (the heading), why it happened, and what the product must do. "
               "Kinds: *given* is a fact about something the studio has whatever is built; "
               "*ruling* is the owner's decision; *situation* is something the product "
               "must survive.", ""]
        for topic in topics_of(cap):
            out += [f"## {topic}", ""]
            es = sorted(caps[cap].get(topic, []),
                        key=lambda e: (KIND_RANK.get(e["fields"].get("Kind", ""), 9),
                                       e["bundle"], e["order"]))
            for e in es:
                f = e["fields"]
                out += [f"### {e['id']}: {e['title']}",
                        f"- Why: {f.get('What was going on', '')}",
                        f"- Must: {f.get('What the product must do', '')}",
                        f"- Kind: {KIND_WORD.get(f.get('Kind', ''), '?')}", ""]
            refs = see_also[cap].get(topic, [])
            if refs:
                out.append("See also, filed under another capability:")
                out.append("")
                for i in refs:
                    kcap = place(by_id[i])[0]
                    out.append(f"- {i} ({ml.NAMES.get(kcap, kcap)}): {by_id[i]['title']}")
                out.append("")
        files[os.path.join(ml.KB, cap + ".md")] = "\n".join(out).rstrip() + "\n"

    for fam in sorted(sealed):
        es = sorted(sealed[fam], key=lambda e: (e["capability"], e["order"]))
        out = [f"# Sealed notes: {fam}", "",
               "SEALED. Not part of the pack. Released to the rebuild only after its own "
               "committed design names "
               + ("every one of these tools" if "+" in fam else "this tool")
               + f". {len(es)} notes.", ""]
        for e in es:
            f = e["fields"]
            out += [f"### {e['id']}: {e['title']}",
                    f"- Why: {f.get('What was going on', '')}",
                    f"- Must: {f.get('What the product must do', '')}",
                    f"- Tool: {f.get('Tool', '')}",
                    f"- Where it bit: {ml.NAMES.get(e['capability'], e['capability'])}", ""]
        files[os.path.join(SEALED_DIR, fam + ".md")] = "\n".join(out).rstrip() + "\n"

    # 5. The trace and the owner's list (both stay behind).
    def sources(part_ids):
        s = []
        for p in part_ids:
            for x in parts.get(p, {}).get("sources", []):
                if x not in s:
                    s.append(x)
        return s

    rows = ["finished id\tcapability\tsub-topic or tool\tkind\tmerged ids\treaders' entries\t"
            "register ids"]
    placed_parts = collections.Counter()
    for e in final:
        ids = [e["id"]] + absorbed.get(e["id"], [])
        pids = []
        for i in ids:
            for p in by_id[i]["from"]:
                if p not in pids:
                    pids.append(p)
        placed_parts.update(set(pids))
        where = (("sealed", family(e["fields"].get("Tool", ""))) if e["sealed"] else place(e))
        rows.append("\t".join([e["id"], where[0], where[1], e["fields"].get("Kind", ""),
                               " ".join(ids), " ".join(pids), " ".join(sources(pids))]))
    files[os.path.join(TRACE, "trace.tsv")] = "\n".join(rows) + "\n"
    rrows = ["reader's entry\tbundle\treason\tregister ids"]
    for r in removed:
        for i in r["ids"]:
            rrows.append("\t".join([i, r["bundle"], r["reason"], " ".join(sources([i]))]))
    files[os.path.join(TRACE, "removed.tsv")] = "\n".join(rrows) + "\n"

    asks = collections.defaultdict(list)
    n_state = collections.Counter()
    n_check = 0
    for e in final:
        ids = [e["id"]] + absorbed.get(e["id"], [])
        states = [by_id[i]["fields"]["State"] for i in ids if by_id[i]["fields"].get("State")]
        checks = [by_id[i]["fields"]["Check"] for i in ids if by_id[i]["fields"].get("Check")]
        if not states and not checks:
            continue
        # The least settled state wins when a repeat was folded in.
        rank = ["still open", "outcome not found", "fixed, never shipped"]
        state = min(states, key=rank.index) if states else ""
        cap = "sealed notes" if e["sealed"] else ml.NAMES.get(place(e)[0], place(e)[0])
        line = f"- **{e['id']}** {e['title']} Must: {e['fields'].get('What the product must do', '')}"
        for c in checks:
            line += f"\n  - **Question:** {c}"
            n_check += 1
        if state:
            n_state[state] += 1
        asks[(cap, state or "question only")].append(line)
    out = ["# The knowledge base: what the owner is asked", "",
           "Stays behind (not part of the pack). Written by `tools/assemble_kb.py`; do not "
           "edit by hand.", "",
           f"- {n_state['still open']} lessons the old product never solved (**still open**). "
           "Each is a rule the rebuild must meet; say if any is no longer wanted.",
           f"- {n_state['outcome not found']} reports whose outcome could not be found "
           "(**outcome not found**). Say whether it was fixed, still happens, or no longer "
           "matters.",
           f"- {n_state['fixed, never shipped']} fixes written but never released to the "
           "editors (**fixed, never shipped**), so nobody has used them.",
           f"- {n_check} questions where two sources disagreed and the dates did not settle it.",
           f"- {len(conflicts)} pairs of lessons that cannot both hold.", ""]
    if conflicts:
        out += ["## Lessons that cannot both hold", ""]
        for r in conflicts:
            a, b = (by_id[i] for i in r["ids"])
            out += [f"- **{r['question']}**",
                    f"  - {a['id']}: {a['fields'].get('What the product must do', '')}",
                    f"  - {b['id']}: {b['fields'].get('What the product must do', '')}"]
        out.append("")
    for cap in sorted({k[0] for k in asks}):
        out += [f"## {cap}", ""]
        for state in ("question only", "still open", "outcome not found", "fixed, never shipped"):
            if asks.get((cap, state)):
                out += [f"### {state.capitalize()}", ""] + asks[(cap, state)] + [""]
    files[os.path.join(OWNER, "QUESTIONS.md")] = "\n".join(out).rstrip() + "\n"

    # 6. The count: every reader's entry of every bundle is in a finished
    # entry or a removed line.
    want = set()
    for p in __import__("glob").glob(os.path.join(check_merge.BUNDLES, "*.ids")):
        want.update(l.strip() for l in open(p, encoding="utf-8") if l.strip())
    gone = {i for r in removed for i in r["ids"]}
    lost = sorted(want - set(placed_parts) - gone)
    if lost:
        problems.append(f"count: {len(lost)} readers' entries are in no finished entry and "
                        f"no removed line: {', '.join(lost[:30])}")

    if write and not problems:
        for d in (SEALED_DIR, TRACE, OWNER):
            os.makedirs(d, exist_ok=True)
        keep = set(files)
        for d, pat in ((ml.KB, r"^[a-z][a-z-]+\.md$"), (SEALED_DIR, r"\.md$")):
            for f in os.listdir(d):
                p = os.path.join(d, f)
                if re.search(pat, f) and p not in keep and os.path.isfile(p):
                    os.remove(p)
        for p, text in files.items():
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)

    n_final = sum(1 for e in final if not e["sealed"])
    n_sealed = sum(1 for e in final if e["sealed"])
    print(f"{len(want)} readers' entries -> {len(entries)} merged -> {n_final} lessons that "
          f"cross in {len(caps)} capabilities, {n_sealed} sealed notes in {len(sealed)} "
          f"tool files; {len(gone)} removed by the mergers, {len(drop_to)} repeats across "
          f"capabilities folded, {len(moved)} moved")
    print("to ask the owner:", dict(n_state), f"{n_check} questions, {len(conflicts)} conflicts")
    print("sealed files:", ", ".join(f"{k} ({len(v)})" for k, v in sorted(sealed.items())))
    for n in notes[:40]:
        print("note: " + n)
    for p in problems[:60]:
        print("PROBLEM: " + p)
    print(("written. " if write and not problems else "nothing written. ")
          + ("OK" if not problems else f"NOT OK: {len(problems)} problem(s)"))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
