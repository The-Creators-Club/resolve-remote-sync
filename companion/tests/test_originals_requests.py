"""The Resolve door: request files -> dashboard picks -> one balloon.

docs/SELECTIVE_ORIGINALS.md 12.2/12.3 and section 11 ("the request inbox
rejects paths outside a ticked project"). Strict validation, the File Path to
(slug, rel) mapping, multicams resolved from the walk the watcher already does
(no Resolve call), the 409 sentence surfaced VERBATIM (D9), and the request
file deleted once answered. The dashboard is a stub; the one test of the real
PUT stubs the OPENER, never urlopen (GOTCHAS section 12).
"""

from __future__ import annotations

import io
import json
import os
import time
import unicodedata
import urllib.error
from pathlib import Path

import pytest

from ccsync_companion import originals_requests as orq
from ccsync_companion import selection as selection_mod
from ccsync_companion import upgrade as upgrade_mod

PREFIX = "P:\\"
D9 = ("This project is upload only on this computer, so nothing comes down. "
      "Switch it to full sync first.")
NAME_NFC = unicodedata.normalize("NFC", "Matej Šimalčík")
NAME_NFD = unicodedata.normalize("NFD", "Matej Šimalčík")


def _selection(*extra):
    return [
        {"slug": "beyond-nights", "rel_path": "2026/Beyond Nights", "position": 0,
         "sync_mode": "full"},
        {"slug": "matej", "rel_path": f"2026/{NAME_NFC}", "position": 1, "sync_mode": "full"},
        {"slug": "backup", "rel_path": "2026/Backup Only", "position": 2,
         "sync_mode": "upload_only"},
        *extra,
    ]


def _request(clips, action="add", source="media_pool", **over):
    body = {"v": 1, "action": action, "source": source, "project": "FF5", "timeline": None,
            "clips": clips,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    body.update(over)
    return body


def _clip(path, uid="u1", name="A001"):
    return {"file_path": path, "unique_id": uid, "name": name, "type": "Video"}


class Dash:
    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def put(self, slug, add, remove):
        self.calls.append((slug, add, remove))
        answer = self.answers.get(slug)
        if callable(answer):
            return answer()
        if answer is not None:
            return answer
        n = len(add) or len(remove)
        return 200, {"ok": True, "added": len(add), "removed": len(remove),
                     "total_bytes": n * 1024**3}, ""


def _inbox(tmp_path, dash, memory=None, clock=time.time, cfg=None):
    notes = []
    woke = []
    inbox_dir = tmp_path / "requests"
    inbox_dir.mkdir(exist_ok=True)
    box = orq.OriginalsInbox(
        cfg or {"local_root": str(tmp_path / "root"), "canonical_prefix": PREFIX},
        selection_fn=_selection, put_fn=dash.put, notify_fn=notes.append,
        memory=memory, on_queued=lambda: woke.append(1), inbox=inbox_dir, clock=clock)
    return box, inbox_dir, notes, woke


def _drop(inbox_dir, body, name="1730000000000-000001000002.json"):
    path = inbox_dir / name
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    path.write_bytes(data)
    return path


# -- validation ---------------------------------------------------------------

def test_a_valid_request_parses():
    req = orq.parse_request(json.dumps(_request([_clip("P:\\Projects\\x.braw")])).encode())
    assert req["action"] == "add" and req["source"] == "media_pool"
    assert req["clips"][0]["file_path"] == "P:\\Projects\\x.braw"


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(v=2),
    lambda b: b.update(v=True),
    lambda b: b.update(v="1"),
    lambda b: b.update(action="delete"),
    lambda b: b.update(source="anywhere"),
    lambda b: b.update(clips=[]),
    lambda b: b.update(clips="P:\\x.braw"),
    lambda b: b.update(clips=["P:\\x.braw"]),
    lambda b: b.update(clips=[{"file_path": 5, "unique_id": "u"}]),
    lambda b: b.update(clips=[{"file_path": "x"}]),
    lambda b: b.update(clips=[_clip("x" * (orq.MAX_PATH_CHARS + 1))]),
    lambda b: b.update(clips=[_clip("x")] * (orq.MAX_CLIPS + 1)),
    lambda b: b.update(created_at=None),
    lambda b: b.update(project=7),
])
def test_malformed_requests_are_refused(mutate):
    body = _request([_clip("P:\\Projects\\x.braw")])
    mutate(body)
    with pytest.raises(orq.RequestError):
        orq.parse_request(json.dumps(body).encode())


