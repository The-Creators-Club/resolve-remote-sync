"""`broll-index` entry point. See SPEC.md "Indexer CLI contract"."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .claude_client import describe_auth
from .config import Config, load_config
from .duplicates import do_duplicates
from .manifest import do_export_manifest
from .migrate import migrate_sqlite_db
from .origins import record_originals
from .pipeline import run_pipeline
from .rebase import do_rebase
from .scanner import do_scan
from .sorter import do_sort
from .storage.base import Storage
from .storage.http_backend import HttpBackend
from .storage.sqlite_backend import SqliteBackend
from .taxonomy import apply_taxonomy_file, assign_categories, propose_taxonomy


def _resolve_source_path(cfg: Config, video: dict[str, Any]) -> Path | None:
    """Video row -> absolute source path, via config's share -> local root mapping.
    Returns None for a share not present in config (unknown/misconfigured)."""
    share_cfg = cfg.shares.get(video["share"])
    if share_cfg is None:
        return None
    return Path(share_cfg.root) / video["rel_path"]


def build_storage(cfg: Config) -> Storage:
    if cfg.db.mode == "sqlite":
        if not cfg.db.path:
            raise ValueError("db.path is required when db.mode == 'sqlite'")
        return SqliteBackend(cfg.db.path)
    if cfg.db.mode == "api":
        if not cfg.db.url:
            raise ValueError("db.url is required when db.mode == 'api'")
        return HttpBackend(cfg.db.url, cfg.db.token or "", cfg.local_state_db_path)
    raise ValueError(f"unknown db.mode: {cfg.db.mode!r} (expected 'sqlite' or 'api')")


def cmd_scan(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)
    # The share's own `source` mode decides which side of a proxy/original pair is
    # the archive copy. Read from config rather than taken as a CLI flag on purpose:
    # it must hold identically on every rescan, and a flag remembered wrong once
    # would index 403 GB of camera originals that were never meant to leave the
    # shoot drive.
    share_cfg = cfg.shares.get(args.share)
    source = share_cfg.source if share_cfg else "originals"
    exclude = share_cfg.exclude if share_cfg else []
    count = do_scan(
        storage, args.share, args.root, data_root=cfg.data_root, inbox=args.inbox,
        source=source, exclude=exclude, rehash=getattr(args, "rehash", False),
    )
    note = f", source={source}" if source != "originals" else ""
    if exclude:
        note += f", {len(exclude)} exclude pattern(s)"
    print(f"scan: upserted {count} video(s) from {args.root} (share={args.share}{note})")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)
    print(describe_auth(cfg.use_subscription))
    stages = args.stages.split(",") if args.stages else None
    stages = [s.strip() for s in stages] if stages else None
    count = run_pipeline(cfg, storage, model=args.model, limit=args.limit, stages=stages)
    print(f"run: processed {count} video(s)")
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Thin wrapper over `run --stages transcribe` (see SPEC.md's `transcribe` stage)."""
    cfg = load_config(args.config)
    storage = build_storage(cfg)
    count = run_pipeline(cfg, storage, model=cfg.model, limit=args.limit, stages=["transcribe"])
    print(f"transcribe: processed {count} video(s)")
    return 0


def cmd_taxonomy_propose(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)
    out_path = propose_taxonomy(storage, model=cfg.taxonomy_model, out_path=args.out)
    print(f"taxonomy propose: wrote {out_path}")
    return 0


def cmd_taxonomy_apply(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)
    categories = apply_taxonomy_file(storage, args.taxonomy_file)
    print(f"taxonomy apply: loaded {len(categories)} categories into the DB")
    return 0


def cmd_taxonomy_assign(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)
    r = assign_categories(storage, args.rules_file, dry_run=args.dry_run,
                          reassign=args.reassign)
    verb = "would assign" if args.dry_run else "assigned"
    print(f"taxonomy assign: {verb} {r['assigned']} of {r['videos_considered']} "
          f"video(s) across {r['categories']} categories "
          f"({r.get('by_fallback', 0)} via the fallback tier, "
          f"{r.get('by_path', 0)} by the interviewee path prior); "
          f"{r.get('kept', 0)} left where they already were; "
          f"{r['unmatched']} matched no rule")
    width = max((len(s) for s in r["per_category"]), default=10)
    for slug, n in sorted(r["per_category"].items(), key=lambda kv: -kv[1]):
        # Both numbers matter: `n` is what lands in the folder under one-home-
        # per-clip, `breadth` is how many clips mention the subject at all. A
        # large gap means the subject is usually somebody else's stronger match.
        print(f"  {slug:<{width}}  {n:>5}   (matches {r['breadth'].get(slug, 0)})")
    return 0


