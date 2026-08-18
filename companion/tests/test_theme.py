"""The window icon: the new mark, in brand red, on every companion window.

Every root in popup.py and tray.py calls theme.apply_window_icon, and until
2026-08-11 that painted April's pre-composed assets/icon.png while the tray
next to it drew the new mark -- two logos for one app. These tests pin the
render (real pixels, not "a call happened"), the cache, the fallback chain for
frozen builds published before the asset existed, and the never-raises contract
that lets a headless run with no display at all keep going.

Nothing here may build a real Tk window (conftest._no_real_tk_windows) -- the
tk module is faked, which is also the only way to see WHICH PhotoImage
constructor argument the applier reached for.
"""

from __future__ import annotations

import base64
import io

import pytest

from ccsync_companion import theme


# -- fakes -------------------------------------------------------------------

class _FakePhotoImage:
    """Records how it was constructed. Never touches Tcl."""

    def __init__(self, *, master=None, data=None, file=None):
        self.master = master
        self.data = data
        self.file = file


class _FakeTk:
    PhotoImage = _FakePhotoImage


class _FakeRoot:
    def __init__(self):
        self.iconphoto_calls: list = []

    def iconphoto(self, default, image):
        self.iconphoto_calls.append((default, image))


def _decode(b64: str):
    from PIL import Image

    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")


@pytest.fixture(autouse=True)
def _clean_icon_cache():
    """The render cache is module state, so one test's fake asset path would
    otherwise be another's answer (same hazard class as conftest's
    process-global guards)."""
    saved = dict(theme._WINDOW_ICON_CACHE)
    theme._WINDOW_ICON_CACHE.clear()
    yield
    theme._WINDOW_ICON_CACHE.clear()
    theme._WINDOW_ICON_CACHE.update(saved)


# -- the render --------------------------------------------------------------

def test_the_window_icon_is_the_new_mark_not_the_old_pre_composed_one():
    """The white mark is the tintable asset; icon.png is already coloured and
    cannot become red without repainting it."""
    # The PRODUCT's mark since 2026-08-17 (COMMERCIAL_READINESS.md item 10):
    # the studio logo it used to be is still shipped, but only a site that
    # asks for it by name ($CCSYNC_BRAND_LOGO) wears it.
    assert theme.WINDOW_ICON_ASSET == "ccsync_mark.png"
    assert theme.window_mark_path() is not None
    assert theme.window_mark_path() != theme.icon_path()
    # icon_path() deliberately still means the pre-composed file (other code
    # and test_tray depend on that spelling); it is now only the fallback.
    assert theme.icon_path() == theme.asset_path("icon.png")


def _pixels(image) -> list:
    """Every RGBA pixel. tobytes() rather than getdata(), which Pillow 13
    deprecates."""
    raw = image.convert("RGBA").tobytes()
    return [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]


def _visible_pixels(image) -> list:
    """The RGB of every pixel that is not fully transparent."""
    return [(r, g, b) for r, g, b, a in _pixels(image) if a > 0]


def test_the_mark_is_rendered_in_the_brand_red():
    """Assert on the produced pixels. A tint that silently missed would still
    'return a string'.

    EVERY visible pixel, edges included: the render puts the colour down flat
    and varies only alpha, so nothing composites as a dark halo over a light
    title bar."""
    image = _decode(theme.window_icon_png_b64())

    assert image.size == (theme.WINDOW_ICON_SIZE, theme.WINDOW_ICON_SIZE)
    visible = _visible_pixels(image)
    assert visible, "the tinted mark came out fully transparent"
    assert set(visible) == {theme.RGB_RED}

    # ...and RGB_RED is the same red the rest of the chrome is painted in --
    # no second spelling of the brand colour.
    assert theme.RED == "#%02x%02x%02x" % theme.RGB_RED


def test_the_tint_keeps_the_marks_own_silhouette():
    """The colour is pasted THROUGH the asset's alpha, so the shape (and its
    anti-aliased edges) must come out of the file untouched."""
    from PIL import Image

    with Image.open(theme.window_mark_path()) as src:
        expected = (src.convert("RGBA")
                       .resize((theme.WINDOW_ICON_SIZE, theme.WINDOW_ICON_SIZE),
                               Image.LANCZOS)
                       .getchannel("A"))

    got = _decode(theme.window_icon_png_b64()).getchannel("A")
    assert got.tobytes() == expected.tobytes()
    # A real logo, not a solid square: some of the canvas has to be empty.
    assert got.getextrema() == (0, 255)


def test_a_different_colour_renders_a_different_icon():
    red = theme.window_icon_png_b64()
    green = theme.window_icon_png_b64(color=theme.RGB_GREEN)

    assert red != green
    assert set(_visible_pixels(_decode(green))) == {theme.RGB_GREEN}


