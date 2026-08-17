"""A fake DSM for the offline Synology tests.

Deliberately NOT dashboard/tests/fake_synology.py: server/ and dashboard/ are
separate deployables and neither takes a source dependency on the other (the
dashboard's fake imports ccsync_dashboard.nas.base). What the two must agree on
is the SHAPES, and both are written from the same record --
docs/synology-spikes-2026-08-17.md, measured on a live DS423+.

Two levels, because the traps live at two levels:

  * `FakeDsmApi` stands in for common.synology_api -- the level the BACKEND
    sees. It reproduces the behaviours that make DSM's API a minefield:
      - `Group.Member add` returns success while reading only `name`, so a
        client that sends `members` silently adds nobody;
      - `Group get` reports a missing group as an error 3205;
      - `Share.Permission set` is what installs the editors ACE, so the fake
        only reports a group as writable once that call was made;
      - `User create` refuses a duplicate with 3107.
  * `FakeSsh` records every privileged command and answers the handful the
    backend reads back (`id -u`, `stat -c`, `docker compose ls`). Its recording
    is what proves the thing that matters most on DSM: that NOTHING under the
    tree share is ever chmod'd or chown'd (spike 1).
"""
from __future__ import annotations

import json


class DsmCall:
    def __init__(self, api, method, version, post, params):
        self.api = api
        self.method = method
        self.version = version
        self.post = post
        self.params = params

    def __repr__(self):
        return f"<{self.api}.{self.method} v{self.version} {self.params}>"


