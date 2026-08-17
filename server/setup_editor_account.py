#!/usr/bin/env python3
"""Create (or update) a TrueNAS user account for a remote editor.

    python setup_editor_account.py --name jsmith --ssh-pubkey-file C:\\keys\\jsmith.pub [--dry-run]

Steps (all via the TrueNAS REST API, /api/v2.0):
  1. Ensure the `editors` group exists (create it if missing).
  2. Ensure a user `--name` exists, member of `editors`, with:
       - the given SSH public key installed (for rclone-over-SFTP, lanes A/B)
       - SMB access enabled (for the SMB/Syncthing mount path)
       - password login disabled once a pubkey is on file (key-only SSH)
  3. Fix up the home directory's ownership and mode so sshd will actually
     accept the key (see below) -- this step is not optional.
  4. Verify the account looks right (group membership, sshpubkey present,
     smb flag on, home dir sane) and print a rclone remote config stanza the
     editor's companion app needs for lanes A/B.

Idempotent: if the user already exists, it is updated in place (PUT) rather
than re-created; if the group already exists it's reused. Re-running against
an existing editor is the supported way to repair a broken home dir.

HOME DIRECTORY PERMISSIONS (step 3) -- confirmed against live 25.10:
`home_create=True` makes the new home inherit the parent `homes` dataset's
NFSv4 ACL. On this pool that ACL carries an inheritable
`everyone@:rwxp...:fd----I:allow` ACE, so the home is created mode 0777 and
owned by the *dataset* owner (broll), not the new user. sshd runs with
`StrictModes yes`, which refuses public-key auth outright when the home
directory is group/world-writable or not owned by the authenticating user:

    Authentication refused: bad ownership or modes for directory
    <pool root>/homes/<editor>

The key itself is installed perfectly, so from the editor's side this is
indistinguishable from "the admin never added my key" -- rclone just reports
`ssh: unable to authenticate, attempted methods [none publickey]`. Worse, a
plain chmod cannot fix it: the dataset has `aclmode=restricted`, under which
chmod on a non-trivial ACL fails with EPERM. So this script calls
`filesystem.setperm` with `stripacl` to replace the inherited ACL with a
trivial 0700 owned by the editor.

PASSWORD LOGIN -- resolved, no longer an open question: TrueNAS 25.10 simply
refuses to combine the two, rejecting `password_disabled=True` for any SMB
user with HTTP 422 "Password authentication may not be disabled for SMB
users." The API blocks the combination up front rather than silently
breaking SMB, so this script attempts it, treats that specific 422 as the
expected answer, and leaves the account password-enabled with SMB working.
SSH is still effectively key-only because sshd itself is configured with
`PasswordAuthentication no`.

Env vars: TRUENAS_HOST / TRUENAS_USER (no defaults -- they come from [nas]
host / admin_user in site.toml, see docs/SERVER.md), TRUENAS_PW (required).
"""
import argparse
import re
import sys

# truenas_api / run_ssh / wait_for_job / ok are imported even though this
# module no longer calls them directly: they are the names ScriptCalls resolves
# the backend's NAS access through, and the offline suite patches them HERE
# (see common.ScriptCalls). Removing them as "unused" would make the backend
# reach past every monkeypatch in server/tests.
from common import (  # noqa: F401
    DEFAULT_HOMES_PARENT, EDITORS_GROUP, ScriptCalls, add_host_key_arg,
    add_nas_kind_arg, add_site_arg, cli, get_backend, ok, require_site_value,
    run_ssh, set_host_key_pin, shell_quote, site_value, synology_api, truenas_api,
    wait_for_job,
)

# The platform half of this script -- the group and /user calls, filesystem.
# setperm, and the StrictModes re-check -- moved to server/backends/ on
# 2026-08-17 (SYNOLOGY_PORT_PLAN WP3). What stayed here is what is true on
# every NAS: the username shape, which home paths must never be touched, the
# verification, and the rclone stanza the editor needs.
_ARGS = None   # set by main(); None means "kind from $CCSYNC_NAS_KIND/site.toml"
_BACKEND = None