def test_the_base64_really_is_a_png_tk_can_decode():
    """PhotoImage(data=...) is the whole reason this returns base64 rather
    than a path -- Tk 8.6 only accepts base64-encoded image data, and only
    formats it has a handler for. Verified against a real Tk 8.6 by hand
    (2026-08-11); pinned here as 'decodes as a PNG' because opening a Tk root
    in this suite is forbidden."""
    raw = base64.b64decode(theme.window_icon_png_b64(), validate=True)

    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


# -- the cache ---------------------------------------------------------------

def test_the_render_happens_once_per_colour_and_size():
    """apply_window_icon runs per window; a LANCZOS downscale of a 512x512 PNG
    per popup is waste (tray._MARK_MASK_CACHE's precedent)."""
    from PIL import Image

    opens = []
    real_open = Image.open

    def counting_open(*args, **kwargs):
        opens.append(args[0])
        return real_open(*args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Image, "open", counting_open)
        first = theme.window_icon_png_b64()
        second = theme.window_icon_png_b64()

    assert first is second
    assert len(opens) == 1


def test_a_failed_render_is_cached_too_rather_than_retried_every_window(tmp_path):
    """None is a real answer, not an error, so it has to be remembered like
    one -- otherwise a build without the asset pays a failed decode per popup."""
    from PIL import Image

    opens = []
    real_open = Image.open

    def counting_open(*args, **kwargs):
        opens.append(args[0])
        return real_open(*args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(theme, "window_mark_path", lambda: tmp_path / "gone.png")
        mp.setattr(Image, "open", counting_open)
        assert theme.window_icon_png_b64() is None
        assert theme.window_icon_png_b64() is None

    assert len(opens) == 1

    # ...and a build with no such asset at all caches its None under its own key
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(theme, "window_mark_path", lambda: None)
        assert theme.window_icon_png_b64() is None
    assert theme._WINDOW_ICON_CACHE[(None, theme.RGB_RED, theme.WINDOW_ICON_SIZE)] is None


# -- apply_window_icon: the fallback chain -----------------------------------

def test_apply_window_icon_hands_tk_the_tinted_mark_as_data():
    root = _FakeRoot()

    theme.apply_window_icon(_FakeTk, root)

    image = root._ccsync_icon_image
    assert image.file is None, "the tinted mark has no file -- data= is the route"
    assert image.data == theme.window_icon_png_b64()
    assert image.master is root
    # Parked on the root AND handed to iconphoto: Tk drops an icon whose image
    # is garbage-collected.
    assert root.iconphoto_calls == [(True, image)]


def test_it_falls_back_to_icon_png_when_the_build_predates_the_mark(monkeypatch):
    """asset_path() answers None for a frozen build published before a file
    was added to build.spec's datas. Old logo beats no logo."""
    monkeypatch.setattr(theme, "window_mark_path", lambda: None)
    root = _FakeRoot()

    theme.apply_window_icon(_FakeTk, root)

    image = root._ccsync_icon_image
    assert image.data is None
    assert image.file == str(theme.icon_path())
    assert root.iconphoto_calls == [(True, image)]


def test_it_falls_back_to_icon_png_when_the_mark_file_is_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "window_mark_path", lambda: tmp_path / "gone.png")
    root = _FakeRoot()

    theme.apply_window_icon(_FakeTk, root)

    assert root._ccsync_icon_image.file == str(theme.icon_path())


def test_it_falls_back_to_the_file_when_tk_cannot_decode_png_data(monkeypatch):
    """A Tk older than 8.6 has no PNG handler at all. Losing the tint is fine;
    losing the icon is not."""
    class _NoPngTk:
        @staticmethod
        def PhotoImage(*, master=None, data=None, file=None):
            if data is not None:
                raise Exception('image format "png" is not supported')
            return _FakePhotoImage(master=master, file=file)

    root = _FakeRoot()
    theme.apply_window_icon(_NoPngTk, root)

    assert root._ccsync_icon_image.file == str(theme.icon_path())


def test_it_does_nothing_at_all_when_the_build_has_neither_asset(monkeypatch):
    monkeypatch.setattr(theme, "window_mark_path", lambda: None)
    monkeypatch.setattr(theme, "icon_path", lambda: None)
    root = _FakeRoot()

    theme.apply_window_icon(_FakeTk, root)

    assert root.iconphoto_calls == []
    assert not hasattr(root, "_ccsync_icon_image")


# -- the never-raises contract -----------------------------------------------

