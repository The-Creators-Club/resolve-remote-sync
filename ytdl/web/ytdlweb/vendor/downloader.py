"""Core YouTube download logic.

VENDORED VERBATIM from yt-credit-downloader/downloader.py (2026-08-11). The
only edits are the ones the container forced, each marked `# [vendor]`:
yt_dlp is imported lazily inside the functions that use it, and build_opts()
takes a `cookies_file` alongside `cookies_browser` because there is no browser
profile for uid 3000 to read cookies out of. Everything else -- especially the
three redundant metadata channels and the .credits.json sidecar -- is
unchanged, because the downstream DaVinci Resolve credits script reads them.

Downloads a video with yt-dlp and embeds the channel name and video URL into the
file's metadata so a downstream DaVinci Resolve script can read them back and
build a credits timeline automatically.

Metadata is written in three redundant places so it survives regardless of
container and is trivial to read back:
  1. Standard container tags: artist = channel, comment = video URL.
  2. Custom container tags: meta_channel, meta_video_url, meta_channel_url.
  3. A sidecar "<video>.credits.json" file next to the video.

Read it back with ffprobe:
    ffprobe -v quiet -print_format json -show_format video.mp4
...or just read the sidecar .credits.json.
"""

from __future__ import annotations

import json
import os
import subprocess
from fractions import Fraction
from pathlib import Path

# [vendor] yt_dlp is imported inside the functions below, not here -- see
# ytdlweb/vendor/__init__.py. A container venv without it must degrade
# per-route, not turn `import ytdlweb.main` into an ImportError.


# ---- editing-codec safety --------------------------------------------------
# YouTube's *best* streams are VP9 or AV1 video with Opus audio. DaVinci Resolve
# on Windows cannot decode any of those reliably — it renders some frames and
# flashes "Media Offline" on the rest. So we (a) ask YouTube for AVC/AAC when we
# can, and (b) verify the finished file and re-encode it if we still ended up
# with something Resolve chokes on.
EDIT_SAFE_VCODECS = {"h264"}
EDIT_SAFE_ACODECS = {"aac"}

# Hide the console window ffmpeg/ffprobe would otherwise flash when the app runs
# as a frozen GUI .exe.
_NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}

QUALITY_HEIGHTS = {
    "best": None, "2160p": 2160, "1440p": 1440,
    "1080p": 1080, "720p": 720, "480p": 480,
}