@pytest.mark.parametrize("raw", [b"not json", b"[1,2]", b"\xff\xfe{}",
                                 b" " * (orq.MAX_REQUEST_BYTES + 1)],
                         ids=["not-json", "array", "not-utf8", "oversize"])
def test_non_json_and_oversize_files_are_refused(raw):
    with pytest.raises(orq.RequestError):
        orq.parse_request(raw)


def test_a_malformed_file_is_logged_and_deleted_without_a_call(tmp_path):
    dash = Dash()
    box, inbox_dir, notes, _ = _inbox(tmp_path, dash)
    path = _drop(inbox_dir, b"{oops")
    assert box.poll_once() == 1
    assert not path.exists()
    assert dash.calls == [] and notes == []


def test_a_request_older_than_an_hour_is_deleted_unanswered(tmp_path):
    dash = Dash()
    later = time.time() + orq.MAX_AGE_SECONDS + 60
    box, inbox_dir, notes, _ = _inbox(tmp_path, dash, clock=lambda: later)
    path = _drop(inbox_dir, _request([_clip("P:\\Projects\\2026\\Beyond Nights\\A.braw")]))
    box.poll_once()
    assert not path.exists()
    assert dash.calls == [] and notes == []


def test_a_stale_half_written_tmp_is_cleared_and_a_fresh_one_left(tmp_path):
    box, inbox_dir, _, _ = _inbox(tmp_path, Dash())
    stale = inbox_dir / "1-1.json.tmp"
    stale.write_bytes(b"{")
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    fresh = inbox_dir / "2-2.json.tmp"
    fresh.write_bytes(b"{")
    box.poll_once()
    assert not stale.exists() and fresh.exists()


# -- path mapping ---------------------------------------------------------------

@pytest.mark.parametrize("path,root,expected", [
    ("P:\\Projects\\2026\\Show\\Footage\\A001.braw", "F:\\Creators_Club",
     "Projects/2026/Show/Footage/A001.braw"),
    ("p:/projects/2026/Show/A001.braw", "F:\\Creators_Club", "projects/2026/Show/A001.braw"),
    ("F:\\Creators_Club\\Projects\\2026\\Show\\A001.braw", "F:\\Creators_Club",
     "Projects/2026/Show/A001.braw"),
    ("/Volumes/T7/Creators_Club/Projects/2026/Show/A001.braw", "/Volumes/T7/Creators_Club",
     "Projects/2026/Show/A001.braw"),
    ("D:\\Elsewhere\\A001.braw", "F:\\Creators_Club", None),
    ("", "F:\\Creators_Club", None),
])
def test_file_path_maps_to_a_tree_rel(path, root, expected):
    assert orq.tree_rel_for(path, root, PREFIX) == expected


def test_tree_rels_group_by_project_and_refuse_paths_outside_a_tick():
    grouped, outside, skipped = orq.map_to_projects([
        "Projects/2026/Beyond Nights/Footage Lusty/A001.braw",
        "projects/2026/beyond nights/Footage Lusty/A002.braw",
        "Projects/2026/Beyond Nights/Footage Lusty/Proxy/A001.mov",
        "Projects/2026/Beyond Nights/Audio/zoom.wav",
        "Projects/2026/Not Ticked/A.braw",
        "Projects/2026/Beyond Nights",
        f"Projects/2026/{NAME_NFD}/C0001.MP4",
    ], _selection())
    assert grouped == {
        "beyond-nights": ["Footage Lusty/A001.braw", "Footage Lusty/A002.braw"],
        "matej": ["C0001.MP4"],
    }
    assert outside == 2
    assert skipped == 2


# -- end to end ------------------------------------------------------------------

def test_an_add_is_put_once_per_project_and_answered_in_one_balloon(tmp_path):
    dash = Dash()
    box, inbox_dir, notes, woke = _inbox(tmp_path, dash)
    path = _drop(inbox_dir, _request([
        _clip("P:\\Projects\\2026\\Beyond Nights\\Footage Lusty\\A001.braw", "u1"),
        _clip("P:\\Projects\\2026\\Beyond Nights\\Footage Lusty\\A002.braw", "u2"),
        _clip(f"P:\\Projects\\2026\\{NAME_NFD}\\C0001.MP4", "u3"),
    ]))
    assert box.poll_once() == 1
    assert not path.exists(), "deleted once answered"
    assert dash.calls == [
        ("beyond-nights", [{"rel": "Footage Lusty/A001.braw", "is_dir": False},
                           {"rel": "Footage Lusty/A002.braw", "is_dir": False}], []),
        ("matej", [{"rel": "C0001.MP4", "is_dir": False}], []),
    ]
    assert len(notes) == 1
    assert notes[0].startswith("Bringing 3 originals to this computer (3.0 GB).")
    assert "\u2014" not in notes[0]
    assert woke == [1], "the lane is woken to fetch the new plan"


