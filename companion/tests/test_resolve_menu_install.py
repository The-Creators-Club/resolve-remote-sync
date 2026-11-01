"""The "originals on request" Resolve menu scripts and their installer.

docs/SELECTIVE_ORIGINALS.md section 12. Nothing here touches Resolve: the Lua
scripts run against a stub resolve object written below, under whichever Lua
is to hand (a lua/luajit binary on PATH, or the lupa module), and the test
skips that half when there is none.
"""

from __future__ import annotations

import importlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ccsync_companion import resolve_menu_install as rmi

MENU_DIR = Path(rmi.__file__).resolve().parent / "resolve_menu"
COMPANION_ROOT = Path(__file__).resolve().parent.parent

SHIPPED = [
    "Bring originals - selected media pool clips.lua",
    "Bring originals - timeline clips between In and Out.lua",
    "Bring originals - whole timeline.lua",
    "Stop originals - selected media pool clips.lua",
    "Stop originals - timeline clips between In and Out.lua",
]

TRICKY_PATH = 'P:\\Projects\\Ep "One"\\Matej Šimalčík\\A001\tC002.braw'


@pytest.fixture
def resolve_root(tmp_path):
    # Fusion/ exists once Resolve has run for this user; Scripts/ may not.
    fusion = tmp_path / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion"
    fusion.mkdir(parents=True)
    return fusion / "Scripts"


# --------------------------------------------------------------------------
# installer


