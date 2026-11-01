-- Shared body of the CC Sync "originals on request" menu scripts
-- (docs/SELECTIVE_ORIGINALS.md section 12). NOT installed on its own: the
-- companion's resolve_menu_install.py splices this file into each entry
-- script at the @@CCSYNC_COMMON@@ line, so every installed script is one
-- self-contained file. dofile() relative to the script was rejected because
-- nothing documents what chunk name Resolve's menu runner gives a script
-- (debug.getinfo(1, "S").source may be "@<path>", "=?" or the source text),
-- and a menu item that fails to find its module fails with nothing on screen.
--
-- Written for Lua 5.1 and LuaJIT 2.x alike (README: "Lua 5.1"; Fusion embeds
-- LuaJIT): no goto, no integer division, no utf8 library, no bit ops.
--
-- The entry script defines CCSYNC_ACTION ("add" | "remove") and
-- CCSYNC_SCOPE ("media_pool" | "timeline_range" | "timeline_all") before
-- this body runs.

local function say(msg)
  -- print() lands in Workspace > Console. A UIManager window was considered
  -- and left out: its dispatcher loop blocks the script until closed, and
  -- nothing here can be checked against a running Resolve before it ships.
  print("CC Sync: " .. msg)
end

local function json_string(s)
  if s == nil then
    return "null"
  end
  s = tostring(s)
  -- Byte ranges, not %c: under plain Lua %c is iscntrl() in the C locale of
  -- the host, which is free to classify bytes >= 0x80 as control and would
  -- then shred UTF-8 names (Matej Šimalčík) into \u00XX escapes. Bytes
  -- >= 0x80 pass through untouched; the file is UTF-8 because Resolve's
  -- strings are.
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

-- The scripting API hands lists to Lua as tables keyed 1..n, but nothing
-- promises pairs() visits them in order, and the request should list clips
-- in the order the user sees them.
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

-- A Resolve call that raises (a stale object after a project switch, a
-- method an older build lacks) must cost one field, never the whole run.
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

local function clip_record(mpi)
  local path = call(mpi, "GetClipProperty", "File Path")
  if type(path) ~= "string" then path = "" end
  local kind = call(mpi, "GetClipProperty", "Type")
  if type(kind) ~= "string" then kind = "" end
  local uid = call(mpi, "GetUniqueId")
  local name = call(mpi, "GetName")
  return {
    file_path = path,
    unique_id = uid and tostring(uid) or "",
    name = name and tostring(name) or "",
    type = kind,
  }
end

