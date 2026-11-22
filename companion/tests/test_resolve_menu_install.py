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
# docs/GRADING_FRAMES.md 3.2 (2026-11-22): the four grading-frames items, on their own shared body.
FRAMES_SHIPPED = [
    "Bring grading frame - clip under the playhead.lua",
    "Bring grading frames - selected media pool clips.lua",
    "Bring grading frames - timeline clips between In and Out.lua",
    "Go to grading frame.lua",
]
ALL_SHIPPED = SHIPPED + FRAMES_SHIPPED

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


def test_install_writes_every_script_self_contained(resolve_root):
    res = rmi.install_menu_scripts(resolve_root)
    assert res["ok"] is True, res
    assert sorted(res["installed"]) == sorted(ALL_SHIPPED)
    assert res["removed"] == []
    target = resolve_root / "Edit" / "CC Sync"
    everywhere = resolve_root / "Utility" / "CC Sync"
    # The originals items on the Edit page, the grading-frame items on EVERY page (a colourist
    # is on the Color page, where nothing under Edit is listed).
    assert sorted(p.name for p in target.iterdir()) == sorted(SHIPPED)
    assert sorted(p.name for p in everywhere.iterdir()) == sorted(FRAMES_SHIPPED)
    assert (Path.home() / ".ccsync" / "requests" / "frames").is_dir()
    for name in FRAMES_SHIPPED:
        text = (everywhere / name).read_text(encoding="utf-8")
        # Each carries ITS OWN shared body and only that one.
        assert "CCSYNC_FRAMES_LIB" in text and "CCSYNC_ACTION" not in text
        assert rmi.FRAMES_SPLICE_MARKER not in text
    for name in SHIPPED:
        assert "CCSYNC_FRAMES_LIB" not in (target / name).read_text(encoding="utf-8")
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
    assert sorted(ALL_SHIPPED + [rmi.COMMON_NAME, rmi.FRAMES_COMMON_NAME]) == on_disk
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


# --------------------------------------------------------------------------
# grading frames (docs/GRADING_FRAMES.md 3.2 and 3.3, 2026-11-22): the arithmetic and the
# multicam resolution, executed in real Lua against a fake Resolve object tree


# Timelines, items and clips with the fields the frames scripts read. Calls that MOVE Resolve
# (SetCurrentTimeline, SetCurrentTimecode) are recorded in CCSYNC_CALLS instead.
FRAMES_STUB = r"""
local W = CCSYNC_WORLD
CCSYNC_CALLS = {}
local function note(...) CCSYNC_CALLS[#CCSYNC_CALLS + 1] = table.concat({...}, "|") end
local function mpi(c)
  if c == nil then return nil end
  return {
    GetClipProperty = function(self, key)
      if key == "File Path" then return c.path or "" end
      if key == "FPS" then return c.fps end
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
    GetLeftOffset = function(self) return it.left end,
    -- One frame LOW, as measured in the spike (2.4 row n): never used for a clip at normal
    -- speed. `src_start` / `src_end` are for the items copied from a live timeline below; with no
    -- `src_end` the item answers like a Resolve that has no GetSourceEndFrame.
    GetSourceStartFrame = function(self) return it.src_start or ((it.left or 0) - 1) end,
    GetSourceEndFrame = function(self) return it.src_end end,
    GetName = function(self) return it.name end,
    GetProperty = function(self, key) if key == "Speed" then return it.speed end return nil end,
  }
end
local timelines = {}
for i, T in ipairs(W.timelines or {}) do
  local tl = {}
  tl.GetName = function(self) return T.name end
  tl.GetStartFrame = function(self) return T.start end
  tl.GetEndFrame = function(self) return T.last end
  tl.GetSetting = function(self, key)
    if key == "timelineFrameRate" then return T.fps end
    if key == "timelineDropFrameTimecode" then return T.drop and "1" or "0" end
    return nil
  end
  tl.GetCurrentTimecode = function(self) return T.tc end
  tl.SetCurrentTimecode = function(self, tc) note("SetCurrentTimecode", T.name, tc); T.tc = tc; return true end
  tl.GetMarkInOut = function(self) return T.marks or {} end
  tl.GetTrackCount = function(self, kind) return #((T.tracks or {})[kind] or {}) end
  tl.GetItemListInTrack = function(self, kind, index)
    local out = {}
    for j, it in ipairs(T.tracks[kind][index]) do out[j] = item(it) end
    return out
  end
  tl.GetCurrentVideoItem = function(self) if T.current then return item(T.current) end return nil end
  timelines[i] = tl
end
local current = W.current and timelines[W.current] or nil
local selected = {}
for i, c in ipairs(W.selected or {}) do selected[i] = mpi(c) end
local project = {
  GetName = function(self) return W.project end,
  GetCurrentTimeline = function(self) return current end,
  GetTimelineCount = function(self) return #timelines end,
  GetTimelineByIndex = function(self, i) return timelines[i] end,
  SetCurrentTimeline = function(self, tl) note("SetCurrentTimeline", tl:GetName()); current = tl; return true end,
  GetMediaPool = function(self) return { GetSelectedClips = function(self) return selected end } end,
}
resolve = { GetProjectManager = function(self) return { GetCurrentProject = function(self) return project end } end }
bmd = { createdir = function(dir) end }
local real_getenv = os.getenv
os.getenv = function(name)
  if name == "USERPROFILE" or name == "HOME" then return W.home end
  return real_getenv(name)
end
CCSYNC_PRINTED = {}
local real_print = print
print = function(...)
  local parts = {}
  for i = 1, select("#", ...) do parts[#parts + 1] = tostring((select(i, ...))) end
  CCSYNC_PRINTED[#CCSYNC_PRINTED + 1] = table.concat(parts, "\t")
  real_print(...)
end
"""


