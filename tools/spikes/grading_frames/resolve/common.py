import sys, os, hashlib, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rs
HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "Grading frames spike 2026-11-22"

def df_tc(frame, fps=30):
    # 29.97 drop-frame timecode from an absolute frame count
    d, m = divmod(frame, 17982)
    if m < 2: m += 2
    frame += 18 * d + 2 * ((m - 2) // 1798)
    f = frame % 30; s = (frame // 30) % 60; mi = (frame // 1800) % 60; h = frame // 108000
    return "%02d:%02d:%02d;%02d" % (h, mi, s, f)

def open_spike():
    r = rs.connect(); pm = r.GetProjectManager(); p = pm.GetCurrentProject()
    if p.GetName() != NAME:
        raise SystemExit("not in the spike project: %r" % p.GetName())
    return r, pm, p

def timeline(p, name):
    for i in range(1, p.GetTimelineCount() + 1):
        t = p.GetTimelineByIndex(i)
        if t.GetName() == name:
            return t
    raise SystemExit("no timeline %r" % name)

def clips(p):
    out = {}
    def walk(f):
        for c in f.GetClipList() or []:
            out.setdefault(c.GetClipProperty("Clip Name"), c)
        for s in f.GetSubFolderList() or []:
            walk(s)
    walk(p.GetMediaPool().GetRootFolder())
    return out

def still(p, t, frame, label):
    tc = df_tc(frame)
    ok_tc = t.SetCurrentTimecode(tc)
    time.sleep(1.0)
    out = os.path.join(HERE, "stills", label + ".png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out): os.remove(out)
    t0 = time.time()
    ok = p.ExportCurrentFrameAsStill(out)
    dt = time.time() - t0
    h = None
    if os.path.exists(out):
        from PIL import Image
        im = Image.open(out).convert("RGB")
        h = hashlib.sha1(im.tobytes()).hexdigest()[:12]
        im.resize((640, 360)).save(out[:-4] + "_small.jpg", quality=80)
        size = im.size
    else:
        size = None
    print("  still %-28s tc %s set=%s export=%s %.1fs size=%s pix=%s" % (label, tc, ok_tc, ok, dt, size, h))
    return h
