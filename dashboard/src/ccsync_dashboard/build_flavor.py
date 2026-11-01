"""Which flavour of this build runs: the vendor/customer build or the studio's.

GL-31 (reshaped by the owner 2026-10-07, ledger CR-374, docs/
PRELAUNCH_REVIEW_2026-10-06.md Track B "GL-45 AI billing"): ONE codebase, one
image. The Claude Code and Codex CLI providers, their SET UP wizard and its
subscription sign-in relay, the CLI auto-update and the CLI-only triage agent
all drive a PERSONAL subscription, which a customer's service may not do
(COM-H1). They stay in the tree for the studio's own dashboard, and the
vendor build HARD-DISABLES them.

"Hard" means no site setting, Settings checkbox, API call, notice acceptance
or `site.toml [features]` line can turn them on: `site_store.feature_enabled`
asks `cli_feature_locked()` BEFORE it looks at any row, so a stored
`features.ai_cli_providers = 1` is inert on a locked build.

The one switch is a process environment variable, `DASH_STUDIO_CLI_PROVIDERS`,
that exists only in the deploy (the container's env), never in the database,
the manifest, an API response or a settings page. The vendor build's default
is absent, i.e. LOCKED. The studio sets it from its OWN `site.toml`:

    [studio]
    allow_cli_providers = true

which `server/install_dashboard_app.py` projects into the env var. The
studio's existing site must carry that line before the first deploy of this
change, or its CLI providers (and triage) go dark on that deploy; see
docs/STUDIO_BUILD.md. A customer who edits their own deploy env defeats it,
which is accepted: the lock is about what we ship and default, and the
customer terms say the same (a contract, not DRM).
"""
from __future__ import annotations

import os

ENV_VAR = "DASH_STUDIO_CLI_PROVIDERS"

# The `[features]` flags that only mean something with a CLI behind them.
CLI_FEATURES = frozenset({"ai_cli_providers", "ai_cli_auto_update"})

LOCKED_DETAIL = ("Claude Code and Codex are not available in this build. "
                 "Use an API key (Claude API, OpenAI or DeepSeek).")


def studio_cli_allowed() -> bool:
    """True only when the deploy opted the studio's own flavour in."""
    return os.environ.get(ENV_VAR, "").strip() == "1"


def cli_feature_locked(name: str) -> bool:
    """Whether `[features] <name>` is forced off by the build."""
    return str(name or "").strip() in CLI_FEATURES and not studio_cli_allowed()


def cli_build_locked() -> bool:
    return not studio_cli_allowed()


def stranded_cli_rows(conn) -> bool:
    """A locked build over a site that stored `features.ai_cli_providers = 1`:
    the signature of a studio container that lost the env var (CR-374
    overseer, 2026-10-07)."""
    if not cli_build_locked():
        return False
    row = conn.execute("SELECT value FROM site_settings WHERE key = ?",
                       ("features.ai_cli_providers",)).fetchone()
    return row is not None and str(row[0]).strip() == "1"
