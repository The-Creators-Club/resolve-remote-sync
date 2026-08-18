"""The vendored `broll_vlm/` package: still byte-identical to the indexer, and
still WORKING once it is inside the companion.

Two halves, and the second is the one that would have caught the real bug:

  * parity -- every file under `ccsync_companion/broll_vlm/` is its source's
    bytes below the marker line (the prompt is a headerless exact copy; see
    the package's __init__ for why it cannot carry a header). tools/release.ps1
    refuses to build on drift and server/tests/test_cross_component.py pins the
    same comparison across components; this is the copy that runs in the
    companion's own suite, where an engineer editing the companion will see it.
  * a real `describe_video` pass -- the indexer's own end-to-end shape
    (frames.json + extracted frames + a fake llama-server speaking the
    OpenAI-compatible API) driven through shim config/storage objects, from
    inside `ccsync_companion`. That proves the vendored path runs UNMODIFIED
    here: relative imports resolve inside the sub-package, the prompt file is
    found beside it, the TF-IDF category fallback works without fastembed, and
    the pixel-stat quality flags work with nothing but Pillow.
"""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from ccsync_companion.broll_vlm import compact_format, local_vlm

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "broll" / "indexer" / "broll_index"
VENDORED_DIR = REPO_ROOT / "companion" / "src" / "ccsync_companion" / "broll_vlm"

VENDOR_MARKER = b"# --- vendored content below, byte-identical ---"
VENDORED_MODULES = ("local_models.py", "local_runtime.py", "local_vlm.py",
                    "compact_format.py", "contract.py")
VENDORED_PROMPT = "prompts/index_clip_v7_compact.md"


def _body_below_marker(path: Path) -> bytes:
    raw = path.read_bytes()
    assert raw.count(VENDOR_MARKER) == 1, (
        f"{path} must carry the marker exactly once, as the last line of its header "
        f"(found {raw.count(VENDOR_MARKER)})")
    rest = raw.split(VENDOR_MARKER, 1)[1]
    if rest.startswith(b"\r\n"):
        return rest[2:]
    return rest[1:] if rest.startswith(b"\n") else rest


@pytest.mark.parametrize("name", VENDORED_MODULES)
def test_each_vendored_module_matches_its_source(name):
    source = (SRC_DIR / name).read_bytes()
    body = _body_below_marker(VENDORED_DIR / name)
    assert body == source, (
        f"{VENDORED_DIR / name} has drifted from {SRC_DIR / name} "
        f"({len(body)} bytes below the marker vs {len(source)}). Edit the INDEXER's "
        f"copy, then re-copy the whole file in below the marker line.")


def test_the_prompt_is_an_exact_copy():
    """No header on this one: `build_compact_prompt` sends the file's text to
    the model, so a vendoring header would become part of the prompt AND
    differ from what the indexer sends -- the drift this vendoring exists to
    prevent. Whole-file equality is the stronger check anyway."""
    assert (VENDORED_DIR / VENDORED_PROMPT).read_bytes() == (SRC_DIR / VENDORED_PROMPT).read_bytes()


def test_the_prompt_ships_where_the_code_looks_for_it():
    assert compact_format.PROMPT_PATH == VENDORED_DIR / "prompts" / "index_clip_v7_compact.md"
    assert compact_format.PROMPT_PATH.is_file()


def test_the_vendored_set_is_exactly_what_is_pinned():
    """A sixth module that appeared here without a parity pair would be
    unchecked forever."""
    present = sorted(p.name for p in VENDORED_DIR.glob("*.py") if p.name != "__init__.py")
    assert present == sorted(VENDORED_MODULES)


def test_the_prompt_is_declared_as_pyinstaller_data():
    """A frozen build without this file raises FileNotFoundError on the first
    clip -- long after the build looked fine."""
    spec = (REPO_ROOT / "companion" / "build.spec").read_text(encoding="utf-8")
    assert "broll_vlm/prompts/index_clip_v7_compact.md" in spec
    assert "ccsync_companion/broll_vlm/prompts" in spec


# ---------------------------------------------------------------------------
# describe_video, unmodified, inside the companion
# ---------------------------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    """The llama-server's OpenAI-compatible surface, as much of it as
    local_vlm speaks."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.calls.append(body)  # type: ignore[attr-defined]
        script = self.server.script      # type: ignore[attr-defined]
        text = script[min(len(self.server.calls) - 1, len(script) - 1)]  # type: ignore[attr-defined]
        payload = {
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40},
            "timings": {"prompt_ms": 50.0, "predicted_ms": 25.0},
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake_llama_server():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    httpd.script = ["S F1-F2 | wide shot of a harbour at dusk | boats;water | 港口 // harbour\n"
                    "S F3 | newsreader | newsreader | - // -\nT harbour;evening\n"]
    httpd.calls = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


