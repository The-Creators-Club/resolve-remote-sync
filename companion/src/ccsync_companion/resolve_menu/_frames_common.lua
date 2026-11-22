-- Shared body of the CC Sync "grading frames" menu scripts (docs/GRADING_FRAMES.md sections 3.2
-- and 3.3, 2026-11-22). NOT installed on its own: resolve_menu_install.py splices this file into
-- each entry script at the @@CCSYNC_FRAMES_COMMON@@ line, so every installed script is one
-- self-contained file (the same reason as _originals_common.lua: nothing documents the chunk name
-- Resolve's menu runner gives a script, so a dofile() beside it cannot be trusted).
--
-- Written for Lua 5.1 and LuaJIT 2.x alike: no goto, no integer division, no utf8 library, no bit
-- ops. The entry script sets CCSYNC_FRAMES_SCOPE to "playhead" | "timeline_range" | "media_pool" |
-- "goto" before this body runs. "library" defines the functions below and runs nothing: that is
-- how the tests reach the arithmetic.
--
-- The companion never calls Resolve (CR-68). These scripts run INSIDE Resolve at the editor's
-- click, read the timeline, and write a request file; "Go to grading frame" also moves Resolve to
-- the angle timeline, which is the editor's own action.

local function say(msg)
  -- print() lands in Workspace > Console, as in the originals scripts.
  print("CC Sync: " .. msg)
end

local function json_string(s)
  if s == nil then
    return "null"
  end
  s = tostring(s)
  -- Byte ranges, not %c (see _originals_common.lua): bytes >= 0x80 pass through untouched.
  return '"' .. s:gsub('[%z\1-\31"\\]', function(c)
    if c == '"' then return '\\"' end
    if c == "\\" then return "\\\\" end
    if c == "\n" then return "\\n" end
    if c == "\r" then return "\\r" end
    if c == "\t" then return "\\t" end
    if c == "\b" then return "\\b" end
    if c == "\f" then return "\\f" end
    return string.format("\\u%04x", c:byte())
  end) .. '"'
end

local function ordered_values(t)
  local out = {}
  if type(t) ~= "table" then
    return out
  end
  local keys = {}
  for k in pairs(t) do
    keys[#keys + 1] = k
  end
  table.sort(keys, function(a, b)
    local na, nb = tonumber(a), tonumber(b)
    if na and nb then return na < nb end
    if na then return true end
    if nb then return false end
    return tostring(a) < tostring(b)
  end)
  for _, k in ipairs(keys) do
    out[#out + 1] = t[k]
  end
  return out
end

-- A Resolve call that raises must cost one field, never the whole run.
local function call(obj, method, ...)
  if obj == nil then
    return nil
  end
  local fn = obj[method]
  if fn == nil then
    return nil
  end
  local ok, value = pcall(fn, obj, ...)
  if ok then
    return value
  end
  return nil
end

-- ------------------------------------------------------------------------------------------
-- The arithmetic (pure; tested in tests/test_resolve_menu_install.py)
-- ------------------------------------------------------------------------------------------

local function round(x)
  return math.floor(x + 0.5)
end

-- "29.97", "29.97 DF", 23.976 -> the number. Resolve hands rates back as strings.
local function rate(value)
  if type(value) == "number" then return value end
  if type(value) ~= "string" then return nil end
  return tonumber(value:match("^%s*([%d%.]+)"))
end

-- The timecode base: 23.976 -> 24, 29.97 -> 30, 119.88 -> 120.
local function nominal(fps)
  return round(fps)
end

local function drop_count(fps)
  local base = nominal(fps)
  if base == 30 then return 2 end
  if base == 60 then return 4 end
  return 0
end

-- Timecode -> frame number. Drop-frame (a ';' separator, 29.97 or 59.94) counts the frame
-- numbers it skips, so the answer is a real frame count, which is what GetStart() is.
local function tc_to_frames(tc, fps, drop)
  local h, m, s, f = tostring(tc or ""):match("^(%d+)[:;.](%d+)[:;.](%d+)[:;.](%d+)$")
  if h == nil or fps == nil then
    return nil
  end
  h, m, s, f = tonumber(h), tonumber(m), tonumber(s), tonumber(f)
  local base = nominal(fps)
  local total = ((h * 60 + m) * 60 + s) * base + f
  local d = drop and drop_count(fps) or 0
  if d > 0 then
    local minutes = h * 60 + m
    total = total - d * (minutes - math.floor(minutes / 10))
  end
  return total
end

local function frames_to_tc(n, fps, drop)
  if n == nil or fps == nil then
    return nil
  end
  local base = nominal(fps)
  local d = drop and drop_count(fps) or 0
  if d > 0 then
    local per10 = base * 600 - d * 9
    local per1 = base * 60 - d
    local tens = math.floor(n / per10)
    local rem = n % per10
    if rem > d then
      n = n + d * 9 * tens + d * math.floor((rem - d) / per1)
    else
      n = n + d * 9 * tens
    end
  end
  local f = n % base
  local s = math.floor(n / base) % 60
  local m = math.floor(n / (base * 60)) % 60
  local h = math.floor(n / (base * 3600))
  return string.format("%02d:%02d:%02d%s%02d", h, m, s, d > 0 and ";" or ":", f)
end

-- The file frame under timeline frame `playhead` of an item (doc 3.3, 2.4 row n):
--   GetLeftOffset() + (playhead - GetStart()), NEVER GetSourceStartFrame(), which was one frame
--   low in the spike (4146 against 4147, and the frame shown was 4147 + 37).
-- When the clip's rate differs from the timeline's (2.6: a 119.88 fps clip on a 29.97 timeline
-- plays four source frames to one), GetLeftOffset counts TIMELINE frames, so the result is scaled
-- by clip fps / timeline fps and is not exact. -> frame, exact.
local function source_frame(left_offset, playhead, item_start, clip_fps, timeline_fps)
  local m = left_offset + (playhead - item_start)
  if clip_fps ~= nil and timeline_fps ~= nil and math.abs(clip_fps - timeline_fps) > 0.001 then
    return round(m * clip_fps / timeline_fps), false
  end
  return m, true
end

-- A RETIMED ITEM (review against a live Resolve 21.0.1, 2026-11-22). The left-offset rule above
-- holds only at normal speed. A slow-motion clip on the HMCC Spans timeline read: 122 timeline
-- frames, GetLeftOffset 7027, GetSourceStartFrame 5621, GetSourceEndFrame 5719 (a 119.88 fps
-- clip, so the left-offset rule says frame 28108, far outside what is on screen). And nothing
-- says "retimed": GetProperty("Speed") is nil on every item in that build. What does show it is
-- the source span against the timeline span: at normal speed they agree to a frame or two
-- (measured: 124 for 125, 156 for 156, 1893 for 1892 at four source frames to one).
-- So when the span disagrees, the frame is worked out from the item's own source range instead,
--   GetSourceStartFrame + (pos - start) * (source span / timeline span),
-- and marked inexact (GetSourceStartFrame can be a frame low, doc 2.4 row n; the companion
-- fetches a wider margin for an inexact frame). nil when the item is not retimed, or when an
-- older Resolve cannot say: then the left-offset rule stands, as the spike measured it.
local function retimed_frame(src_start, src_end, start, stop, pos, clip_fps, timeline_fps)
  if src_start == nil or src_end == nil or start == nil or stop == nil or stop <= start then
    return nil
  end
  local ratio = 1
  if clip_fps ~= nil and timeline_fps ~= nil and timeline_fps > 0 then
    ratio = clip_fps / timeline_fps
  end
  local span, dur = src_end - src_start, stop - start
  if math.abs(span - dur * ratio) <= 2 + ratio then
    return nil
  end
  return src_start + round((pos - start) * span / dur)
end

-- "<name> Multicam - Angle N" (the Multicam Pipeline's item name) -> name, N.
local function multicam_parts(item_name)
  if type(item_name) ~= "string" then return nil end
  local base, n = item_name:match("^(.-) Multicam %- Angle (%d+)$")
  if base == nil or base == "" then return nil end
  return base, tonumber(n)
end

-- The Multicam Pipeline names an angle timeline "<name> <em dash> ANGLE N (<camera>)". The em dash
-- is written as its UTF-8 bytes: these files carry no em dash character of their own.
local EM_DASH = "\226\128\148"

local function is_angle_timeline(timeline_name, base, n)
  if type(timeline_name) ~= "string" then return false end
  local prefix = base .. " " .. EM_DASH .. " ANGLE " .. tostring(n) .. " ("
  return timeline_name:sub(1, #prefix) == prefix and timeline_name:sub(-1) == ")"
end

CCSYNC_FRAMES_LIB = {
  rate = rate, tc_to_frames = tc_to_frames, frames_to_tc = frames_to_tc,
  source_frame = source_frame, retimed_frame = retimed_frame, multicam_parts = multicam_parts,
  is_angle_timeline = is_angle_timeline, json_string = json_string,
}

-- ------------------------------------------------------------------------------------------
-- Reading Resolve
-- ------------------------------------------------------------------------------------------

local MULTICAM_REFUSAL = "is a multicam this script cannot follow (not built by the Multicam "
  .. "Pipeline, or its angle timeline was renamed). Select the angle's clip in the media pool "
  .. "and use Bring grading frames - selected media pool clips instead."

local function timeline_fps(timeline)
  return rate(call(timeline, "GetSetting", "timelineFrameRate"))
end

local function timeline_drop(timeline)
  local setting = call(timeline, "GetSetting", "timelineDropFrameTimecode")
  if setting ~= nil then
    return tostring(setting) == "1"
  end
  local tc = call(timeline, "GetCurrentTimecode")
  return type(tc) == "string" and tc:find(";") ~= nil
end

local function playhead_frame(timeline)
  local tc = call(timeline, "GetCurrentTimecode")
  return tc_to_frames(tc, timeline_fps(timeline), timeline_drop(timeline)), tc
end

local function find_angle_timeline(project, base, n)
  local count = tonumber(call(project, "GetTimelineCount")) or 0
  local found = nil
  for i = 1, count do
    local tl = call(project, "GetTimelineByIndex", i)
    if is_angle_timeline(call(tl, "GetName"), base, n) then
      if found ~= nil then
        return nil   -- two candidates: refused, never guessed (doc section 9)
      end
      found = tl
    end
  end
  return found
end

local function item_at(timeline, pos)
  local count = tonumber(call(timeline, "GetTrackCount", "video")) or 0
  -- Top track first: the picture the angle shows is the topmost clip.
  for index = count, 1, -1 do
    for _, it in ipairs(ordered_values(call(timeline, "GetItemListInTrack", "video", index))) do
      local s, e = tonumber(call(it, "GetStart")), tonumber(call(it, "GetEnd"))
      if s ~= nil and e ~= nil and s <= pos and pos < e and call(it, "GetMediaPoolItem") ~= nil then
        return it
      end
    end
  end
  return nil
end

-- The file frame under timeline frame `pos` of a plain item -> frame, exact. The left-offset rule
-- (doc 3.3), unless the item is retimed (retimed_frame above). GetSourceStartFrame is read ONLY
-- to notice and place a retimed item, never for a clip at normal speed, where it was a frame low.
local function item_frame(item, pos, clip_fps, tl_fps)
  local left = tonumber(call(item, "GetLeftOffset")) or 0
  local start = tonumber(call(item, "GetStart")) or 0
  local stop = tonumber(call(item, "GetEnd")) or (start + 1)
  local slow = retimed_frame(tonumber(call(item, "GetSourceStartFrame")),
    tonumber(call(item, "GetSourceEndFrame")), start, stop, pos, clip_fps, tl_fps)
  if slow ~= nil then
    return slow, false
  end
  return source_frame(left, pos, start, clip_fps, tl_fps)
end

-- A plain item's record at timeline frame `pos`: the clip, its frame, and the source frames of
-- the item's whole use (first and last), all by the plain-clip rule.
local function plain_at(timeline, item, pos)
  local mpi = call(item, "GetMediaPoolItem")
  local path = call(mpi, "GetClipProperty", "File Path")
  if type(path) ~= "string" or path == "" then
    return nil
  end
  local start = tonumber(call(item, "GetStart")) or 0
  local stop = tonumber(call(item, "GetEnd")) or (start + 1)
  local clip_fps = rate(call(mpi, "GetClipProperty", "FPS"))
  local tl_fps = timeline_fps(timeline)
  local frame, exact = item_frame(item, pos, clip_fps, tl_fps)
  local first = item_frame(item, start, clip_fps, tl_fps)
  local last = item_frame(item, stop - 1, clip_fps, tl_fps)
  -- Speed is nil on every item in Resolve 21.0.1 (checked live, 2026-11-22), which is why
  -- item_frame reads the source span instead. Kept for a build that does answer it.
  local speed = rate(call(item, "GetProperty", "Speed"))
  if speed ~= nil and math.abs(speed - 100) > 0.001 then
    exact = false
  end
  local uid = call(mpi, "GetUniqueId")
  local name = call(mpi, "GetName")
  return {
    file_path = path, unique_id = uid and tostring(uid) or "", name = name and tostring(name) or "",
    frame = frame, first = first, last = last, exact = exact,
    clip_fps = clip_fps, timeline_fps = tl_fps,
  }
end

-- What is under timeline frame `pos` of `item`: a plain clip by the plain rule, or a Multicam
-- Pipeline multicam resolved to its angle clip (doc 3.3, 2.4 row o):
--   m = GetLeftOffset() + (pos - GetStart()) is the frame inside the multicam; the angle comes
--   from the item's name; the angle timeline by the pipeline's naming; its frame
--   angle:GetStartFrame() + m falls in an item there, which gives the clip and its frame.
-- -> record, or nil and the refusal clause.
local function resolve_at(project, timeline, item, pos)
  local rec = plain_at(timeline, item, pos)
  if rec ~= nil then
    return rec
  end
  local item_name = call(item, "GetName")
  local base, n = multicam_parts(item_name)
  if base == nil then
    return nil, tostring(item_name or "the clip") .. " " .. MULTICAM_REFUSAL
  end
  local angle = find_angle_timeline(project, base, n)
  if angle == nil then
    return nil, tostring(item_name) .. " " .. MULTICAM_REFUSAL
  end
  local m = (tonumber(call(item, "GetLeftOffset")) or 0) + (pos - (tonumber(call(item, "GetStart")) or 0))
  local angle_pos = (tonumber(call(angle, "GetStartFrame")) or 0) + m
  local inner = item_at(angle, angle_pos)
  if inner == nil then
    return nil, tostring(item_name) .. " has no clip in its angle timeline at that frame."
  end
  rec = plain_at(angle, inner, angle_pos)
  if rec == nil then
    return nil, tostring(item_name) .. " " .. MULTICAM_REFUSAL
  end
  -- The use of THIS multicam item, carried into the angle clip and kept inside it.
  local s = tonumber(call(item, "GetStart")) or pos
  local e = tonumber(call(item, "GetEnd")) or (pos + 1)
  local inner_s = tonumber(call(inner, "GetStart")) or angle_pos
  local inner_e = tonumber(call(inner, "GetEnd")) or (angle_pos + 1)
  local offset = angle_pos - pos
  local lo = math.max(s + offset, inner_s)
  local hi = math.min(e - 1 + offset, inner_e - 1)
  local clip_fps, tl_fps = rec.clip_fps, rec.timeline_fps
  rec.first = item_frame(inner, lo, clip_fps, tl_fps)
  rec.last = item_frame(inner, hi, clip_fps, tl_fps)
  rec.angle_timeline = tostring(call(angle, "GetName") or "")
  rec.angle_timecode = frames_to_tc(angle_pos, timeline_fps(angle) or tl_fps, timeline_drop(angle))
  rec.angle = angle
  rec.angle_pos = angle_pos
  return rec
end

-- ------------------------------------------------------------------------------------------
-- The request file (doc 3.4; SELECTIVE_ORIGINALS.md 12.2's contract, into requests/frames)
-- ------------------------------------------------------------------------------------------

local function home_dir()
  local windows = package.config ~= nil and package.config:sub(1, 1) == "\\"
  if windows then
    return os.getenv("USERPROFILE"), "\\", true
  end
  return os.getenv("HOME"), "/", false
end

local function write_request(body)
  local home, sep, windows = home_dir()
  if home == nil or home == "" then
    say("could not find your home folder, so the request was not sent.")
    return false
  end
  local dir = home .. sep .. ".ccsync" .. sep .. "requests" .. sep .. "frames"
  math.randomseed(os.time() + math.floor((os.clock() * 1000000) % 1000000))
  local stem = string.format("%.0f-%06d%06d", os.time() * 1000,
    math.random(0, 999999), math.random(0, 999999))
  local final = dir .. sep .. stem .. ".json"
  local tmp = final .. ".tmp"
  local f = io.open(tmp, "wb")
  if f == nil and bmd ~= nil and bmd.createdir ~= nil then
    -- The companion creates this folder when it installs the scripts; this is the fallback.
    pcall(bmd.createdir, dir)
    f = io.open(tmp, "wb")
  end
  if f == nil then
    say("could not write to " .. dir .. ", so the request was not sent. Is CC Sync running?")
    return false
  end
  local ok = f:write(body)
  f:close()
  if not ok then
    os.remove(tmp)
    say("could not write the request file.")
    return false
  end
  local renamed, err = os.rename(tmp, final)
  if not renamed then
    os.remove(tmp)
    say("could not finish the request file (" .. tostring(err) .. ").")
    return false
  end
  return true
end

local function num(n)
  if n == nil then return "null" end
  if n == math.floor(n) then return string.format("%d", n) end
  return string.format("%.6g", n)
end

local function encode(source, project_name, timeline_name, clips, refused)
  local parts = {}
  for _, c in ipairs(clips) do
    local frames, uses = {}, {}
    for _, f in ipairs(c.frames) do frames[#frames + 1] = num(f) end
    for _, u in ipairs(c.uses) do uses[#uses + 1] = "[" .. num(u[1]) .. ", " .. num(u[2]) .. "]" end
    parts[#parts + 1] = "{\"file_path\": " .. json_string(c.file_path)
      .. ", \"unique_id\": " .. json_string(c.unique_id)
      .. ", \"name\": " .. json_string(c.name)
      .. ", \"frames\": [" .. table.concat(frames, ", ") .. "]"
      .. ", \"uses\": [" .. table.concat(uses, ", ") .. "]"
      .. ", \"clip_fps\": " .. num(c.clip_fps)
      .. ", \"timeline_fps\": " .. num(c.timeline_fps)
      .. ", \"exact\": " .. (c.exact and "true" or "false")
      .. ", \"timecode\": " .. json_string(c.timecode)
      .. ", \"angle_timeline\": " .. json_string(c.angle_timeline)
      .. ", \"angle_timecode\": " .. json_string(c.angle_timecode) .. "}"
  end
  local why = {}
  for _, r in ipairs(refused) do why[#why + 1] = json_string(r) end
  return "{\"v\": 1"
    .. ", \"source\": " .. json_string(source)
    .. ", \"project\": " .. json_string(project_name)
    .. ", \"timeline\": " .. json_string(timeline_name)
    .. ", \"clips\": [" .. table.concat(parts, ", ") .. "]"
    .. ", \"refused\": [" .. table.concat(why, ", ") .. "]"
    .. ", \"created_at\": " .. json_string(os.date("!%Y-%m-%dT%H:%M:%SZ"))
    .. "}\n"
end

-- One entry per file, uses and frames merged (a clip cut in three times is one fetch).
local function collector()
  local by_path, list = {}, {}
  local function add(rec, frame, use, timecode)
    local c = by_path[rec.file_path]
    if c == nil then
      c = { file_path = rec.file_path, unique_id = rec.unique_id, name = rec.name, frames = {},
            uses = {}, clip_fps = rec.clip_fps, timeline_fps = rec.timeline_fps, exact = rec.exact,
            timecode = timecode, angle_timeline = rec.angle_timeline,
            angle_timecode = rec.angle_timecode }
      by_path[rec.file_path] = c
      list[#list + 1] = c
    end
    c.exact = c.exact and rec.exact
    if frame ~= nil then c.frames[#c.frames + 1] = frame end
    if use ~= nil then c.uses[#c.uses + 1] = use end
  end
  return add, list
end

-- Timeline:GetMarkInOut(), read exactly as _originals_common.lua reads it (relative to the
-- timeline's start unless only the absolute reading fits).
local function mark_range(timeline)
  local marks = call(timeline, "GetMarkInOut")
  if type(marks) ~= "table" then return nil end
  local m = marks.video
  if type(m) ~= "table" or m["in"] == nil or m.out == nil then m = marks.audio end
  if type(m) ~= "table" then return nil end
  local mark_in, mark_out = tonumber(m["in"]), tonumber(m.out)
  if mark_in == nil or mark_out == nil then return nil end
  if mark_out < mark_in then mark_in, mark_out = mark_out, mark_in end
  local start = tonumber(call(timeline, "GetStartFrame")) or 0
  local last = tonumber(call(timeline, "GetEndFrame"))
  if last ~= nil and mark_out + start > last + 1 and mark_in >= start and mark_out <= last + 1 then
    return mark_in, mark_out
  end
  return mark_in + start, mark_out + start
end

local function noun(n)
  return n == 1 and "1 clip" or (tostring(n) .. " clips")
end

-- ------------------------------------------------------------------------------------------
-- The four menu items
-- ------------------------------------------------------------------------------------------

local function open_project()
  local app = resolve
  if app == nil and Resolve ~= nil then
    local ok, value = pcall(Resolve)
    if ok then app = value end
  end
  if app == nil then
    say("this script runs from inside DaVinci Resolve (Workspace > Scripts).")
    return nil
  end
  local project = call(call(app, "GetProjectManager"), "GetCurrentProject")
  if project == nil then
    say("no project is open.")
  end
  return project
end

local function run_goto(project, timeline)
  local item = call(timeline, "GetCurrentVideoItem")
  if item == nil then
    say("there is no clip under the playhead.")
    return
  end
  local pos = playhead_frame(timeline)
  if pos == nil then
    say("could not read the playhead's timecode.")
    return
  end
  local rec, why = resolve_at(project, timeline, item, pos)
  if rec == nil then
    say(why)
    return
  end
  if rec.angle == nil then
    say("the clip under the playhead is not a multicam: its Camera Raw panel is live right here, "
      .. "on the Color page.")
    return
  end
  if not call(project, "SetCurrentTimeline", rec.angle) then
    say("could not open the angle timeline " .. rec.angle_timeline .. ".")
    return
  end
  if not call(rec.angle, "SetCurrentTimecode", rec.angle_timecode) then
    say("opened " .. rec.angle_timeline .. ", but could not move the playhead to "
      .. tostring(rec.angle_timecode) .. ".")
    return
  end
  say("opened " .. rec.angle_timeline .. " at " .. rec.angle_timecode
    .. ". Change the raw settings on the Color page here; the multicam shows them.")
end

local function run(scope)
  local project = open_project()
  if project == nil then return end
  local project_name = call(project, "GetName")
  project_name = project_name and tostring(project_name) or ""
  local timeline = call(project, "GetCurrentTimeline")
  local timeline_name = timeline and call(timeline, "GetName") or nil
  if timeline_name ~= nil then timeline_name = tostring(timeline_name) end
  if scope ~= "media_pool" and timeline == nil then
    say("no timeline is open.")
    return
  end
  if scope == "goto" then
    run_goto(project, timeline)
    return
  end

  local add, clips = collector()
  local refused = {}
  local source = scope

  if scope == "playhead" then
    local item = call(timeline, "GetCurrentVideoItem")
    if item == nil then
      say("there is no clip under the playhead.")
      return
    end
    local pos, tc = playhead_frame(timeline)
    if pos == nil then
      say("could not read the playhead's timecode.")
      return
    end
    local rec, why = resolve_at(project, timeline, item, pos)
    if rec == nil then
      say(why)
      return
    end
    add(rec, rec.frame, { rec.first, rec.last }, tc)
  elseif scope == "media_pool" then
    local pool = call(project, "GetMediaPool")
    for _, mpi in ipairs(ordered_values(call(pool, "GetSelectedClips"))) do
      local path = call(mpi, "GetClipProperty", "File Path")
      local name = call(mpi, "GetName")
      if type(path) == "string" and path ~= "" then
        local uid = call(mpi, "GetUniqueId")
        add({ file_path = path, unique_id = uid and tostring(uid) or "",
              name = name and tostring(name) or "", exact = true,
              clip_fps = rate(call(mpi, "GetClipProperty", "FPS")) }, nil, nil, nil)
      else
        refused[#refused + 1] = tostring(name or "a clip") .. " has no file of its own (a multicam "
          .. "or compound clip). Select its angle clips instead."
      end
    end
    if #clips == 0 and #refused == 0 then
      say("no clips are selected in the media pool. Select some and run this again.")
      return
    end
  else
    local lo, hi = mark_range(timeline)
    if lo == nil then
      source = "timeline_all"
    end
    local count = tonumber(call(timeline, "GetTrackCount", "video")) or 0
    for index = 1, count do
      for _, item in ipairs(ordered_values(call(timeline, "GetItemListInTrack", "video", index))) do
        local s, e = tonumber(call(item, "GetStart")), tonumber(call(item, "GetEnd"))
        if s ~= nil and e ~= nil and (lo == nil or (s <= hi and e > lo))
            and call(item, "GetMediaPoolItem") ~= nil then
          local rec = plain_at(timeline, item, s)
          if rec ~= nil then
            add(rec, nil, { rec.first, rec.last }, nil)
          else
            -- A multicam: its angle clip at the item's first and middle frames (D1), each one a
            -- frame asked for in that clip.
            for _, pos in ipairs({ s, s + math.floor((e - 1 - s) / 2) }) do
              local inner, why = resolve_at(project, timeline, item, pos)
              if inner ~= nil then
                add(inner, inner.frame, nil, nil)
              elseif why ~= nil then
                refused[#refused + 1] = why
                break
              end
            end
          end
        end
      end
    end
    if #clips == 0 and #refused == 0 then
      say(lo == nil and "this timeline has no clips from the media pool."
        or "no clips from the media pool sit between the In and Out marks.")
      return
    end
  end

  if #clips == 0 then
    say(refused[1])
    return
  end
  local body = encode(source, project_name, timeline_name, clips, refused)
  if write_request(body) then
    say("asked for grading frames of " .. noun(#clips) .. ". The companion will confirm.")
  end
end

if CCSYNC_FRAMES_SCOPE ~= "library" then
  local ok, err = pcall(run, CCSYNC_FRAMES_SCOPE)
  if not ok then
    say("something went wrong, nothing was sent (" .. tostring(err) .. ").")
  end
end
