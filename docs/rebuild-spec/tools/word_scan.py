#!/usr/bin/env python3
"""Step 6, part 1: the word scan (REBUILD_PLAN.md, "How the purge is checked").

    python docs/rebuild-spec/tools/word_scan.py            scan, write the report
    python docs/rebuild-spec/tools/word_scan.py --terms    only list what was gathered

"A script builds the banned list from the inventory and the code (every tool,
library, file, route, setting, table and internal noun) and fails the pack on
any hit."

The list is gathered from the three repositories as they stand, never typed
by hand, so a noun nobody thought to ban is still caught:

  libraries   every package named in a lock, requirements, pyproject or
              package file
  names       every source file's name; every class; every table; every
              setting key of the example site file and the app's own settings;
              every environment variable; every word of every route
  shapes      anything in the pack shaped like code whatever its name: a
              snake_case or dotted identifier, an ALL_CAPS variable, a path,
              a source-file extension, a version number, a bug number

A gathered name of several words ("lane_guard", "PendingTracker") is looked
for as the phrase ("lane guard", "pending tracker"), which is how an internal
noun survives being written in plain words. A gathered single word is looked
for as a word.

Most hits on ordinary words are innocent: a file called `music` does not make
"music" a secret. So every hit is either answered in
tools/word_scan_allow.txt (the word, and why it may cross) or is a leak. The
scan passes when nothing is left unanswered. The report goes to the
gitignored _raw/word-scan/report.md: it is a list of the old build's own
nouns and must never be committed or cross.

What is scanned (the pack as it stands): the built text of every piece
(_raw/spec-built/, made by `check_spec.py --build`), OWNER_REQUIREMENTS.md,
CAPABILITIES.md and the knowledge base's capability files. Text inside double
quotes is wording a person is shown, which crosses by the owner's decision;
hits there are reported apart, and need an answer only if the word is one of
the old build's own tools or libraries.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import merged_lib as ml  # noqa: E402

EDITING = os.path.abspath(os.path.join(ml.SPEC, "..", "..", ".."))
REPOS = {
    "ccsync": os.path.join(EDITING, "ccsync"),
    "cards": os.path.join(EDITING, "Resolve", "MulticamPipeline"),
    "sorter": os.path.join(EDITING, "footage-sorter"),
}
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "dist-server",
             "build", "legacy", "scratch", "cache", "data", "docs", "private", "feed",
             "design", "shots", ".pytest_cache", "site-packages", "_raw"}
SOURCE_EXT = (".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".ps1", ".sh", ".lua", ".cmd",
              ".html", ".css", ".kt", ".ahk")
OUT = os.path.join(ml.SPEC, "_raw", "word-scan")
ALLOW = os.path.join(HERE, "word_scan_allow.txt")
BUILT = os.path.join(ml.SPEC, "_raw", "spec-built")

# Words too common to carry anything, whatever file is named after them.
STOP = set("""a an and are as at be by do for from go has have if in into is it its me my no not of
off on one or our out so the their them then this to up us was we what when who why will with you
your all any can did end get got had her him his how let may new now old own put run say see set
she too two use via way yes yet also back been both each even ever every here just keep kept last
less like made make many more most much must near need next none once only open over part same
some such take than that they time used very want well were where which while work would about
after again being below above could doing done down first found given going known later least
other right shall since still their there these thing those three under until using were whole
without within main test tests util utils common base core lib app apps index init types type
""".split())


def walk(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        if re.search(r"[\\/](tests?|__tests__)([\\/]|$)", d):
            continue
        for f in files:
            yield os.path.join(d, f)


def split_name(name: str):
    """'lane_guard' / 'PendingTracker' / 'cards-pool' -> ['lane','guard'] ..."""
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", name) if w]


def gather():
    """-> {term (lower, words joined by one space): set of (kind, where)}"""
    terms = collections.defaultdict(set)

    def add(kind, raw, where):
        words = split_name(raw)
        if not words or len(words) > 5:
            return
        if all(w.isdigit() for w in words):
            return
        term = " ".join(words)
        if len(term) < 3:
            return
        terms[term].add((kind, where))

    for repo, root in REPOS.items():
        if not os.path.isdir(root):
            print(f"note: {repo} is not at {root}; its names are not gathered", file=sys.stderr)
            continue
        for path in walk(root):
            base = os.path.basename(path)
            low = base.lower()
            rel = repo + ":" + os.path.relpath(path, root).replace("\\", "/")
            # libraries
            if low in ("requirements.lock", "requirements.txt") or low.startswith("requirements"):
                for line in open(path, encoding="utf-8", errors="replace"):
                    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*(?:[=<>~!]=|@|;|$)", line.strip())
                    if m and not line.lstrip().startswith(("#", "-")):
                        terms[m.group(1).lower()].add(("library", rel))
            elif low == "package.json":
                try:
                    pj = json.load(open(path, encoding="utf-8"))
                except Exception:
                    pj = {}
                for k in ("dependencies", "devDependencies", "optionalDependencies"):
                    for name in (pj.get(k) or {}):
                        terms[name.lower().split("/")[-1]].add(("library", rel))
                        if name.startswith("@"):
                            terms[name.lower()].add(("library", rel))
            elif low == "pyproject.toml":
                txt = open(path, encoding="utf-8", errors="replace").read()
                for m in re.finditer(r'"([A-Za-z0-9][A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*[=<>~!]', txt):
                    terms[m.group(1).lower()].add(("library", rel))
            if not low.endswith(SOURCE_EXT) and low not in ("site.example.toml",):
                continue
            # the file's own name
            stem = base.rsplit(".", 1)[0]
            if not re.fullmatch(r"__\w+__", stem):
                add("file", stem, rel)
            try:
                txt = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if len(txt) > 3_000_000:
                continue
            for m in re.finditer(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Z][A-Za-z0-9_]+)", txt, re.M):
                add("class", m.group(1), rel)
            for m in re.finditer(r"CREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?([a-z_][a-z0-9_]+)", txt, re.I):
                add("table", m.group(1), rel)
            for m in re.finditer(r"\b((?:DASH|CCSYNC|BROLL|MUSIC|CARDS|TC|SORTER|YTDL|TRUENAS|SYNCTHING)_[A-Z0-9_]{3,})\b", txt):
                terms[m.group(1).lower().replace("_", " ")].add(("env", rel))
            for m in re.finditer(r"""["'`](/(?:api|cards|broll|music|ytdl|sorter|agent|partials|admin|account|fleet|share|static)[A-Za-z0-9_/{}<>:.\-]*)["'`]""", txt):
                for seg in m.group(1).split("/"):
                    if seg and not re.search(r"[{}<>:]", seg) and len(seg) > 3:
                        add("route", seg, rel)
            if low.endswith(".toml"):
                for m in re.finditer(r"^\s*([a-z][a-z0-9_]+)\s*=", txt, re.M):
                    add("setting", m.group(1), rel)
                for m in re.finditer(r"^\s*\[([a-z][a-z0-9_.]+)\]", txt, re.M):
                    add("setting", m.group(1), rel)
    # Programs the code RUNS are in no lock file. The sealed drawer is filed by
    # exactly those tools (one file per tool the old build chose), so its
    # file names are the list. Platform and browser facilities are givens.
    sealed = os.path.join(ml.SPEC, "sealed")
    for f in sorted(os.listdir(sealed)) if os.path.isdir(sealed) else []:
        if not f.endswith(".md") or f == "README.md":
            continue
        for fam in f[:-3].split("+"):
            if fam.endswith("-facilities") or fam in ("browser-features", "resolve-scripting-api",
                                                       "resolve-own-transcription",
                                                       "resolve-editing-a-timeline-by-script"):
                continue
            first = fam.split("-")[0]
            for t in {fam.replace("-", " "), fam, first if len(first) > 4 else fam}:
                terms[t].add(("library", "sealed:" + f))
    # the app's own setting keys, read from its config module
    cfg = os.path.join(REPOS["ccsync"], "companion", "src", "ccsync_companion", "config.py")
    if os.path.exists(cfg):
        for m in re.finditer(r"""["']([a-z][a-z0-9]*(?:_[a-z0-9]+)+)["']""", open(cfg, encoding="utf-8").read()):
            add("setting", m.group(1), "ccsync:companion config")
    return terms


SHAPES = [
    ("snake_case", re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")),
    ("ALL_CAPS", re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")),
    ("dotted", re.compile(r"\b[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\(")),
    ("source file", re.compile(r"\b[\w-]+\.(?:py|pyc|ts|tsx|js|mjs|cjs|ps1|sh|lua|toml|ini|yaml|yml|sqlite|db|lock|exe|dll|so|dylib|log|tsv|cmd|bat)\b", re.I)),
    ("path", re.compile(r"(?<![\w.])(?:~|[A-Za-z]:)?(?:[\\/][\w.\-]+){2,}")),
    ("route", re.compile(r"(?<![\w.:/])/(?:api|cards|broll|music|ytdl|sorter|agent|partials|admin|account|fleet)\b[\w/\-]*")),
    ("version", re.compile(r"\b0\.\d+\.\d+\b|\bv\d{2,3}\b")),
    # Not the knowledge base's own lesson ids (ACC-001, RSV-147 ...), which cross.
    ("bug number", re.compile(r"\b(?:CR|LG|WP)-\d+[a-z]?\b|\b(?:tests?|trust-model|release-pipeline|wire|dash-api|ytdl-web)-\d+\b")),
    ("http verb", re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+/")),
]


def pack_files():
    files = []
    for p in sorted(glob.glob(os.path.join(BUILT, "*.md"))):
        files.append(("spec/" + os.path.basename(p), p))
    for n in ("OWNER_REQUIREMENTS.md", "CAPABILITIES.md"):
        files.append(("spec/" + n, os.path.join(ml.SPEC, "spec", n)))
    for p in sorted(glob.glob(os.path.join(ml.KB, "*.md"))):
        if os.path.basename(p) != "README.md":
            files.append(("knowledge-base/" + os.path.basename(p), p))
    return files


def read_allow():
    """-> {term: reason}. Lines: `term | why it may cross`."""
    allow = {}
    if os.path.exists(ALLOW):
        for line in open(ALLOW, encoding="utf-8"):
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            t, _, why = line.partition("|")
            allow[t.strip().lower()] = why.strip()
    return allow


QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
LESSON_LINE = re.compile(r"^(- (Met|Not yet met|Met for another part)|### [A-Z][A-Z0-9]{2}-\d{3}:)")


def main():
    terms = gather()
    if "--terms" in sys.argv:
        for t in sorted(terms):
            print(t, "|", ", ".join(sorted({k for k, _ in terms[t]})))
        print(len(terms), "terms", file=sys.stderr)
        return
    allow = read_allow()
    files = pack_files()
    if not any(n.startswith("spec/") and n not in ("spec/OWNER_REQUIREMENTS.md", "spec/CAPABILITIES.md")
               for n, _ in files):
        print("no built text: run `python docs/rebuild-spec/tools/check_spec.py --build` first")
        sys.exit(1)

    singles = {t for t in terms if " " not in t and t not in STOP and len(t) > 2}
    phrases = {t for t in terms if " " in t}
    # one pass per line: words for singles, a sliding window for phrases
    hits = collections.defaultdict(lambda: {"out": 0, "quoted": 0, "where": []})
    maxlen = max((len(p.split()) for p in phrases), default=1)
    for name, path in files:
        for n, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
            line = line.rstrip("\n")
            if LESSON_LINE.match(line) and not line.startswith("### "):
                continue
            spans = [(m.start(), m.end()) for m in QUOTED.finditer(line)]

            def note(key, pos, sample=line, name=name, n=n, spans=spans):
                h = hits[key]
                inq = any(a <= pos < b for a, b in spans)
                h["quoted" if inq else "out"] += 1
                if len(h["where"]) < 4 and not (inq and h["out"] == 0 and len(h["where"]) >= 2):
                    s = max(0, pos - 60)
                    h["where"].append(f"{name}:{n}{' (shown wording)' if inq else ''}: "
                                      f"...{sample[s:pos + 80].strip()}...")

            for kind, rx in SHAPES:
                for m in rx.finditer(line):
                    note(f"[{kind}] {m.group(0)}", m.start())
            toks = [(m.group(0).lower(), m.start()) for m in re.finditer(r"[A-Za-z][A-Za-z0-9']*", line)]
            for i, (w, pos) in enumerate(toks):
                if w in singles:
                    note(w, pos)
                for k in range(2, maxlen + 1):
                    if i + k > len(toks):
                        break
                    ph = " ".join(t for t, _ in toks[i:i + k])
                    if ph in phrases:
                        # the words must be next to each other in the line
                        if toks[i + k - 1][1] - pos <= len(ph) + 2 * k:
                            note(ph, pos)

    os.makedirs(OUT, exist_ok=True)
    kinds_of = {t: sorted({k for k, _ in terms[t]}) for t in terms}
    left, answered = [], []
    for key, h in hits.items():
        term = key.split("] ", 1)[1].lower() if key.startswith("[") else key
        libs = "library" in kinds_of.get(key, [])
        needs = h["out"] > 0 or libs or key.startswith("[")
        if not needs:
            continue
        (answered if (term in allow or key.lower() in allow) else left).append((key, h))

    def order(x):
        key, h = x
        shape = key.startswith("[")
        lib = "library" in kinds_of.get(key, [])
        phrase = " " in key and not shape
        return (0 if shape else 1 if lib else 2 if phrase else 3, -h["out"] - h["quoted"], key)

    out = ["# Word scan: what the pack says that the old build's code also says", "",
           "STAYS BEHIND, and is never committed: this is a list of the old build's own names.",
           "", f"{len(terms)} names gathered from the three repositories; {len(files)} files of "
           f"the pack scanned. {len(left)} hits unanswered, {len(answered)} answered in "
           "`tools/word_scan_allow.txt`.", ""]
    groups = [("Shaped like code", lambda k: k.startswith("[")),
              ("A library or tool the old build used", lambda k: not k.startswith("[") and "library" in kinds_of.get(k, [])),
              ("A name of several words (an internal noun written out)", lambda k: not k.startswith("[") and " " in k and "library" not in kinds_of.get(k, [])),
              ("A single word that is also a name in the code", lambda k: not k.startswith("[") and " " not in k and "library" not in kinds_of.get(k, []))]
    for title, test in groups:
        rows = sorted((x for x in left if test(x[0])), key=order)
        out += [f"## {title}: {len(rows)}", ""]
        for key, h in rows:
            src = "" if key.startswith("[") else " (" + ", ".join(kinds_of.get(key, [])) + ")"
            out.append(f"- **{key}**{src}: {h['out']} in the text, {h['quoted']} in shown wording")
            for w in h["where"][:3]:
                out.append(f"  - {w[:300]}")
        out.append("")
    with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    with open(os.path.join(OUT, "unanswered.txt"), "w", encoding="utf-8", newline="\n") as f:
        for key, h in sorted(left, key=order):
            f.write(f"{key}\t{h['out']}\t{h['quoted']}\t{','.join(kinds_of.get(key, []))}\n")
    by = collections.Counter()
    for key, _ in left:
        for title, test in groups:
            if test(key):
                by[title.split(":")[0].split(" (")[0]] += 1
    print(f"{len(terms)} names gathered; {len(files)} pack files; "
          f"{len(left)} hits unanswered, {len(answered)} answered")
    for k, v in by.items():
        print(f"   {v:5d}  {k}")
    print("report: docs/rebuild-spec/_raw/word-scan/report.md")
    print("OK" if not left else "NOT OK")
    sys.exit(0 if not left else 1)


if __name__ == "__main__":
    main()