def cmd_origins(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)
    roots = {name: s.root for name, s in cfg.shares.items()}
    r = record_originals(storage, roots, verify=args.verify, dry_run=args.dry_run)
    verb = "would record" if args.dry_run else "recorded"
    print(f"origins: {verb} {r['resolved']} original path(s) of {r['rows']} row(s); "
          f"{r['unresolved']} unresolved")
    if args.verify:
        print(f"  verified on disk: {r['verified']}   not found right now: "
              f"{r['missing_on_disk']}")
    return 0


def cmd_sort(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)
    plan = do_sort(cfg, storage, dry_run=args.dry_run)
    verb = "would move" if args.dry_run else "moved"
    for entry in plan:
        print(f"{verb}: {entry['from']} -> {entry['to']}")
    print(f"sort: {len(plan)} video(s) {'planned' if args.dry_run else 'moved'}")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if cfg.db.mode != "sqlite":
        print(
            "migrate requires db.mode 'sqlite' — the ingest API owns its own database's "
            "schema and applies its own migrations on startup; run migrate against the "
            "co-located DB instead.",
            file=sys.stderr,
        )
        return 2
    if not cfg.db.path:
        raise ValueError("db.path is required when db.mode == 'sqlite'")
    report = migrate_sqlite_db(cfg.db.path)
    print(report)
    return 0


def cmd_rebase(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)

    if args.apply and cfg.db.mode != "sqlite":
        print(
            "rebase --apply requires db.mode 'sqlite' (the ingest API has no rename/delete "
            "endpoint). Run it against the co-located DB, then point the web app at it.",
            file=sys.stderr,
        )
        return 2

    plan, report = do_rebase(
        storage,
        to_share=args.to_share,
        root=args.root,
        data_root=cfg.data_root,
        dry_run=not args.apply,
        prune_duplicates=args.prune_duplicates,
    )

    out = Path(args.out)
    out.write_text(report, encoding="utf-8")
    print(report if args.verbose else plan.summary())
    print(f"\nrebase: full report written to {out}")
    if not args.apply:
        print("rebase: DRY RUN — nothing written. Re-run with --apply to commit.")
    return 0


def cmd_duplicates(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)

    if not args.verify:
        print(
            "!!! WARNING: --no-verify skips whole-file hash confirmation.\n"
            "!!! A false-positive partial-hash match will be marked duplicate and SKIPPED\n"
            "!!! when the archive is copied to the NAS — this can PERMANENTLY LOSE FOOTAGE.\n"
            "!!! Only proceed if you understand and accept that risk.",
            file=sys.stderr,
        )

    def resolve_path(video: dict[str, Any]) -> Path | None:
        return _resolve_source_path(cfg, video)

    plan, report = do_duplicates(storage, resolve_path=resolve_path, verify=args.verify, apply=args.apply)

    out = Path(args.out)
    out.write_text(report, encoding="utf-8")
    print(report if args.verbose else plan.summary())
    print(f"\nduplicates: full report written to {out}")
    if not args.apply:
        print("duplicates: DRY RUN — nothing written. Re-run with --apply to commit.")
    return 0


