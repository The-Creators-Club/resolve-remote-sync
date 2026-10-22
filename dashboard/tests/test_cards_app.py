"""/cards/app/: the Timeline Cards apps' updates (cards_app.py, 2026-10-22).

The routes on their own, over a vault in tmp_path: latest.json is served,
a file it names is served, and nothing else in the folder (or above it) is.
"""

import json
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ccsync_dashboard import cards_app


def _client(vault):
    app = FastAPI()
    app.state.settings = types.SimpleNamespace(cards_vault_root=str(vault))
    app.include_router(cards_app.router)
    return TestClient(app)


def _publish(vault, latest, files):
    folder = vault / "Apps" / "Timeline Cards"
    folder.mkdir(parents=True)
    (folder / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder


def test_nothing_published_is_a_404(tmp_path):
    r = _client(tmp_path).get("/cards/app/latest.json")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_latest_and_a_named_file(tmp_path):
    _publish(tmp_path, {"android": {"version": "1.0.2", "file": "Timeline-Cards-1.0.2.apk",
                                    "sha256": "ab", "bytes": 3}},
             {"Timeline-Cards-1.0.2.apk": b"apk", "secret.apk": b"no"})
    c = _client(tmp_path)
    j = c.get("/cards/app/latest.json").json()
    assert j["ok"] is True and j["android"]["version"] == "1.0.2"
    r = c.get("/cards/app/Timeline-Cards-1.0.2.apk")
    assert r.status_code == 200 and r.content == b"apk"
    assert r.headers["content-type"] == "application/vnd.android.package-archive"
    # in the folder but not named by latest.json: not served
    assert c.get("/cards/app/secret.apk").status_code == 404
    # anything that is not a bare build name: not served
    assert c.get("/cards/app/latest.json.apk").status_code == 404
    assert c.get("/cards/app/..%2Flatest.json").status_code == 404


def test_listed_but_missing(tmp_path):
    _publish(tmp_path, {"windows": {"version": "1.0.2", "file": "Timeline-Cards-Setup-1.0.2.exe"}}, {})
    r = _client(tmp_path).get("/cards/app/Timeline-Cards-Setup-1.0.2.exe")
    assert r.status_code == 404