def test_the_409_sentence_reaches_the_editor_verbatim(tmp_path):
    dash = Dash({"backup": (409, {"detail": D9}, "HTTP 409")})
    box, inbox_dir, notes, woke = _inbox(tmp_path, dash)
    path = _drop(inbox_dir, _request([
        _clip("P:\\Projects\\2026\\Backup Only\\A.braw", "u1"),
        _clip("P:\\Projects\\2026\\Beyond Nights\\B.braw", "u2"),
    ]))
    box.poll_once()
    assert not path.exists()
    assert [c[0] for c in dash.calls] == ["backup", "beyond-nights"], \
        "an upload-only tick still goes to the dashboard, whose sentence says how to fix it"
    assert notes[0].startswith(D9), notes[0]
    assert "Bringing 1 original to this computer" in notes[0]


def test_a_refusal_alone_is_still_a_balloon(tmp_path):
    dash = Dash({"backup": (409, {"detail": D9}, "HTTP 409")})
    box, inbox_dir, notes, woke = _inbox(tmp_path, dash)
    _drop(inbox_dir, _request([_clip("P:\\Projects\\2026\\Backup Only\\A.braw")]))
    box.poll_once()
    assert notes == [D9]
    assert woke == []


def test_an_unreachable_dashboard_keeps_the_file_and_does_not_resend_answered_projects(tmp_path):
    flaky = {"n": 0}

    def _matej():
        flaky["n"] += 1
        if flaky["n"] == 1:
            return 0, None, "dashboard unreachable"
        return 200, {"ok": True, "added": 1, "removed": 0, "total_bytes": 10}, ""

    dash = Dash({"matej": _matej})
    box, inbox_dir, notes, _ = _inbox(tmp_path, dash)
    path = _drop(inbox_dir, _request([
        _clip("P:\\Projects\\2026\\Beyond Nights\\A.braw", "u1"),
        _clip(f"P:\\Projects\\2026\\{NAME_NFC}\\B.braw", "u2"),
    ]))
    assert box.poll_once() == 0
    assert path.exists() and notes == []
    assert box.poll_once() == 1
    assert not path.exists()
    assert [c[0] for c in dash.calls] == ["beyond-nights", "matej", "matej"]
    assert len(notes) == 1 and notes[0].startswith("Bringing 2 originals")


def test_a_remove_sends_plain_rels(tmp_path):
    dash = Dash()
    box, inbox_dir, notes, _ = _inbox(tmp_path, dash)
    _drop(inbox_dir, _request([_clip("P:\\Projects\\2026\\Beyond Nights\\A.braw")],
                              action="remove", source="timeline_range"))
    box.poll_once()
    assert dash.calls == [("beyond-nights", [], ["A.braw"])]
    assert notes[0].startswith("Stopped bringing 1 original.")
    assert "stay" in notes[0]


def test_paths_outside_a_ticked_project_are_refused_and_said(tmp_path):
    dash = Dash()
    box, inbox_dir, notes, _ = _inbox(tmp_path, dash)
    _drop(inbox_dir, _request([_clip("P:\\Projects\\2026\\Not Ticked\\A.braw"),
                               _clip("D:\\Elsewhere\\B.braw", "u2")]))
    box.poll_once()
    assert dash.calls == []
    assert notes == ["Nothing was queued: 2 clips are not in a project this computer syncs."]


def test_a_multicam_is_resolved_from_the_watchers_walk_without_a_resolve_call(tmp_path):
    memory = orq.ClipPathMemory()
    walk = {"ok": True, "items": [
        {"file_path": "P:\\Projects\\2026\\Beyond Nights\\Cam A\\A.braw",
         "media_pool_uid": "angleA", "via_multicam": "MC1"},
        {"file_path": "P:\\Projects\\2026\\Beyond Nights\\Cam B\\B.braw",
         "media_pool_uid": "angleB", "via_multicam": "MC1"},
        {"file_path": "P:\\Projects\\2026\\Beyond Nights\\Solo.braw",
         "media_pool_uid": "solo", "via_multicam": None},
    ]}
    assert memory.remember(walk) is walk, "the watcher gets its result back untouched"
    dash = Dash()
    box, inbox_dir, notes, _ = _inbox(tmp_path, dash, memory=memory)
    _drop(inbox_dir, _request([
        {"file_path": "", "unique_id": "MC1", "name": "Interview MC", "type": "Multicam"},
        {"file_path": "", "unique_id": "solo", "name": "Solo", "type": "Video"},
        {"file_path": "", "unique_id": "never-seen", "name": "Compound", "type": "Compound"},
    ], source="timeline_all"))
    box.poll_once()
    assert dash.calls == [("beyond-nights", [
        {"rel": "Cam A/A.braw", "is_dir": False},
        {"rel": "Cam B/B.braw", "is_dir": False},
        {"rel": "Solo.braw", "is_dir": False}], [])]
    assert "1 clip could not be matched to a file" in notes[0]