def test_scripts_root_per_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert rmi.scripts_root("win32") == (tmp_path / "Roaming" / "Blackmagic Design"
                                         / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts")
    mac = rmi.scripts_root("darwin")
    assert mac == (Path.home() / "Library" / "Application Support" / "Blackmagic Design"
                   / "DaVinci Resolve" / "Fusion" / "Scripts")
    assert rmi.scripts_root("linux") is None
    monkeypatch.delenv("APPDATA")
    assert rmi.scripts_root("win32") is None


def test_install_writes_five_self_contained_scripts(resolve_root):
    res = rmi.install_menu_scripts(resolve_root)
    assert res["ok"] is True, res
    assert sorted(res["installed"]) == sorted(SHIPPED)
    assert res["removed"] == []
    target = resolve_root / "Edit" / "CC Sync"
    assert sorted(p.name for p in target.iterdir()) == sorted(SHIPPED)
    for name in SHIPPED:
        data = (target / name).read_bytes()
        assert b"\r\n" not in data
        text = data.decode("utf-8")
        assert text.startswith(rmi.OWNED_MARKER)
        assert rmi.SPLICE_MARKER not in text
        assert "local function json_string" in text
    assert (Path.home() / ".ccsync" / "requests" / "originals").is_dir()


def test_install_is_idempotent_and_repairs_a_changed_file(resolve_root):
    first = rmi.install_menu_scripts(resolve_root)
    target = resolve_root / "Edit" / "CC Sync"
    before = {n: (target / n).stat().st_mtime_ns for n in SHIPPED}
    second = rmi.install_menu_scripts(resolve_root)
    assert first["ok"] and second["ok"]
    assert second["installed"] == [] and second["removed"] == []
    assert {n: (target / n).stat().st_mtime_ns for n in SHIPPED} == before

    (target / SHIPPED[2]).write_bytes(b"-- edited by hand\n")
    third = rmi.install_menu_scripts(resolve_root)
    assert third["installed"] == [SHIPPED[2]]
    assert (target / SHIPPED[2]).read_bytes() == rmi.render_scripts()[SHIPPED[2]]


def test_stale_removal_is_confined_to_owned_scripts_in_our_folder(resolve_root):
    target = resolve_root / "Edit" / "CC Sync"
    target.mkdir(parents=True)
    owned_old = target / "Bring originals - old name.lua"
    owned_old.write_text(rmi.OWNED_MARKER + "; old\n", encoding="utf-8")
    hand_made = target / "My own helper.lua"
    hand_made.write_text("print('mine')\n", encoding="utf-8")
    notes = target / "notes.txt"
    notes.write_text(rmi.OWNED_MARKER, encoding="utf-8")
    leftover = target / (SHIPPED[0] + rmi._TMP_SUFFIX)
    leftover.write_bytes(b"half")
    # Same ownership line, but outside our folder: not ours to remove.
    sibling = resolve_root / "Edit" / "Someone else.lua"
    sibling.write_text(rmi.OWNED_MARKER + "\n", encoding="utf-8")
    other_folder = resolve_root / "Edit" / "Other" / "Bring originals - old name.lua"
    other_folder.parent.mkdir()
    other_folder.write_text(rmi.OWNED_MARKER + "\n", encoding="utf-8")

    res = rmi.install_menu_scripts(resolve_root)
    assert res["ok"], res
    assert res["removed"] == [owned_old.name]
    assert not owned_old.exists() and not leftover.exists()
    assert hand_made.exists() and notes.exists() and sibling.exists() and other_folder.exists()


def test_missing_resolve_creates_nothing(tmp_path):
    root = tmp_path / "nowhere" / "Fusion" / "Scripts"
    res = rmi.install_menu_scripts(root)
    assert res["ok"] is False
    assert res["installed"] == [] and res["removed"] == []
    assert "not seem to be installed" in res["message"]
    assert not (tmp_path / "nowhere").exists()


def test_unsupported_platform_and_missing_package_data_never_raise(monkeypatch, resolve_root):
    monkeypatch.setattr(rmi, "scripts_root", lambda platform=None: None)
    res = rmi.install_menu_scripts()
    assert res["ok"] is False and res["message"]

    monkeypatch.setattr(rmi, "_source_dir", lambda: None)
    res = rmi.install_menu_scripts(resolve_root)
    assert res["ok"] is False
    assert "not in this build" in res["message"]
    assert not (resolve_root / "Edit").exists()


def test_frozen_build_reads_package_data_from_meipass(monkeypatch, tmp_path):
    bundle = tmp_path / "meipass" / "ccsync_companion" / "resolve_menu"
    shutil.copytree(MENU_DIR, bundle)
    monkeypatch.setattr(rmi.sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    assert rmi._source_dir() == bundle


def test_crlf_checkout_installs_the_same_bytes(tmp_path):
    crlf = tmp_path / "crlf"
    crlf.mkdir()
    for p in MENU_DIR.glob("*.lua"):
        (crlf / p.name).write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert rmi.render_scripts(crlf) == rmi.render_scripts(MENU_DIR)


def test_build_spec_and_pyproject_ship_every_lua_file():
    on_disk = sorted(p.name for p in MENU_DIR.glob("*.lua"))
    assert sorted(SHIPPED + [rmi.COMMON_NAME]) == on_disk
    spec = (COMPANION_ROOT / "build.spec").read_text(encoding="utf-8")
    for name in on_disk:
        assert f'"{name}"' in spec, name
    assert '"ccsync_companion/resolve_menu"' in spec
    pyproject = (COMPANION_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"ccsync_companion" = ["resolve_menu/*.lua"]' in pyproject


def test_lua_source_rules():
    for p in MENU_DIR.glob("*.lua"):
        text = p.read_text(encoding="utf-8")
        assert "\u2014" not in text, p.name
        # Lua 5.1 has neither; Resolve's README names 5.1.
        assert not re.search(r"^\s*goto\s", text, re.M), p.name
        assert "//" not in text.replace("://", ""), p.name
    common = (MENU_DIR / rmi.COMMON_NAME).read_text(encoding="utf-8")
    # The escape must use byte ranges (see the comment there) and cover the
    # two characters JSON requires plus every control byte.
    assert "gsub('[%z\\1-\\31\"\\\\]'" in common
    for lua_line in ('if c == \'"\' then return \'\\\\"\' end',
                     'if c == "\\\\" then return "\\\\\\\\" end',
                     'return string.format("\\\\u%04x", c:byte())'):
        assert lua_line in common, lua_line
    assert 'os.rename(tmp, final)' in common
    assert 'GetClipProperty", "File Path"' in common
    assert 'm["in"]' in common  # `in` is a Lua keyword; m.in is a syntax error


# --------------------------------------------------------------------------
# the scripts themselves, under a stub Resolve


def _lua_literal(value) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    data = str(value).encode("utf-8")
    return '"' + "".join(chr(b) if (chr(b).isalnum() or chr(b) == " ") and b < 128
                         else f"\\{b:03d}" for b in data) + '"'


def _lua_table(obj) -> str:
    if isinstance(obj, dict):
        return "{" + ", ".join(f"[{_lua_literal(k)}] = {_lua_table(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        return "{" + ", ".join(_lua_table(v) for v in obj) + "}"
    return _lua_literal(obj)


# The stub mirrors the README's shapes: lists are 1-based tables, marks are
# {video = {in = .., out = ..}}, every method is called with a colon.
STUB = r"""
local W = CCSYNC_WORLD
local function mpi(c)
  if c == nil then return nil end
  return {
    GetClipProperty = function(self, key)
      if c.raise_type and key == "Type" then error("stale object") end
      if key == "File Path" then return c.path end
      if key == "Type" then return c.type end
      return nil
    end,
    GetUniqueId = function(self) return c.uid end,
    GetName = function(self) return c.name end,
  }
end
local function item(it)
  return {
    GetMediaPoolItem = function(self) return mpi(it.clip) end,
    GetStart = function(self) return it.s end,
    GetEnd = function(self) return it.e end,
  }
end
local function items(list)
  local out = {}
  for i, it in ipairs(list or {}) do out[i] = item(it) end
  return out
end
local timeline = nil
if W.timeline then
  local T = W.timeline
  timeline = {
    GetName = function(self) return T.name end,
    GetStartFrame = function(self) return T.start end,
    GetEndFrame = function(self) return T.last end,
    GetMarkInOut = function(self) return T.marks or {} end,
    GetTrackCount = function(self, kind) return #((T.tracks or {})[kind] or {}) end,
    GetItemListInTrack = function(self, kind, index) return items(T.tracks[kind][index]) end,
    GetCurrentVideoItem = function(self) if T.current then return item(T.current) end return nil end,
  }
end
local selected = {}
for i, c in ipairs(W.selected or {}) do selected[i] = mpi(c) end
local project = nil
if W.project then
  project = {
    GetName = function(self) return W.project end,
    GetCurrentTimeline = function(self) return timeline end,
    GetMediaPool = function(self) return { GetSelectedClips = function(self) return selected end } end,
  }
end
resolve = {
  GetProjectManager = function(self)
    return { GetCurrentProject = function(self) return project end }
  end,
}
CCSYNC_CREATEDIR_CALLS = {}
bmd = { createdir = function(dir) CCSYNC_CREATEDIR_CALLS[#CCSYNC_CREATEDIR_CALLS + 1] = dir end }
local real_getenv = os.getenv
os.getenv = function(name)
  if name == "USERPROFILE" or name == "HOME" then return W.home end
  return real_getenv(name)
end
if W.posix then package.config = "/\n;\n?\n!\n-\n" end
CCSYNC_PRINTED = {}
local real_print = print
print = function(...)
  local parts = {}
  for i = 1, select("#", ...) do parts[#parts + 1] = tostring((select(i, ...))) end
  CCSYNC_PRINTED[#CCSYNC_PRINTED + 1] = table.concat(parts, "\t")
  real_print(...)
end
"""


def _runners():
    found = []
    for exe in ("luajit", "lua5.1", "lua"):
        path = shutil.which(exe)
        if path:
            found.append(("exe", path))
    for mod in ("lupa.lua51", "lupa.luajit21"):
        try:
            found.append(("lupa", importlib.import_module(mod)))
        except Exception:  # noqa: BLE001 - absent or unbuildable: skip that runtime
            pass
    return found


RUNNERS = _runners()


def _run_lua(runner, script: str, world: dict, tmp_path: Path) -> str:
    kind, impl = runner
    source = "CCSYNC_WORLD = " + _lua_table(world) + "\n" + STUB + "\n" + script
    if kind == "exe":
        chunk = tmp_path / "run.lua"
        chunk.write_text(source, encoding="utf-8")
        proc = subprocess.run([impl, str(chunk)], capture_output=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.decode("utf-8", "replace")
    lua = impl.LuaRuntime()
    lua.execute(source)
    printed = lua.globals().CCSYNC_PRINTED
    return "\n".join(str(printed[i]) for i in range(1, len(printed) + 1))


def _requests(home: Path) -> list[Path]:
    inbox = home / ".ccsync" / "requests" / "originals"
    return sorted(inbox.iterdir()) if inbox.is_dir() else []


def _one_request(home: Path) -> dict:
    files = _requests(home)
    assert len(files) == 1, files
    assert re.fullmatch(r"\d+-\d{12}\.json", files[0].name), files[0].name
    return json.loads(files[0].read_bytes().decode("utf-8"))


CLIP_A = {"path": TRICKY_PATH, "uid": "uid-a", "name": "A001 \"take\"", "type": "Video"}
CLIP_B = {"path": "P:\\Projects\\Ep1\\B.mov", "uid": "uid-b", "name": "B", "type": "Video + Audio"}
CLIP_C = {"path": "P:\\Projects\\Ep1\\C.wav", "uid": "uid-c", "name": "C", "type": "Audio"}
CLIP_D = {"path": "P:\\Projects\\Ep1\\D.mov", "uid": "uid-d", "name": "D", "type": "Video"}
CLIP_MC = {"path": "", "uid": "uid-mc", "name": "Multicam 1", "type": "Multicam"}


def _rec(c):
    return {"file_path": c["path"], "unique_id": c["uid"], "name": c["name"], "type": c["type"]}


def _timeline(marks=None, start=86400, last=86600, current=None):
    return {
        "name": "Cut 3 - Šimalčík",
        "start": start,
        "last": last,
        "marks": marks or {},
        "current": current,
        "tracks": {
            "video": [
                [{"clip": CLIP_A, "s": 86400, "e": 86410},
                 {"clip": CLIP_B, "s": 86410, "e": 86420},
                 {"clip": None, "s": 86412, "e": 86418},
                 {"clip": CLIP_D, "s": 86421, "e": 86430}],
                [{"clip": CLIP_MC, "s": 86405, "e": 86600}],
            ],
            "audio": [
                [{"clip": CLIP_B, "s": 86410, "e": 86420},
                 {"clip": CLIP_C, "s": 86415, "e": 86500}],
            ],
        },
    }


def _script(name: str) -> str:
    return rmi.render_scripts()[name].decode("utf-8")


def _world(tmp_path, **kw):
    home = tmp_path / "home"
    (home / ".ccsync" / "requests" / "originals").mkdir(parents=True)
    world = {"home": str(home), "project": "Repro Rights Ep 2"}
    world.update(kw)
    return world, home


needs_lua = pytest.mark.skipif(not RUNNERS, reason="no Lua interpreter (lua/luajit on PATH or lupa)")
runner_ids = [f"{k}:{getattr(i, '__name__', i)}" for k, i in RUNNERS]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_media_pool_request(runner, tmp_path):
    world, home = _world(tmp_path, selected=[CLIP_A, CLIP_MC, CLIP_A], timeline=_timeline())
    out = _run_lua(runner, _script(SHIPPED[0]), world, tmp_path)
    req = _one_request(home)
    assert set(req) == {"v", "action", "source", "project", "timeline", "clips", "created_at"}
    assert req["v"] == 1 and req["action"] == "add" and req["source"] == "media_pool"
    assert req["project"] == "Repro Rights Ep 2"
    assert req["timeline"] == "Cut 3 - Šimalčík"
    assert req["clips"] == [_rec(CLIP_A), _rec(CLIP_MC)]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", req["created_at"])
    assert "2 clips" in out
    assert not list((home / ".ccsync" / "requests" / "originals").glob("*.tmp"))


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_media_pool_without_timeline_sends_null(runner, tmp_path):
    world, home = _world(tmp_path, selected=[CLIP_B])
    _run_lua(runner, _script(SHIPPED[3]), world, tmp_path)
    req = _one_request(home)
    assert req["action"] == "remove" and req["timeline"] is None
    assert req["clips"] == [_rec(CLIP_B)]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
@pytest.mark.parametrize("marks", [
    {"video": {"in": 10, "out": 20}},             # relative to the timeline start
    {"video": {"in": 86410, "out": 86420}},       # absolute: relative reading overruns the end
    {"audio": {"in": 10, "out": 20}},             # only audio marks set
])
def test_timeline_range_request(runner, marks, tmp_path):
    world, home = _world(tmp_path, timeline=_timeline(marks=marks))
    _run_lua(runner, _script(SHIPPED[1]), world, tmp_path)
    req = _one_request(home)
    assert req["source"] == "timeline_range" and req["action"] == "add"
    # A ends exactly at In (excluded), the item with no media pool clip is
    # skipped, B on video and audio is one entry, D starts after Out.
    assert req["clips"] == [_rec(CLIP_B), _rec(CLIP_MC), _rec(CLIP_C)]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_timeline_range_on_a_zero_start_timeline(runner, tmp_path):
    tl = _timeline(marks={"video": {"in": 86410, "out": 86420}}, start=0, last=90000)
    world, home = _world(tmp_path, timeline=tl)
    _run_lua(runner, _script(SHIPPED[4]), world, tmp_path)
    req = _one_request(home)
    assert req["action"] == "remove"
    assert req["clips"] == [_rec(CLIP_B), _rec(CLIP_MC), _rec(CLIP_C)]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_no_marks_falls_back_to_the_playhead(runner, tmp_path):
    tl = _timeline(current={"clip": CLIP_D, "s": 86421, "e": 86430})
    world, home = _world(tmp_path, timeline=tl)
    _run_lua(runner, _script(SHIPPED[1]), world, tmp_path)
    req = _one_request(home)
    assert req["source"] == "timeline_playhead"
    assert req["clips"] == [_rec(CLIP_D)]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_whole_timeline(runner, tmp_path):
    world, home = _world(tmp_path, timeline=_timeline())
    _run_lua(runner, _script(SHIPPED[2]), world, tmp_path)
    req = _one_request(home)
    assert req["source"] == "timeline_all"
    assert req["clips"] == [_rec(c) for c in (CLIP_A, CLIP_B, CLIP_D, CLIP_MC, CLIP_C)]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
@pytest.mark.parametrize("script_index,world_kw,expect", [
    (0, {"selected": []}, "no clips are selected"),
    (1, {}, "no timeline is open"),
    (1, {"timeline": "no-marks-no-playhead"}, "no clip under the playhead"),
    (2, {"project": None}, "no project is open"),
])
def test_nothing_to_send_writes_nothing(runner, script_index, world_kw, expect, tmp_path):
    if world_kw.get("timeline") == "no-marks-no-playhead":
        world_kw = {"timeline": _timeline()}
    world, home = _world(tmp_path, **world_kw)
    out = _run_lua(runner, _script(SHIPPED[script_index]), world, tmp_path)
    assert _requests(home) == []
    assert expect in out
    assert "\u2014" not in out


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_a_raising_method_costs_one_field(runner, tmp_path):
    clip = dict(CLIP_B, raise_type=True)
    world, home = _world(tmp_path, selected=[clip])
    _run_lua(runner, _script(SHIPPED[0]), world, tmp_path)
    req = _one_request(home)
    assert req["clips"] == [dict(_rec(CLIP_B), type="")]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_control_characters_are_escaped(runner, tmp_path):
    nasty = {"path": "P:\\a\\b\x01\x1f\n\r\b\f\"q\".mov", "uid": "u\\1", "name": "tab\there", "type": "Video"}
    world, home = _world(tmp_path, selected=[nasty])
    _run_lua(runner, _script(SHIPPED[0]), world, tmp_path)
    files = _requests(home)
    raw = files[0].read_bytes()
    assert b"\x01" not in raw and b"\x1f" not in raw
    assert _one_request(home)["clips"] == [_rec(nasty)]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_creates_a_missing_request_folder(runner, tmp_path):
    home = tmp_path / "fresh home"
    home.mkdir()
    world = {"home": str(home), "project": "P", "selected": [CLIP_C]}
    _run_lua(runner, _script(SHIPPED[0]), world, tmp_path)
    assert _one_request(home)["clips"] == [_rec(CLIP_C)]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_posix_home_and_separator(runner, tmp_path):
    world, home = _world(tmp_path, selected=[CLIP_C], posix=True)
    _run_lua(runner, _script(SHIPPED[0]), world, tmp_path)
    assert _one_request(home)["clips"] == [_rec(CLIP_C)]
