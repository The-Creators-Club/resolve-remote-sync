"""Page inputs and the server guard. A FAIL is a confirmed bug. Temp folders only."""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import threading

import pytest

import test_field_service as tfs
from ccsync_companion import field_server, loopback_guard
from test_field_service import SERIAL, World, card_of


def _run(w, ids):
    run = w.finish(w.svc.start_copy(SERIAL, ids))
    w.svc.invalidate()
    return run


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows")
def test_a_laptop_folder_that_is_a_junction_onto_a_field_drive_is_not_a_second_copy(tmp_path):
    w = World(tmp_path)
    target = w.drives["A"] / "laptop-mirror"           # on CIB_D1
    target.mkdir()
    link = w.drives["L"] / "FieldBackup"                # "a folder on the laptop's D:"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    fid = w.add_folder()
    st = w.svc.state(refresh=True)
    print([(d["id"][-30:], d["kind"], d["counts"]) for d in st["destinations"]])
    _run(w, ["vol:AAAA0001", fid])
    v = card_of(w.svc.state(refresh=True))["verdict"]
    print("VERDICT", v["state"], v["headline"])
    assert v["safeToFormat"] is False, "both copies are on CIB_D1 (one through a junction), yet safe"


def test_add_folder_takes_the_laptops_drive_and_refuses_the_card(tmp_path):
    w = World(tmp_path)
    assert w.svc.add_folder(str(w.drives["L"]))[-1] == str(w.drives["L"])
    with pytest.raises(ValueError, match="card or a USB stick"):
        w.svc.add_folder(str(w.card / "backup"))


class _Svc:
    def __init__(self):
        self.calls = []

    def start_copy(self, serial, dests):
        self.calls.append(("copy", serial, dests))
        return {"id": "r"}

    def state(self, refresh=False):
        return {"ok": True}

    def stop_all(self):
        pass


def _req(port, method, path, headers, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request(method, path, body=body, headers=headers)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


def test_the_guard(tmp_path):
    svc = _Svc()
    srv = field_server.make_server({"dashboard_url": "https://dash.example"}, svc, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    body = json.dumps({"serial": "X", "dests": ["vol:A"]})
    cases = {
        "evil origin": {"Host": f"127.0.0.1:{port}", "Origin": "https://evil.example", "Content-Type": "application/json"},
        "rebinding host": {"Host": f"evil.example:{port}", "Origin": f"http://evil.example:{port}", "Content-Type": "application/json"},
        "null origin": {"Host": f"127.0.0.1:{port}", "Origin": "null", "Content-Type": "application/json"},
        "no origin no token": {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"},
        "own origin text/plain": {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}", "Content-Type": "text/plain"},
        "own origin json": {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"},
        "dashboard origin json": {"Host": f"127.0.0.1:{port}", "Origin": "https://dash.example", "Content-Type": "application/json"},
    }
    got = {}
    for name, h in cases.items():
        got[name], _ = _req(port, "POST", "/field/api/copy", h, body)
    srv.shutdown()
    srv.server_close()
    assert got == {"evil origin": 403, "rebinding host": 403, "null origin": 403, "no origin no token": 403,
                   "own origin text/plain": 415, "own origin json": 200, "dashboard origin json": 200}
    assert [c[1] for c in svc.calls] == ["X", "X"]            # only the two allowed callers started anything