def backend():
    """The ServerBackend, built once per run.

    ScriptCalls binds it to THIS module's truenas_api/run_ssh names, so the
    offline suite's monkeypatches still see every call it asserts on.
    """
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = get_backend(_ARGS, calls=ScriptCalls(sys.modules[__name__]))
    return _BACKEND


# sshd StrictModes rejects a home dir that is group- or world-writable, or
# not owned by the user logging in. 0700 satisfies both and matches what
# TrueNAS already does for the .ssh subdirectory it creates.
HOME_MODE = "700"

# The PARENT dataset every editor home is created under (see the `home` value
# in main()'s user-create body -- with home_create=True TrueNAS appends the
# username itself, so this is the parent, never a home). Site-supplied since
# 2026-08-17 (<pool_root>/homes); blank when the site is unconfigured, and
# is_forbidden_home() treats blank as forbidden, so an unset site can never
# aim setperm at "/".
HOMES_PARENT = DEFAULT_HOMES_PARENT

# Paths ensure_home_permissions must refuse outright. `/`, `/nonexistent` and
# `/var/empty` are the classic no-home sentinels; HOMES_PARENT is here because
# a hand-created account whose `home` was set to the parent instead of
# <parent>/<username> would otherwise get
# `filesystem.setperm mode:700 stripacl:True` applied to the SHARED dataset
# root -- stripping the ACL off every other editor's route in over SMB.
FORBIDDEN_HOME_PATHS = ("/", "/nonexistent", "/var/empty", "/mnt", "/root",
                        "/home", HOMES_PARENT)


def is_forbidden_home(home: str) -> bool:
    """True when `home` is a path whose permissions must never be rewritten:
    blank, a no-home sentinel, or a shared parent dataset. Trailing slashes
    are noise, not a difference."""
    cleaned = str(home or "").strip()
    if not cleaned:
        return True
    normalized = cleaned.rstrip("/") or "/"
    return normalized in {p.rstrip("/") or "/" for p in FORBIDDEN_HOME_PATHS}

# The same shape installer/windows_bootstrap.ps1 enforces on -EditorName
# (lowercased there, because unix usernames are case-sensitive and a mismatch
# only ever surfaces as a generic SSH auth failure on the editor's side).
USERNAME_RE = re.compile(r"^[a-z][a-z0-9._-]{0,30}$")


def normalize_username(name: str) -> str:
    """Lowercase and validate an editor username, or raise ValueError.

    Lowercasing mirrors the bootstrap so the account and the editor's
    rclone.conf can never disagree by case.
    """
    cleaned = str(name or "").strip().lower()
    if not USERNAME_RE.match(cleaned):
        raise ValueError(
            f"invalid --name {name!r}: an editor username must start with a letter and "
            f"contain only lowercase a-z, 0-9, '.', '_' or '-' (max 31 chars). This is "
            f"the unix/SMB username, and installer/windows_bootstrap.ps1 lowercases "
            f"-EditorName to the same shape."
        )
    return cleaned


def find_group(name: str, dry_run: bool):
    """Re-export: the body moved to backends/<kind>.py on 2026-08-17 (WP3).
    Kept at its old name because it is this script's vocabulary."""
    return backend().find_group(name, dry_run)


def ensure_group(name: str, dry_run: bool):
    """Return (db_id, unix_gid) for the group, or (-1, -1) in dry-run.

    NOTE: the /user endpoints' `group`/`groups` fields take the group's
    database id, NOT its unix gid — passing the gid fails validation with
    "This group does not exist" (learned against the live 25.10 API). The
    unix gid is needed separately, for chown-ing the home directory.

    Re-export; body in backends/<kind>.py since 2026-08-17.
    """
    return backend().ensure_group(name, dry_run)