local function collector()
  local seen, list = {}, {}
  local function add(mpi)
    if mpi == nil then
      return
    end
    local rec = clip_record(mpi)
    -- An id-less clip (should not happen) still de-duplicates on what it
    -- has, so one clip cut into a timeline forty times is one entry.
    local key = rec.unique_id ~= "" and ("id:" .. rec.unique_id)
      or ("p:" .. rec.file_path .. "|" .. rec.name)
    if not seen[key] then
      seen[key] = true
      list[#list + 1] = rec
    end
  end
  return add, list
end

local TRACK_TYPES = { "video", "audio" }

local function each_item(timeline, fn)
  for _, track_type in ipairs(TRACK_TYPES) do
    local count = tonumber(call(timeline, "GetTrackCount", track_type)) or 0
    for index = 1, count do
      for _, item in ipairs(ordered_values(call(timeline, "GetItemListInTrack", track_type, index))) do
        fn(item)
      end
    end
  end
end

-- Timeline:GetMarkInOut() is undocumented on its frame base. The README's
-- example ({'video': {'in': 0, 'out': 134}}) reads as 0-based from the
-- timeline's start, which cannot be an absolute frame on a default
-- 01:00:00:00 timeline (start 86400), while TimelineItem:GetStart() is
-- documented as "the start frame position on the timeline", i.e. absolute.
-- So marks are read as relative and offset by GetStartFrame(), UNLESS the
-- relative reading lands past the timeline's end while the absolute reading
-- fits, which only an absolute value can do. Both readings agree on a
-- timeline that starts at frame 0. Not verified against a running Resolve
-- (section 10 of the plan).
local function mark_range(timeline)
  local marks = call(timeline, "GetMarkInOut")
  if type(marks) ~= "table" then
    return nil
  end
  local m = marks.video
  if type(m) ~= "table" or m["in"] == nil or m.out == nil then
    m = marks.audio
  end
  if type(m) ~= "table" then
    return nil
  end
  local mark_in, mark_out = tonumber(m["in"]), tonumber(m.out)
  if mark_in == nil or mark_out == nil then
    return nil
  end
  if mark_out < mark_in then
    mark_in, mark_out = mark_out, mark_in
  end
  local start = tonumber(call(timeline, "GetStartFrame")) or 0
  local last = tonumber(call(timeline, "GetEndFrame"))
  if last ~= nil and mark_out + start > last + 1
      and mark_in >= start and mark_out <= last + 1 then
    return mark_in, mark_out
  end
  return mark_in + start, mark_out + start
end

local function overlaps(item, lo, hi)
  local s = tonumber(call(item, "GetStart"))
  local e = tonumber(call(item, "GetEnd"))
  if s == nil or e == nil then
    return false
  end
  -- GetEnd() is the first frame after the item; the Out mark is the last
  -- frame inside the range.
  return s <= hi and e > lo
end

local function home_dir()
  local windows = package.config ~= nil and package.config:sub(1, 1) == "\\"
  if windows then
    return os.getenv("USERPROFILE"), "\\", true
  end
  return os.getenv("HOME"), "/", false
end

local function try_mkdir(dir, windows)
  -- bmd.createdir is Fusion's own and opens no window; os.execute on Windows
  -- flashes a console, so it is the last resort. The companion creates this
  -- folder when it installs the scripts, so neither normally runs.
  if bmd ~= nil and bmd.createdir ~= nil then
    pcall(bmd.createdir, dir)
  end
  local probe = io.open(dir .. (windows and "\\" or "/") .. ".ccsync-probe", "wb")
  if probe then
    probe:close()
    os.remove(dir .. (windows and "\\" or "/") .. ".ccsync-probe")
    return
  end
  if windows then
    os.execute('mkdir "' .. dir .. '" 2>nul')
  else
    os.execute("mkdir -p '" .. dir:gsub("'", "'\\''") .. "' 2>/dev/null")
  end
end

local function write_request(body)
  local home, sep, windows = home_dir()
  if home == nil or home == "" then
    say("could not find your home folder, so the request was not sent.")
    return false
  end
  local dir = home .. sep .. ".ccsync" .. sep .. "requests" .. sep .. "originals"
  math.randomseed(os.time() + math.floor((os.clock() * 1000000) % 1000000))
  -- Plain Lua has no sub-second clock; the random part keeps two runs in the
  -- same second apart.
  local stem = string.format("%.0f-%06d%06d", os.time() * 1000,
    math.random(0, 999999), math.random(0, 999999))
  local final = dir .. sep .. stem .. ".json"
  local tmp = final .. ".tmp"
  local f = io.open(tmp, "wb")
  if f == nil then
    try_mkdir(dir, windows)
    f = io.open(tmp, "wb")
  end
  if f == nil then
    say("could not write to " .. dir .. ", so the request was not sent.")
    return false
  end
  local ok = f:write(body)
  f:close()
  if not ok then
    os.remove(tmp)
    say("could not write the request file.")
    return false
  end
  -- The companion only reads *.json, so it never sees a half-written file.
  local renamed, err = os.rename(tmp, final)
  if not renamed then
    os.remove(tmp)
    say("could not finish the request file (" .. tostring(err) .. ").")
    return false
  end
  return true
end

local function encode(action, source, project_name, timeline_name, clips)
  local parts = {}
  for _, c in ipairs(clips) do
    parts[#parts + 1] = "{\"file_path\": " .. json_string(c.file_path)
      .. ", \"unique_id\": " .. json_string(c.unique_id)
      .. ", \"name\": " .. json_string(c.name)
      .. ", \"type\": " .. json_string(c.type) .. "}"
  end
  return "{\"v\": 1"
    .. ", \"action\": " .. json_string(action)
    .. ", \"source\": " .. json_string(source)
    .. ", \"project\": " .. json_string(project_name)
    .. ", \"timeline\": " .. json_string(timeline_name)
    .. ", \"clips\": [" .. table.concat(parts, ", ") .. "]"
    .. ", \"created_at\": " .. json_string(os.date("!%Y-%m-%dT%H:%M:%SZ"))
    .. "}\n"
end

local function run(action, scope)
  local app = resolve
  if app == nil and Resolve ~= nil then
    local ok, value = pcall(Resolve)
    if ok then app = value end
  end
  if app == nil then
    say("this script runs from inside DaVinci Resolve (Workspace > Scripts).")
    return
  end
  local project = call(call(app, "GetProjectManager"), "GetCurrentProject")
  if project == nil then
    say("no project is open.")
    return
  end
  local project_name = call(project, "GetName")
  project_name = project_name and tostring(project_name) or ""
  local timeline = call(project, "GetCurrentTimeline")
  local timeline_name = timeline and call(timeline, "GetName") or nil
  if timeline_name ~= nil then timeline_name = tostring(timeline_name) end

  local add, clips = collector()
  local source = scope

  if scope == "media_pool" then
    local pool = call(project, "GetMediaPool")
    for _, mpi in ipairs(ordered_values(call(pool, "GetSelectedClips"))) do
      add(mpi)
    end
    if #clips == 0 then
      say("no clips are selected in the media pool. Select some and run this again.")
      return
    end
  else
    if timeline == nil then
      say("no timeline is open.")
      return
    end
    local lo, hi
    if scope == "timeline_range" then
      lo, hi = mark_range(timeline)
      if lo == nil then
        source = "timeline_playhead"
      end
    end
    if source == "timeline_playhead" then
      local item = call(timeline, "GetCurrentVideoItem")
      if item ~= nil then
        add(call(item, "GetMediaPoolItem"))
      end
      if #clips == 0 then
        say("no In and Out marks are set and there is no clip under the playhead.")
        return
      end
    else
      each_item(timeline, function(item)
        if source == "timeline_all" or overlaps(item, lo, hi) then
          add(call(item, "GetMediaPoolItem"))
        end
      end)
      if #clips == 0 then
        if source == "timeline_all" then
          say("this timeline has no clips from the media pool.")
        else
          say("no clips from the media pool sit between the In and Out marks.")
        end
        return
      end
    end
  end

  local body = encode(action, source, project_name, timeline_name, clips)
  if write_request(body) then
    local noun = #clips == 1 and "1 clip" or (tostring(#clips) .. " clips")
    if action == "add" then
      say("asked for the originals of " .. noun .. ". The companion will confirm.")
    else
      say("asked to stop bringing the originals of " .. noun .. ". The companion will confirm.")
    end
  end
end

local ok, err = pcall(run, CCSYNC_ACTION, CCSYNC_SCOPE)
if not ok then
  say("something went wrong, nothing was sent (" .. tostring(err) .. ").")
end