class FakeDsmApi:
    """Callable with common.synology_api's signature."""

    def __init__(self, users=None, groups=None, shares=None, sftp_enabled=False,
                 sftp_rules=None, member_add_reads="name"):
        # {name: {"uid": int, "description": str, "expired": "normal"}}
        self.users = dict(users or {})
        # {name: gid}
        self.groups = dict(groups or {})
        # {name: {"vol_path": str, "rw_groups": set()}}
        self.shares = dict(shares or {})
        self.membership = {}          # {group: set(usernames)}
        self.sftp_enabled = sftp_enabled
        self.sftp_port = 22
        self.sftp_rules = list(sftp_rules or [
            {"app_id": "SYNO.SFTP", "entity_type": "everyone",
             "entity_name": "everyone", "allow_ip": ["0.0.0.0"], "deny_ip": []},
        ])
        self.snapshots = {}
        self.calls = []
        self.next_uid = 1042
        self.next_gid = 65536
        # Which parameter Group.Member add honours. "name" is DSM's real
        # behaviour; set it to something else to prove the read-back catches a
        # call that lies (the spike's silent-no-op trap).
        self.member_add_reads = member_add_reads

    # -- the entry point ---------------------------------------------------

    def __call__(self, api, method, version=1, post=False, dry_run=False, **params):
        self.calls.append(DsmCall(api, method, version, post, params))
        if dry_run:
            return {}
        handler = getattr(self, f"_{api.replace('.', '_')}__{method}", None)
        if handler is None:
            raise self.error(103, f"{api}.{method}")
        return handler(**params)

    def of(self, api, method=""):
        return [c for c in self.calls
                if c.api == api and (not method or c.method == method)]

    @staticmethod
    def error(code, what="call"):
        import common  # noqa: PLC0415 - the tests put server/ on sys.path

        return common.DsmError(code, f"{what} failed: DSM error {code}")

    # -- users -------------------------------------------------------------

    def _SYNO_Core_User__list(self, type="local", offset=0, limit=200, additional=None):
        rows = [{"name": name, "uid": info["uid"],
                 "description": info.get("description", ""),
                 "email": "", "expired": info.get("expired", "normal")}
                for name, info in sorted(self.users.items())]
        return {"users": rows[offset:offset + limit], "total": len(rows), "offset": offset}

    def _SYNO_Core_User__create(self, name, **kw):
        if name in self.users:
            raise self.error(3107, "SYNO.Core.User.create")
        uid = self.next_uid
        self.next_uid += 1
        self.users[name] = {"uid": uid, "description": kw.get("description", ""),
                            "expired": "normal"}
        return {"name": name, "uid": uid}

    def _SYNO_Core_User__set(self, name, **kw):
        if name not in self.users:
            raise self.error(3106, "SYNO.Core.User.set")
        self.users[name].update({k: v for k, v in kw.items() if k != "password"})
        return {"name": name, "uid": self.users[name]["uid"]}

    def _SYNO_Core_User_Group__get(self, name):
        if name not in self.users:
            raise self.error(3106, "SYNO.Core.User.Group.get")
        groups = ["users"] + [g for g, members in self.membership.items()
                              if name in members]
        return {"groups": groups}

    # -- groups ------------------------------------------------------------

    def _SYNO_Core_Group__get(self, name, **kw):
        wanted = name if isinstance(name, list) else [name]
        rows = [{"name": n, "gid": self.groups[n], "description": ""}
                for n in wanted if n in self.groups]
        if not rows:
            raise self.error(3205, "SYNO.Core.Group.get")
        return {"groups": rows}

    def _SYNO_Core_Group__create(self, name):
        if name in self.groups:
            raise self.error(3206, "SYNO.Core.Group.create")
        gid = self.next_gid
        self.next_gid += 1
        self.groups[name] = gid
        return {"gid": gid, "name": name}

    def _SYNO_Core_Group_Member__add(self, group, **params):
        # The trap: success whatever it was sent, and only `name` is read.
        names = params.get(self.member_add_reads) or []
        if isinstance(names, str):
            names = [names]
        self.membership.setdefault(group, set()).update(names)
        return {}

    def _SYNO_Core_Group_Member__list(self, group, offset=0, limit=200):
        if group not in self.groups:
            raise self.error(3205, "SYNO.Core.Group.Member.list")
        members = sorted(self.membership.get(group, set()))
        rows = [{"name": n, "uid": self.users.get(n, {}).get("uid"),
                 "description": ""} for n in members]
        return {"users": rows[offset:offset + limit], "total": len(rows), "offset": offset}

    # -- shares ------------------------------------------------------------

    def _SYNO_Core_Share__get(self, name, **kw):
        if name not in self.shares:
            raise self.error(3301, "SYNO.Core.Share.get")
        row = dict(self.shares[name])
        row.pop("rw_groups", None)
        row["name"] = name
        return row

    def _SYNO_Core_Share__create(self, name, shareinfo):
        info = json.loads(shareinfo) if isinstance(shareinfo, str) else dict(shareinfo)
        self.shares[name] = {"vol_path": info.get("vol_path", "/volume1"),
                             "rw_groups": set()}
        return {"name": name}

    def _SYNO_Core_Share_Permission__set(self, name, user_group_type, permissions):
        rows = json.loads(permissions) if isinstance(permissions, str) else permissions
        share = self.shares.setdefault(name, {"vol_path": "/volume1", "rw_groups": set()})
        for row in rows:
            if row.get("is_writable"):
                share.setdefault("rw_groups", set()).add(row["name"])
        return {}

    def _SYNO_Core_Share_Permission__list(self, name, user_group_type, offset=0, limit=100):
        share = self.shares.get(name, {})
        items = [{"name": "administrators", "is_writable": True, "is_admin": True}]
        items += [{"name": g, "is_writable": True, "is_admin": False}
                  for g in sorted(share.get("rw_groups", ()))]
        return {"items": items, "total": len(items)}

    # -- services ----------------------------------------------------------

    def _SYNO_Core_FileServ_FTP_SFTP__get(self):
        return {"enable": self.sftp_enabled, "portnum": self.sftp_port}

    def _SYNO_Core_FileServ_FTP_SFTP__set(self, enable, portnum=22):
        self.sftp_enabled = bool(enable)
        self.sftp_port = int(portnum)
        return {}

    def _SYNO_Core_AppPriv_Rule__list(self, app_id):
        return {"rules": [r for r in self.sftp_rules if r["app_id"] == app_id]}

    # -- snapshots ---------------------------------------------------------

    def _SYNO_Core_Share_Snapshot__create(self, name, desc=""):
        stamp = f"GMT+08-2026.08.17-14.00.{len(self.snapshots):02d}"
        self.snapshots.setdefault(name, []).append(stamp)
        return {"data": stamp}


class FakeSsh:
    """Callable with common.run_ssh's signature, recording every command."""

    def __init__(self, answers=None, rc=0):
        self.commands = []
        self.answers = list(answers or [])   # [(substring, (rc, out, err)), ...]
        self.default_rc = rc

    def __call__(self, cmd, dry_run=False, timeout=120):
        self.commands.append(cmd)
        if dry_run:
            return 0, "", ""
        for needle, result in self.answers:
            if needle in cmd:
                return result
        return self.default_rc, "", ""

    @property
    def text(self) -> str:
        return "\n".join(self.commands)


class FakePutText:
    """Callable with common.sftp_put_text's signature."""

    def __init__(self, ok=True):
        self.ok = ok
        self.uploads = []       # [(remote_dir, {name: body}), ...]

    def __call__(self, remote_dir, files, dry_run=False):
        self.uploads.append((remote_dir, dict(files)))
        return self.ok

    def file(self, name):
        for _dir, files in self.uploads:
            if name in files:
                return files[name]
        return ""
