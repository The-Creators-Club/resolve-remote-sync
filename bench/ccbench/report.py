"""Turn results/results.jsonl into a markdown report:
- a leaderboard table per lane (engine x params, **median** MB/s across
  repeats with min/max and repeat count alongside, verified, loopback)
- a "recommended per-lane config" section (lane A: up/large, lane B: down/large,
  lane C: bidirectional/small) with the exact flag set to use
- a "did we beat Resolve Cloud" section against a configurable baseline,
  shown both as Mbps and MB/s since the ~60 unit Blackmagic quotes is ambiguous

Three rules this module now follows, because a benchmark that breaks them
picks the wrong winner:

1. **Median, not max.** Best-of-N rewards the run that got lucky with a warm
   cache. The median of the repeats is reported; min/max are kept as columns
   so a wide spread is visible instead of hidden.
2. **The lane is whatever the run recorded.** `RunResult.lane` is written by
   matrix.py from bench.toml. `classify_lane()` survives only as a fallback
   for legacy rows written before the lane was carried.
3. **Loopback rows are not comparable.** A syncthing pair on 127.0.0.1 (or an
   rclone `local_test_dir` selftest run) measures local disk, not the network.
   Those rows are flagged in a `Loopback` column and are never chosen as a
   lane winner while any real-network row exists.

Units: `MB_s` everywhere is decimal MB/s (bytes / 1e6 / s), so 60 Mbps is
exactly 7.5 MB/s.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ccbench.result import RunResult, read_results

DEFAULT_BASELINE_MBPS = 60.0  # "beat Blackmagic Cloud's observed ~60 mb/s"


def classify_lane(dataset: str, direction: str) -> str:
    """LEGACY fallback only: map a (dataset, direction) pair to a lane letter
    for rows written before matrix.py carried the lane explicitly. Matches on
    substring, which is exactly why it is no longer the primary path -- see
    `lane_of()`."""
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


def lane_of(result: RunResult) -> str:
    """The lane this run belongs to: what the run recorded, falling back to
    dataset-name classification only for legacy rows with no lane."""
    lane = (result.lane or "").strip()
    if lane:
        return lane
    return classify_lane(result.dataset, result.direction)


def combo_key_no_repeat(r: RunResult) -> tuple:
    return (r.engine, lane_of(r), r.direction, r.dataset, json.dumps(r.params, sort_keys=True))


@dataclass
class ComboSummary:
    """Repeats of one (engine, lane, direction, dataset, params) combo,
    collapsed to a median with the spread kept visible."""

    row: RunResult  # the repeat closest to the median (or a failed representative)
    median_mb_s: float
    min_mb_s: float
    max_mb_s: float
    n_ok: int
    n_total: int
    verified: bool  # every ok repeat verified
    loopback: bool

    @property
    def engine(self) -> str:
        return self.row.engine

    @property
    def direction(self) -> str:
        return self.row.direction

    @property
    def dataset(self) -> str:
        return self.row.dataset

    @property
    def params(self) -> dict[str, Any]:
        return self.row.params

    @property
    def lane(self) -> str:
        return lane_of(self.row)

    @property
    def ok(self) -> bool:
        return self.n_ok > 0

    @property
    def skipped(self) -> bool:
        return self.row.skipped

    @property
    def reason(self) -> str:
        return self.row.reason


def summarize_repeats(results: list[RunResult]) -> list[ComboSummary]:
    """Collapse repeats to one median-based summary per combo."""
    groups: dict[tuple, list[RunResult]] = defaultdict(list)
    for r in results:
        groups[combo_key_no_repeat(r)].append(r)

    summaries: list[ComboSummary] = []
    for _key, rows in groups.items():
        ok_rows = [r for r in rows if r.ok]
        if not ok_rows:
            rep = rows[0]  # keep one representative failed/skipped row
            summaries.append(
                ComboSummary(
                    row=rep, median_mb_s=0.0, min_mb_s=0.0, max_mb_s=0.0,
                    n_ok=0, n_total=len(rows), verified=False,
                    loopback=any(r.loopback for r in rows),
                )
            )
            continue
        speeds = [r.MB_s for r in ok_rows]
        median = statistics.median(speeds)
        representative = min(ok_rows, key=lambda r: abs(r.MB_s - median))
        summaries.append(
            ComboSummary(
                row=representative,
                median_mb_s=median,
                min_mb_s=min(speeds),
                max_mb_s=max(speeds),
                n_ok=len(ok_rows),
                n_total=len(rows),
                verified=all(r.verified for r in ok_rows),
                loopback=any(r.loopback for r in ok_rows),
            )
        )
    return summaries


def _fmt_params(params: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(params.items())) or "-"


def _rclone_flags(params: dict[str, Any]) -> str:
    """The exact rclone flags that reproduce a measured run.

    Every swept value is emitted explicitly, including zeros. A falsy value is
    not "unset": `--multi-thread-streams 0` disables multi-threading, whereas
    *omitting* the flag selects rclone's default of 4. Dropping a zero here
    would print a recommendation for a config this benchmark never ran, and
    quite possibly the one it measured as slower.
    """
    flags = [f"--transfers {params.get('transfers', 4)}"]
    if "multi_thread_streams" in params:
        flags.append(f"--multi-thread-streams {params['multi_thread_streams']}")
    if "sftp_chunk_size_kib" in params:
        flags.append(f"--sftp-chunk-size {params['sftp_chunk_size_kib']}Ki")
    elif "sftp_chunk_size_mb" in params:
        # Legacy row from before the unit fix: the sweep was in megabytes,
        # which SFTP (256 KiB max packet) cannot honour. Show it, flag it.
        flags.append(
            f"--sftp-chunk-size {params['sftp_chunk_size_mb']}M "
            f"(LEGACY MB unit -- invalid for SFTP, re-run with sftp_chunk_size_kib)"
        )
    return " ".join(flags)


def _leaderboard_table(summaries: list[ComboSummary]) -> str:
    header = (
        "| Engine | Direction | Dataset | Params | median MB/s | min | max | n | "
        "Verified (how) | Bytes from | Loopback | Notes |\n"
    )
    header += "|---|---|---|---|---:|---:|---:|---:|---|---|---|---|\n"
    lines = [header.rstrip("\n")]
    rows_sorted = sorted(summaries, key=lambda s: s.median_mb_s, reverse=True)
    for s in rows_sorted:
        if s.skipped and not s.ok:
            notes = f"skipped: {s.reason}"
        elif not s.ok:
            notes = f"FAILED: {s.reason}"
        else:
            notes = s.reason
        verified = f"{'yes' if s.verified else 'no'} ({s.row.verify_method or 'n/a'})"
        lines.append(
            f"| {s.engine} | {s.direction} | {s.dataset} | {_fmt_params(s.params)} | "
            f"{s.median_mb_s:.1f} | {s.min_mb_s:.1f} | {s.max_mb_s:.1f} | {s.n_ok}/{s.n_total} | "
            f"{verified} | {s.row.bytes_source} | {'YES -- not comparable' if s.loopback else 'no'} | "
            f"{notes} |"
        )
    return "\n".join(lines)


def _winner(summaries: list[ComboSummary]) -> ComboSummary | None:
    """Highest median MB/s. Loopback rows only win if nothing else ran, and
    verified rows are preferred over unverified ones."""
    candidates = [s for s in summaries if s.ok]
    if not candidates:
        return None
    comparable = [s for s in candidates if not s.loopback] or candidates
    verified_candidates = [s for s in comparable if s.verified]
    pool = verified_candidates or comparable
    return max(pool, key=lambda s: s.median_mb_s)


def _recommend_lane(letter: str, label: str, summaries: list[ComboSummary]) -> str:
    lines = [f"### Lane {letter}: {label}", ""]
    winner = _winner(summaries)
    if winner is None:
        lines.append("No successful runs recorded for this lane yet.")
        return "\n".join(lines)

    caveats = []
    if not winner.verified:
        caveats.append("NOT independently verified")
    else:
        caveats.append(f"verified via {winner.row.verify_method}")
    if winner.loopback:
        caveats.append("**LOOPBACK measurement -- not comparable with network runs**")
    if winner.row.bytes_source.endswith("fallback"):
        caveats.append("byte count fell back to the dataset manifest (upper bound, not measured)")

    lines.append(
        f"**Winner: `{winner.engine}`** at **{winner.median_mb_s:.1f} MB/s median** "
        f"(min {winner.min_mb_s:.1f} / max {winner.max_mb_s:.1f} over {winner.n_ok} repeat(s); "
        + "; ".join(caveats) + ")."
    )
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


def _baseline_section(all_summaries: list[ComboSummary], baseline_mbps: float) -> str:
    baseline_mb_s_from_mbps = baseline_mbps / 8.0  # Mbps -> MB/s (both decimal)
    baseline_mb_s_literal = baseline_mbps  # in case "60 mb/s" was actually meant as MB/s

    lines = [
        "## Did we beat Resolve Cloud?",
        "",
        f"Baseline: Blackmagic Cloud observed **~{baseline_mbps:.0f} mb/s** "
        f"(unit ambiguous in the wild, so both readings are shown):",
        f"- if that means {baseline_mbps:.0f} **Mbps** (megabits/sec) -> **{baseline_mb_s_from_mbps:.1f} MB/s**",
        f"- if that means {baseline_mbps:.0f} **MB/s** (megabytes/sec) literally -> **{baseline_mb_s_literal:.1f} MB/s**",
        "",
        "All MB/s figures are medians of the repeats, in decimal MB (bytes / 1e6).",
        "",
    ]
    for letter, label in (("A", "video-originals up"), ("B", "proxies down"), ("C", "everything-else bidirectional")):
        lane_rows = [s for s in all_summaries if s.lane == letter]
        winner = _winner(lane_rows)
        if winner is None:
            lines.append(f"- Lane {letter} ({label}): no data yet")
            continue
        beats_mbps = winner.median_mb_s > baseline_mb_s_from_mbps
        beats_literal = winner.median_mb_s > baseline_mb_s_literal
        verdict = (
            "beats both readings"
            if beats_mbps and beats_literal
            else "beats the Mbps reading only"
            if beats_mbps
            else "does NOT beat either reading"
        )
        loopback_note = " **(loopback only -- not a real-network result)**" if winner.loopback else ""
        lines.append(
            f"- Lane {letter} ({label}): best = **{winner.engine} @ {winner.median_mb_s:.1f} MB/s "
            f"median** -> {verdict}{loopback_note}"
        )
    lines.append("")
    return "\n".join(lines)


def render_report(results: list[RunResult], baseline_mbps: float = DEFAULT_BASELINE_MBPS) -> str:
    summaries = summarize_repeats(results)

    by_lane: dict[str, list[ComboSummary]] = defaultdict(list)
    for s in summaries:
        by_lane[s.lane].append(s)

    parts = ["# ccbench results", ""]

    lane_labels = {
        "A": "video originals, editor -> NAS (up, large files)",
        "B": "proxies, NAS -> editor (down, large files)",
        "C": "everything else, bidirectional (small files)",
        "net": "raw network ceiling (iperf3)",
        "?": "unclassified",
    }
    for letter in sorted(by_lane, key=lambda k: (["A", "B", "C", "net", "?"].index(k) if k in lane_labels else 99, k)):
        rows = by_lane.get(letter)
        if not rows:
            continue
        parts.append(f"## Lane {letter}: {lane_labels.get(letter, letter)}")
        parts.append("")
        parts.append(_leaderboard_table(rows))
        parts.append("")

    parts.append("## Recommended per-lane config")
    parts.append("")
    parts.append(_recommend_lane("A", "video originals up (rclone SFTP/SMB, multi-stream)", by_lane.get("A", [])))
    parts.append(_recommend_lane("B", "proxies down (rclone SFTP/SMB, multi-stream)", by_lane.get("B", [])))
    parts.append(_recommend_lane("C", "everything else, bidirectional (Syncthing)", by_lane.get("C", [])))

    parts.append(_baseline_section(summaries, baseline_mbps))

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