def _run_frames(runner, script: str, world: dict, tmp_path: Path) -> tuple[str, list]:
    kind, impl = runner
    source = ("CCSYNC_WORLD = " + _lua_table(world) + "\n" + FRAMES_STUB + "\n" + script
              + "\nfor _, c in ipairs(CCSYNC_CALLS) do print('CALL ' .. c) end\n")
    if kind == "exe":
        chunk = tmp_path / "run.lua"
        chunk.write_text(source, encoding="utf-8")
        proc = subprocess.run([impl, str(chunk)], capture_output=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        text = proc.stdout.decode("utf-8", "replace")
    else:
        lua = impl.LuaRuntime()
        lua.execute(source)
        printed = lua.globals().CCSYNC_PRINTED
        text = "\n".join(str(printed[i]) for i in range(1, len(printed) + 1))
    calls = [line[5:] for line in text.splitlines() if line.startswith("CALL ")]
    return text, calls


def _frames_common() -> str:
    return (MENU_DIR / rmi.FRAMES_COMMON_NAME).read_text(encoding="utf-8")


def _lib(runner, body: str, tmp_path: Path) -> list[str]:
    """Run `body` with the shared body loaded as a library (nothing runs), and return what it
    printed, one value per line."""
    script = 'CCSYNC_FRAMES_SCOPE = "library"\n' + _frames_common() + "\nlocal L = CCSYNC_FRAMES_LIB\n" + body
    text, _ = _run_frames(runner, script, {"home": str(tmp_path)}, tmp_path)
    return [line for line in text.splitlines() if not line.startswith("CALL ")]


def _frames_requests(home: Path) -> list[dict]:
    inbox = home / ".ccsync" / "requests" / "frames"
    files = sorted(inbox.iterdir()) if inbox.is_dir() else []
    return [json.loads(p.read_bytes().decode("utf-8")) for p in files]


EM = "\u2014"
G011 = {"path": "P:\\Projects\\2026\\Talk UA\\BMCC\\G011_10211743_C075.braw", "uid": "uid-g011",
        "name": "G011_10211743_C075.braw", "fps": "29.97", "type": "Video"}
A007 = {"path": "P:\\Projects\\2026\\Base Drone\\A007_08090854_C137.braw", "uid": "uid-a007",
        "name": "A007_08090854_C137.braw", "fps": "29.97", "type": "Video"}
FX3 = {"path": "P:\\Projects\\2026\\Base Drone\\fx3_20261021_2780.braw", "uid": "uid-fx3",
       "name": "fx3_20261021_2780.braw", "fps": "119.88", "type": "Video"}
MC_CLIP = {"path": "", "uid": "uid-mc", "name": "Talk UA 10-21 - war stories Multicam",
           "type": "Multicam"}
MC_ITEM_NAME = "Talk UA 10-21 - war stories Multicam - Angle 1"
ANGLE_NAME = f"Talk UA 10-21 - war stories {EM} ANGLE 1 (BMCC)"
# 01:00:00;00 at 29.97 drop-frame is frame 107892.
HOUR_DF = 107892


def _tl(name, current=None, tc="01:00:00;00", start=HOUR_DF, fps="29.97", drop=True, video=(),
        marks=None):
    return {"name": name, "fps": fps, "drop": drop, "start": start, "last": start + 200000,
            "tc": tc, "current": current, "marks": marks or {},
            "tracks": {"video": [list(track) for track in video]}}


def _frames_world(tmp_path, timelines, current=1, **kw):
    home = tmp_path / "home"
    (home / ".ccsync" / "requests" / "frames").mkdir(parents=True)
    world = {"home": str(home), "project": "Talk UA", "timelines": timelines, "current": current}
    world.update(kw)
    return world, home


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_frames_arithmetic_in_lua(runner, tmp_path):
    out = _lib(runner, r"""
print(L.source_frame(4147, 107892 + 37, 107892, 29.97, 29.97))
print(L.source_frame(4759, 200000, 200000, 119.88, 29.97))
print(L.tc_to_frames("01:00:00;00", 29.97, true))
print(L.tc_to_frames("00:01:00;02", 29.97, true))
print(L.tc_to_frames("01:00:00:00", 24, false))
print(L.frames_to_tc(L.tc_to_frames("01:00:14;29", 29.97, true), 29.97, true))
print(L.frames_to_tc(L.tc_to_frames("17:46:52;10", 29.97, true), 29.97, true))
print(L.frames_to_tc(1800, 29.97, true))
print(L.frames_to_tc(86400 + 25, 24, false))
print(L.rate("29.97 DF"), L.rate(23.976), L.rate(nil))
print(L.multicam_parts("Talk UA 10-21 - war stories Multicam - Angle 2"))
print(L.multicam_parts("A007_08090854_C137.braw"))
""", tmp_path)
    tab = "\t"
    # 2.4 row n: GetLeftOffset 4147 (GetSourceStartFrame said 4146), 37 frames in -> 4184, exact.
    assert out[0] == f"4184{tab}true"
    # 2.6: a 119.88 fps clip on a 29.97 timeline plays four source frames to one -> scaled, inexact.
    assert out[1] == f"19036{tab}false"
    assert out[2:5] == ["107892", "1800", "86400"]
    assert out[5:9] == ["01:00:14;29", "17:46:52;10", "00:01:00;02", "01:00:01:01"]
    assert out[9] == f"29.97{tab}23.976{tab}nil"
    assert out[10] == f"Talk UA 10-21 - war stories{tab}2"
    assert out[11] == "nil"


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_frames_angle_timeline_match_is_exact(runner, tmp_path):
    out = _lib(runner, f"""
print(L.is_angle_timeline({_lua_literal(ANGLE_NAME)}, "Talk UA 10-21 - war stories", 1))
print(L.is_angle_timeline({_lua_literal(ANGLE_NAME)}, "Talk UA 10-21 - war stories", 2))
print(L.is_angle_timeline("Talk UA 10-21 - war stories - ANGLE 1 (BMCC)", "Talk UA 10-21 - war stories", 1))
print(L.is_angle_timeline({_lua_literal(ANGLE_NAME + " copy")}, "Talk UA 10-21 - war stories", 1))
""", tmp_path)
    assert out == ["true", "false", "false", "false"]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_playhead_on_a_plain_clip_uses_left_offset_never_source_start(runner, tmp_path):
    """2.4 row n end to end: an item whose GetSourceStartFrame says 4146 and GetLeftOffset 4147,
    the playhead 37 frames in. The request asks for 4184 (and the item's whole use)."""
    item = {"clip": A007, "s": HOUR_DF, "e": HOUR_DF + 600, "left": 4147, "name": "A007"}
    cut = _tl("HMCC Spans", current=item, tc="01:00:01;07", video=[[item]])
    world, home = _frames_world(tmp_path, [cut])
    out, calls = _run_frames(runner, _script(FRAMES_SHIPPED[0]), world, tmp_path)
    assert "asked for grading frames of 1 clip" in out
    req, = _frames_requests(home)
    assert req["source"] == "playhead" and req["refused"] == []
    clip, = req["clips"]
    assert clip["file_path"] == A007["path"]
    assert clip["frames"] == [4184]
    assert clip["uses"] == [[4147, 4147 + 599]]
    assert clip["exact"] is True and clip["clip_fps"] == 29.97 and clip["timeline_fps"] == 29.97
    assert clip["timecode"] == "01:00:01;07"
    assert calls == [], "asking for frames never moves Resolve"
    # ...and the companion reads exactly what the script wrote.
    from ccsync_companion import grading_frames
    parsed = grading_frames.parse_request(json.dumps(req).encode("utf-8"))
    assert parsed["clips"][0]["frames"] == [4184]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_a_clip_at_another_frame_rate_is_scaled_and_marked_inexact(runner, tmp_path):
    """2.6: 119.88 fps on a 29.97 timeline, round((GetLeftOffset + playhead - GetStart) * 4)."""
    item = {"clip": FX3, "s": HOUR_DF, "e": HOUR_DF + 300, "left": 4759, "name": "fx3"}
    cut = _tl("Drone cut", current=item, tc="01:00:00;10", video=[[item]])
    world, home = _frames_world(tmp_path, [cut])
    _run_frames(runner, _script(FRAMES_SHIPPED[0]), world, tmp_path)
    clip, = _frames_requests(home)[0]["clips"]
    assert clip["frames"] == [round((4759 + 10) * 119.88 / 29.97)]
    assert clip["exact"] is False
    assert clip["clip_fps"] == 119.88 and clip["timeline_fps"] == 29.97


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_playhead_on_a_multicam_resolves_to_the_angle_clip(runner, tmp_path):
    """2.4 row o: the multicam item's offset plus the playhead is the frame inside the multicam;
    the angle timeline (same timebase) at its start plus that frame holds the angle clip."""
    mc = {"clip": MC_CLIP, "s": HOUR_DF + 1000, "e": HOUR_DF + 5000, "left": 6000, "name": MC_ITEM_NAME}
    cut = _tl("Talk UA cut", current=mc, tc="01:00:35;10", video=[[mc]])
    playhead = HOUR_DF + 35 * 30 + 10 - 0      # 01:00:35;10 (no dropped frame inside the first minute)
    angle_item = {"clip": G011, "s": HOUR_DF, "e": HOUR_DF + 25260, "left": 0, "name": "G011"}
    angle = _tl(ANGLE_NAME, video=[[angle_item]])
    other = _tl(f"Talk UA 10-21 - war stories {EM} ANGLE 2 (Sony)",
                video=[[{"clip": A007, "s": HOUR_DF, "e": HOUR_DF + 25260, "left": 0, "name": "x"}]])
    world, home = _frames_world(tmp_path, [cut, other, angle])
    out, calls = _run_frames(runner, _script(FRAMES_SHIPPED[0]), world, tmp_path)
    assert "asked for grading frames of 1 clip" in out, out
    clip, = _frames_requests(home)[0]["clips"]
    m = 6000 + (playhead - (HOUR_DF + 1000))
    assert clip["file_path"] == G011["path"]
    assert clip["frames"] == [m]
    assert clip["angle_timeline"] == ANGLE_NAME
    assert clip["uses"] == [[6000, 6000 + 3999]]
    assert calls == []


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
@pytest.mark.parametrize("angle_names", [
    [f"Talk UA 10-21 - war stories {EM} ANGLE 1 (BMCC) renamed"],      # renamed: no match
    [ANGLE_NAME, ANGLE_NAME],                                           # two matches: never guessed
])
def test_a_multicam_the_script_cannot_resolve_is_refused_not_guessed(runner, tmp_path, angle_names):
    mc = {"clip": MC_CLIP, "s": HOUR_DF, "e": HOUR_DF + 5000, "left": 0, "name": MC_ITEM_NAME}
    cut = _tl("Talk UA cut", current=mc, video=[[mc]])
    angles = [_tl(n, video=[[{"clip": G011, "s": HOUR_DF, "e": HOUR_DF + 9000, "left": 0,
                              "name": "G011"}]]) for n in angle_names]
    world, home = _frames_world(tmp_path, [cut, *angles])
    out, _ = _run_frames(runner, _script(FRAMES_SHIPPED[0]), world, tmp_path)
    assert "multicam this script cannot follow" in out and "selected media pool clips" in out
    assert _frames_requests(home) == []


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_go_to_grading_frame_opens_the_angle_timeline_at_the_matching_timecode(runner, tmp_path):
    mc = {"clip": MC_CLIP, "s": HOUR_DF, "e": HOUR_DF + 5000, "left": 6557, "name": MC_ITEM_NAME}
    cut = _tl("Talk UA cut", current=mc, tc="01:00:00;00", video=[[mc]])
    angle = _tl(ANGLE_NAME, video=[[{"clip": G011, "s": HOUR_DF, "e": HOUR_DF + 25260, "left": 0,
                                    "name": "G011"}]])
    world, home = _frames_world(tmp_path, [cut, angle])
    out, calls = _run_frames(runner, _script(FRAMES_SHIPPED[3]), world, tmp_path)
    expected_tc = _lib(runner, f"print(L.frames_to_tc({HOUR_DF + 6557}, 29.97, true))", tmp_path)[0]
    assert calls == [f"SetCurrentTimeline|{ANGLE_NAME}", f"SetCurrentTimecode|{ANGLE_NAME}|{expected_tc}"]
    assert f"opened {ANGLE_NAME} at {expected_tc}" in out
    assert _frames_requests(home) == [], "going there asks for nothing"


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_go_to_grading_frame_on_a_plain_clip_says_where_the_panel_is(runner, tmp_path):
    item = {"clip": A007, "s": HOUR_DF, "e": HOUR_DF + 600, "left": 0, "name": "A007"}
    world, _home = _frames_world(tmp_path, [_tl("Cut", current=item, video=[[item]])])
    out, calls = _run_frames(runner, _script(FRAMES_SHIPPED[3]), world, tmp_path)
    assert "not a multicam" in out and calls == []


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_range_request_sends_each_clips_uses_and_a_multicams_angle_frames(runner, tmp_path):
    a1 = {"clip": A007, "s": HOUR_DF, "e": HOUR_DF + 100, "left": 50, "name": "A007"}
    a2 = {"clip": A007, "s": HOUR_DF + 300, "e": HOUR_DF + 400, "left": 900, "name": "A007"}
    outside = {"clip": FX3, "s": HOUR_DF + 5000, "e": HOUR_DF + 5100, "left": 0, "name": "fx3"}
    mc = {"clip": MC_CLIP, "s": HOUR_DF + 100, "e": HOUR_DF + 300, "left": 1000, "name": MC_ITEM_NAME}
    cut = _tl("Cut", video=[[a1, mc, a2, outside]], marks={"video": {"in": 0, "out": 450}})
    angle = _tl(ANGLE_NAME, video=[[{"clip": G011, "s": HOUR_DF, "e": HOUR_DF + 25260, "left": 0,
                                    "name": "G011"}]])
    world, home = _frames_world(tmp_path, [cut, angle])
    _run_frames(runner, _script(FRAMES_SHIPPED[2]), world, tmp_path)
    req, = _frames_requests(home)
    assert req["source"] == "timeline_range"
    by_path = {c["file_path"]: c for c in req["clips"]}
    assert set(by_path) == {A007["path"], G011["path"]}, "the clip outside the marks is left out"
    assert by_path[A007["path"]]["uses"] == [[50, 149], [900, 999]]
    assert by_path[A007["path"]]["frames"] == []
    # The multicam item's first and middle frames, in the angle clip.
    assert by_path[G011["path"]]["frames"] == [1000, 1000 + 99]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_media_pool_request_sends_the_clips_and_refuses_a_multicam(runner, tmp_path):
    world, home = _frames_world(tmp_path, [_tl("Cut")], selected=[A007, MC_CLIP])
    _run_frames(runner, _script(FRAMES_SHIPPED[1]), world, tmp_path)
    req, = _frames_requests(home)
    assert req["source"] == "media_pool"
    clip, = req["clips"]
    assert clip["file_path"] == A007["path"] and clip["frames"] == [] and clip["uses"] == []
    assert len(req["refused"]) == 1 and "has no file of its own" in req["refused"][0]


def test_frames_lua_carries_no_em_dash_and_never_uses_source_start_frame():
    text = _frames_common()
    assert "\u2014" not in text
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    # Read in ONE place, to notice and place a retimed item (item_frame); a clip at normal speed
    # is always worked out from GetLeftOffset.
    assert code.count("GetSourceStartFrame") == 1
    assert "retimed_frame(tonumber(call(item, \"GetSourceStartFrame\"))" in code
    assert "GetLeftOffset" in code


# -- retimed items: numbers read off a live Resolve 21.0.1 timeline, 2026-11-22 ----------------
# (the HMCC Spans timeline of the project the spike was copied from; GetProperty("Speed") was nil
# on every item, so the source span is the only thing that says "retimed")

@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_the_retime_rule_in_lua(runner, tmp_path):
    out = _lib(runner, r"""
print(L.retimed_frame(4146, 4302, 109603, 109759, 109603 + 37, 29.97, 29.97))
print(L.retimed_frame(4477, 4601, 107896, 108021, 107900, 29.97, 29.97))
print(L.retimed_frame(19038, 20931, 108514, 108987, 108524, 119.88, 29.97))
print(L.retimed_frame(5621, 5719, 109379, 109501, 109379, 119.88, 29.97))
print(L.retimed_frame(5621, 5719, 109379, 109501, 109379 + 61, 119.88, 29.97))
print(L.retimed_frame(nil, nil, 109379, 109501, 109400, 119.88, 29.97))
""", tmp_path)
    # Normal speed: the spans agree to a frame or two, so the left-offset rule stands (nil).
    assert out[0:3] == ["nil", "nil", "nil"]
    # The slow-motion item: 122 timeline frames over 98 source frames, placed from its own start.
    assert out[3:5] == ["5621", "5670"]
    # A Resolve that cannot say is not "retimed".
    assert out[5] == "nil"


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_playhead_on_a_retimed_item_is_placed_from_its_source_range_and_marked_inexact(runner, tmp_path):
    """The left-offset rule on this item says round((7027 + 61) * 4) = 28352, on a clip of 6,540
    frames: the companion would refuse it as outside the clip, or fetch the wrong frame and say
    it was ready."""
    slow = {"clip": FX3, "s": 109379, "e": 109501, "left": 7027, "src_start": 5621, "src_end": 5719,
            "name": "fx3"}
    cut = _tl("HMCC Spans", current=slow, tc="01:00:51;19", video=[[slow]])
    assert 107892 + 51 * 30 + 19 == 109379 + 62
    world, home = _frames_world(tmp_path, [cut])
    _run_frames(runner, _script(FRAMES_SHIPPED[0]), world, tmp_path)
    clip, = _frames_requests(home)[0]["clips"]
    assert clip["frames"] == [5621 + round(62 * 98 / 122)]
    assert clip["exact"] is False
    assert clip["uses"] == [[5621, 5621 + round(121 * 98 / 122)]]


@needs_lua
@pytest.mark.parametrize("runner", RUNNERS, ids=runner_ids)
def test_a_normal_speed_item_with_real_source_numbers_still_uses_the_left_offset(runner, tmp_path):
    """Row n's own item as the live timeline reports it: left 4147, source 4146..4302 over 156
    frames. Reading the source range must not change its answer."""
    item = {"clip": A007, "s": 109603, "e": 109759, "left": 4147, "src_start": 4146,
            "src_end": 4302, "name": "G008"}
    cut = _tl("HMCC Spans", current=item, tc="01:00:58;08", video=[[item]])
    assert 107892 + 58 * 30 + 8 == 109603 + 37
    world, home = _frames_world(tmp_path, [cut])
    _run_frames(runner, _script(FRAMES_SHIPPED[0]), world, tmp_path)
    clip, = _frames_requests(home)[0]["clips"]
    assert clip["frames"] == [4184] and clip["exact"] is True


def test_a_grading_frame_item_left_under_edit_by_an_earlier_install_is_moved_to_utility(resolve_root):
    """Review, 2026-11-22: under Edit the items are invisible on the Color page. An owned copy
    there is removed, the Utility one written, and a second run changes nothing."""
    edit = resolve_root / "Edit" / "CC Sync"
    edit.mkdir(parents=True)
    old = edit / FRAMES_SHIPPED[0]
    old.write_bytes(rmi.render_scripts()[FRAMES_SHIPPED[0]])
    res = rmi.install_menu_scripts(resolve_root)
    assert res["ok"], res
    assert FRAMES_SHIPPED[0] in res["removed"] and not old.exists()
    assert (resolve_root / "Utility" / "CC Sync" / FRAMES_SHIPPED[0]).is_file()
    again = rmi.install_menu_scripts(resolve_root)
    assert again["installed"] == [] and again["removed"] == []