@pytest.mark.parametrize("break_it", ["photoimage", "iconphoto", "render", "asset"])
def test_the_applier_never_raises_whatever_misbehaves(break_it, monkeypatch):
    """Load-bearing: an icon is decoration, and none of the popups may die
    over it (headless test runs have no display at all)."""
    class _ExplodingTk:
        @staticmethod
        def PhotoImage(*args, **kwargs):
            raise RuntimeError("no display name and no $DISPLAY environment variable")

    class _ExplodingRoot:
        def iconphoto(self, *args, **kwargs):
            raise RuntimeError("bad window path name")

    if break_it == "photoimage":
        theme.apply_window_icon(_ExplodingTk, _FakeRoot())
    elif break_it == "iconphoto":
        theme.apply_window_icon(_FakeTk, _ExplodingRoot())
    elif break_it == "render":
        def _boom(*args, **kwargs):
            raise RuntimeError("PIL exploded")

        monkeypatch.setattr(theme, "window_icon_png_b64", _boom)
        theme.apply_window_icon(_FakeTk, _FakeRoot())
    else:
        def _boom():
            raise RuntimeError("sys._MEIPASS is a lie")

        monkeypatch.setattr(theme, "window_mark_path", _boom)
        monkeypatch.setattr(theme, "icon_path", _boom)
        theme.apply_window_icon(_FakeTk, _FakeRoot())


def test_the_renderer_never_raises_when_pillow_is_missing(monkeypatch):
    """The frozen build carries Pillow (the tray needs it), but theme is also
    imported by paths that do not, and a broken import here would take out
    every popup."""
    import builtins

    real_import = builtins.__import__

    def no_pil(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("No module named 'PIL'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pil)
    assert theme.window_icon_png_b64() is None


# -- the build ---------------------------------------------------------------

def test_the_frozen_build_ships_both_the_mark_and_the_fallback():
    """Nothing at runtime can tell you the datas entry is missing -- a frozen
    build without the mark just shows the old logo, which is exactly why that
    fallback is silent."""
    from pathlib import Path

    spec = (Path(__file__).resolve().parent.parent / "build.spec").read_text(
        encoding="utf-8")

    assert f"src/ccsync_companion/assets/{theme.WINDOW_ICON_ASSET}" in spec
    assert "src/ccsync_companion/assets/icon.png" in spec


# -- which mark: env, then the site manifest, then the product's own ----------
# 2026-08-18. Item 10 shipped the indirection with ONE selector, $CCSYNC_BRAND_
# LOGO, which is machine environment -- so a fleet that had its own logo lost it
# the moment its editors upgraded, and getting it back meant touching every
# machine. The manifest already carries org_name/org_short/product_name; the
# mark now travels with them.

def test_no_selector_wears_the_products_own_mark(monkeypatch):
    monkeypatch.delenv("CCSYNC_BRAND_LOGO", raising=False)
    monkeypatch.setattr(theme, "brand_logo_site", lambda: None)
    assert theme.brand_logo_override() is None
    assert theme.window_mark_path() == theme.asset_path("ccsync_mark.png")


def test_the_site_manifest_selects_a_mark_the_build_ships(monkeypatch):
    """A bare name means "the asset in this build" -- which is the whole
    reason build.spec still ships cc_mark_white.png beside the neutral one."""
    monkeypatch.delenv("CCSYNC_BRAND_LOGO", raising=False)
    monkeypatch.setattr(theme, "brand_logo_site",
                        lambda: theme.asset_path("cc_mark_white.png"))
    assert theme.window_mark_path() == theme.asset_path("cc_mark_white.png")


def test_the_env_var_beats_the_manifest(monkeypatch):
    """The escape hatch has to be one: a machine pinned to a mark by hand --
    a vendor rig testing a customer build, an editor mid-migration -- must not
    be overruled by whatever its dashboard publishes."""
    monkeypatch.setenv("CCSYNC_BRAND_LOGO", "ccsync_mark.png")
    monkeypatch.setattr(theme, "brand_logo_site",
                        lambda: theme.asset_path("cc_mark_white.png"))
    assert theme.window_mark_path() == theme.asset_path("ccsync_mark.png")


def test_a_manifest_naming_a_missing_file_falls_back_rather_than_failing(monkeypatch, tmp_path):
    """A wrong logo path must not stop an editor's tray coming up -- the same
    rule the env var has always followed, now that a SERVER can set it."""
    monkeypatch.delenv("CCSYNC_BRAND_LOGO", raising=False)
    monkeypatch.setattr(theme, "brand_logo_site",
                        lambda: theme._resolve_logo(str(tmp_path / "gone.png")))
    assert theme.brand_logo_override() is None
    assert theme.window_mark_path() == theme.asset_path("ccsync_mark.png")


def test_brand_logo_site_reads_the_cached_manifest(monkeypatch):
    from ccsync_companion import site as site_mod

    monkeypatch.setattr(site_mod, "brand_logo", lambda: "cc_mark_white.png")
    assert theme.brand_logo_site() == theme.asset_path("cc_mark_white.png")


def test_brand_logo_site_never_raises(monkeypatch):
    """theme is imported by the tray and by every popup; an unreadable
    manifest may not be the reason one of them fails to draw."""
    from ccsync_companion import site as site_mod

    def boom():
        raise RuntimeError("manifest on fire")

    monkeypatch.setattr(site_mod, "brand_logo", boom)
    assert theme.brand_logo_site() is None
    assert theme.window_mark_path() == theme.asset_path("ccsync_mark.png")
