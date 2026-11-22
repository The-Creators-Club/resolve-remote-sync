"""Decode chosen frames of a .braw with Blackmagic's own decoder (the DLL
Resolve ships), outside Resolve, on the CPU. Prints, per frame: the read
result, the process result, and a hash of the decoded picture.

usage: braw_probe.py <clip.braw> <frame> [<frame> ...] [--jpg out_prefix]
"""
import ctypes
import hashlib
import os
import sys

sys.coinit_flags = 0  # multithreaded apartment: the decoder calls back from its own threads
import comtypes  # noqa: E402
import comtypes.client  # noqa: E402

DLL = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\BlackmagicRawAPI.dll"
bm = comtypes.client.GetModule(DLL)

results = {}
state = {"frame": None, "jpg": None}


def say(*a):
    print(*a, flush=True)


class Callback(comtypes.COMObject):
    _com_interfaces_ = [bm.IBlackmagicRawCallback]

    def ReadComplete(self, job, result, frame):
        r = results.setdefault(state["frame"], {})
        r["read"] = hex(result & 0xFFFFFFFF)
        if result == 0 and frame:
            try:
                frame.SetResolutionScale(bm.blackmagicRawResolutionScaleQuarter)
                frame.CreateJobDecodeAndProcessFrame(None, None).Submit()
            except Exception as e:  # noqa: BLE001
                r["decode_submit_error"] = repr(e)
        return 0

    def DecodeComplete(self, job, result):
        return 0

    def ProcessComplete(self, job, result, processedImage):
        r = results.setdefault(state["frame"], {})
        r["process"] = hex(result & 0xFFFFFFFF)
        try:
            if result == 0 and processedImage:
                w = processedImage.GetWidth()
                h = processedImage.GetHeight()
                n = processedImage.GetResourceSizeBytes()
                rtype = processedImage.GetResourceType()
                r["size"] = (w, h, n)
                r["resource_type"] = rtype
                if rtype != bm.blackmagicRawResourceTypeBufferCPU:
                    r["note"] = "not a CPU buffer, pixels not read"
                    return 0
                ptr = processedImage.GetResource()
                addr = ptr if isinstance(ptr, int) else ctypes.cast(ptr, ctypes.c_void_p).value
                data = ctypes.string_at(addr, n)
                r["sha1"] = hashlib.sha1(data).hexdigest()
                step = max(1, n // 20000)
                sample = data[::step]
                r["mean_level"] = round(sum(sample) / len(sample), 1)
                if state["jpg"]:
                    from PIL import Image
                    out = f"{state['jpg']}_{state['frame']}.jpg"
                    Image.frombuffer("RGBA", (w, h), data, "raw", "RGBA", 0, 1).convert("RGB").save(out, quality=85)
                    r["saved"] = out
        except Exception as e:  # noqa: BLE001
            r["callback_error"] = repr(e)
        return 0

    def TrimProgress(self, job, progress):
        return 0

    def TrimComplete(self, job, result):
        return 0

    def SidecarMetadataParseWarning(self, clip, fileName, lineNumber, info):
        return 0

    def SidecarMetadataParseError(self, clip, fileName, lineNumber, info):
        return 0

    def PreparePipelineComplete(self, userData, result):
        return 0


def main():
    args = sys.argv[1:]
    if "--jpg" in args:
        i = args.index("--jpg")
        state["jpg"] = args[i + 1]
        del args[i:i + 2]
    path, frames = args[0], [int(x) for x in args[1:]]
    lib = ctypes.WinDLL(DLL)
    lib.CreateBlackmagicRawFactoryInstance.restype = ctypes.POINTER(bm.IBlackmagicRawFactory)
    factory = lib.CreateBlackmagicRawFactoryInstance()
    codec = factory.CreateCodec()
    cfg = codec.QueryInterface(bm.IBlackmagicRawConfiguration)
    cfg.SetPipeline(bm.blackmagicRawPipelineCPU, None, None)
    try:
        clip = codec.OpenClip(path)
    except Exception as e:  # noqa: BLE001
        say("OpenClip FAILED:", repr(e))
        return
    say("opened:", os.path.basename(path))
    try:
        say("  frames", clip.GetFrameCount(), "size", clip.GetWidth(), "x", clip.GetHeight(),
            "fps", clip.GetFrameRate())
    except Exception as e:  # noqa: BLE001
        say("  clip header read FAILED:", repr(e))
        return
    cb = Callback()
    codec.SetCallback(cb)
    for fr in frames:
        state["frame"] = fr
        results.pop(fr, None)
        try:
            tc = clip.GetTimecodeForFrame(fr)
            clip.CreateJobReadFrame(fr).Submit()
            codec.FlushJobs()
        except Exception as e:  # noqa: BLE001
            results.setdefault(fr, {})["submit_error"] = repr(e)
            tc = "?"
        say(f"  frame {fr} tc {tc}:", results.get(fr))


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