def test_the_app_feeds_the_watchers_walk_into_the_memory(monkeypatch):
    """The getter handed to the watcher is the old one, remembered on the way
    past -- the same single bridge call, nothing added."""
    from ccsync_companion import app as app_mod
    from ccsync_companion import resolve_bridge

    calls = []
    walk = {"ok": True, "items": [{"file_path": "P:\\Projects\\x.braw",
                                   "media_pool_uid": "u", "via_multicam": "M"}]}
    monkeypatch.setattr(resolve_bridge, "poll_timeline_items",
                        lambda: calls.append(1) or walk)
    source = Path(app_mod.__file__).read_text(encoding="utf-8")
    assert "get_timeline_items=lambda: self._clip_paths.remember(\n" \
           "                resolve_bridge.poll_timeline_items())" in source
    memory = orq.ClipPathMemory()
    assert memory.remember(resolve_bridge.poll_timeline_items()) is walk
    assert calls == [1]
    assert memory.paths_for("M") == ["P:\\Projects\\x.braw"]


def test_memory_is_bounded():
    memory = orq.ClipPathMemory(limit=3)
    for n in range(10):
        memory.remember({"items": [{"file_path": f"P:\\{n}.braw", "media_pool_uid": f"u{n}"}]})
    assert memory.paths_for("u0") == []
    assert memory.paths_for("u9") == ["P:\\9.braw"]


# -- the real PUT, opener stubbed ------------------------------------------------

class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _client(tmp_path, monkeypatch, outcome):
    sent = []

    class _Opener:
        def open(self, req, timeout=None):
            sent.append(req)
            if isinstance(outcome, Exception):
                raise outcome
            return _Resp(json.dumps(outcome).encode())

    monkeypatch.setattr(upgrade_mod, "build_no_redirect_opener", lambda *h: _Opener())
    monkeypatch.setattr(selection_mod, "_machine_name", lambda: "RUSKIN-PC")
    client = selection_mod.SelectionClient(
        {"dashboard_url": "https://dash.example/", "dashboard_token": "t" * 30},
        tmp_path, editor_name_fn=lambda: "Ruskin", identity_token_fn=lambda: "cce1.abc")
    return client, sent


def test_put_originals_wire_shape(tmp_path, monkeypatch):
    client, sent = _client(tmp_path, monkeypatch,
                           {"ok": True, "added": 1, "removed": 0, "total_bytes": 5})
    status, body, error = client.put_originals(
        "beyond-nights", [{"rel": f"{NAME_NFC}/A.braw", "is_dir": False}], [])
    assert (status, error) == (200, "") and body["total_bytes"] == 5
    req = sent[0]
    assert req.get_method() == "PUT"
    assert req.full_url == ("https://dash.example/api/v1/selection/ruskin/beyond-nights/"
                            "originals?machine=RUSKIN-PC")
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers["x-ccsync-token"] == "t" * 30
    assert headers["x-ccsync-identity"] == "cce1.abc"
    assert headers["content-type"] == "application/json"
    assert json.loads(req.data.decode("utf-8")) == {
        "add": [{"rel": f"{NAME_NFC}/A.braw", "is_dir": False}], "remove": [],
        "via": "resolve"}


def test_put_originals_hands_back_the_409_body(tmp_path, monkeypatch):
    err = urllib.error.HTTPError("https://dash.example/x", 409, "Conflict", {},
                                 io.BytesIO(json.dumps({"detail": D9}).encode()))
    client, _sent = _client(tmp_path, monkeypatch, err)
    status, body, _error = client.put_originals("backup", [{"rel": "A.braw", "is_dir": False}], [])
    assert status == 409 and body == {"detail": D9}


def test_put_originals_unreachable_is_status_zero(tmp_path, monkeypatch):
    client, _sent = _client(tmp_path, monkeypatch, urllib.error.URLError("refused"))
    status, body, error = client.put_originals("x", [], ["A.braw"])
    assert status == 0 and body is None and "unreachable" in error