def cmd_export_manifest(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)

    def resolve_path(video: dict[str, Any]) -> Path | None:
        return _resolve_source_path(cfg, video)

    plan, content = do_export_manifest(storage, resolve_path=resolve_path, fmt=args.format)

    out = Path(args.out)
    out.write_text(content, encoding="utf-8")

    print(f"export-manifest: {plan.summary()}")
    if plan.unresolved:
        print(
            f"export-manifest: {len(plan.unresolved)} video(s) skipped — unknown share (not in config)",
            file=sys.stderr,
        )
    print(f"export-manifest: wrote {out} (format={args.format})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="broll-index")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="walk a share root, upsert discovered videos")
    p_scan.add_argument("--share", required=True)
    p_scan.add_argument("--root", required=True)
    p_scan.add_argument("--inbox", default=None, help="inbox subfolder (relative to --root)")
    p_scan.add_argument("--rehash", action="store_true",
                        help="re-read every known file's head/tail instead of trusting "
                             "its stored hash when the size is unchanged (see do_scan)")
    p_scan.set_defaults(func=cmd_scan)

    p_run = sub.add_parser("run", help="drain the job queue through probe/proxy/frames/claude")
    p_run.add_argument("--model", default=None, choices=["haiku", "sonnet", "fable"])
    p_run.add_argument("--limit", type=int, default=None)
    p_run.add_argument("--stages", default=None, help="comma-separated: probe,proxy,frames,transcribe,claude,embed")
    p_run.set_defaults(func=cmd_run)

    p_transcribe = sub.add_parser(
        "transcribe", help="convenience wrapper over `run --stages transcribe`"
    )
    p_transcribe.add_argument("--limit", type=int, default=None)
    p_transcribe.set_defaults(func=cmd_transcribe)

    p_taxonomy = sub.add_parser("taxonomy", help="taxonomy propose/apply")
    taxonomy_sub = p_taxonomy.add_subparsers(dest="taxonomy_command", required=True)

    p_propose = taxonomy_sub.add_parser("propose", help="cluster themes, write taxonomy_proposal.md")
    p_propose.add_argument("--out", default="taxonomy_proposal.md")
    p_propose.set_defaults(func=cmd_taxonomy_propose)

    p_apply = taxonomy_sub.add_parser("apply", help="load approved taxonomy.yaml into categories")
    p_apply.add_argument("taxonomy_file")
    p_apply.set_defaults(func=cmd_taxonomy_apply)

    p_assign = taxonomy_sub.add_parser(
        "assign", help="assign each indexed video its single best category from match rules")
    p_assign.add_argument("rules_file", help="e.g. taxonomy.rules.yaml")
    p_assign.add_argument("--dry-run", action="store_true")
    p_assign.add_argument(
        "--reassign", action="store_true",
        help="also re-file clips that already have a category. This MOVES files in "
             "the shared archive and invalidates stored archive paths, so anything "
             "already cut with them must be relinked. Off by default.")
    p_assign.set_defaults(func=cmd_taxonomy_assign)

    p_origins = sub.add_parser(
        "origins", help="record where each clip's TRUE original lives")
    p_origins.add_argument("--verify", action="store_true",
                           help="stat each path and stamp the ones that exist now")
    p_origins.add_argument("--dry-run", action="store_true")
    p_origins.set_defaults(func=cmd_origins)

    p_sort = sub.add_parser("sort", help="move indexed inbox clips into their category folder")
    p_sort.add_argument("--dry-run", action="store_true")
    p_sort.set_defaults(func=cmd_sort)

    p_migrate = sub.add_parser(
        "migrate", help="apply pending schema migrations to the configured sqlite DB"
    )
    p_migrate.set_defaults(func=cmd_migrate)

    p_rebase = sub.add_parser(
        "rebase",
        help="re-point an existing index at a new storage root, matching by content hash",
    )
    p_rebase.add_argument("--to-share", required=True, help="share name files now live under")
    p_rebase.add_argument("--root", required=True, help="new (consolidated) share root")
    p_rebase.add_argument("--apply", action="store_true", help="commit changes (default: dry run)")
    p_rebase.add_argument(
        "--prune-duplicates",
        action="store_true",
        help="with --apply, delete index rows superseded by a duplicate",
    )
    p_rebase.add_argument("--out", default="rebase_report.md")
    p_rebase.add_argument("--verbose", action="store_true", help="print the full report")
    p_rebase.set_defaults(func=cmd_rebase)

    p_duplicates = sub.add_parser(
        "duplicates",
        help="find clips that already exist elsewhere in the index and mark duplicate_of",
    )
    p_duplicates.add_argument(
        "--verify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="confirm partial-hash candidates with a whole-file hash before marking "
        "(default: on; --no-verify is faster but risks false positives, which lose "
        "footage on copy — see SPEC.md)",
    )
    p_duplicates.add_argument("--apply", action="store_true", help="commit changes (default: dry run)")
    p_duplicates.add_argument("--out", default="duplicates_report.md")
    p_duplicates.add_argument("--verbose", action="store_true", help="print the full report")
    p_duplicates.set_defaults(func=cmd_duplicates)

    p_manifest = sub.add_parser(
        "export-manifest",
        help="write the set of files to copy to the NAS (every video except confirmed duplicates)",
    )
    p_manifest.add_argument("--out", required=True)
    p_manifest.add_argument("--format", choices=["list", "robocopy", "rsync"], default="list")
    p_manifest.set_defaults(func=cmd_export_manifest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
