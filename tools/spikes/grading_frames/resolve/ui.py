"""Tiny UI helper for the spike: list Resolve's windows, capture one (PrintWindow,
works when covered), post a click or a key to one. Never moves the real mouse.

  ui.py list
  ui.py shot <main|popup> <out.png> [x0 y0 x1 y1]
  ui.py click <main|popup> <x> <y>          (window-image coordinates)
  ui.py key <main|popup> <down|up|enter|esc|tab> [...]
  ui.py type <main|popup> <text>
"""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time

u = ctypes.windll.user32
g = ctypes.windll.gdi32
u.SetProcessDPIAware()


def resolve_pid():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Resolve.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return int(out.split(",")[1].strip('"'))


def windows():
    pid = resolve_pid()
    res = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(h, l):
        p = wt.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            c = ctypes.create_unicode_buffer(200); u.GetClassNameW(h, c, 200)
            t = ctypes.create_unicode_buffer(200); u.GetWindowTextW(h, t, 200)
            r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
            res.append({"h": h, "cls": c.value, "title": t.value, "rect": (r.left, r.top, r.right - r.left, r.bottom - r.top)})
        return True
    u.EnumWindows(PROC(cb), 0)
    return res


def pick(which):
    ws = windows()
    main = [w for w in ws if w["title"].startswith("DaVinci Resolve")]
    pops = [w for w in ws if not w["title"].startswith("DaVinci Resolve") and w["rect"][2] > 20]
    if which == "main":
        return main[0]
    if not pops:
        raise SystemExit("no popup window")
    return pops[0]


def shot(w, out, crop=None):
    from PIL import Image
    x, y, ww, hh = w["rect"]
    hdc = u.GetWindowDC(w["h"]); mdc = g.CreateCompatibleDC(hdc); bmp = g.CreateCompatibleBitmap(hdc, ww, hh)
    g.SelectObject(mdc, bmp)
    u.PrintWindow(w["h"], mdc, 2)

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                    ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD), ("a", wt.LONG), ("b", wt.LONG), ("c", wt.DWORD), ("d", wt.DWORD)]
    bi = BMI(); bi.biSize = ctypes.sizeof(BMI); bi.biWidth = ww; bi.biHeight = -hh; bi.biPlanes = 1; bi.biBitCount = 32
    buf = ctypes.create_string_buffer(ww * hh * 4)
    g.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bi), 0)
    g.DeleteObject(bmp); g.DeleteDC(mdc); u.ReleaseDC(w["h"], hdc)
    im = Image.frombuffer("RGBA", (ww, hh), buf, "raw", "BGRA", 0, 1).convert("RGB")
    if crop:
        im = im.crop(crop)
    im.save(out)
    print("saved", out, im.size)


def client_lparam(w, x, y):
    pt = wt.POINT(w["rect"][0] + x, w["rect"][1] + y)
    u.ScreenToClient(w["h"], ctypes.byref(pt))
    return (pt.y << 16) | (pt.x & 0xFFFF)


def click(w, x, y):
    l = client_lparam(w, x, y)
    u.PostMessageW(w["h"], 0x0200, 0, l); time.sleep(0.08)
    u.PostMessageW(w["h"], 0x0201, 1, l); time.sleep(0.06)
    u.PostMessageW(w["h"], 0x0202, 0, l); time.sleep(0.1)
    print("clicked", x, y, "in", w["cls"])


VK = {"down": 0x28, "up": 0x26, "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "left": 0x25, "right": 0x27}


def key(w, name):
    vk = VK[name]
    u.PostMessageW(w["h"], 0x0100, vk, 1); time.sleep(0.05)
    u.PostMessageW(w["h"], 0x0101, vk, 0xC0000001); time.sleep(0.12)
    print("key", name)


def typ(w, text):
    for ch in text:
        u.PostMessageW(w["h"], 0x0102, ord(ch), 1); time.sleep(0.04)
    print("typed", text)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "list":
        for w in windows():
            print(w)
    elif a[0] == "shot":
        shot(pick(a[1]), a[2], tuple(int(v) for v in a[3:7]) if len(a) >= 7 else None)
    elif a[0] == "click":
        click(pick(a[1]), int(a[2]), int(a[3]))
    elif a[0] == "key":
        w = pick(a[1])
        for k in a[2:]:
            key(w, k)
    elif a[0] == "type":
        typ(pick(a[1]), a[2])
