"""`broll-index` entry point. See SPEC.md "Indexer CLI contract"."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import local_models, local_runtime
from .claude_client import describe_auth
from .config import Config, ConfigError, load_config
from .dashboard_site import dashboard_url_from_config, resolve_model_tier
from .duplicates import do_duplicates
from .manifest import do_export_manifest
from .migrate import migrate_sqlite_db
from .origins import record_originals
from .pipeline import run_pipeline
from .rebase import do_rebase
from .scanner import do_scan
from .site_data import DEFAULT_DUPLICATES_REPORT
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
    if cfg.indexer.backend == "local":
        # CLI --tier > config.yaml indexer.model_tier > dashboard manifest >
        # default "good" (dashboard_site.resolve_model_tier).
        cfg.indexer.model_tier = resolve_model_tier(cfg, getattr(args, "tier", None))
        t = local_models.tier(cfg.indexer.model_tier)
        print(f"backend: local — {t.label} ({t.vram_note})")
    else:
        print(describe_auth(cfg.anthropic))
    storage = build_storage(cfg)
    stages = args.stages.split(",") if args.stages else None
    stages = [s.strip() for s in stages] if stages else None
    count = run_pipeline(cfg, storage, model=args.model, limit=args.limit, stages=stages)
    print(f"run: processed {count} video(s)")
    return 0


def cmd_models_pull(args: argparse.Namespace) -> int:
    """Download the pinned llama.cpp runtime + one tier's GGUF weights into
    `indexer.local_cache_dir` (see local_runtime.py). Safe to re-run: a file
    already present with the correct sha256 is not re-fetched."""
    cfg = load_config(args.config)
    tier_key = (args.tier or resolve_model_tier(cfg, None)).strip().lower()
    try:
        local_models.tier(tier_key)
    except ValueError as e:
        print(f"models pull: {e}", file=sys.stderr)
        return 2

    gpu = local_runtime.probe_gpu()
    try:
        local_runtime.refuse_if_tier_unfit(tier_key, gpu, force=args.force)
    except local_runtime.LocalRuntimeError as e:
        print(f"models pull: {e}", file=sys.stderr)
        return 2

    cache_dir = Path(cfg.indexer.local_cache_dir) if cfg.indexer.local_cache_dir \
        else local_runtime.default_cache_dir()
    print(f"models pull: fetching the {local_models.TIERS[tier_key].label} tier into {cache_dir}")
    exe = local_runtime.ensure_runtime(cache_dir)
    weights, mmproj = local_runtime.ensure_model(cache_dir, tier_key)
    print(f"models pull: runtime  {exe}")
    print(f"models pull: weights  {weights}")
    print(f"models pull: mmproj   {mmproj}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report GPU/tier/runtime/model state for the local backend — the first
    thing to run when 'the local backend won't start' comes up."""
    cfg = load_config(args.config)
    print(f"backend configured: {cfg.indexer.backend}")

    gpu = local_runtime.probe_gpu()
    if gpu.present and gpu.vram_gb:
        kind = "unified memory" if gpu.is_apple_silicon else "VRAM"
        print(f"GPU: {gpu.name or '(unnamed)'} — {gpu.vram_gb:.1f} GB {kind} ({gpu.detail})")
    else:
        print(f"GPU: none detected ({gpu.detail})")
    recommended = local_runtime.recommend_tier(gpu)
    print(f"recommended tier: {recommended or 'none — search-only, or backend: anthropic'}")

    tier_key = resolve_model_tier(cfg, None)
    t = local_models.tier(tier_key)
    print(f"configured tier (resolved: CLI > config.yaml > dashboard manifest > default): "
          f"{tier_key} — {t.label}")

    cache_dir = Path(cfg.indexer.local_cache_dir) if cfg.indexer.local_cache_dir \
        else local_runtime.default_cache_dir()
    print(f"local_cache_dir: {cache_dir}")

    exe_path = Path(cfg.indexer.llama_server_path) if cfg.indexer.llama_server_path \
        else local_runtime.server_path(cache_dir)
    present = exe_path.is_file()
    print(f"llama-server: {exe_path} "
          f"({'present' if present else 'NOT downloaded yet — run `broll-index models pull`'})")
    if present:
        version = local_runtime.llama_server_version(exe_path)
        if version:
            print(f"llama-server reports: {version}")

    weights, mmproj = local_runtime.model_paths(cache_dir, t)
    for label, p in (("weights", weights), ("mmproj", mmproj)):
        print(f"{label}: {p} ({'present' if p.is_file() else 'NOT downloaded yet'})")

    dash_url = dashboard_url_from_config(cfg)
    print(f"dashboard manifest URL: {dash_url or '(none configured or derivable from db.url)'}")
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Thin wrapper over `run --stages transcribe` (see SPEC.md's `transcribe` stage)."""
    cfg = load_config(args.config)
    # Inside a `run`, an unconfigured whisper environment is a stage that skips;
    # asked for BY NAME it is a refusal, or the operator reads "processed 12
    # video(s)" and believes 12 transcripts exist (2026-08-17, item 14).
    if cfg.whisper.enabled:
        try:
            cfg.require_whisper()
        except ConfigError as exc:
            print(f"transcribe: {exc}", file=sys.stderr)
            return 2
    storage = build_storage(cfg)
    count = run_pipeline(cfg, storage, model=cfg.model, limit=args.limit, stages=["transcribe"])
    print(f"transcribe: processed {count} video(s)")
    return 0


def cmd_taxonomy_propose(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    storage = build_storage(cfg)
    out_path = propose_taxonomy(storage, model=cfg.taxonomy_model, out_path=args.out,
                                settings=cfg.anthropic)
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
    # The default now lives under the git-ignored private/ tree, which a fresh
    # checkout does not have (2026-08-17); creating it beats failing after the
    # whole-file verification pass has already run.
    out.parent.mkdir(parents=True, exist_ok=True)
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
    p_run.add_argument("--tier", default=None, choices=list(local_models.VALID_TIERS),
                       help="local backend only: overrides indexer.model_tier / the dashboard "
                            "manifest for this run (see dashboard_site.resolve_model_tier)")
    p_run.set_defaults(func=cmd_run)

    p_models = sub.add_parser("models", help="local-backend model/runtime management")
    models_sub = p_models.add_subparsers(dest="models_command", required=True)
    p_models_pull = models_sub.add_parser(
        "pull", help="download the pinned llama.cpp runtime + one tier's GGUF weights")
    p_models_pull.add_argument("--tier", default=None, choices=list(local_models.VALID_TIERS))
    p_models_pull.add_argument("--force", action="store_true",
                               help="pull even if this machine's GPU looks too small for the tier")
    p_models_pull.set_defaults(func=cmd_models_pull)

    p_doctor = sub.add_parser(
        "doctor", help="report GPU / tier / runtime / model state for the local backend")
    p_doctor.set_defaults(func=cmd_doctor)

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
    # The report names every duplicated file, so it is the site's catalogue in
    # list form and must not land in the tracked tree (2026-08-17,
    # COMMERCIAL_READINESS.md item 10 / section B).
    p_duplicates.add_argument("--out", default=DEFAULT_DUPLICATES_REPORT)
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