def ensure_home_permissions(home: str, uid: int, unix_gid: int, username: str) -> bool:
    """Make `home` acceptable to sshd's StrictModes check. Returns True if OK.

    See this module's docstring: homes created by `home_create=True` inherit a
    world-writable ACL from the parent dataset and are owned by the dataset
    owner, which makes sshd refuse the editor's key with an error only visible
    in the server's auth log. `filesystem.setperm` with `stripacl` replaces the
    inherited ACL with a trivial one; a plain chmod would fail with EPERM
    because the dataset is aclmode=restricted.

    The refusal below stays HERE, in front of every backend: "never rewrite the
    permissions of a shared parent" is a rule about OUR tree layout, not about
    TrueNAS, and a backend that forgot it would strip the ACL off every other
    editor's route in. Only the platform fix itself moved (2026-08-17).
    """
    if is_forbidden_home(home):
        print(f"WARNING: refusing to touch permissions on home path {home!r} for {username} "
              f"-- it is a shared parent or a no-home sentinel, and setperm here would "
              f"strip the ACL off every other editor's path in. Fix the account's home to "
              f"{HOMES_PARENT}/{username} and re-run.", file=sys.stderr)
        return False

    return backend().ensure_home_permissions(home, uid, unix_gid, username)


def verify_home_permissions(home: str, username: str) -> bool:
    """Re-read the home dir over SSH and confirm sshd will accept it.

    Deliberately re-checks the exact two conditions sshd's StrictModes tests --
    not group/world-writable, and owned by the user -- rather than trusting the
    setperm job's success, because getting this wrong is silent.

    Re-export; body in backends/<kind>.py since 2026-08-17.
    """
    return backend().verify_home_permissions(home, username)


