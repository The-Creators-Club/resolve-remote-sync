"""How long a WAV plays, from its header alone.

Copied from footage-sorter `footage_sorter/wav.py` (itself a port of
lib/ingest/wav.js) so the card listing's `wav` map is computed exactly as the
sorter computes it for a card on its own disk.

duration = dataBytes / byteRate. Only the RIFF chunk table is walked; the bulk
'data' chunk is never read. A data size of 0xFFFFFFFF, or one that overruns
the file, means the recorder never closed the header: what is on disk counts.
Read-only. None for anything that is not a parseable WAV.
"""
from __future__ import annotations

import os
import struct
from typing import Optional


def wav_info(file: str) -> Optional[dict]:
    try:
        with open(file, "rb") as fh:
            length = os.fstat(fh.fileno()).st_size
            if length < 12:
                return None
            head = fh.read(12)
            if head[0:4] != b"RIFF" or head[8:12] != b"WAVE":
                return None
            pos = 12
            byte_rate = data_bytes = sample_rate = channels = bits = 0
            while pos + 8 <= length:
                fh.seek(pos)
                hdr = fh.read(8)
                if len(hdr) < 8:
                    break
                cid, sz = hdr[0:4], struct.unpack("<I", hdr[4:8])[0]
                pos += 8
                if cid == b"fmt ":
                    n = min(sz, 64)
                    fmt = fh.read(n)
                    if n >= 16 and len(fmt) >= 16:
                        channels = struct.unpack("<H", fmt[2:4])[0]
                        sample_rate = struct.unpack("<I", fmt[4:8])[0]
                        byte_rate = struct.unpack("<I", fmt[8:12])[0]
                        bits = struct.unpack("<H", fmt[14:16])[0]
                    pos += sz + (sz % 2)
                elif cid == b"data":
                    data_bytes = sz
                    if sz == 0xFFFFFFFF or pos + sz > length:
                        data_bytes = max(0, length - pos)
                    break
                else:
                    pos += sz + (sz % 2)          # chunks are word-aligned
            if byte_rate <= 0 or data_bytes <= 0:
                return None
            return {"seconds": data_bytes / byte_rate, "byteRate": byte_rate,
                    "dataBytes": data_bytes, "sampleRate": sample_rate,
                    "channels": channels, "bits": bits}
    except OSError:
        return None


def wav_seconds(file: str) -> Optional[float]:
    info = wav_info(file)
    return None if info is None else float(info["seconds"])
