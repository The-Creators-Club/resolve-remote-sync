#!/usr/bin/env python3
"""Build the knowledge-base register (REBUILD_PLAN.md, step 2, part 1).

Turns every place real-world feedback was written down into numbered items
with a stable id, and packs the items into slices a reader can take one at a
time. Costs no model usage: it only reads files and git.

    python docs/rebuild-spec/tools/build_register.py

Everything it writes goes under docs/rebuild-spec/_raw/, which is gitignored:
the owner's messages can hold passwords and people's names, so the raw
register is NEVER committed.

Ids:
    P-00001   one of the owner's messages to Claude Code (history.jsonl)
    L-0001    one entry of the bug ledger (KNOWN_BUGS.md)
    G-cc-01   one section of a gotchas file (cc = ccsync, tc = Timeline Cards)
    H-...     one section of a hunt, sweep, audit or review
    D-...     one section of a plan or investigation in the other two repos
    M-...     one memory note
    C-cc-<hash>  one commit (cc, ed = Editing, fs = footage-sorter)
"""
from __future__ import annotations

import collections
import datetime as dt
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CC = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
ED = os.path.abspath(os.path.join(CC, ".."))
TC = os.path.join(ED, "Resolve", "MulticamPipeline")
FS = os.path.join(ED, "footage-sorter")
CLAUDE = os.path.join(os.path.expanduser("~"), ".claude")
OUT = os.path.join(CC, "docs", "rebuild-spec", "_raw")

SEP = re.escape(os.sep)
PRODUCT_FOLDER = re.compile(
    "ccsync|resolve-remote-sync|resolve-relink|MulticamPipeline|footage-sorter|"
    "broll-platform|music-tagger|MontagePipeline|Projects" + SEP + "Editing$|^E:"
    + SEP + "Projects$",
    re.I,
)
PRODUCT_WORD = re.compile(
    "ccsync|cc sync|companion|dashboard|ruskin|leso|syncthing|proxy|proxies|"
    "timeline cards|sorter|b-?roll|resolve|tray|truenas|ytdl|youtube|multicam|"
    "transcript|whisper|cut list|canvas|footage|camera card|nas\\b",
    re.I,
)
DATE = re.compile(r"(20\d\d-\d\d-\d\d)")

BUDGET = {"P": 120_000, "L": 250_000, "G": 250_000, "H": 250_000,
          "D": 250_000, "M": 220_000, "C": 220_000}
# The owner's messages are short, so a byte budget alone would hand one
# reader 400 of them. Each has to be followed to its outcome: cap the count.
ITEM_CAP = {"P": 250}

Item = collections.namedtuple("Item", "id src date title where text order")
items: list[Item] = []
auto_no: list[tuple[str, str, str]] = []   # (id-or-name, reason, title)


def read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n")


def first_date(*texts: str) -> str:
    for t in texts:
        m = DATE.search(t or "")
        if m:
            return m.group(1)
    return ""


def slug(s: str, n: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:n].strip("-") or "x"


# --------------------------------------------------------------- markdown

def split_md(text: str, max_level: int):
    """Yield (level, heading, first_line_no, body) for each heading of level
    <= max_level, ignoring headings inside code fences. Text before the first
    heading comes out as level 0."""
    lines = text.split("\n")
    out = []
    cur = [0, "", 1, []]
    fence = False
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,6})\s+(.*)$", line)
        if m and len(m.group(1)) <= max_level:
            out.append(tuple(cur[:3]) + ("\n".join(cur[3]),))
            cur = [len(m.group(1)), m.group(2).strip(), i, [line]]
        else:
            cur[3].append(line)
    out.append(tuple(cur[:3]) + ("\n".join(cur[3]),))
    return [c for c in out if c[3].strip()]


def merge_small(chunks, floor: int):
    """Fold a chunk shorter than `floor` characters into the one after it, so
    a bare heading does not become an item of its own."""
    out = []
    carry = None
    for c in chunks:
        if carry is not None:
            c = (carry[0], carry[1] + " / " + c[1] if c[1] else carry[1],
                 carry[2], carry[3] + "\n" + c[3])
            carry = None
        if len(c[3]) < floor:
            carry = c
        else:
            out.append(c)
    if carry is not None:
        if out:
            last = out[-1]
            out[-1] = (last[0], last[1], last[2], last[3] + "\n" + carry[3])
        else:
            out.append(carry)
    return out