def find_user(name: str, dry_run: bool):
    """Re-export; body in backends/<kind>.py since 2026-08-17."""
    return backend().find_user(name, dry_run)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="unix/SMB username for the editor")
    ap.add_argument("--ssh-pubkey-file", required=True, help="path to the editor's SSH public key (.pub)")
    ap.add_argument("--full-name", default=None, help="defaults to --name")
    ap.add_argument("--tailnet-host", default="<TAILNET-HOSTNAME-OR-IP>",
                     help="tailnet address of the NAS, for the printed rclone stanza")
    add_host_key_arg(ap)
    add_site_arg(ap)
    add_nas_kind_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)
    global _ARGS
    _ARGS = args
    homes_parent = require_site_value(HOMES_PARENT, "[tree] pool_root")

    try:
        name = normalize_username(args.name)
    except ValueError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    if name != args.name:
        print(f"normalized --name {args.name!r} -> {name!r} (unix usernames are "
              f"case-sensitive; the bootstrap lowercases -EditorName the same way)")
    args.name = name

    if args.dry_run:
        pubkey = "<contents of %s -- not read in dry-run>" % args.ssh_pubkey_file
    else:
        try:
            with open(args.ssh_pubkey_file, "r", encoding="utf-8") as f:
                pubkey = f.read().strip()
        except OSError as e:
            print(f"FAILED to read --ssh-pubkey-file {args.ssh_pubkey_file}: {e}", file=sys.stderr)
            return 1
        if not pubkey or not pubkey.split(" ")[0].startswith("ssh-"):
            print(f"WARNING: {args.ssh_pubkey_file} does not look like an OpenSSH public key "
                  f"(expected it to start with 'ssh-ed25519'/'ssh-rsa'/...). Proceeding anyway.",
                  file=sys.stderr)

    gid, unix_gid = ensure_group(EDITORS_GROUP, args.dry_run)

    existing = find_user(args.name, args.dry_run)
    full_name = args.full_name or args.name

    if args.dry_run:
        print(f"[dry-run] would ensure user {args.name!r} exists, group={EDITORS_GROUP}, "
              f"smb=True, sshpubkey=<from file>")
        print(f"[dry-run] would set the home directory to mode 0{HOME_MODE} owned by "
              f"{args.name}:{EDITORS_GROUP} via filesystem.setperm (stripacl), then verify "
              f"sshd StrictModes will accept it")
    elif existing:
        print(f"user already exists, updating in place: {args.name} (uid {existing['uid']})")
        user_id, err = backend().update_editor(existing, gid, pubkey)
        if err:
            print(f"FAILED to update user {args.name!r}: {err}", file=sys.stderr)
            return 1
        print(f"updated user: {args.name} (sshpubkey, smb, group membership)")
    else:
        created, err = backend().create_editor(args.name, full_name, gid, pubkey,
                                               homes_parent)
        if err:
            print(f"FAILED to create user {args.name!r}: {err}", file=sys.stderr)
            return 1
        user_id = created["id"]
        print(f"created user: {args.name} (uid {created.get('uid', '?')}), group {EDITORS_GROUP}, smb enabled")

    if args.dry_run:
        print("\nrclone remote config stanza (add to the editor's rclone.conf, "
              "or use installer/windows_bootstrap.ps1 / macos_bootstrap.sh which write it for you):\n")
        print(_rclone_stanza(args.name, args.tailnet_host))
        return 0

    # --- verify + attempt key-only SSH, without breaking SMB ---
    current, err = backend().get_user(user_id)
    if err:
        print(f"FAILED to re-fetch user {args.name!r} for verification: {err}", file=sys.stderr)
        return 1

    problems = []
    if not current.get("sshpubkey"):
        problems.append("sshpubkey is not set")
    if not current.get("smb"):
        problems.append("smb flag is not set")
    if gid not in current.get("groups", []) and current.get("group") != gid:
        problems.append(f"user is not a member of group {EDITORS_GROUP!r}")

    if problems:
        print("WARNING: verification found issues after create/update:")
        for p in problems:
            print(f"  - {p}")
        print("Not attempting to disable password login until the above is resolved.")
        return 1

    print(f"verified: sshpubkey set, smb=True, member of {EDITORS_GROUP}")

    # --- home directory: the step that decides whether SSH works at all ---
    home = current.get("home")
    uid = current.get("uid")
    home_ok = False
    if home and uid is not None and unix_gid >= 0:
        if ensure_home_permissions(home, uid, unix_gid, args.name):
            home_ok = verify_home_permissions(home, args.name)
    else:
        print(f"WARNING: cannot fix home permissions (home={home!r}, uid={uid!r}, "
              f"gid={unix_gid!r})", file=sys.stderr)

    # Key-only SSH: 25.10 refuses password_disabled for SMB users by design,
    # so a 422 here is the expected answer, not a problem to escalate.
    state, detail = backend().set_password_disabled(user_id)
    if state == "ok":
        print("set password_disabled=True (key-only SSH)")
    elif state == "smb-refused":
        print("password login left enabled: TrueNAS does not allow password_disabled for SMB "
              "users. SSH is still key-only because sshd is configured with "
              "PasswordAuthentication no.")
    elif state == "not-applicable":
        # DSM has no such flag at all -- its nearest neighbour disables the
        # whole account, SMB session and dashboard login included. Not a
        # warning: nothing is wrong (2026-08-17).
        print(f"password login left as the platform manages it: {detail}")
    else:
        print(f"WARNING: could not set password_disabled=True: {detail}",
              file=sys.stderr)

    if not home_ok:
        print("\nWARNING: the account exists and the key is installed, but the home directory "
              "is not in a state sshd will accept -- SFTP/rclone (lanes A and B) will fail "
              "with a generic 'unable to authenticate' error on the editor's side. Fix the "
              "home directory before telling the editor they're good to go.", file=sys.stderr)

    print("\nrclone remote config stanza (add to the editor's rclone.conf, "
          "or use installer/windows_bootstrap.ps1 / macos_bootstrap.sh which write it for you):\n")
    print(_rclone_stanza(args.name, args.tailnet_host))
    return 0


def _rclone_stanza(name: str, tailnet_host: str) -> str:
    """The remote an editor pastes into rclone.conf, from site.toml.

    Three of these four were literals until 2026-08-17, and two are wrong on a
    Synology site: DSM often moves sshd off 22, and its editors have
    /sbin/nologin -- so rclone's `shell_type = unix` cannot run md5sum over SSH
    and every checksum call fails ([net] shell_type = "none" there,
    docs/synology-spikes-2026-08-17.md spike 6). The installers write this file
    for the editor; this printout is the manual fallback and must not disagree
    with them.
    """
    remote = site_value("net", "rclone_remote") or "ccsync_sftp"
    port = site_value("net", "sftp_port") or "22"
    shell_type = site_value("net", "shell_type") or "unix"
    return (
        f"[{remote}]\n"
        f"type = sftp\n"
        f"host = {tailnet_host}\n"
        f"user = {name}\n"
        f"port = {port}\n"
        f"key_file = ~/.ssh/ccsync_ed25519\n"
        f"shell_type = {shell_type}\n"
    )


if __name__ == "__main__":
    sys.exit(cli(main))
