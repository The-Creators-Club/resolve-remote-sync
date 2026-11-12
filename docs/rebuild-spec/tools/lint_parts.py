#!/usr/bin/env python3
"""A first net for the purge rule and the terse rule on knowledge-base parts.

    python docs/rebuild-spec/tools/lint_parts.py [slice ...]

Reads only the three text fields of each entry (title, "What was going on",
"What the product must do"): the Tool, Sources and "Stays behind" lines stay
behind and may name anything. Reports words that give away how the old
product was built, and entries over the length limits. It is a net, not the
purge check: the real word scan (step 6) builds its list from the code.
"""
from __future__ import annotations

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = os.path.abspath(os.path.join(HERE, "..", "knowledge-base", "_parts"))

BANNED = [
    r"rclone", r"syncthing", r"ffmpeg", r"ffprobe", r"yt-?dlp", r"whisper", r"pyannote",
    r"opencc", r"ollama", r"qwen", r"python", r"\btk\b", r"tkinter", r"tcl", r"pyinstaller",
    r"docker", r"container", r"sqlite", r"postgres", r"fastapi", r"\bnode\b", r"npm",
    r"powershell", r"tailscale", r"funnel", r"claude", r"anthropic", r"obsidian", r"github",
    r"\blane [abc]\b", r"pystray", r"htmx", r"websocket", r"\bwsgi\b", r"asgi",
    r"\bcr-\d+", r"\bv\d\d\b", r"\b0\.\d+\.\d+\b", r"\.py\b", r"\.ps1\b", r"\.toml\b", r"\.json\b",
    r"[a-z]+_[a-z_]+", r"/api/", r"\bdeno\b", r"bgutil", r"\bclap\b", r"zfs", r"smtp", r"imap",
    r"ruskin", r"leso\b", r"\balex\b", r"creator-1", r"razer", r"\b\d+\.\d+\.\d+\.\d+\b",
    r"breaker", r"enforce cycle", r"collector", r"pin(ned)? job", r"sidecar",
]
RX = re.compile("|".join(f"(?:{b})" for b in BANNED), re.I)


def words(s: str) -> int:
    return len(s.split())


def lint(path: str):
    out = []
    eid = ""
    section = ""
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if section != "entries":
            continue
        m = re.match(r"^###\s+(\S+?):\s*(.*)$", line)
        field = None
        if m:
            eid, field, text, limit = m.group(1), "title", m.group(2), 15
        else:
            m = re.match(r"^-\s+(What was going on|What the product must do):\s*(.*)$", line)
            if m:
                field, text, limit = m.group(1), m.group(2), 34
        if not field:
            continue
        hits = sorted({h.group(0).lower() for h in RX.finditer(text)})
        if hits:
            out.append(f"{eid} [{field}] names: {', '.join(hits)}")
        if words(text) > limit:
            out.append(f"{eid} [{field}] is {words(text)} words")
    return out


def main():
    names = sys.argv[1:] or sorted(
        os.path.basename(p)[:-3] for p in glob.glob(os.path.join(PARTS, "*.md"))
        if os.path.basename(p) != "KB_BRIEF.md")
    total = 0
    for n in names:
        p = os.path.join(PARTS, n + ".md")
        if not os.path.exists(p):
            continue
        found = lint(p)
        total += len(found)
        if found:
            print(f"== {n}: {len(found)}")
            for f in found:
                print("  " + f)
    print(f"{total} finding(s)")


if __name__ == "__main__":
    main()