def add_doc(prefix: str, src: str, path: str, max_level: int, floor: int = 600,
            fallback_date: str = ""):
    text = read(path)
    rel = os.path.relpath(path, ED).replace("\\", "/")
    file_date = first_date(os.path.basename(path), text[:400]) or fallback_date
    parent = ""
    n = 0
    for level, heading, line, body in merge_small(split_md(text, max_level), floor):
        if level and level < max_level:
            parent = heading
        n += 1
        date = first_date(heading, parent, body[:300]) or file_date
        title = heading or "(top of file)"
        if parent and parent != heading and level == max_level:
            title = parent + " > " + heading
        items.append(Item(f"{prefix}-{n:03d}", src, date, title[:300],
                          f"{rel}:{line}", body, len(items)))
    return n


# --------------------------------------------------------- the owner's words

def session_files():
    return {os.path.basename(f)[:-6]: f
            for f in glob.glob(os.path.join(CLAUDE, "projects", "*", "*.jsonl"))}


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def replies_for(path: str):
    """[(epoch_ms, first 80 chars of the prompt, final reply text)] for one
    session file: for each real prompt, the last text the assistant wrote
    before the next one."""
    out = []
    cur = None
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with f:
        for line in f:
            if '"type":"user"' not in line and '"type":"assistant"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("isSidechain"):
                continue
            msg = o.get("message") or {}
            if o.get("type") == "user":
                c = msg.get("content")
                if isinstance(c, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                    continue
                t = text_of(c).strip()
                if not t:
                    continue
                if cur:
                    out.append(tuple(cur))
                try:
                    ms = int(dt.datetime.fromisoformat(
                        o.get("timestamp", "").replace("Z", "+00:00")).timestamp() * 1000)
                except Exception:
                    ms = 0
                cur = [ms, t[:80], ""]
            elif o.get("type") == "assistant" and cur:
                t = text_of(msg.get("content")).strip()
                if t:
                    cur[2] = t
    if cur:
        out.append(tuple(cur))
    return out


def paste_text(pc: dict) -> str:
    parts = []
    for k, v in (pc or {}).items():
        if not isinstance(v, dict):
            continue
        c = v.get("content")
        if not c and v.get("contentHash"):
            p = os.path.join(CLAUDE, "paste-cache", v["contentHash"] + ".txt")
            if os.path.exists(p):
                c = read(p)
        if c:
            parts.append(f"[pasted #{k}]\n{c[:6000]}")
    return "\n".join(parts)


def add_prompts():
    rows = []
    skipped = collections.Counter()
    with open(os.path.join(CLAUDE, "history.jsonl"), encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            d = (o.get("display") or "").strip()
            if not d:
                skipped["empty"] += 1
                continue
            if d.startswith("/") and " " not in d:
                skipped["a bare slash command"] += 1
                continue
            proj = o.get("project", "")
            if not (PRODUCT_FOLDER.search(proj) or PRODUCT_WORD.search(d)):
                skipped["typed outside the product's folders and naming nothing of it"] += 1
                continue
            rows.append(o)
    rows.sort(key=lambda o: o.get("timestamp", 0))
    files = session_files()
    cache: dict[str, list] = {}
    first_seen: dict[str, int] = {}
    for o in rows:
        first_seen.setdefault(o.get("sessionId", ""), o.get("timestamp", 0))
    with_reply = 0
    for n, o in enumerate(rows, 1):
        sid = o.get("sessionId", "")
        ts = o.get("timestamp", 0)
        d = o["display"].strip()
        when = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc)
        text = d
        pasted = paste_text(o.get("pastedContents"))
        if pasted:
            text += "\n" + pasted
        reply = ""
        if sid in files:
            if sid not in cache:
                cache[sid] = replies_for(files[sid])
            best = None
            for ms, head, rep in cache[sid]:
                if head[:60] == d[:60] or abs(ms - ts) < 8000:
                    if best is None or abs(ms - ts) < abs(best[0] - ts):
                        best = (ms, rep)
            if best and best[1]:
                reply = best[1]
                with_reply += 1
        if reply:
            if len(reply) > 3000:
                reply = reply[:1200] + "\n[...]\n" + reply[-1700:]
            text += "\n--- what Claude answered at the end of that turn ---\n" + reply
        title = d.replace("\n", " ")[:120]
        # order: each session's messages together, sessions by first message
        order = (first_seen.get(sid, ts), ts)
        items.append(Item(f"P-{n:05d}", "P", when.strftime("%Y-%m-%d"), title,
                          f"{proj_short(o.get('project', ''))} | session {sid[:8]} | "
                          f"{when.strftime('%H:%M')} UTC",
                          text, order))
    return len(rows), with_reply, skipped


def proj_short(p: str) -> str:
    return p.replace("E:\\Projects\\", "").replace("C:\\Users\\alex", "~") or "?"


# ------------------------------------------------------------------ ledger

def add_ledger():
    text = read(os.path.join(CC, "KNOWN_BUGS.md"))
    chunks = split_md(text, 3)
    parent = ""
    parent_date = ""
    n = 0
    pending = None  # a ## preamble, folded into its first ### when short
    out = []
    for level, heading, line, body in chunks:
        if level <= 2:
            parent = heading
            parent_date = first_date(heading, body[:400])
            out.append([level, heading, line, body, parent, parent_date])
        else:
            out.append([level, heading, line, body, parent, parent_date])
    # fold a short ## preamble (under 500 chars beyond its heading) forward
    folded = []
    for c in out:
        if pending is not None:
            if c[0] == 3:
                c[3] = pending[3] + "\n" + c[3]
                c[2] = pending[2]
                pending = None
            else:
                folded.append(pending)
                pending = None
        if c[0] <= 2 and len(c[3]) - len(c[1]) < 500:
            pending = c
        else:
            folded.append(c)
    if pending is not None:
        folded.append(pending)
    for level, heading, line, body, par, pdate in folded:
        n += 1
        title = heading if level <= 2 or not par else par + " > " + heading
        items.append(Item(f"L-{n:04d}", "L", first_date(heading, body[:300]) or pdate,
                          title[:300], f"ccsync/KNOWN_BUGS.md:{line}", body, len(items)))
    return n


# ----------------------------------------------------------------- memory

MEM_DIRS = {
    "E--Projects-Editing-ccsync": "cc",
    "E--Projects-Editing-ccsync-dashboard": "ccd",
    "E--Projects-Editing": "ed",
    "E--Projects-Editing-Resolve-MulticamPipeline": "tc",
    "E--Projects-Editing-Resolve-MontagePipeline": "mp",
    "E--Projects-Editing-footage-sorter": "fs",
    "E--Projects-footage-sorter": "fs2",
    "E--Projects-Editing-Launcher": "la",
    "E--Projects-resolve-relink": "rr",
    "E--Projects": "pr",
    "C--Users-alex": "home",
}
ALWAYS_PRODUCT = {"cc", "ccd", "tc", "fs", "fs2", "rr"}


def add_memory():
    n = 0
    for d, ab in MEM_DIRS.items():
        for path in sorted(glob.glob(os.path.join(CLAUDE, "projects", d, "memory", "*.md"))):
            name = os.path.basename(path)
            if name == "MEMORY.md":
                continue
            text = read(path)
            mid = f"M-{ab}-{slug(name[:-3], 60)}"
            desc = ""
            m = re.search(r"^description:\s*(.+)$", text, re.M)
            if m:
                desc = m.group(1).strip()
            if ab not in ALWAYS_PRODUCT and not PRODUCT_WORD.search(text):
                auto_no.append((mid, "not about the product (no product word in the note)",
                                desc[:150] or name))
                continue
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")
            items.append(Item(mid, "M", first_date(name, desc, text) or mtime,
                              (desc or name)[:300], f"memory/{d}/{name}", text, len(items)))
            n += 1
    other = [os.path.basename(os.path.dirname(os.path.dirname(p)))
             for p in glob.glob(os.path.join(CLAUDE, "projects", "*", "memory", "*.md"))]
    skipped = collections.Counter(d for d in other if d not in MEM_DIRS)
    return n, skipped


# ---------------------------------------------------------------- commits

def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def add_commits(repo: str, ab: str, rev: str, paths: tuple[str, ...] = ()):
    fmt = "%x1e%H%x1f%ad%x1f%s%x1f%b"
    raw = git(repo, "log", rev, "--date=short", "--reverse", f"--format={fmt}")
    keep = None
    if paths:
        keep = set(git(repo, "log", rev, "--format=%H", "--", *paths).split())
    n = 0
    for rec in raw.split("\x1e"):
        if not rec.strip():
            continue
        h, date, subj, body = (rec.split("\x1f") + ["", "", "", ""])[:4]
        h = h.strip()
        cid = f"C-{ab}-{h[:9]}"
        if keep is not None and h not in keep:
            auto_no.append((cid, "touches nothing in the product (another part of the Editing repo)",
                            subj[:150]))
            continue
        body = re.sub(r"\n(Co-Authored-By|Claude-Session):.*", "", body.strip())
        items.append(Item(cid, "C", date, subj[:300], f"{ab} {h[:9]}",
                          subj + ("\n\n" + body if body.strip() else ""), len(items)))
        n += 1
    return n


# ------------------------------------------------------------------ slices

def write_slices():
    os.makedirs(os.path.join(OUT, "slices"), exist_ok=True)
    for f in glob.glob(os.path.join(OUT, "slices", "*")):
        os.remove(f)
    by_src = collections.defaultdict(list)
    for it in items:
        by_src[it.src].append(it)
    slice_of = {}
    index = []
    for src in "PLGHDMC":
        group = sorted(by_src.get(src, []), key=lambda it: it.order)
        budget = BUDGET[src]
        packs, cur, size = [], [], 0
        for it in group:
            b = len(it.text.encode("utf-8")) + 200
            if cur and (size + b > budget or len(cur) >= ITEM_CAP.get(src, 10**9)):
                packs.append(cur)
                cur, size = [], 0
            cur.append(it)
            size += b
        if cur:
            packs.append(cur)
        for k, pack in enumerate(packs, 1):
            name = f"{src}{k:02d}"
            with open(os.path.join(OUT, "slices", name + ".md"), "w",
                      encoding="utf-8", newline="\n") as f:
                f.write(f"# Register slice {name}: {len(pack)} items\n\n")
                for it in pack:
                    f.write(f"<<<ITEM {it.id} | {it.date or 'no date'} | {it.where}>>>\n")
                    if src != "P":
                        f.write(f"TITLE: {it.title}\n")
                    f.write(it.text.rstrip() + "\n<<<END {0}>>>\n\n".format(it.id))
            with open(os.path.join(OUT, "slices", name + ".ids"), "w",
                      encoding="utf-8", newline="\n") as f:
                f.write("\n".join(it.id for it in pack) + "\n")
            for it in pack:
                slice_of[it.id] = name
            dates = sorted(d for d in (it.date for it in pack) if d)
            index.append((name, len(pack), sum(len(it.text.encode("utf-8")) for it in pack),
                          dates[0] if dates else "", dates[-1] if dates else ""))
    return slice_of, index


def write_days():
    """One small file per day: what was committed, entered in the ledger and
    noted that day, so a reader following one of the owner's reports to its
    outcome knows where to look."""
    d = os.path.join(OUT, "by-day")
    os.makedirs(d, exist_ok=True)
    for f in glob.glob(os.path.join(d, "*.md")):
        os.remove(f)
    days = collections.defaultdict(list)
    for it in items:
        if it.date and it.src in "LMCHD":
            days[it.date].append(it)
    for day, its in days.items():
        with open(os.path.join(d, day + ".md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# {day}\n\n")
            for it in sorted(its, key=lambda i: (i.src, i.id)):
                f.write(f"- {it.id} ({it.where}): {it.title}\n")
    return len(days)


def main():
    os.makedirs(OUT, exist_ok=True)
    summary = {"built": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}

    n, with_reply, skipped = add_prompts()
    summary["P"] = {"items": n, "with Claude's closing answer": with_reply,
                    "left out of the register": dict(skipped)}
    last_p = max((it for it in items if it.src == "P"), key=lambda i: i.id)
    summary["P"]["last message"] = last_p.date

    summary["L"] = {"items": add_ledger()}

    g = add_doc("G-cc", "G", os.path.join(CC, "docs", "GOTCHAS.md"), 2)
    g2 = add_doc("G-tc", "G", os.path.join(TC, "GOTCHAS.md"), 2)
    summary["G"] = {"items": g + g2}

    hn = 0
    hunt_files = sorted(glob.glob(os.path.join(CC, "docs", "bug-hunt-*.md")))
    hunt_files += sorted(glob.glob(os.path.join(CC, "docs", "bug-hunt-*", "fable-review-*.md")))
    hunt_files += [os.path.join(CC, "docs", x) for x in (
        "RESILIENCE_SWEEP_2026-08-28.md", "USABILITY_RESILIENCE_SWEEP_2026-09-03.md",
        "UI_PORT_REVIEW_2026-09-25.md", "PRELAUNCH_REVIEW_2026-10-06.md",
        "AUDIT_2026-11-10.md")]
    for path in hunt_files:
        base = os.path.basename(path)[:-3]
        tag = slug(base.replace("bug-hunt-", "bh").replace("RESILIENCE_SWEEP", "rs")
                   .replace("USABILITY_", "u").replace("PRELAUNCH_REVIEW", "plr")
                   .replace("UI_PORT_REVIEW", "uir").replace("AUDIT", "aud")
                   .replace("fable-review-", "fr-"), 24)
        hn += add_doc(f"H-{tag}", "H", path, 3)
    summary["H"] = {"items": hn, "files": len(hunt_files)}
    raw_hunt = [p for p in glob.glob(os.path.join(CC, "docs", "bug-hunt-*", "**", "*"),
                                     recursive=True)
                if os.path.isfile(p) and p not in hunt_files]
    summary["H"]["raw hunt files not itemised"] = len(raw_hunt)

    dn = 0
    for path in sorted(glob.glob(os.path.join(TC, "docs", "*.md"))):
        dn += add_doc("D-tc-" + slug(os.path.basename(path)[:-3], 22), "D", path, 2)
    for path in sorted(glob.glob(os.path.join(FS, "docs", "*.md"))):
        dn += add_doc("D-fs-" + slug(os.path.basename(path)[:-3], 22), "D", path, 2)
    summary["D"] = {"items": dn}

    mn, mskipped = add_memory()
    summary["M"] = {"items": mn, "folders not read (not this product)": dict(mskipped)}

    summary["C"] = {
        "ccsync": add_commits(CC, "cc", "HEAD"),
        "Editing": add_commits(ED, "ed", "HEAD",
                               ("Resolve/MulticamPipeline", "Resolve/MontagePipeline")),
        "footage-sorter": add_commits(FS, "fs", "--all"),
    }
    summary["heads"] = {"ccsync": git(CC, "rev-parse", "--short", "HEAD").strip(),
                        "Editing": git(ED, "rev-parse", "--short", "HEAD").strip(),
                        "footage-sorter": git(FS, "rev-parse", "--short", "HEAD").strip()}

    ids = [it.id for it in items]
    dup = [i for i, c in collections.Counter(ids).items() if c > 1]
    if dup:
        sys.exit(f"duplicate ids: {dup[:10]}")

    slice_of, index = write_slices()
    summary["days"] = write_days()
    summary["auto no-entry"] = len(auto_no)
    summary["total items"] = len(items)
    summary["slices"] = {name: {"items": n, "bytes": b, "from": a, "to": z}
                         for name, n, b, a, z in index}

    with open(os.path.join(OUT, "register.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("id\tsrc\tslice\tdate\tbytes\twhere\ttitle\n")
        for it in items:
            f.write("\t".join([it.id, it.src, slice_of[it.id], it.date,
                               str(len(it.text.encode("utf-8"))), it.where,
                               it.title.replace("\t", " ").replace("\n", " ")]) + "\n")
    with open(os.path.join(OUT, "auto_no_entry.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("id\treason\ttitle\n")
        for i, r, t in auto_no:
            f.write(f"{i}\t{r}\t{t.replace(chr(9), ' ')}\n")
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