def format_selector(quality: str, prefer_avc: bool = True) -> str:
    """Build a yt-dlp format string for a UI quality choice.

    With `prefer_avc`, AVC video + AAC audio are tried first so the merged file
    needs no re-encode at all. YouTube only serves AVC up to 1080p, so anything
    above that asks for the best stream there is and gets converted afterwards.

    YTDL-4 (2026-08-11): the AVC alternatives are prepended ONLY at <=1080p.
    yt-dlp takes the first *satisfiable* alternative, and
    `[height<=2160][vcodec^=avc1]` is satisfied by the 1080p AVC stream nearly
    every video has -- so 1440p/2160p/best used to download 1080p, report
    success, and never reach ensure_edit_ready at all. Silent quality loss with
    no error anywhere.
    """
    if quality == "audio":
        return "bestaudio[acodec^=mp4a]/bestaudio/best" if prefer_avc else "bestaudio/best"

    h = QUALITY_HEIGHTS.get(quality)
    hf = f"[height<={h}]" if h else ""
    generic = f"bestvideo{hf}+bestaudio/best{hf}"
    if not prefer_avc or h is None or h > 1080:
        return generic
    return (f"bestvideo{hf}[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            f"bestvideo{hf}[vcodec^=avc1]+bestaudio/{generic}")


# Kept for callers/tests that still reference the old table.
QUALITY_FORMATS = {q: format_selector(q, prefer_avc=False)
                   for q in (*QUALITY_HEIGHTS, "audio")}


def _credits_action(field: str, meta_key: str):
    """Copy an info-dict field into a custom container tag (meta_<key>)."""
    from yt_dlp.postprocessor.metadataparser import MetadataParserPP  # [vendor] lazy
    return (MetadataParserPP.Actions.INTERPRET, field, f"%(meta_{meta_key})s")


def build_opts(outdir: str, quality: str, container: str = "mp4",
               progress_hook=None, ffmpeg_location: str | None = None,
               edit_codec: str = "h264", cookies_browser: str | None = None,
               cookies_file: str | None = None) -> dict:
    from yt_dlp.postprocessor.metadataparser import MetadataParserPP  # [vendor] lazy

    # For DNxHR we re-encode regardless, so take the highest-quality source
    # available; for H.264 prefer AVC/AAC so the file can be stream-copied.
    fmt = format_selector(quality, prefer_avc=(edit_codec == "h264"))
    audio_only = quality == "audio"

    postprocessors = [
        # 1. Copy channel / urls into custom meta_* tags (runs pre-download so
        #    FFmpegMetadata can pick them up).
        {
            "key": "MetadataParser",
            "when": "pre_process",
            "actions": [
                _credits_action("%(channel,uploader)s", "channel"),
                _credits_action("%(webpage_url)s", "video_url"),
                _credits_action("%(channel_url,uploader_url)s", "channel_url"),
                _credits_action("%(uploader,channel)s", "uploader"),
                # Map channel -> standard artist tag, url -> comment tag.
                (MetadataParserPP.Actions.INTERPRET, "%(channel,uploader)s", "%(artist)s"),
                (MetadataParserPP.Actions.INTERPRET, "%(webpage_url)s", "%(meta_comment)s"),
            ],
        },
        # 2. Embed all of the above into the media file.
        {"key": "FFmpegMetadata", "add_metadata": True},
    ]

    if audio_only:
        postprocessors.append(
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}
        )

    opts = {
        "format": fmt,
        # .NB truncates to N *bytes* — filesystems like NFS cap names at 255
        # bytes, which long CJK titles (3 bytes/char) easily exceed.
        "outtmpl": os.path.join(outdir, "%(uploader).60B - %(title).140B [%(id)s].%(ext)s"),
        "merge_output_format": None if audio_only else container,
        "postprocessors": postprocessors,
        "writethumbnail": False,
        "noplaylist": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "ignoreerrors": False,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,  # progress is reported via progress_hooks instead
        # Resilience against transient YouTube throttling / HTTP 403s.
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "file_access_retries": 5,
        # YouTube now requires solving JS challenges for full-quality formats.
        # Use whichever runtime is installed and allow fetching the solver.
        "js_runtimes": {"deno": {}, "node": {}},
        "remote_components": ["ejs:github"],
    }
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser, None, None, None)
    # [vendor] The container has no browser profile to read, so the NAS-side
    # escape hatch for YouTube bot checks is an exported cookies.txt instead.
    if cookies_file:
        opts["cookiefile"] = cookies_file
    if ffmpeg_location:
        opts["ffmpeg_location"] = ffmpeg_location
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]
    return opts


def _tool(name: str, ffmpeg_location: str | None) -> str:
    """Resolve ffmpeg/ffprobe to the bundled copy when we have one."""
    if ffmpeg_location:
        p = os.path.join(ffmpeg_location, name + (".exe" if os.name == "nt" else ""))
        if os.path.exists(p):
            return p
    return name


def probe_streams(filepath: str, ffmpeg_location: str | None = None) -> dict:
    """ffprobe a file into a dict.

    YTDL-22 (2026-08-11): a failure comes back as `{"_probe_error": why}`, not
    as `{}`. An empty dict is indistinguishable from "this file has no video
    stream", which ensure_edit_ready reads as "audio-only, nothing to fix" -- so
    a container whose /opt/ffmpeg has no ffprobe delivered every VP9/Opus
    download unconverted and silent, the exact Media-Offline-in-Resolve outcome
    this module exists to prevent.
    """
    cmd = [_tool("ffprobe", ffmpeg_location), "-v", "error",
           "-print_format", "json", "-show_streams", filepath]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", **_NO_WINDOW)
    except Exception as exc:  # noqa: BLE001
        return {"_probe_error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"_probe_error": (out.stderr or "").strip()[-300:] or
                f"ffprobe exited {out.returncode}"}
    try:
        return json.loads(out.stdout or "{}")
    except ValueError as exc:
        return {"_probe_error": f"unparseable ffprobe output: {exc}"}


def _same_rate(a, b, tol: float = 0.01) -> bool:
    """Are ffprobe's two frame-rate fields the same rate?

    YTDL-23 (2026-08-11): compared as numbers, not as the raw strings ffprobe
    prints. `24000/1001` vs `24/1` and `30000/1001` vs `2997/100` are the same
    rate written differently; string-comparing them read as VFR and triggered a
    full libx264 re-encode -- generation loss plus minutes of container CPU on a
    file that was already fine. An unreadable or absent rate counts as "same":
    the cost of a missed VFR fix is smaller than the cost of re-encoding
    everything that fails to parse.
    """
    try:
        fa, fb = Fraction(str(a)), Fraction(str(b))
    except (TypeError, ValueError, ZeroDivisionError):
        return True
    if fa == fb:
        return True
    if fa <= 0 or fb <= 0:
        return True
    return abs(float(fa) - float(fb)) <= tol * max(float(fa), float(fb))


