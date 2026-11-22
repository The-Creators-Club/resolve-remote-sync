"""Guarded connection to the running Resolve for the grading-frames spike.
CR-68: scriptapp() only when the script server has a registered host."""
import io, os, sys
if hasattr(sys.stdout, "buffer") and getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
from ccsync_companion import script_server

def connect():
    ok = script_server.ready_to_connect()
    if not ok:
        raise SystemExit("script server not ready: %r" % (script_server.state(),))
    api = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
    os.environ.setdefault("RESOLVE_SCRIPT_API", api)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
    sys.path.append(os.path.join(api, "Modules"))
    import DaVinciResolveScript as d
    r = d.scriptapp("Resolve")
    if r is None:
        raise SystemExit("scriptapp returned None")
    return r
