"""Turn results/results.jsonl into a markdown report:
- a leaderboard table per lane (engine x params, best-of-repeats MB/s, verified)
- a "recommended per-lane config" section (lane A: up/large, lane B: down/large,
  lane C: bidirectional/small) with the exact flag set to use
- a "did we beat Resolve Cloud" section against a configurable baseline,
  shown both as Mbps and MB/s since the ~60 unit Blackmagic quotes is ambiguous
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ccbench.result import RunResult, read_results

DEFAULT_BASELINE_MBPS = 60.0  # "beat Blackmagic Cloud's observed ~60 mb/s"


def classify_lane(dataset: str, direction: str) -> str:
    """Map a (dataset, direction) pair to the SPEC.md-canonical lane letter.
    Matches on substring so dataset dirs like 'large', 'data/large',
    'large_selftest' all work without requiring an exact name."""
    name = dataset.lower()
    if "large" in name and direction == "up":
        return "A"
    if "large" in name and direction == "down":
        return "B"
    if "small" in name:
        return "C"
    if dataset == "network":
        return "net"
    return "?"


def combo_key_no_repeat(r: RunResult) -> tuple:
    return (r.engine, r.direction, r.dataset, json.dumps(r.params, sort_keys=True))


def best_per_combo(results: list[RunResult]) -> list[RunResult]:
    """Collapse repeats: keep the best (highest MB/s) ok run per
    (engine, direction, dataset, params) combo. Ties prefer verified."""
    groups: dict[tuple, list[RunResult]] = defaultdict(list)
    for r in results:
        groups[combo_key_no_repeat(r)].append(r)

    best: list[RunResult] = []
    for _key, rows in groups.items():
        ok_rows = [r for r in rows if r.ok]
        if not ok_rows:
            best.append(rows[0])  # keep one representative failed/skipped row
            continue
        ok_rows.sort(key=lambda r: (r.verified, r.MB_s), reverse=True)
        best.append(ok_rows[0])
    return best


def _fmt_params(params: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(params.items())) or "-"


def _rclone_flags(params: dict[str, Any]) -> str:
    flags = [f"--transfers {params.get('transfers', 4)}"]
    mts = params.get("multi_thread_streams", 0)
    if mts:
        flags.append(f"--multi-thread-streams {mts}")
    if "sftp_chunk_size_mb" in params:
        flags.append(f"--sftp-chunk-size {params['sftp_chunk_size_mb']}M")
    return " ".join(flags)


def _leaderboard_table(rows: list[RunResult]) -> str:
    header = "| Engine | Direction | Dataset | Params | MB/s | Verified | Notes |\n"
    header += "|---|---|---|---|---:|---|---|\n"
    lines = [header.rstrip("\n")]
    rows_sorted = sorted(rows, key=lambda r: r.MB_s, reverse=True)
    for r in rows_sorted:
        if r.skipped:
            notes = f"skipped: {r.reason}"
        elif not r.ok:
            notes = f"FAILED: {r.reason}"
        else:
            notes = ""
        lines.append(
            f"| {r.engine} | {r.direction} | {r.dataset} | {_fmt_params(r.params)} | "
            f"{r.MB_s:.1f} | {'yes' if r.verified else 'no'} | {notes} |"
        )
    return "\n".join(lines)


def _winner(rows: list[RunResult]) -> RunResult | None:
    candidates = [r for r in rows if r.ok]
    if not candidates:
        return None
    verified_candidates = [r for r in candidates if r.verified]
    pool = verified_candidates or candidates
    return max(pool, key=lambda r: r.MB_s)


def _recommend_lane(letter: str, label: str, rows: list[RunResult]) -> str:
    lines = [f"### Lane {letter}: {label}", ""]
    winner = _winner(rows)
    if winner is None:
        lines.append("No successful runs recorded for this lane yet.")
        return "\n".join(lines)

    lines.append(f"**Winner: `{winner.engine}`** at **{winner.MB_s:.1f} MB/s** "
                  f"({'verified' if winner.verified else 'NOT independently verified'}).")
    lines.append("")
    if winner.engine in ("rclone_sftp", "rclone_smb"):
        remote_type = "sftp" if winner.engine == "rclone_sftp" else "smb"
        lines.append(f"Exact flags: `rclone copy ... {_rclone_flags(winner.params)}` (remote type: {remote_type})")
    elif winner.engine == "robocopy_smb":
        lines.append(f"Exact flags: `robocopy SRC DST /E /MT:{winner.params.get('mt', 8)} /R:1 /W:1`")
    elif winner.engine == "syncthing":
        lines.append("Syncthing verdict: use it as configured (event-driven, no stream/thread knob to tune).")
    lines.append("")
    return "\n".join(lines)


def _baseline_section(all_best: list[RunResult], baseline_mbps: float) -> str:
    baseline_mb_s_from_mbps = baseline_mbps / 8.0  # Mbps -> MB/s
    baseline_mb_s_literal = baseline_mbps  # in case "60 mb/s" was actually meant as MB/s

    lines = [
        "## Did we beat Resolve Cloud?",
        "",
        f"Baseline: Blackmagic Cloud observed **~{baseline_mbps:.0f} mb/s** "
        f"(unit ambiguous in the wild, so both readings are shown):",
        f"- if that means {baseline_mbps:.0f} **Mbps** (megabits/sec) -> **{baseline_mb_s_from_mbps:.1f} MB/s**",
        f"- if that means {baseline_mbps:.0f} **MB/s** (megabytes/sec) literally -> **{baseline_mb_s_literal:.1f} MB/s**",
        "",
    ]
    for letter, label in (("A", "video-originals up"), ("B", "proxies down"), ("C", "everything-else bidirectional")):
        lane_rows = [r for r in all_best if classify_lane(r.dataset, r.direction) == letter]
        winner = _winner(lane_rows)
        if winner is None:
            lines.append(f"- Lane {letter} ({label}): no data yet")
            continue
        beats_mbps = winner.MB_s > baseline_mb_s_from_mbps
        beats_literal = winner.MB_s > baseline_mb_s_literal
        verdict = (
            "beats both readings"
            if beats_mbps and beats_literal
            else "beats the Mbps reading only"
            if beats_mbps
            else "does NOT beat either reading"
        )
        lines.append(
            f"- Lane {letter} ({label}): best = **{winner.engine} @ {winner.MB_s:.1f} MB/s** -> {verdict}"
        )
    lines.append("")
    return "\n".join(lines)


def render_report(results: list[RunResult], baseline_mbps: float = DEFAULT_BASELINE_MBPS) -> str:
    best = best_per_combo(results)

    by_lane: dict[str, list[RunResult]] = defaultdict(list)
    for r in best:
        by_lane[classify_lane(r.dataset, r.direction)].append(r)

    parts = ["# ccbench results", ""]

    lane_labels = {
        "A": "video originals, editor -> NAS (up, large files)",
        "B": "proxies, NAS -> editor (down, large files)",
        "C": "everything else, bidirectional (small files)",
        "net": "raw network ceiling (iperf3)",
        "?": "unclassified",
    }
    for letter in ("A", "B", "C", "net", "?"):
        rows = by_lane.get(letter)
        if not rows:
            continue
        parts.append(f"## Lane {letter}: {lane_labels[letter]}")
        parts.append("")
        parts.append(_leaderboard_table(rows))
        parts.append("")

    parts.append("## Recommended per-lane config")
    parts.append("")
    parts.append(_recommend_lane("A", "video originals up (rclone SFTP/SMB, multi-stream)", by_lane.get("A", [])))
    parts.append(_recommend_lane("B", "proxies down (rclone SFTP/SMB, multi-stream)", by_lane.get("B", [])))
    parts.append(_recommend_lane("C", "everything else, bidirectional (Syncthing)", by_lane.get("C", [])))

    parts.append(_baseline_section(best, baseline_mbps))

    return "\n".join(parts) + "\n"


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("report", help="render a markdown report from results.jsonl")
    p.add_argument("--results", default="results/results.jsonl", help="path to results.jsonl")
    p.add_argument("--out", default="results/report.md", help="markdown output path")
    p.add_argument("--baseline-mbps", type=float, default=DEFAULT_BASELINE_MBPS)
    p.set_defaults(func=_cli_run)


def _cli_run(args: argparse.Namespace) -> int:
    results = read_results(Path(args.results))
    if not results:
        print(f"no results found at {args.results}")
        return 1
    report = render_report(results, baseline_mbps=args.baseline_mbps)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"wrote report -> {out_path}")
    print()
    print(report)
    return 0
