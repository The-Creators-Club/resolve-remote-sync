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
    /mnt/tank/TheCreatorsPool/homes/<editor>

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

Env vars: TRUENAS_HOST (default 192.168.0.102), TRUENAS_USER (default
truenas_admin), TRUENAS_PW (required).
"""
import argparse
import re
import sys

from common import (
    EDITORS_GROUP, add_host_key_arg, ok, run_ssh, set_host_key_pin, shell_quote,
    truenas_api, wait_for_job,
)

# sshd StrictModes rejects a home dir that is group- or world-writable, or
# not owned by the user logging in. 0700 satisfies both and matches what
# TrueNAS already does for the .ssh subdirectory it creates.
HOME_MODE = "700"

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
    resp = truenas_api("GET", "/group", params={"group": name}, dry_run=dry_run)
    if dry_run:
        return None
    if not ok(resp):
        print(f"FAILED to query group {name!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    matches = [g for g in resp.json() if g.get("group") == name]
    return matches[0] if matches else None


def ensure_group(name: str, dry_run: bool):
    """Return (db_id, unix_gid) for the group, or (-1, -1) in dry-run.

    NOTE: the /user endpoints' `group`/`groups` fields take the group's
    database id, NOT its unix gid — passing the gid fails validation with
    "This group does not exist" (learned against the live 25.10 API). The
    unix gid is needed separately, for chown-ing the home directory.
    """
    existing = find_group(name, dry_run)
    if dry_run:
        print(f"[dry-run] would ensure group {name!r} exists")
        return -1, -1
    if existing:
        print(f"group already exists, skipping: {name} (gid {existing['gid']}, id {existing['id']})")
        return existing["id"], existing["gid"]

    resp = truenas_api("POST", "/group", json_body={"name": name, "smb": True}, dry_run=dry_run)
    if not ok(resp):
        print(f"FAILED to create group {name!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    created = resp.json()
    # POST /group returns the new row id (an int), not a dict, on 25.10.
    group_id = created if isinstance(created, int) else created.get("id")
    # Re-read to learn the unix gid the system assigned.
    fresh = find_group(name, dry_run=False)
    unix_gid = fresh["gid"] if fresh else -1
    print(f"created group: {name} (id {group_id}, gid {unix_gid})")
    return group_id, unix_gid


def ensure_home_permissions(home: str, uid: int, unix_gid: int, username: str) -> bool:
    """Make `home` acceptable to sshd's StrictModes check. Returns True if OK.

    See this module's docstring: homes created by `home_create=True` inherit a
    world-writable ACL from the parent dataset and are owned by the dataset
    owner, which makes sshd refuse the editor's key with an error only visible
    in the server's auth log. `filesystem.setperm` with `stripacl` replaces the
    inherited ACL with a trivial one; a plain chmod would fail with EPERM
    because the dataset is aclmode=restricted.
    """
    if not home or home in ("/", "/nonexistent", "/var/empty"):
        print(f"WARNING: refusing to touch permissions on home path {home!r} for {username}",
              file=sys.stderr)
        return False

    body = {
        "path": home,
        "mode": HOME_MODE,
        "uid": uid,
        "gid": unix_gid,
        "options": {"stripacl": True, "recursive": False, "traverse": False},
    }
    resp = truenas_api("POST", "/filesystem/setperm", json_body=body, dry_run=False)
    if not ok(resp):
        print(f"FAILED to set permissions on {home}: HTTP {resp.status_code} {resp.text}",
              file=sys.stderr)
        return False

    job_id = resp.json()
    state, error = wait_for_job(job_id)
    if state != "SUCCESS":
        print(f"FAILED to set permissions on {home}: job {job_id} ended {state}: {error}",
              file=sys.stderr)
        return False

    print(f"home permissions set: {home} -> {username}:{unix_gid} mode 0{HOME_MODE} (ACL stripped)")
    return True


def verify_home_permissions(home: str, username: str) -> bool:
    """Re-read the home dir over SSH and confirm sshd will accept it.

    Deliberately re-checks the exact two conditions sshd's StrictModes tests —
    not group/world-writable, and owned by the user — rather than trusting the
    setperm job's success, because getting this wrong is silent.
    """
    rc, out, err = run_ssh(
        f'echo "$SUDO_PW" | sudo -S -p "" stat -c "%a %U" {shell_quote(home)}',
        dry_run=False,
    )
    line = (out or "").strip().splitlines()
    if rc != 0 or not line:
        print(f"WARNING: could not stat {home} to verify permissions: {err.strip()[:200]}",
              file=sys.stderr)
        return False

    parts = line[-1].split()
    if len(parts) != 2:
        print(f"WARNING: unexpected stat output for {home}: {line[-1]!r}", file=sys.stderr)
        return False

    mode_str, owner = parts
    try:
        mode = int(mode_str, 8)
    except ValueError:
        print(f"WARNING: could not parse mode {mode_str!r} for {home}", file=sys.stderr)
        return False

    problems = []
    if mode & 0o022:
        problems.append(f"mode 0{mode_str} is group- or world-writable")
    if owner != username:
        problems.append(f"owned by {owner}, not {username}")

    if problems:
        print(f"WARNING: {home} will be REJECTED by sshd StrictModes: {'; '.join(problems)}",
              file=sys.stderr)
        print("         The editor's key is installed but public-key auth will fail with "
              "'bad ownership or modes for directory' in the NAS auth log.", file=sys.stderr)
        return False

    print(f"verified: home {home} is mode 0{mode_str}, owned by {owner} (sshd StrictModes will accept it)")
    return True


def find_user(name: str, dry_run: bool):
    resp = truenas_api("GET", "/user", params={"username": name}, dry_run=dry_run)
    if dry_run:
        return None
    if not ok(resp):
        print(f"FAILED to query user {name!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    matches = [u for u in resp.json() if u.get("username") == name]
    return matches[0] if matches else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="unix/SMB username for the editor")
    ap.add_argument("--ssh-pubkey-file", required=True, help="path to the editor's SSH public key (.pub)")
    ap.add_argument("--full-name", default=None, help="defaults to --name")
    ap.add_argument("--tailnet-host", default="<TAILNET-HOSTNAME-OR-IP>",
                     help="tailnet address of the NAS, for the printed rclone stanza")
    add_host_key_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)

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
        body = {
            "sshpubkey": pubkey,
            "smb": True,
            "groups": sorted(set(existing.get("groups", []) + [gid])),
        }
        resp = truenas_api("PUT", f"/user/id/{existing['id']}", json_body=body, dry_run=False)
        if not ok(resp):
            print(f"FAILED to update user {args.name!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
        user_id = existing["id"]
        print(f"updated user: {args.name} (sshpubkey, smb, group membership)")
    else:
        body = {
            "username": args.name,
            "full_name": full_name,
            "group_create": False,
            "group": gid,
            "groups": [gid],
            # With home_create=True, `home` is the PARENT dir — TrueNAS
            # appends the username itself (25.10 API semantics).
            "home": "/mnt/tank/TheCreatorsPool/homes",
            "home_create": True,
            "shell": "/usr/bin/bash",
            # Stays False: 25.10 rejects password_disabled for SMB users
            # outright (see module docstring). sshd's own
            # `PasswordAuthentication no` is what makes SSH key-only.
            "password_disabled": False,
            "random_password": True,
            "sshpubkey": pubkey,
            "smb": True,
            "locked": False,
        }
        resp = truenas_api("POST", "/user", json_body=body, dry_run=False)
        if not ok(resp):
            print(f"FAILED to create user {args.name!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
        created = resp.json()
        user_id = created["id"]
        print(f"created user: {args.name} (uid {created.get('uid', '?')}), group {EDITORS_GROUP}, smb enabled")

    if args.dry_run:
        print("\nrclone remote config stanza (add to the editor's rclone.conf, "
              "or use installer/windows_bootstrap.ps1 / macos_bootstrap.sh which write it for you):\n")
        print(_rclone_stanza(args.name, args.tailnet_host))
        return 0

    # --- verify + attempt key-only SSH, without breaking SMB ---
    resp = truenas_api("GET", f"/user/id/{user_id}", dry_run=False)
    if not ok(resp):
        print(f"FAILED to re-fetch user {args.name!r} for verification: HTTP {resp.status_code}", file=sys.stderr)
        return 1
    current = resp.json()

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
    resp = truenas_api("PUT", f"/user/id/{user_id}", json_body={"password_disabled": True}, dry_run=False)
    if ok(resp):
        print("set password_disabled=True (key-only SSH)")
    elif resp is not None and resp.status_code == 422 and "SMB" in resp.text:
        print("password login left enabled: TrueNAS does not allow password_disabled for SMB "
              "users. SSH is still key-only because sshd is configured with "
              "PasswordAuthentication no.")
    else:
        print(f"WARNING: could not set password_disabled=True: HTTP {resp.status_code} {resp.text}",
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
    return (
        f"[creators_club_sftp]\n"
        f"type = sftp\n"
        f"host = {tailnet_host}\n"
        f"user = {name}\n"
        f"port = 22\n"
        f"key_file = ~/.ssh/ccsync_ed25519\n"
        f"shell_type = unix\n"
    )


if __name__ == "__main__":
    sys.exit(main())
