#!/usr/bin/env python3
"""Shared reading of the knowledge base's files (REBUILD_PLAN.md, step 2).

    merged()   every finished and sealed entry of knowledge-base/_merged/*.md,
               and every removed line
    parts()    every reader's entry of knowledge-base/_parts/*.md, with the
               register ids it cites

Nothing here writes anything.
"""
from __future__ import annotations

import glob
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.abspath(os.path.join(HERE, ".."))
KB = os.path.join(SPEC, "knowledge-base")
MERGED = os.path.join(KB, "_merged")
PARTS = os.path.join(KB, "_parts")
CROSS = os.path.join(KB, "_cross")

PART_ID = re.compile(r"\b[PLGHDMC]\d\d-\d{3}\b")

# The file a bundle's entries end up in. The Timeline Cards editor was merged
# in three pieces; they are one capability.
def capability_of(bundle: str) -> str:
    return re.sub(r"-\d+$", "", bundle)


NAMES = {
    "accounts-privacy-legal": "Accounts, privacy and the legal paperwork",
    "broll": "The b-roll archive",
    "cards-board": "Timeline Cards: the board",
    "cards-editor": "Timeline Cards: the editor",
    "cards-footage-in": "Timeline Cards: footage in, ready to cut",
    "cards-to-resolve-and-exports": "Timeline Cards: the hand-over to Resolve, and exports",
    "dashboard": "The dashboard",
    "editor-app": "The app on each editor's computer",
    "fleet-jobs": "Work shared out across the computers",
    "footage-sorter-and-camera-cards": "The Footage Sorter and camera cards",
    "music": "Music",
    "proxies-and-file-moves": "Proxies and file moves",
    "releases-and-updates": "Releases and updates",
    "resolve-on-the-editors-computer": "Resolve on the editor's computer",
    "server-install-and-running": "The server: installing it and keeping it running",
    "sync": "Sync",
    "whole-product": "The whole product",
    "youtube": "YouTube downloads",
}


def merged(only: list[str] | None = None):
    """-> (entries, removed). An entry: id, title, bundle, capability, topic,
    sealed, order, fields{}. A removed line: bundle, ids[], reason."""
    entries, removed = [], []
    for path in sorted(glob.glob(os.path.join(MERGED, "*.md"))):
        bundle = os.path.basename(path)[:-3]
        if only and bundle not in only:
            continue
        text = open(path, encoding="utf-8", errors="replace").read().replace("\r\n", "\n")
        topic, cur = "", None
        for line in text.split("\n"):
            if line.startswith("## "):
                topic, cur = line[3:].strip(), None
                continue
            low = topic.lower()
            if low == "removed":
                if line.startswith("- "):
                    cols = [c.strip() for c in line[2:].split("|", 1)]
                    removed.append({"bundle": bundle, "ids": PART_ID.findall(cols[0]),
                                    "reason": cols[1] if len(cols) > 1 else ""})
                continue
            m = re.match(r"^###\s+(\S+?):\s*(.*)$", line)
            if m:
                cur = {"id": m.group(1), "title": m.group(2).strip(), "bundle": bundle,
                       "capability": capability_of(bundle), "topic": topic,
                       "sealed": low == "sealed", "order": len(entries), "fields": {}}
                entries.append(cur)
                continue
            m = re.match(r"^-\s+([A-Za-z ]+?):\s*(.*)$", line)
            if m and cur is not None:
                cur["fields"][m.group(1).strip()] = m.group(2).strip()
    for e in entries:
        e["from"] = PART_ID.findall(e["fields"].get("From", ""))
    return entries, removed


_REG = r"[PLGHDMC]-[A-Za-z0-9_.\-]+"
_RANGE = re.compile(r"^([PL])-(\d+)\.\.([PL])-(\d+)$")


def _expand(token: str):
    m = _RANGE.match(token)
    if not m:
        return [token]
    a, b = int(m.group(2)), int(m.group(4))
    w = len(m.group(2))
    return [f"{m.group(1)}-{n:0{w}d}" for n in range(a, b + 1)]


def parts():
    """-> {part entry id: {capability, kind, date, state, found, sources[]}}"""
    out = {}
    for path in sorted(glob.glob(os.path.join(PARTS, "*.md"))):
        if os.path.basename(path).startswith("KB_"):
            continue
        text = open(path, encoding="utf-8", errors="replace").read().replace("\r\n", "\n")
        section, cur = "", None
        for line in text.split("\n"):
            if line.startswith("## "):
                section, cur = line[3:].strip().lower(), None
                continue
            if section != "entries":
                continue
            m = re.match(r"^###\s+(\S+?):\s*(.*)$", line)
            if m:
                cur = {"title": m.group(2).strip(), "sources": []}
                out[m.group(1)] = cur
                continue
            m = re.match(r"^-\s+([A-Za-z ]+?):\s*(.*)$", line)
            if m and cur is not None:
                k, v = m.group(1).strip(), m.group(2).strip()
                if k == "Sources":
                    for tok in re.findall(_REG + r"(?:\.\." + _REG + r")?", v):
                        cur["sources"].extend(_expand(tok.rstrip(".,;")))
                else:
                    cur[k.lower()] = v
    return out
