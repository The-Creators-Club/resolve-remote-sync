"""Gear identify (gear_ai.py): the website's photo -> the Claude Code CLI kept hot.

The CLI here is a fake that speaks the same stream-json protocol (one JSON
user message per stdin line, a `result` event per turn), so these tests
check the process lifetime the owner asked for -- one CLI reused across
photos, closed after an hour of no photos, recycled after MAX_TURNS -- and
the route's own gate, without a real `claude` or a network.
"""
import json
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import gear_ai
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"

FAKE = textwrap.dedent('''
    import json, os, sys
    n = 0
    for line in sys.stdin:
        msg = json.loads(line)
        n += 1
        text = [c for c in msg["message"]["content"] if c["type"] == "text"][0]["text"]
        if "DIE" in text:
            sys.exit(3)
        print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
        reply = {"name": "Thing %d" % n, "category": "Audio", "weight_g": 12.4, "qty": 2,
                 "note": "pid %d" % os.getpid(), "confidence": "high"}
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                          "result": "```json\\n" + json.dumps(reply) + "\\n```"}), flush=True)
''')


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def fake_cli(tmp_path):
    path = tmp_path / "fake_claude.py"
    path.write_text(FAKE, encoding="utf-8")
    return [sys.executable, str(path)]


@pytest.fixture
def hot(fake_cli, tmp_path):
    clock = Clock()
    h = gear_ai.HotClaude(lambda: fake_cli, lambda: None, lambda: tmp_path, max_turns=3, clock=clock)
    h.clock = clock
    yield h
    h.shutdown()


def photo(text="New photo."):
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAAA"}},
            {"type": "text", "text": text}]


def test_photos_reuse_one_hot_cli(hot):
    a = gear_ai.parse_suggestion(hot.ask(photo()))
    b = gear_ai.parse_suggestion(hot.ask(photo()))
    assert (a["name"], b["name"]) == ("Thing 1", "Thing 2")   # one conversation, two turns
    assert a["note"] == b["note"]                              # the same process
    assert hot.running()


def test_closed_after_an_hour_without_a_photo_and_restarted_by_the_next(hot):
    first = gear_ai.parse_suggestion(hot.ask(photo()))
    hot.clock.t += gear_ai.IDLE_SECONDS - 1
    assert not hot.close_if_idle() and hot.running()           # 59:59 later: still hot
    hot.clock.t += 1
    assert hot.close_if_idle() and not hot.running()           # an hour: closed
    again = gear_ai.parse_suggestion(hot.ask(photo()))
    assert again["name"] == "Thing 1" and again["note"] != first["note"]   # a fresh CLI


def test_a_photo_resets_the_hour(hot):
    hot.ask(photo())
    hot.clock.t += 3000
    hot.ask(photo())
    hot.clock.t += 3000
    assert not hot.close_if_idle()                             # 50 min since the LAST photo


def test_recycled_after_max_turns(hot):
    notes = [gear_ai.parse_suggestion(hot.ask(photo()))["note"] for _ in range(4)]
    assert len(set(notes[:3])) == 1 and notes[3] != notes[0]


def test_a_cli_that_exits_is_an_error_and_the_next_photo_starts_over(hot):
    with pytest.raises(gear_ai.GearError) as e:
        hot.ask(photo("DIE"))
    assert e.value.status == 502
    assert gear_ai.parse_suggestion(hot.ask(photo()))["name"] == "Thing 1"


def test_parse_tidies_the_reply():
    s = gear_ai.parse_suggestion('Sure: {"name": " Cable ", "weight_g": "40.6", "qty": 0, "confidence": "HIGH"}')
    assert s == {"name": "Cable", "category": "", "weight_g": 41, "qty": 1, "note": "", "confidence": "high"}
    with pytest.raises(gear_ai.GearError):
        gear_ai.parse_suggestion("no json here")


@pytest.fixture
def client(tmp_path, fake_cli, monkeypatch):
    settings = Settings(db_path=str(tmp_path / "gear.db"), session_secret=SECRET)
    monkeypatch.setattr(gear_ai, "_hot", gear_ai.HotClaude(lambda: fake_cli, lambda: None, lambda: tmp_path))
    with TestClient(create_app(settings)) as c:
        yield c
    gear_ai.shutdown()
    monkeypatch.setattr(gear_ai, "_hot", None)


def test_route_answers_with_the_right_token_and_no_session(client):
    r = client.post(gear_ai.PATH, headers={"X-Gear-Token": gear_ai.token_for(SECRET)},
                    json={"image": "data:image/jpeg;base64,AAAA", "categories": ["Audio"]})
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]["name"] == "Thing 1"


@pytest.mark.parametrize("token", ["", "nope", gear_ai.token_for("another-secret")])
def test_route_refuses_without_the_token(client, token):
    r = client.post(gear_ai.PATH, headers={"X-Gear-Token": token} if token else {},
                    json={"image": "AAAA"})
    assert r.status_code == 401
    assert "Thing" not in r.text


def test_token_is_derived_from_the_session_secret():
    assert gear_ai.token_for(SECRET) == gear_ai.token_for(SECRET) != gear_ai.token_for(SECRET + "x")
    assert gear_ai.token_for("") == ""
