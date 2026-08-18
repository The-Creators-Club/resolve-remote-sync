"""In-process fake TrueNAS REST API (api/v2.0 subset) for admin-users tests.

Same approach as fake_syncthing.py: a plain-http HTTPServer (TrueNASClient
in tests is pointed at it via Settings.truenas_base_url, bypassing the
https:// production default), mutate `server.state` to simulate scenarios.
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PREFIX = "/api/v2.0"


def default_state() -> dict:
    return {
        "groups": [],
        "users": [],
        "jobs": {},
        "next_group_id": 100,
        "next_gid": 3001,
        "next_user_id": 1,
        "next_uid": 3000,
        "next_job_id": 1,
        # usernames whose home dir simulates the "home directory trap" --
        # a PUT that tries to set sshpubkey on them gets TrueNAS 25.10's
        # real 422 (see server/README.md's "home directory trap" section).
        "block_sshpubkey_usernames": set(),
        # jobs to fail on purpose, by id, for negative-path tests
        "fail_setperm": False,
        # GET /system/info and GET /pool/snapshottask -- the two READ-ONLY
        # routes the setup wizard's "Connect to your NAS" / "Protect your
        # data" checks use (2026-08-18). Shapes trimmed to the fields those
        # checks read; `snapshot_tasks` starts empty, which is the state of a
        # NAS nobody has run server/setup_snapshots.py against.
        "system_info": {"version": "TrueNAS-SCALE-25.10.4", "hostname": "fake-nas"},
        "snapshot_tasks": [],
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        state = self.server.state  # type: ignore[attr-defined]
        url = urlparse(self.path)
        path = url.path[len(PREFIX):] if url.path.startswith(PREFIX) else url.path
        q = {k: v[0] for k, v in parse_qs(url.query).items()}

        if path == "/group":
            name = q.get("group")
            rows = [g for g in state["groups"] if name is None or g["group"] == name]
            self._json(rows)
        elif path == "/user":
            name = q.get("username")
            rows = [u for u in state["users"] if name is None or u["username"] == name]
            self._json(rows)
        elif re.match(r"^/user/id/\d+$", path):
            uid = int(path.rsplit("/", 1)[1])
            row = next((u for u in state["users"] if u["id"] == uid), None)
            self._json(row if row else {"error": "no such user"}, status=200 if row else 404)
        elif path == "/system/info":
            self._json(state["system_info"])
        elif path == "/pool/snapshottask":
            self._json(state["snapshot_tasks"])
        elif path == "/core/get_jobs":
            job_id = int(q.get("id"))
            job = state["jobs"].get(job_id)
            self._json([job] if job else [])
        else:
            self._json({"error": "not found"}, status=404)

    def do_POST(self):
        state = self.server.state  # type: ignore[attr-defined]
        url = urlparse(self.path)
        path = url.path[len(PREFIX):] if url.path.startswith(PREFIX) else url.path
        body = self._body()

        if path == "/group":
            gid = state["next_group_id"]
            state["next_group_id"] += 1
            unix_gid = state["next_gid"]
            state["next_gid"] += 1
            state["groups"].append({"id": gid, "group": body["name"], "gid": unix_gid})
            self._json(gid)
        elif path == "/user":
            uid = state["next_user_id"]
            state["next_user_id"] += 1
            unix_uid = state["next_uid"]
            state["next_uid"] += 1
            home_parent = body.get("home", "")
            home = f"{home_parent}/{body['username']}" if body.get("home_create") else home_parent
            row = {
                "id": uid,
                "uid": unix_uid,
                "username": body["username"],
                "full_name": body.get("full_name"),
                "home": home,
                "group": {"id": body.get("group")},
                "groups": list(body.get("groups") or []),
                "sshpubkey": body.get("sshpubkey"),
                "smb": bool(body.get("smb")),
                "locked": bool(body.get("locked")),
                "password_disabled": bool(body.get("password_disabled")),
            }
            state["users"].append(row)
            self._json(row)
        elif path == "/filesystem/setperm":
            job_id = state["next_job_id"]
            state["next_job_id"] += 1
            state["jobs"][job_id] = {
                "id": job_id,
                "state": "FAILED" if state["fail_setperm"] else "SUCCESS",
                "error": "simulated setperm failure" if state["fail_setperm"] else None,
            }
            self._json(job_id)
        else:
            self._json({"error": "not found"}, status=404)

    def do_PUT(self):
        state = self.server.state  # type: ignore[attr-defined]
        url = urlparse(self.path)
        path = url.path[len(PREFIX):] if url.path.startswith(PREFIX) else url.path
        body = self._body()

        m = re.match(r"^/user/id/(\d+)$", path)
        if not m:
            self._json({"error": "not found"}, status=404)
            return
        uid = int(m.group(1))
        row = next((u for u in state["users"] if u["id"] == uid), None)
        if row is None:
            self._json({"error": "no such user"}, status=404)
            return

        if "sshpubkey" in body and row["username"] in state["block_sshpubkey_usernames"]:
            self._json({
                "user_update.sshpubkey": [
                    {"message": "Home directory is not writable, leave this blank\"", "errno": 22}
                ]
            }, status=422)
            return

        if body.get("password_disabled") is True and row.get("smb"):
            self._json({
                "user_update.password_disabled": [
                    {"message": "Password authentication may not be disabled for SMB users."}
                ]
            }, status=422)
            return

        row.update(body)
        self._json(row)


class FakeTrueNAS:
    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.state = default_state()  # type: ignore[attr-defined]
        import threading
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def state(self) -> dict:
        return self.httpd.state  # type: ignore[attr-defined]

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}{PREFIX}"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