def _color_args(v: dict) -> list[str]:
    """Carry the source's colour tags across a re-encode."""
    args = []
    for flag, key in (("-color_primaries", "color_primaries"),
                      ("-color_trc", "color_transfer"),
                      ("-colorspace", "color_space")):
        val = v.get(key)
        if val and val != "unknown":
            args += [flag, val]
    if v.get("color_range") in ("tv", "pc"):
        args += ["-color_range", v["color_range"]]
    return args


def ensure_edit_ready(filepath: str, edit_codec: str = "h264",
                      ffmpeg_location: str | None = None,
                      on_status=None) -> str:
    """Convert `filepath` to something DaVinci Resolve can actually decode.

    Returns the path of the usable file (the original, if it was already fine).
    A converted file replaces the original — a VP9/AV1/Opus download is not
    worth keeping around once a working version exists.

    edit_codec:
      "h264"  — H.264 High + AAC in .mp4. Streams that are already fine are
                copied, so an AVC/AAC download costs nothing.
      "dnxhr" — DNxHR HQ + 16-bit PCM in .mov. Always re-encodes; big files,
                but the smoothest scrubbing in Resolve.
      "none"  — leave the file exactly as downloaded.
    """
    if edit_codec not in ("h264", "dnxhr") or not filepath or not os.path.exists(filepath):
        return filepath

    probe = probe_streams(filepath, ffmpeg_location)
    # YTDL-22 (2026-08-11): "ffprobe could not answer" is not "there is no video
    # stream". Convert on suspicion instead of shipping a possibly-VP9 file, and
    # treat a failure of that conversion as non-fatal below -- we never learned
    # that it was needed.
    probe_failed = bool(probe.get("_probe_error"))
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and not probe_failed:
        return filepath  # audio-only download; nothing to fix

    vcodec = video.get("codec_name") if video else None
    acodec = audio.get("codec_name") if audio else None
    # A varying average frame rate means VFR timestamps, which Resolve also
    # dislikes — re-encoding to CFR fixes it while we're here.
    vfr = bool(video) and not _same_rate(video.get("avg_frame_rate"),
                                         video.get("r_frame_rate"))

    stem = str(Path(filepath).with_suffix(""))
    if edit_codec == "h264":
        need_v = probe_failed or vcodec not in EDIT_SAFE_VCODECS or vfr
        need_a = probe_failed or (audio is not None and acodec not in EDIT_SAFE_ACODECS)
        if not need_v and not need_a:
            return filepath
        out_ext = ".mp4"
        vargs = (["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                  "-profile:v", "high", "-pix_fmt", "yuv420p", "-fps_mode", "cfr"]
                 + _color_args(video or {})) if need_v else ["-c:v", "copy"]
        aargs = ["-c:a", "aac", "-b:a", "320k"] if need_a else ["-c:a", "copy"]
        muxargs = ["-movflags", "+use_metadata_tags+faststart"]
        label = "H.264"
    else:
        out_ext = ".mov"
        vargs = (["-c:v", "dnxhd", "-profile:v", "dnxhr_hq", "-pix_fmt", "yuv422p",
                  "-fps_mode", "cfr"] + _color_args(video or {}))
        aargs = ["-c:a", "pcm_s16le"]
        muxargs = ["-movflags", "+use_metadata_tags"]
        label = "DNxHR HQ"

    if on_status:
        on_status(f"converting to {label} (was {vcodec or 'unprobeable'}"
                  + (f"/{acodec}" if acodec else "") + ")")

    tmp = f"{stem}.editready{out_ext}"
    cmd = ([_tool("ffmpeg", ffmpeg_location), "-y", "-hide_banner", "-loglevel", "error",
            "-i", filepath, "-map", "0:v:0", "-map", "0:a:0?"]
           + vargs + aargs + ["-map_metadata", "0"] + muxargs + [tmp])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", **_NO_WINDOW)
    except FileNotFoundError:
        return filepath  # no ffmpeg available — keep what we have
    if res.returncode != 0 or not os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
        if probe_failed:
            # YTDL-22 (2026-08-11): this conversion was a guess (ffprobe never
            # said the file needed one, and an audio-only download makes
            # `-map 0:v:0` fail outright). Losing the video over a guess is
            # worse than delivering it as downloaded.
            if on_status:
                on_status("could not probe the codecs and the safety conversion "
                          "failed; kept as downloaded")
            return filepath
        raise RuntimeError("Edit-ready conversion failed: "
                           + (res.stderr or "").strip()[-500:])

    return _swap_in(tmp, stem + out_ext, filepath, on_status)


def _swap_in(tmp: str, final: str, original: str, on_status=None) -> str:
    """Put the converted file at `final` and get rid of `original`.

    Windows refuses to overwrite or delete a file another process holds open —
    if the clip is already in an open Resolve project, os.replace() fails with
    "Access is denied". A plain rename of the locked file *is* allowed, so fall
    back to moving it aside instead of deleting it.
    """
    same = os.path.abspath(final) == os.path.abspath(original)
    try:
        if not same:
            os.remove(original)
        os.replace(tmp, final)
        return final
    except OSError:
        pass

    aside = str(Path(original).with_suffix("")) + ".original" + Path(original).suffix
    try:
        os.replace(original, aside)
        os.replace(tmp, final)
    except OSError:
        # Even the rename failed — keep the converted file under its own name
        # rather than throwing the work away.
        if on_status:
            on_status(f"converted, but could not replace "
                      f"{os.path.basename(original)} — saved as {os.path.basename(tmp)}")
        return tmp

    if on_status:
        on_status(f"original was in use — kept as {os.path.basename(aside)}")
    return final


def _write_sidecar(info: dict, filepath: str) -> str:
    """Write a <video>.credits.json sidecar with the key fields."""
    data = {
        "channel": info.get("channel") or info.get("uploader"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "uploader": info.get("uploader"),
        "video_url": info.get("webpage_url"),
        "title": info.get("title"),
        "video_id": info.get("id"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
    }
    sidecar = str(Path(filepath).with_suffix("")) + ".credits.json"
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return sidecar


# Extensions the post-merge guess below will try, when yt-dlp told us nothing.
_GUESS_EXTS = (".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".mov", ".opus", ".aac")


def _final_filepath(ydl, info: dict) -> str | None:
    """Where the download actually landed, or None if it did not.

    YTDL-15 (2026-08-11): `requested_downloads[0]['filepath']` is what yt-dlp
    records AFTER merging and post-processing; prepare_filename only predicts a
    name, and its five-extension guess list quietly returned a path that does
    not exist (or None) for anything else. The worker then recorded the video as
    downloaded and wrote a ledger row pointing at nothing -- a row that flags
    the clip "already in the fleet" forever and is fixable only by hand-editing
    ytdl.db. **None means the video failed**; a path always exists on disk.
    """
    for d in (info.get("requested_downloads") or []):
        p = d.get("filepath") or d.get("_filename")
        if p and os.path.exists(p):
            return p

    try:
        guess = ydl.prepare_filename(info)
    except Exception:  # noqa: BLE001
        return None
    if not guess:
        return None
    if os.path.exists(guess):
        return guess
    # After a merge/convert the extension differs from the predicted one.
    stem = str(Path(guess).with_suffix(""))
    for ext in _GUESS_EXTS:
        if os.path.exists(stem + ext):
            return stem + ext
    return None


def download(url: str, outdir: str, quality: str = "best",
             container: str = "mp4", progress_hook=None,
             ffmpeg_location: str | None = None,
             write_sidecar: bool = False, edit_codec: str = "h264",
             on_status=None, cookies_browser: str | None = None,
             cookies_file: str | None = None) -> dict:
    """Download `url` into `outdir`. Returns a summary dict.

    The channel name and video URL are always embedded in the media file
    (artist + comment tags). The optional .credits.json sidecar is off by
    default — the embedded tags are enough for the Resolve credits script.

    `edit_codec` guarantees the result is decodable by DaVinci Resolve; see
    ensure_edit_ready().
    """
    import yt_dlp  # [vendor] lazy

    os.makedirs(outdir, exist_ok=True)
    opts = build_opts(outdir, quality, container, progress_hook, ffmpeg_location,
                      edit_codec, cookies_browser, cookies_file)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = _final_filepath(ydl, info)

    if filepath and quality != "audio":
        filepath = ensure_edit_ready(filepath, edit_codec, ffmpeg_location, on_status)

    sidecar = _write_sidecar(info, filepath) if (write_sidecar and filepath) else None
    return {
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "video_url": info.get("webpage_url"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "filepath": filepath,
        "sidecar": sidecar,
    }


def probe_info(url: str) -> dict:
    """Fetch metadata + available heights without downloading (for the UI)."""
    import yt_dlp  # [vendor] lazy

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    heights = sorted({f.get("height") for f in info.get("formats", [])
                      if f.get("height")}, reverse=True)
    return {
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "heights": heights,
    }