class ConfigShim(SimpleNamespace):
    """What `describe_video` reads off the indexer's Config. The companion has
    no yaml config and no Config class; it hands the vendored code this."""


class StorageShim:
    """The two Storage methods `describe_video` calls. In the real ingest
    these become a fleet-route POST; here they just record."""

    def __init__(self, taxonomy):
        self._taxonomy = taxonomy
        self.written = {}

    def get_categories(self):
        return self._taxonomy

    def write_index_result(self, video_id, *, themes, quality_flags, category_hint,
                           segments, model):
        self.written[video_id] = {"themes": themes, "quality_flags": quality_flags,
                                  "category_hint": category_hint, "segments": segments,
                                  "model": model}


def _make_frames(data_root: Path, video_id: int, n: int) -> None:
    from PIL import Image

    sheets = data_root / "sheets" / str(video_id)
    frames = sheets / "frames"
    frames.mkdir(parents=True)
    timestamps = []
    for i in range(n):
        timestamps.append(float(i * 4))
        Image.new("RGB", (32, 18), color=(90, 90, 90)).save(frames / f"frame_{i:04d}.jpg", "JPEG")
    (sheets / "frames.json").write_text(
        json.dumps({"timestamps": timestamps, "sheets": []}), encoding="utf-8")


def _cfg(data_root: Path) -> ConfigShim:
    return ConfigShim(
        data_root=data_root,
        indexer=SimpleNamespace(model_tier="good", local_cache_dir="", llama_server_path="",
                                gpu_layers=99, frames_per_call=9, merge_similar_segments=True),
        embedding=SimpleNamespace(cache_dir=""),
    )


def test_describe_video_runs_the_vendored_path_inside_the_companion(
        tmp_path, fake_llama_server):
    data_root = tmp_path / "data"
    data_root.mkdir()
    _make_frames(data_root, 77, 3)
    storage = StorageShim([
        {"slug": "places/coast", "label": "Coast", "description": "harbours, boats, sea"},
        {"slug": "people/interview", "label": "Interview", "description": "talking heads"},
    ])

    result = local_vlm.describe_video(
        _cfg(data_root), storage, {"id": 77},
        server_url=f"http://127.0.0.1:{fake_llama_server.server_port}")

    # Segment times come from the frame table, never from the model.
    assert [s["t_start"] for s in result["segments"]] == [0.0, 8.0]
    assert result["segments"][0]["t_end"] == 4.0
    # On-screen text survives, CJK and all -- this is the field the whole
    # local backend exists for.
    assert result["segments"][0]["onscreen_text"] == "港口"
    assert result["segments"][0]["onscreen_text_en"] == "harbour"
    # The contract's canonicalisation ran (contract.py, vendored beside it).
    assert result["segments"][1]["description"] == "newsreader"
    assert storage.written[77]["model"] == "local:qwen3-vl-4b-q4_k_m"
    assert storage.written[77]["category_hint"] in ("places/coast", "people/interview", None)


def test_category_assignment_falls_back_to_tfidf_without_fastembed(tmp_path):
    """The companion has no fastembed and never will (it is the indexer's
    embed stage's dependency). The fallback has to be stdlib-only, or every
    clip this machine indexes comes back uncategorised."""
    assigner = compact_format.CategoryAssigner([
        {"slug": "places/coast", "label": "Coast", "description": "harbours, boats, sea"},
        {"slug": "people/interview", "label": "Interview", "description": "talking heads"},
    ], prefer="tfidf")
    assert assigner.method == "tfidf"
    slug, score = assigner.assign("boats moored in a harbour, sea and water")
    assert slug == "places/coast"
    assert score > 0


def test_pixel_quality_flags_need_nothing_but_pillow(tmp_path):
    from PIL import Image

    paths = []
    for i in range(3):
        p = tmp_path / f"f{i}.jpg"
        Image.new("RGB", (64, 36), color=(250, 250, 250)).save(p, "JPEG")
        paths.append(p)
    flags, stats = compact_format.pixel_quality_flags(paths)
    assert "overexposed" in flags
    assert len(stats) == 3
