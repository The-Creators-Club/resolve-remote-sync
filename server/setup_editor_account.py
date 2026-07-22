#!/usr/bin/env python3
"""Create (or update) a TrueNAS user account for a remote editor.

    python setup_editor_account.py --name jsmith --ssh-pubkey-file C:\\keys\\jsmith.pub [--dry-run]

Steps (all via the TrueNAS REST API, /api/v2.0):
  1. Ensure the `editors` group exists (create it if missing).
  2. Ensure a user `--name` exists, member of `editors`, with:
       - the given SSH public key installed (for rclone-over-SFTP, lanes A/B)
       - SMB access enabled (for the SMB/Syncthing mount path)
       - password login disabled once a pubkey is on file (key-only SSH)
  3. Verify the account looks right (group membership, sshpubkey present,
     smb flag on) and print a rclone remote config stanza the editor's
     companion app needs for lanes A/B.

Idempotent: if the user already exists, it is updated in place (PUT) rather
than re-created; if the group already exists it's reused.

ASSUMPTION / OPEN QUESTION (flagged, not resolved by this script): TrueNAS's
per-user "Disable Password Login" (`password_disabled`) field is documented
as blocking *all* password based logins for the account, which historically
has also broken SMB (SMB auth is password-hash based). This script sets
`password_disabled=True` only when it can also confirm `smb=True` remained
set afterward (see verify step); if TrueNAS reports SMB got disabled as a
side effect, the script leaves password_disabled alone, prints a warning,
and asks the admin to decide (key-only SSH vs SMB access are in tension for
this account). See server/README.md.

Env vars: TRUENAS_HOST (default 192.168.0.102), TRUENAS_USER (default
truenas_admin), TRUENAS_PW (required).
"""
import argparse
import sys

from common import EDITORS_GROUP, ok, truenas_api


def find_group(name: str, dry_run: bool):
    resp = truenas_api("GET", "/group", params={"group": name}, dry_run=dry_run)
    if dry_run:
        return None
    if not ok(resp):
        print(f"FAILED to query group {name!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    matches = [g for g in resp.json() if g.get("group") == name]
    return matches[0] if matches else None


def ensure_group(name: str, dry_run: bool) -> int:
    """Return the group's DB id (real mode) or -1 (dry-run, unknown).

    NOTE: the /user endpoints' `group`/`groups` fields take the group's
    database id, NOT its unix gid — passing the gid fails validation with
    "This group does not exist" (learned against the live 25.10 API).
    """
    existing = find_group(name, dry_run)
    if dry_run:
        print(f"[dry-run] would ensure group {name!r} exists")
        return -1
    if existing:
        print(f"group already exists, skipping: {name} (gid {existing['gid']}, id {existing['id']})")
        return existing["id"]

    resp = truenas_api("POST", "/group", json_body={"name": name, "smb": True}, dry_run=dry_run)
    if not ok(resp):
        print(f"FAILED to create group {name!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    created = resp.json()
    # POST /group returns the new row id (an int), not a dict, on 25.10.
    group_id = created if isinstance(created, int) else created.get("id")
    print(f"created group: {name} (id {group_id})")
    return group_id


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
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

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

    gid = ensure_group(EDITORS_GROUP, args.dry_run)

    existing = find_user(args.name, args.dry_run)
    full_name = args.full_name or args.name

    if args.dry_run:
        print(f"[dry-run] would ensure user {args.name!r} exists, group={EDITORS_GROUP}, "
              f"smb=True, sshpubkey=<from file>, password_disabled=True")
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
            "password_disabled": False,  # flipped to True below once we can verify smb survives it
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

    # Try key-only SSH (password_disabled=True), then re-verify SMB is still on.
    resp = truenas_api("PUT", f"/user/id/{user_id}", json_body={"password_disabled": True}, dry_run=False)
    if ok(resp):
        recheck = truenas_api("GET", f"/user/id/{user_id}", dry_run=False)
        if ok(recheck) and recheck.json().get("smb"):
            print("set password_disabled=True (key-only SSH); smb flag still True afterward")
        else:
            # roll back -- SMB access matters more for this project than key-only SSH
            truenas_api("PUT", f"/user/id/{user_id}", json_body={"password_disabled": False}, dry_run=False)
            print("WARNING: setting password_disabled=True appeared to disable SMB access too; "
                  "rolled back to password_disabled=False so SMB keeps working. This is the "
                  "open question flagged in this script's docstring -- decide manually whether "
                  "key-only SSH or SMB access wins for this account, then set password_disabled "
                  "by hand in the TrueNAS UI.")
    else:
        print(f"WARNING: could not set password_disabled=True: HTTP {resp.status_code} {resp.text}", file=sys.stderr)

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
