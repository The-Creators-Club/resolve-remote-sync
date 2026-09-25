"""CSS and markup facts for the terminal look's sheets (docs/UI_REDESIGN_PORT_PLAN.md
2.1-2.4, R8, R10, R20; phase 0). Since 2026-09-25 the terminal look is the
only look: the classic sheets are deleted and every dashboard template is a
terminal template, so the template scans below read all of templates/."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
CC = STATIC / "cc"
# Every template is a terminal one now (the classic look was deleted
# 2026-09-25 and templates/cc/ moved up over its twins).
TEMPLATES_CC = ROOT / "templates"
REPO = ROOT.parent
NOTICES = REPO / "docs" / "legal" / "THIRD_PARTY_NOTICES.md"

THEME_BEGIN = "/* ==== theme-common BEGIN"
THEME_END = "/* ==== theme-common END"
HUD_BEGIN = "/* ==== hud-common BEGIN"
HUD_END = "/* ==== hud-common END"

# ytdl's own deny-by-default scan (ytdl/web/tests/test_mounted_prefix.py): a
# quote, backtick or parenthesis directly before a slash.
_ABSOLUTE = re.compile(r"""["'`(](/[^"'`)\s>]*)""")


def css(name: str) -> str:
    return (CC / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def sheets() -> list[Path]:
    return sorted(CC.glob("*.css"))


def _between(text: str, begin: str, end: str) -> str:
    body = text.split(begin, 1)[1]
    return body.split(end, 1)[0]


def _strip_block(text: str, begin: str, end: str) -> str:
    if begin not in text:
        return text
    head, rest = text.split(begin, 1)
    return head + rest.split(end, 1)[1]


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_the_four_sheets_exist():
    for name in ("terminal.css", "components.css", "phone.css", "hud.css"):
        assert (CC / name).is_file(), name


# The dashboard's classic style.css was the fourth copy of theme-common until
# 2026-09-25; terminal.css is the dashboard's copy now, and it may not drift
# from the three SPA sheets that still carry the block.
SPA_SHEETS = [REPO / "broll" / "web" / "static" / "style.css",
              REPO / "music" / "web" / "static" / "style.css",
              REPO / "ytdl" / "web" / "static" / "style.css"]


@pytest.mark.parametrize("sheet", SPA_SHEETS, ids=lambda p: p.parts[-4])
def test_theme_common_is_byte_identical_to_the_spa_sheets(sheet):
    other = sheet.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert css("terminal.css").count(THEME_BEGIN) == 1
    assert _between(css("terminal.css"), THEME_BEGIN, THEME_END) == \
        _between(other, THEME_BEGIN, THEME_END)


def test_every_token_theme_common_reads_is_declared_in_the_cc_root():
    text = css("terminal.css")
    block = _between(text, THEME_BEGIN, THEME_END)
    root = re.search(r":root\s*\{(.*?)\n\}", text, re.S).group(1)
    declared = set(re.findall(r"(--[a-z0-9-]+)\s*:", root)) | set(
        re.findall(r"(--[a-z0-9-]+)\s*:", block))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", block))
    assert used <= declared, sorted(used - declared)


def test_no_hud_dock_or_snav_rule_outside_hud_common():
    for path in sheets():
        text = _strip_comments(_strip_block(path.read_text(encoding="utf-8"), HUD_BEGIN, HUD_END))
        # the lifts after hud-common may KEY on the dock's presence
        text = re.sub(r":has\([^)]*\)", "", text)
        for sel in re.findall(r"([^{}]+)\{", text):
            if sel.strip().startswith("@"):
                continue
            assert not re.search(r"\.hud|#hud-|\.dock\b|\.snav", sel), f"{path.name}: {sel.strip()}"


def test_no_customer_domain_in_the_terminal_files():
    files = list(CC.rglob("*")) + list(TEMPLATES_CC.rglob("*"))
    for p in files:
        if p.is_file() and p.suffix in (".css", ".js", ".html"):
            assert "thecreatorsclub" not in p.read_text(encoding="utf-8").lower(), p


def test_every_sheet_passes_ytdls_absolute_url_scan():
    for path in sheets():
        hits = [m.group(1) for m in _ABSOLUTE.finditer(path.read_text(encoding="utf-8"))
                if m.group(1) != "/"]
        assert not hits, f"{path.name}: {hits[:5]}"


def test_generated_content_never_starts_with_a_slash():
    for path in sheets():
        for value in re.findall(r'content:\s*"([^"]*)"', path.read_text(encoding="utf-8")):
            assert not value.startswith("/") or value == "/", f"{path.name}: {value!r}"


def test_nothing_moves_forever_and_nothing_blurs():
    for path in sheets():
        text = _strip_comments(path.read_text(encoding="utf-8"))
        for rule in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            if "infinite" in rule[1]:
                assert ".spin" in rule[0], f"{path.name}: {rule[0].strip()}"
        assert "backdrop-filter" not in text, path.name


def test_no_bench_only_class_or_second_scrollbar():
    text = "".join(_strip_comments(_strip_block(p.read_text(encoding="utf-8"), THEME_BEGIN,
                                                THEME_END)) for p in sheets())
    for banned in (".tune", ".opts", ".swatch", ".iv-switch", ".acct-bench", ".fl-new",
                   ".bench ", "::-webkit-scrollbar-thumb {", "Permanent Marker", "--hand"):
        assert banned not in text, banned


def _lum(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_the_primary_key_fill_clears_aa_at_rest_and_on_hover():
    text = css("terminal.css")
    rest = re.search(r"\.key\.primary \{[^}]*--k-bg: (#[0-9a-f]{6})", text).group(1)
    hover = re.search(r"\.key\.primary:hover \{[^}]*--k-bg: (#[0-9a-f]{6})", text).group(1)
    assert _contrast("#ffffff", rest) >= 4.5
    assert _contrast("#ffffff", hover) >= 4.5
    # --red itself is untouched: red text on the background stays AA
    assert "--red: #ff2e2e;" in text and _contrast("#ff2e2e", "#070403") >= 4.5


def test_the_led_blink_stops_and_forced_colours_keep_a_border():
    text = css("terminal.css")
    assert re.search(r"\.led\.err \{[^}]*animation: blink 1\.2s steps\(1\) 4", text)
    assert "@media (forced-colors: active)" in text
    assert re.search(r"forced-colors: active\) \{\s*\.led \{ border", text)


def test_the_terminal_focus_ring_is_2px_hi_and_reaches_switches_and_ticks():
    text = css("terminal.css")
    assert 'html[data-ui="cc"] :focus-visible { outline: 2px solid var(--hi); outline-offset: 2px; }' in text
    assert ".switch:has(input:focus-visible)" in text
    assert ".check:has(input:focus-visible) .g" in text


def test_fields_are_16px_on_phones_and_that_rule_is_last():
    text = css("phone.css").rstrip()
    last = text[text.rindex("@media"):]
    assert "max-width: 760px" in last and "font-size: 16px" in last


def test_the_phone_layer_has_no_text_under_12px():
    for size in re.findall(r"font-size:\s*([0-9.]+)px", _strip_comments(css("phone.css"))):
        assert float(size) >= 12, size


def test_the_font_faces_are_self_hosted_optional_and_relative():
    text = css("terminal.css")
    faces = re.findall(r"@font-face \{(.*?)\}", text, re.S)
    assert len(faces) >= 4
    for face in faces:
        assert "font-display: optional" in face
        assert "url(../fonts/" in face
    assert "fonts.googleapis" not in text and "fonts.gstatic" not in text


def test_the_page_and_toast_leave_room_for_the_dock():
    text = css("terminal.css") + css("phone.css")
    assert "var(--cc-dock-h, 0px)" in text
    assert "bottom: 76px" not in text and "100px; }" not in text


def test_no_box_drawing_in_terminal_templates():
    for p in TEMPLATES_CC.rglob("*.html"):
        text = p.read_text(encoding="utf-8")
        assert not re.search("[─-╿]", text), p


def test_no_bare_classic_vocabulary_in_terminal_templates():
    for p in TEMPLATES_CC.rglob("*.html"):
        for classes in re.findall(r'class="([^"]*)"', p.read_text(encoding="utf-8")):
            words = set(classes.split())
            assert not words & {"stack", "rule", "editors"}, (p.name, classes)


def test_the_retired_bench_panel_is_nowhere_in_static():
    for p in STATIC.rglob("*"):
        if p.is_file() and p.suffix in (".js", ".css", ".html"):
            assert not re.search(r"\btune\b", p.read_text(encoding="utf-8"), re.I), p


def test_no_em_dash_in_the_terminal_sheets():
    for path in sheets():
        text = _strip_comments(path.read_text(encoding="utf-8"))
        assert "—" not in text and "–" not in text, path.name


# ------------------------------------------------------------ fonts (R8, 2.3)


def test_font_bytes_never_change_under_the_same_name():
    manifest = json.loads((STATIC / "fonts" / "manifest.json").read_text(encoding="utf-8"))
    shipped = sorted(p.name for p in (STATIC / "fonts").glob("*.woff2"))
    assert shipped == sorted(manifest)
    for name, digest in manifest.items():
        assert hashlib.sha256((STATIC / "fonts" / name).read_bytes()).hexdigest() == digest, (
            f"{name} changed in place: a changed font is a NEW file name (R8)")


def test_every_font_family_is_named_in_the_notices():
    text = NOTICES.read_text(encoding="utf-8")
    block = text.rsplit("<!-- BEGIN HAND-MAINTAINED -->", 1)[1].split("<!-- END HAND-MAINTAINED -->", 1)[0]
    for p in (STATIC / "fonts").glob("*.woff2"):
        family = "JetBrains Mono" if p.name.startswith("jetbrains") else "Orbitron"
        assert family in block and p.name in block, p.name


def test_every_non_cjk_glyph_the_terminal_uses_is_in_a_shipped_range():
    """Derived, not listed from memory (wave 5): each codepoint above U+007F
    in the terminal files lies inside a JetBrains Mono unicode-range, or is
    CJK / an emoji left to the system face."""
    ranges = []
    for lo, hi in re.findall(r"U\+([0-9A-F]+)-([0-9A-F]+)", css("terminal.css")):
        ranges.append((int(lo, 16), int(hi, 16)))
    files = [p for p in CC.glob("*") if p.suffix in (".css", ".js")]
    files += list(TEMPLATES_CC.rglob("*.html"))
    for p in files:
        text = p.read_text(encoding="utf-8")
        cps = {ord(ch) for ch in text if ord(ch) > 0x7F}
        cps |= {int(m, 16) for m in re.findall(r'"\\([0-9A-Fa-f]{4,5})', text)}
        for cp in cps:
            if 0x2E80 <= cp <= 0x9FFF or 0xAC00 <= cp <= 0xD7AF or 0xFF00 <= cp <= 0xFFEF \
                    or cp >= 0x1F000:
                continue
            assert any(lo <= cp <= hi for lo, hi in ranges), f"{p.name}: U+{cp:04X}"
