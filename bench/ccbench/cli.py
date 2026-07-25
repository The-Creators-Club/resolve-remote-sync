"""ccbench CLI entry point.

    ccbench dataset --out DIR --profile large|small|both
    ccbench run --config bench.toml [--rerun] [--engines e1,e2] [--lanes A,B,C]
    ccbench report --results results/results.jsonl --out results/report.md
    ccbench selftest [--workspace DIR] [--keep]
    ccbench tailscale-check --peer HOST_OR_IP
"""

from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ccbench", description="Sync-transport benchmark harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Imported lazily-ish (still module-level, but grouped here) to keep
    # `ccbench --help` fast and keep each subcommand's argparse wiring next
    # to its implementation.
    from ccbench import dataset, matrix, report, selftest

    dataset.add_subparser(subparsers)
    matrix.add_subparser(subparsers)
    report.add_subparser(subparsers)
    selftest.add_subparser(subparsers)
    _add_tailscale_check_subparser(subparsers)

    return parser


def _add_tailscale_check_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "tailscale-check",
        help="check whether the Tailscale path to a peer is direct or DERP-relayed",
    )
    p.add_argument("--peer", required=True, help="peer hostname, DNS name, node key, or Tailscale IP")

    def _run(args: argparse.Namespace) -> int:
        from ccbench.runners.iperf3 import check_tailscale_path, describe_tailscale_path

        result = check_tailscale_path(args.peer)
        if not result.get("found"):
            print(f"peer {args.peer!r} not found in `tailscale status --json` "
                  f"({result.get('reason', 'is tailscale running/authenticated?')})")
            return 1
        # direct/relayed is decided by CurAddr; Relay is the home DERP region
        # and is populated even on a direct connection.
        print(
            f"peer={result['hostname'] or result['peer_key']} "
            f"path={describe_tailscale_path(result)} "
            f"cur_addr={result.get('cur_addr') or '(none)'} relay={result.get('relay') or '(none)'}"
        )
        return 0 if result["direct"] else 2

    p.set_defaults(func=_run)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
