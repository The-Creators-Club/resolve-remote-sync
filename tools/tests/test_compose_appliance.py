"""Structural checks for dashboard/deploy/compose.appliance.yaml.

ZERO_TOUCH_PLAN.md WP A. This is the file a customer pastes verbatim into
Container Manager / TrueNAS "Install via YAML" -- docs/APPLIANCE_INSTALL.md
walks the paste-and-click path this file is the other half of. There is no
render step for it (unlike compose.yaml/compose.image.yaml, which
server/install_dashboard_app.py fills `{{ }}` placeholders into): what is
committed IS what gets pasted, so these checks read the committed text
directly rather than a rendered copy.

NO YAML PARSER ON PURPOSE. `dashboard/.venv` (the interpreter CLAUDE.md says
to run this suite with) carries no PyYAML -- dashboard/requirements.lock has
never needed one -- so this is regex/text scanning against the raw file, the
same approach the file's own top-of-file comment already uses to reason
about compose-go v1.16.0's schema. A parser would catch more; it would also
be a new dependency for one test file, and the specific facts this suite
cares about (every service present, no REPLACE_ME, no stray host port, every
image pinned, and exactly two required variables) are all things a handful
of regexes state precisely enough.

Run:  cd tools; ..\\dashboard\\.venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "dashboard" / "deploy" / "compose.appliance.yaml"


@pytest.fixture(scope="module")
def text() -> str:
    if not COMPOSE.exists():
        pytest.skip(f"{COMPOSE} does not exist")
    return COMPOSE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def code(text: str) -> str:
    """`text` with every standalone `#...` comment line blanked out.

    This file is deliberately over-commented (it is the thing a customer
    pastes without reading anything else first), and the prose explains what
    is NOT here -- "no REPLACE_ME", "`${CCSYNC_DATA}` is where the dashboard
    writes secrets", "no `network_mode: service:tailscale` on the dashboard
    itself" -- by naming exactly the strings the structural checks below
    look for. Scanning the raw text would make every one of those sentences
    a false positive; this is what compose.appliance.yaml has no comment
    lines mixing code and prose on the same line, verified once at the
    bottom of this module (`test_no_line_mixes_a_directive_with_a_comment`),
    which is what makes stripping whole lines safe rather than approximate.
    """
    return "\n".join(
        "" if line.lstrip().startswith("#") else line
        for line in text.splitlines()
    )


# A service's own top-level YAML key: two spaces of indent, the name, a
# colon. Matches "  dashboard:" but not "    image: ..." (four spaces) or a
# comment mentioning the word "dashboard" in prose.
def _service_names(text: str) -> set[str]:
    in_services = False
    names: set[str] = set()
    for line in text.splitlines():
        if re.match(r"^services:\s*$", line):
            in_services = True
            continue
        if in_services:
            if re.match(r"^\S", line):  # dedented back to top level -- done
                break
            m = re.match(r"^  ([a-zA-Z0-9_-]+):\s*$", line)
            if m:
                names.add(m.group(1))
    return names


def test_every_service_is_present(text: str):
    # secrets-init is this file's own answer to "syncthing and the sftp
    # sidecar need a .env file that is GUARANTEED to exist" -- see the
    # compose-version note at the top of the file for why it exists instead
    # of `env_file: required: false`.
    assert _service_names(text) == {
        "secrets-init", "dashboard", "syncthing", "sftp", "tailscale",
    }


def test_no_replace_me_anywhere(code: str):
    # The customer never sees a secret on this path (ZERO_TOUCH_PLAN.md
    # 3.2) -- unlike compose.yaml/compose.image.yaml, which still ask an
    # operator to hand-fill SYNCTHING_API_KEY et al. A REPLACE_ME here would
    # mean this file quietly regressed to that older shape. (The prose
    # ABOVE the services block is allowed to explain this in words --
    # `code` has already blanked every comment line before this runs.)
    assert "REPLACE_ME" not in code


def test_only_the_loopback_dashboard_port_is_published(code: str):
    # Every `- "<addr>:<host>:<container>"` line anywhere under a `ports:`
    # key. sidecar services (syncthing, sftp, tailscale) must have NO
    # `ports:` key at all -- they are only reachable over the tailnet node's
    # own namespace (network_mode: service:tailscale) or, for tailscale
    # itself, via Serve, never a published host port.
    bindings = re.findall(r'^\s*-\s*"([0-9.]+:\d+:\d+(?:/(?:tcp|udp))?)"\s*$',
                          code, re.MULTILINE)
    assert bindings == ["127.0.0.1:8480:8480"], (
        f"expected exactly the dashboard's loopback bind, got {bindings}")


def test_every_image_is_pinned(code: str):
    image_lines = re.findall(r'^\s*image:\s*"?([^"\n]+)"?\s*$', code, re.MULTILINE)
    # secrets-init, dashboard (both `ccsync`), syncthing, sftp, tailscale.
    assert len(image_lines) == 5, f"expected 5 image: lines, found {image_lines}"
    for image in image_lines:
        assert not image.endswith(":latest"), f"{image!r} is not pinned"
        # Every reference carries EITHER a `:tag` or an `@sha256:` digest
        # after the repository path -- bare `ghcr.io/x/y` with nothing after
        # it would resolve to `:latest` implicitly, which is exactly what
        # this check exists to catch.
        assert re.search(r":[A-Za-z0-9._-]+$", image) or "@sha256:" in image, (
            f"{image!r} has no tag or digest")


def test_ccsync_tree_and_ccsync_data_are_the_only_required_variables(code: str):
    # Every `${VAR...}` reference in the file. CCSYNC_TREE/CCSYNC_DATA must
    # use the `:?` (fail loudly if unset) form; every other variable must
    # carry a `:-default` -- ZERO_TOUCH_PLAN.md's "exactly two things to
    # fill in" is a promise this test enforces mechanically, not just in
    # the comment above the services block.
    refs = re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:[?-][^}]*)?\}", code)
    assert refs, "no ${VAR} references found at all -- did the file change shape?"
    seen_required = set()
    for name, qualifier in refs:
        if name in ("CCSYNC_TREE", "CCSYNC_DATA"):
            assert qualifier.startswith(":?"), (
                f"{name} must use the := required form ({name}{qualifier!r} does not)")
            seen_required.add(name)
        else:
            assert qualifier.startswith(":-"), (
                f"{name} must carry a :-default (found {name}{qualifier!r}) -- "
                f"only CCSYNC_TREE and CCSYNC_DATA are allowed to be required")
    assert seen_required == {"CCSYNC_TREE", "CCSYNC_DATA"}


def test_sidecars_share_the_tailscale_network_namespace(code: str):
    # The whole point of the sidecar shape (ZERO_TOUCH_PLAN.md 3.1): no host
    # port for lane A/B or lane C, ever -- they ride on the tailnet node's
    # own namespace instead. Exactly syncthing and sftp -- not the
    # dashboard, which stays on the default compose network so `tailscale`
    # (a separate container, not sharing ITS namespace) can reach it by
    # service name, and not `tailscale` itself, which IS the namespace.
    assert code.count("network_mode: service:tailscale") == 2


def test_no_line_mixes_a_directive_with_a_comment(text: str):
    # What makes the `code` fixture's whole-line comment stripping SAFE
    # rather than approximate: if every comment in this file starts its own
    # line, blanking lines that start with `#` cannot accidentally eat a
    # real directive that merely trails one.
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or "#" not in line:
            continue
        pytest.fail(f"line mixes code and a trailing comment: {line!r}")


def test_no_cr_in_the_file(text: str):
    # .gitattributes forces LF on every dashboard/deploy/*.yaml -- see that
    # file's own comment for the incident that made this a gate rather than
    # a nice-to-have. Byte-scanning here (not relying on git) means this
    # test fails on a bad EDIT even before it is committed.
    assert "\r" not in text


def test_no_docker_socket_is_mounted(text: str):
    # ZERO_TOUCH_PLAN.md section 5: "No Docker socket, no self-recreate."
    # The stack cannot become root on the NAS host if the dashboard is ever
    # compromised -- a docker.sock bind mount anywhere in this file would
    # quietly take that property away.
    assert "docker.sock" not in text


# ---------------------------------------------------------- the Serve switch
# MOBILE_PLAN.md M6 (2026-08-30): the phone port needs an https origin, and
# `deploy/tailscale/serve.json` is where TLS-on-443 -> dashboard:8480 is
# written down. It is wired in OFF: these three tests are what "off by
# default" means mechanically, because a `TS_SERVE_CONFIG` that ever grew a
# non-empty default would hand every customer's node a Serve config nobody
# asked for on the next `docker compose pull`.

SERVE_JSON = REPO / "dashboard" / "deploy" / "tailscale" / "serve.json"


def test_the_serve_config_exists_and_proxies_to_the_dashboard_service():
    import json
    assert SERVE_JSON.exists(), f"{SERVE_JSON} is missing"
    doc = json.loads(SERVE_JSON.read_text(encoding="utf-8"))
    assert doc["TCP"]["443"]["HTTPS"] is True
    # ${TS_CERT_DOMAIN} is containerboot's substitution, and the dashboard's
    # own serve-config POST (WP B) fills the same slot from LocalAPI's
    # Self.DNSName -- one document, two appliers.
    web = doc["Web"]["${TS_CERT_DOMAIN}:443"]["Handlers"]["/"]
    # `dashboard:8480` -- the compose SERVICE name, not 127.0.0.1: the
    # tailscale container does not share the dashboard's netns (only
    # syncthing and sftp do), so loopback there is its own loopback.
    assert web["Proxy"] == "http://dashboard:8480"


def test_the_serve_switch_is_off_by_default(code: str):
    assert 'TS_SERVE_CONFIG: "${DASH_TAILSCALE_SERVE:-}"' in code, (
        "TS_SERVE_CONFIG must come from DASH_TAILSCALE_SERVE with an EMPTY "
        "default -- a default that names the file turns Serve on for every "
        "customer who never asked for it")


def test_the_serve_config_directory_is_mounted_read_only(code: str):
    assert "- ./tailscale:/config:ro" in code
