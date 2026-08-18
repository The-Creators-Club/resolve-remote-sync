"""The music ingest orchestrator: this machine embedding its editor's drop.

docs/MUSIC_INGEST_PLAN.md, 2026-08-18. An editor drags an album onto the
dashboard's music page; the browser creates a batch and hands the uid to this
companion over the loopback; THIS object claims it on the fleet routes and does
the analysis locally -- ffprobe, an .ogg transcode, the waveform, and the CLAP
audio embedding through `music_clap_sidecar` -- before rclone puts the audio in
the library and the server turns the vector into a tagged, searchable track.

**It is `BrollIngestor` with a different per-item pipeline, deliberately.**
Everything that is hard about this feature -- the gate, the run mode, the
checkpoints, the resumable state file, the lease and its 410, the upload queue,
the progress window, the tray surfaces -- is the same problem, was solved once,
and is tested by ~2,300 lines that must keep passing. What is genuinely
different is four steps of work and one HTTP body, and they are here.

The three ways music differs, all of them consequences of not needing a GPU:

  * **It never blocks proxy generation** (`kind.blocks_proxies` is False). The
    audio tower is ~90 ms per 10 s window on one CPU core; standing the proxy
    generator down for that would trade a real bottleneck for an imaginary one.
  * **There is no tier and no VRAM refusal.** One artefact, and a laptop with
    integrated graphics runs it perfectly well.
  * **There is a fallback that b-roll has no equivalent of.** A machine whose
    sidecar cannot run (a build with no onnxruntime, a fleet with no release
    feed, a model download that will not complete) refuses the CLAIM, and the
    page falls back to the browser upload that lands the file in the library
    and leaves a base-rig queue row -- the loop that existed before this
    feature and still works. An item that fails that way MID-batch is uploaded
    and left `queued_for_base_rig`: the audio is in the library, the ledger
    says who has to finish it, and nothing is lost.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from . import broll_ingest
from . import broll_upload
from . import ingest_kinds
from . import music_clap_sidecar

log = logging.getLogger("ccsync.musicingest")

# `musicweb.ingest_batches.ITEM_PROGRESS`, and a stage this side invents is a
# 400 from the server's transition check.
ITEM_PENDING = "pending"
ITEM_TRANSCODING = "transcoding"
ITEM_EMBEDDING = "embedding"
ITEM_INDEXED = "indexed"
ITEM_UPLOADING = "uploading"
ITEM_LIVE = "live"
# The fallback ending (plan §1, rejected option (a) kept as the safety net).
ITEM_QUEUED_FOR_BASE_RIG = "queued_for_base_rig"

# Where the library sits under the rclone remote's root when the server did not
# say. It always says (`claim` answers `library_remote_rel`), so this is the
# value for a dashboard older than the fleet routes -- never a local path.
LIBRARY_REMOTE_REL = "Assets/Music"

# What an uploaded track is, for the upload queue's ordering. One file per
# item, so the order never actually matters; it is named rather than reusing
# KIND_ORIGINAL because a transcoded .ogg is not the original.
KIND_AUDIO = "audio"


class MusicIngestor(broll_ingest.BrollIngestor):
    """One machine's music ingest. See the module docstring for what it adds.

    Constructed exactly like `BrollIngestor` (the app passes the same seams),
    with the music kind and the CLAP sidecar wired in by default.
    """

    def __init__(self, cfg: dict[str, Any], state_dir: Any, **kwargs) -> None:
        kwargs.setdefault("kind", ingest_kinds.MUSIC_KIND)
        kwargs.setdefault("sidecar", music_clap_sidecar)
        # blake2b-16 over the whole file, NOT b-roll's xxh64 head+tail: the
        # server compares this against `tracks.file_hash` and the base-rig
        # queue, so the digest is a wire contract (`musicweb.db.content_hash`).
        kwargs.setdefault("hash_fn", music_clap_sidecar.content_hash)
        super().__init__(cfg, state_dir, **kwargs)

    # -- the model ---------------------------------------------------------
    def _tier(self) -> str:
        """Music has none. "" rather than "good", so nothing downstream can
        read a b-roll tier off a music batch."""
        return ""

    def _fits(self, tier: str) -> tuple[bool, str]:
        """Can this machine embed at all? -> (fits, refusal).

        Not a hardware question here (that is the whole point of exporting the
        tower): the only ways to answer no are a build with no onnxruntime, a
        fleet with no release feed to fetch the artefact from, and a catalogue
        whose sha256 is still a placeholder. All three are permanent until
        somebody changes something, which is exactly what `tier-unfit` means
        to the gate and to the page.
        """
        try:
            refusal = self.sidecar.refusal(self.cfg)
        except Exception:  # noqa: BLE001
            self.log.debug("the sidecar refusal check failed", exc_info=True)
            return False, ("this machine could not be checked for the music "
                           "indexing model")
        return (not refusal), refusal

    def _model_ready(self, tier: str) -> bool:
        try:
            snapshot = self.sidecar.status()
        except Exception:  # noqa: BLE001
            self.log.debug("the sidecar snapshot failed", exc_info=True)
            return False
        # `runtime_ready` is None until something has asked onnxruntime; that
        # is "not known", not "no", and `_fits` above is what refuses a build
        # that really cannot run it.
        return bool(snapshot.get("ready")) and snapshot.get("runtime_ready") is not False

    def _fetch_model(self) -> None:
        """Download the artefact, with progress, on the tick thread.

        Its own method rather than the base's because the two sidecars take
        different arguments: b-roll's `ensure(tier)` picks a tier, and there is
        no tier here.
        """
        # Same two balloons as the b-roll fetch (BrollIngestor._fetch_model):
        # one before the bytes, one when the model is in.
        fetching = not self._model_ready("")
        if fetching:
            self._say(self._download_started_text(""))
        with self._lock:
            self._model_note = "downloading"
        ok, message = self.sidecar.ensure(self.cfg, stop_event=self._stop_event)
        with self._lock:
            self._model_note = "" if ok else message
        if ok:
            self.log.info("%s", message)
            self._clear_warning()
            if fetching:
                self._say("The music indexing model is ready. Indexing starts now.")
        else:
            self.log.warning("the model is not ready - %s", message)

    def _download_snapshot(self) -> dict[str, Any]:
        """The model download as the progress window's headline.

        The artefact's FILENAME is what the sidecar reports (it downloads two
        files and says which); the window says "the music indexing model"
        instead, because `music-clap-audio-1.onnx` is a true answer to a
        question no editor asked.
        """
        try:
            downloading = self.sidecar.status().get("downloading") or {}
        except Exception:  # noqa: BLE001
            return {}
        if not downloading:
            return {}
        return {"percent": downloading.get("percent"),
                "name": "the music indexing model",
                "rate_bytes_per_s": downloading.get("rate_bytes_per_s"),
                "eta_seconds": downloading.get("eta_seconds")}

    # -- the work order ----------------------------------------------------
    def _remote_rel(self, parsed: dict) -> str:
        return str(parsed.get("library_remote_rel") or LIBRARY_REMOTE_REL)

    def _item_from_manifest(self, entry: dict, staging: Optional[dict]) -> dict:
        """One manifest row plus whatever this machine knows about the file.

        Matched to a staged file by NAME alone: a music drop is flat (the
        library has no folders -- `db.unique_dest` lands everything under the
        share root), so there is no rel_dir to disambiguate with and none to
        carry.
        """
        local_path = ""
        for candidate in ((staging or {}).get("items") or {}).values():
            if candidate.get("name") == entry.get("orig_name"):
                local_path = str(candidate.get("path") or "")
                break
        return {
            "uid": entry.get("uid"), "track_id": entry.get("track_id"),
            "ord": entry.get("ord"), "name": entry.get("orig_name") or "",
            "rel_dir": "",
            "source": entry.get("source") or "upload",
            "local_path": local_path, "thumb": "",
            "hash": entry.get("content_hash"), "probe": None,
            # The name the SERVER allocated, once it has (at `result`). Never
            # guessed here: two items of one drop called `theme.wav` are
            # `theme.wav` and `theme (2).wav`, and only the ledger knows which
            # is which.
            "dest_name": entry.get("dest_name") or "",
            "duration_s": entry.get("duration_s"),
            "size_bytes": entry.get("size_bytes"),
            "duplicate_of": entry.get("duplicate_of"),
            "stage": (broll_ingest.ITEM_DUPLICATE
                      if entry.get("state") == broll_ingest.ITEM_DUPLICATE
                      else entry.get("state") or ITEM_PENDING),
            "outputs": {}, "uploads": {}, "uploaded": [],
            "original_uploaded": False,
            "transcoded": False,
            "attempts": int(entry.get("attempts") or 0), "error": "",
            "seconds": None,
        }

    # -- probing and checkpoints -------------------------------------------
    def _probe(self, path: Any) -> dict:
        """ffprobe, in the shape `musicweb` stores.

        The keys are the server's column names (`_apply_probe`'s
        `duration_s/samplerate/channels/codec`), mapped here rather than at
        three call sites -- and `duration_s` is ffprobe's answer, which is
        good enough to show a length in the drop list and NOT good enough to
        record: the duration that lands on the row comes from the decoded
        sample count (see `_crunch_item`).
        """
        if self._probe_fn is not None:
            return self._probe_fn(self.ffmpeg_path, path)
        # Through `self.sidecar`, not the module: the sidecar is an injected
        # seam so the whole pipeline can be driven on a machine with no ffmpeg
        # and no model, exactly as b-roll's `media` seam is.
        probed = self.sidecar.probe(self.ffmpeg_path, path)
        return {
            "duration_s": probed.get("duration"),
            "samplerate": probed.get("samplerate"),
            "channels": probed.get("channels"),
            "codec": probed.get("codec"),
        }

    def _status_fields(self, item: dict) -> dict[str, Any]:
        """`content_hash`, not `hash`: ItemStatusIn (docs/API.md §6b) declares
        the first and pydantic silently drops the second."""
        return {"attempts": item.get("attempts"),
                "content_hash": item.get("hash"),
                "transcoded": bool(item.get("transcoded")),
                "probe": item.get("probe")}

    # -- the per-track pipeline --------------------------------------------
    def _crunch_item(self, item: dict) -> None:
        """One track, checkpointed at every stage.

        probe -> (.ogg transcode) -> decode + waveform + CLAP embed -> result
        -> upload. Each stage checks `_should_stop()` first, so an editor
        coming back costs at most the stage in flight.
        """
        name = item.get("name") or ""
        self._set_current(name, item.get("stage") or ITEM_PENDING, 0)
        item["attempts"] = int(item.get("attempts") or 0) + 1

        source = item.get("local_path") or ""
        if not source or not os.path.isfile(source):
            self._fail_item(item, "the source file is not on this machine any more")
            return

        # 1. probe + content hash. Both are cheap, both are what the server's
        # two duplicate defences run on, and the hash is what a retry after a
        # failed upload compares against.
        if not item.get("probe"):
            item["probe"] = self._probe(source)
            if not float((item["probe"] or {}).get("duration_s") or 0) > 0:
                self._fail_item(item, "this file has no audio track that could "
                                      "be read")
                return
        if not item.get("hash"):
            try:
                item["hash"] = self._hash_fn(source)
            except OSError as exc:
                self._fail_item(item, f"this file could not be read ({exc})")
                return

        outputs = item.setdefault("outputs", {})

        # 2. .ogg -> 320k mp3, the container's own rule applied HERE so the
        # bytes crossing the wire are the bytes that land.
        audio = outputs.get("audio") or source
        if (not outputs.get("audio")
                and Path(source).suffix.lower() in ingest_kinds.MUSIC_TRANSCODE_EXTS):
            if self._should_stop():
                return
            self._stage(item, ITEM_TRANSCODING, 10)
            try:
                audio = str(self.sidecar.transcode_to_mp3(
                    self.ffmpeg_path, source, self._out_dir(item)))
            except Exception as exc:  # noqa: BLE001 - one track, not the batch
                self._fail_item(item, f"this file could not be converted to mp3: {exc}")
                return
            outputs["audio"] = audio
            item["transcoded"] = True
            # The hash follows the BYTES: the server stores it as the file's
            # content hash and stats the file it received, so hashing the .ogg
            # would record a digest of something nobody has.
            try:
                item["hash"] = self._hash_fn(audio)
            except OSError:
                self.log.debug("could not re-hash the transcoded %s", name,
                               exc_info=True)
            self._save()
        outputs.setdefault("audio", audio)

        # 3. decode, waveform, embedding. The one stage that needs the model.
        if not item.get("embedded"):
            if self._should_stop():
                return
            self._stage(item, ITEM_EMBEDDING, 40)
            try:
                analysis = self.sidecar.embed_file(
                    outputs["audio"], ffmpeg_path=self.ffmpeg_path,
                    stop_event=self._stop_event)
            except music_clap_sidecar.ModelUnavailable as exc:
                # The MODEL, not the file: this machine cannot embed anything,
                # so the track is uploaded and left for the base rig rather
                # than failed (module docstring). The distinction is the
                # sidecar's own exception class precisely because both arrive
                # here and they deserve opposite endings.
                self._queue_for_base_rig(item, str(exc))
                return
            except music_clap_sidecar.SidecarError as exc:
                # THIS file: a decode that failed here would fail on the base
                # rig too, so queueing it would only move the failure.
                self._fail_item(item, f"this track could not be analysed: {exc}")
                return
            except Exception as exc:  # noqa: BLE001
                self._fail_item(item, f"this track could not be analysed: {exc}")
                return
            # `embedded` is cleared again if the row is refused, so a retry
            # re-embeds rather than arriving at the upload stage with no name.
            # The vectors are deliberately not kept in the state file (see
            # _wire_analysis), so re-embedding is the only way back.
            item["embedded"] = True
            item["analysis"] = _wire_analysis(analysis)
            if not self._post_result(item, analysis):
                # The library refused the row, so there is no allocated name
                # and nowhere legitimate for the bytes to go. `_post_result`
                # has already failed the item with the server's own words.
                return
            self._save()

        # 4. hand to the upload queue
        self._stage(item, ITEM_UPLOADING, 90)
        self._enqueue_uploads(item)

    def _queue_for_base_rig(self, item: dict, why: str) -> None:
        """End the item as the base rig's problem, and KEEP the staged file.

        The plan's fallback (§1, rejected option (a)) for the case where this
        machine's model has gone away mid-batch. What it deliberately does NOT
        do is upload the audio: the library's filenames are allocated by the
        SERVER at `result`, and this item never got that far, so the only name
        this side could use is the one the file already has -- which is how you
        overwrite another editor's track that happens to be called
        `theme.wav`. There is no fleet route that allocates a name without an
        embedding (KNOWN_BUGS MUSIC-ING-2), so the honest ending is: the track
        is still on this machine, the ledger says why, and the editor's page
        offers the browser upload, which does the whole safe dance -- name
        allocation, both duplicate defences, the transcode, the queue row.

        `queued_for_base_rig` is in the kind's finished set, so the batch
        completes rather than retrying a model that is not coming back.
        """
        item["error"] = why
        item["final_state"] = ITEM_QUEUED_FOR_BASE_RIG
        self._stage(item, ITEM_QUEUED_FOR_BASE_RIG, 100)
        self.log.warning("%s stays on this machine for the base rig - %s",
                         item.get("name"), why)

    def _post_result(self, item: dict, analysis: dict) -> bool:
        """The embedding, the waveform and the probe -> a `tracks` row.

        docs/API.md §6b's body. The server allocates the FILENAME here and
        answers with it, which is why nothing may be uploaded before this call
        lands: the upload's destination is the server's answer, never a name
        this side invented. -> whether the row was written.
        """
        with self._lock:
            uid = (self._batch or {}).get("uid")
        probe = item.get("probe") or {}
        try:
            size_bytes = os.path.getsize(item["outputs"]["audio"])
        except OSError:
            size_bytes = item.get("size_bytes")
        body = {
            "embedding": _b64_floats(analysis["embedding"]),
            "dim": int(analysis["dim"]),
            "model": analysis.get("model") or self.sidecar.model_id(),
            "name": Path(item["outputs"]["audio"]).name,
            "transcoded": bool(item.get("transcoded")),
            "content_hash": item.get("hash"),
            "size_bytes": size_bytes,
            # From the DECODED sample count (see the sidecar's embed_file):
            # ffprobe's .aac duration is wrong in both directions and the
            # re-encode duplicate defence matches on it.
            "duration": float(analysis["duration"]),
            "probe": {"samplerate": probe.get("samplerate"),
                      "channels": probe.get("channels"),
                      "codec": probe.get("codec")},
            "peaks": _b64_bytes(analysis.get("peaks") or b""),
            "windows": [{"idx": int(w["idx"]), "t0": float(w["t0"]),
                         "t1": float(w["t1"]),
                         "vector": _b64_floats(w["vector"])}
                        for w in analysis.get("windows") or []],
            # bpm / music_key / lufs / peak_db are deliberately absent: they
            # are librosa's, and the companion has no librosa (KNOWN_BUGS
            # MUSIC-ING-1). The server takes them as null and a base-rig
            # retag fills them in.
        }
        status, parsed = self._client().item_result(uid, item["uid"], body)
        if status != 200:
            detail = broll_ingest._detail_of(parsed) or "no detail"
            self.log.warning("the server refused the result for %s (HTTP %s: %s)",
                             item.get("name"), status, detail)
            # 409 model_mismatch is not a transient: this companion's artefact
            # is a different embedding space from the library's, and retrying
            # produces the identical refusal.
            item["embedded"] = False
            self._fail_item(item, f"the library would not take this track: {detail}")
            return False
        if isinstance(parsed, dict):
            item["dest_name"] = str(parsed.get("rel_path") or item.get("dest_name") or "")
            item["track_id"] = parsed.get("track_id")
        item["stage"] = ITEM_INDEXED
        return True

    # -- uploads -----------------------------------------------------------
    def _queue(self) -> Any:
        """The shared upload queue, pointed at the MUSIC library.

        `archive_rel` is what makes one queue implementation serve both kinds:
        b-roll's files hang off `Assets/B-roll Archive`, music's off
        `Assets/Music`, and both are relative to the rclone remote's root
        because only this machine knows what that is mounted at.
        """
        if self._uploader is None:
            with self._lock:
                remote_rel = (self._batch or {}).get("archive_remote_rel")
            self._uploader = broll_upload.UploadQueue(
                lambda: self.cfg, archive_rel=remote_rel or LIBRARY_REMOTE_REL)
            if self._upload_paused:
                self._uploader.pause()
        return self._uploader

    def _enqueue_uploads(self, item: dict, final_state: str = "") -> None:
        """One file, under the name the SERVER allocated.

        A music item owns exactly one file (docs/API.md §6b: "no path field,
        deliberately"), so there is no order to keep and no original to send
        last -- and no traversal to defend against, because the destination is
        the ledger's `dest_name` and nothing about it came off the wire.
        """
        outputs = item.get("outputs") or {}
        local = outputs.get("audio") or item.get("local_path")
        dest = str(item.get("dest_name") or "")
        if not dest:
            # No name yet means the result never landed. Without the server's
            # name there is nowhere legitimate to put the bytes, so this is a
            # failure and not a guess.
            self._fail_item(item, "the library did not name this track, so it "
                                  "could not be uploaded")
            return
        rel = PurePosixPath(dest).name
        item["uploads"] = {rel: KIND_AUDIO}
        # What `_pump_uploads` posts once the bytes are there. Set BEFORE the
        # enqueue so a fast upload cannot be reported under the wrong state.
        item["final_state"] = final_state or ITEM_LIVE
        if local and os.path.isfile(local):
            try:
                self._queue().enqueue(local, rel, KIND_AUDIO,
                                      item_uid=item["uid"],
                                      size_bytes=os.path.getsize(local))
            except Exception:
                self.log.exception("could not queue %s", rel)
        item["stage"] = ITEM_UPLOADING
        self._stage(item, ITEM_UPLOADING, 90)

    def _final_state(self, item: dict) -> str:
        return str(item.get("final_state") or ITEM_LIVE)

    def _post_uploaded(self, batch_uid: str, item: dict, files: list,
                       original_uploaded: bool) -> tuple[int, Any]:
        """`{size}` and nothing else (docs/API.md §6b).

        An item that failed its embedding and is riding the base-rig fallback
        never becomes `live`: its audio is in the library and its analysis is
        not, so it is checkpointed `queued_for_base_rig` instead and the
        ledger keeps the reason.
        """
        size = None
        for entry in files or []:
            if entry.get("size") is not None:
                size = int(entry["size"])
                break
        final = str(item.get("final_state") or ITEM_LIVE)
        client = self._client()
        if final != ITEM_LIVE:
            client.item_status(batch_uid, item["uid"], final,
                               error=(item.get("error") or "")[:2000],
                               attempts=item.get("attempts"))
            return 200, {"ok": True, "state": final}
        return client.item_uploaded_size(batch_uid, item["uid"], size)

    def _mirror_locally(self, item: dict) -> None:
        """Nothing to mirror.

        b-roll moves its finished proxy into the local archive so "Send to
        Resolve" needs no download. The music library is not synced to editors
        at all -- the companion fetches a track on demand when Resolve asks for
        it (MUSIC-on-demand, 2026-08-16) -- so a local copy here would be an
        unmanaged file in a folder nothing prunes.
        """
        return

    # -- what the tray and the dashboard read ------------------------------
    def report(self) -> dict[str, Any]:
        """The reporter's `music_ingest` section.

        b-roll's fields plus `kind`, because the two sections ride the same
        report and land in different columns, and a section that could not
        name itself would be one flatten() away from writing music's counters
        into b-roll's chip.
        """
        section = super().report()
        if not section:
            return {}
        section["kind"] = self.kind.name
        # No tier exists here; sending b-roll's default would put "good" in a
        # column that means "which vision model".
        section["tier"] = ""
        return section


def _wire_analysis(analysis: dict) -> dict[str, Any]:
    """The parts of an analysis worth keeping in the state file.

    NOT the vectors: a 12-window embedding is ~25 kB of base64 per track and
    the state file is rewritten at every checkpoint of every item. A companion
    restarting mid-batch re-embeds the track it was on, which costs seconds --
    the checkpoint that matters is `indexed`, and that one lives on the server.
    """
    return {"dim": int(analysis.get("dim") or 0),
            "duration": float(analysis.get("duration") or 0),
            "n_windows": int(analysis.get("n_windows") or 0),
            "model": analysis.get("model") or ""}


def _b64_floats(vector: Any) -> str:
    """float32 array -> base64 of raw little-endian bytes (docs/API.md §6b).

    `db.to_blob` stores exactly these bytes, so the wire format and the stored
    format are the same thing with a base64 in between. `<f4` explicitly: a
    big-endian machine would otherwise store a vector nothing can read.
    """
    import base64

    import numpy as np

    data = np.asarray(vector, dtype="<f4").tobytes()
    return base64.b64encode(data).decode("ascii")


def _b64_bytes(data: Any) -> str:
    import base64

    return base64.b64encode(bytes(data or b"")).decode("ascii")
