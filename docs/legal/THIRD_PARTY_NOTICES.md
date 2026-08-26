<!-- DRAFT FOR COUNSEL — NOT LEGAL ADVICE. First written 2026-08-17 for
     docs/COMMERCIAL_READINESS.md item 3; the tables below are
     regenerated, and `git log` on this file is when they last were.
     GENERATED FILE — the pip sections below are produced by
     `python tools/gen_notices.py`. Edit that script, not these tables.
     The block between <!-- BEGIN HAND-MAINTAINED --> and
     <!-- END HAND-MAINTAINED --> is written by hand and is preserved
     verbatim across regeneration — it carries the components pip
     cannot see, which is where every copyleft obligation actually is.
     TODO(legal): replace "Cablewrap Creative" with the registered
     legal entity name. The placeholder was inferred from the
     operator's email domain and is almost
     certainly NOT the correct contracting entity — confirm before use.
     TODO(legal): confirm which of these components are actually
     CONVEYED to a customer versus merely present in a developer venv;
     the tables below are the venvs, not the shipped artefacts. -->

# CC Sync — third-party notices

**Draft of 2026-08-17. DRAFT FOR COUNSEL — not legal advice.**

CC Sync is proprietary software (see `LICENSE`). It incorporates, links
against, or arranges the download of the third-party components listed
here. Each remains licensed by its own author under its own terms, which
prevail over `LICENSE` for that component.

**How to read the verification column.** `metadata` means the fact came
out of the installed distribution's own metadata via `pip-licenses`, and
`+text` means the distribution also ships the licence text on disk — both
are VERIFIED. Anything in the hand-maintained section marked *stated from
knowledge — confirm* was not verified against an artefact on this machine
and must be checked before this document is relied on.

## LICENCES NEEDING ATTENTION

Copyleft or otherwise non-permissive licences found in the venvs. Being
listed here is not a finding of non-compliance — it means a human must
decide whether the way we ship this one is compliant. See the
"LGPL components that remain" subsection for the ones already reasoned
through.

| Package | Version | Licence | Present in | Verification |
|---|---|---|---|---|
| `bgutil-ytdlp-pot-provider` | 1.3.1 | **GNU General Public License v3 (GPLv3)** (GPL) | dashboard | metadata |
| `certifi` | 2026.7.22 | **Mozilla Public License 2.0 (MPL 2.0)** (MPL) | dashboard, music/web | metadata+text |
| `certifi` | 2026.6.17 | **Mozilla Public License 2.0 (MPL 2.0)** (MPL) | broll/web | metadata+text |
| `paramiko` | 5.0.0 | **LGPL-2.1** (LGPL) | dashboard | metadata+text |
| `pyinstaller` | 6.21.0 | **GNU General Public License v2 (GPLv2)** (GPL) | companion | metadata+text |
| `pyinstaller-hooks-contrib` | 2026.6 | **Apache Software License; GNU General Public License v2 (GPLv2)** (GPL) | companion | metadata+text |
| `pystray` | 0.19.5 | **GNU Lesser General Public License v3 (LGPLv3)** (LGPL) | companion | metadata+text |
| `tqdm` | 4.69.0 | **MPL-2.0 AND MIT** (MPL) | broll/web | metadata+text |

## Scan warnings

These components were NOT scanned; their packages are missing from
every table below.

- ytdl/web: no venv at E:\Projects\resolve-remote-sync\ytdl\web\.venv — SKIPPED, its packages are not in this inventory

## Python dependencies by component

What is installed in each component's development virtualenv. This is
**not** the same as what a customer receives: the frozen companion ships
only what `companion/build.spec` collects, and the deployed container
installs `dashboard/deploy/requirements.txt`.

### companion

editor tray app; the frozen build ships a SUBSET of this (see build.spec). Venv: `E:\Projects\resolve-remote-sync\companion\.venv` — 28 package(s).

| Package | Version | Licence | Home page |
|---|---|---|---|
| `altgraph` | 0.17.5 | MIT License | https://altgraph.readthedocs.io |
| `asn1crypto` | 1.5.1 | MIT License | https://github.com/wbond/asn1crypto |
| `ccsync-companion` | 0.9.4 | UNKNOWN | UNKNOWN |
| `ccsync-companion` | 0.9.4 | UNKNOWN | UNKNOWN |
| `colorama` | 0.4.6 | BSD License | https://github.com/tartley/colorama |
| `flatbuffers` | 25.12.19 | Apache Software License | https://google.github.io/flatbuffers/ |
| `iniconfig` | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| `numpy` | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| `onnxruntime` | 1.29.0 | MIT License | https://onnxruntime.ai |
| `packaging` | 26.2 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| `pefile` | 2024.8.26 | MIT | https://github.com/erocarrera/pefile |
| `pg8000` | 1.31.5 | BSD License | https://codeberg.org/tlocke/pg8000 |
| `pillow` | 12.3.0 | MIT-CMU | https://python-pillow.github.io |
| `pluggy` | 1.6.0 | MIT License | UNKNOWN |
| `protobuf` | 7.35.1 | 3-Clause BSD License | https://developers.google.com/protocol-buffers/ |
| `py-spy` | 0.4.2 | MIT License | https://github.com/benfred/py-spy |
| `Pygments` | 2.20.0 | BSD-2-Clause | https://pygments.org |
| `pyinstaller` | 6.21.0 | GNU General Public License v2 (GPLv2) | https://pyinstaller.org |
| `pyinstaller-hooks-contrib` | 2026.6 | Apache Software License; GNU General Public License v2 (GPLv2) | https://github.com/pyinstaller/pyinstaller-hooks-contrib |
| `pystray` | 0.19.5 | GNU Lesser General Public License v3 (LGPLv3) | https://github.com/moses-palmer/pystray |
| `pytest` | 9.1.1 | MIT | https://docs.pytest.org/en/latest/ |
| `python-dateutil` | 2.9.0.post0 | Apache Software License; BSD License | https://github.com/dateutil/dateutil |
| `pywin32-ctypes` | 0.2.3 | BSD-3-Clause | https://github.com/enthought/pywin32-ctypes |
| `scramp` | 1.4.17 | MIT No Attribution License (MIT-0) | https://codeberg.org/tlocke/scramp |
| `six` | 1.17.0 | MIT License | https://github.com/benjaminp/six |
| `watchdog` | 6.0.0 | Apache Software License | https://github.com/gorakhargosh/watchdog |
| `xxhash` | 4.0.1 | BSD-2-Clause | https://github.com/ifduyue/python-xxhash |
| `zstandard` | 0.25.0 | BSD-3-Clause | https://github.com/indygreg/python-zstandard |

### dashboard

FastAPI fleet dashboard; the deployed container installs dashboard/deploy/requirements.txt, not this venv. Venv: `E:\Projects\resolve-remote-sync\dashboard\.venv` — 55 package(s).

| Package | Version | Licence | Home page |
|---|---|---|---|
| `annotated-doc` | 0.0.5 | MIT | https://github.com/fastapi/annotated-doc |
| `annotated-types` | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| `anthropic` | 0.122.0 | MIT License | https://github.com/anthropics/anthropic-sdk-python |
| `anyio` | 4.14.2 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| `bcrypt` | 5.0.0 | Apache Software License | https://github.com/pyca/bcrypt/ |
| `bgutil-ytdlp-pot-provider` | 1.3.1 | GNU General Public License v3 (GPLv3) | UNKNOWN |
| `ccsync-dashboard` | 0.1.0 | UNKNOWN | UNKNOWN |
| `ccsync-dashboard` | 0.1.0 | UNKNOWN | UNKNOWN |
| `certifi` | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | https://github.com/certifi/python-certifi |
| `cffi` | 2.1.1 | MIT-0 | https://cffi.readthedocs.io/en/latest/whatsnew.html |
| `charset-normalizer` | 3.5.1 | MIT | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| `click` | 8.4.2 | BSD-3-Clause | https://github.com/pallets/click/ |
| `colorama` | 0.4.6 | BSD License | https://github.com/tartley/colorama |
| `cryptography` | 50.0.0 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| `distro` | 1.9.0 | Apache Software License | https://github.com/python-distro/distro |
| `docstring_parser` | 0.18.0 | MIT License | https://github.com/rr-/docstring_parser |
| `fastapi` | 0.141.1 | MIT | https://github.com/fastapi/fastapi |
| `flatbuffers` | 25.12.19 | Apache Software License | https://google.github.io/flatbuffers/ |
| `h11` | 0.16.0 | MIT License | https://github.com/python-hyper/h11 |
| `httpcore` | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| `httpx` | 0.28.1 | BSD License | https://github.com/encode/httpx |
| `idna` | 3.18 | BSD-3-Clause | https://github.com/kjd/idna |
| `iniconfig` | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| `invoke` | 3.0.3 | BSD-2-Clause | https://github.com/pyinvoke/invoke |
| `jieba` | 0.42.1 | MIT License | https://github.com/fxsjy/jieba |
| `Jinja2` | 3.1.6 | BSD License | https://github.com/pallets/jinja/ |
| `jiter` | 0.16.0 | MIT | https://github.com/pydantic/jiter/ |
| `MarkupSafe` | 3.0.3 | BSD-3-Clause | https://github.com/pallets/markupsafe/ |
| `numpy` | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| `onnxruntime` | 1.28.0 | MIT License | https://onnxruntime.ai |
| `opencc-python-reimplemented` | 0.1.7 | Apache Software License | https://github.com/yichen0831/opencc-python |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| `paramiko` | 5.0.0 | LGPL-2.1 | https://github.com/paramiko/paramiko |
| `pluggy` | 1.6.0 | MIT License | UNKNOWN |
| `protobuf` | 7.35.1 | 3-Clause BSD License | https://developers.google.com/protocol-buffers/ |
| `pycparser` | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| `pydantic` | 2.13.4 | MIT | https://github.com/pydantic/pydantic |
| `pydantic_core` | 2.46.4 | MIT | https://github.com/pydantic |
| `Pygments` | 2.21.0 | BSD-2-Clause | https://pygments.org |
| `PyJWT` | 2.13.0 | MIT | https://github.com/jpadilla/pyjwt |
| `PyNaCl` | 1.6.2 | Apache Software License | https://github.com/pyca/pynacl |
| `pyspnego` | 0.12.1 | MIT | https://github.com/jborean93/pyspnego |
| `pytest` | 9.1.1 | MIT | https://docs.pytest.org/en/latest/ |
| `python-multipart` | 0.0.32 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| `RapidFuzz` | 3.14.5 | MIT | https://github.com/rapidfuzz/RapidFuzz |
| `requests` | 2.34.2 | Apache Software License | https://github.com/psf/requests |
| `smbprotocol` | 1.17.0 | MIT | https://github.com/jborean93/smbprotocol |
| `sniffio` | 1.3.1 | Apache Software License; MIT License | https://github.com/python-trio/sniffio |
| `sspilib` | 0.5.0 | MIT | https://github.com/jborean93/sspilib |
| `starlette` | 1.6.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| `typing-inspection` | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection |
| `typing_extensions` | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| `urllib3` | 2.7.0 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| `uvicorn` | 0.52.3 | BSD-3-Clause | https://uvicorn.dev/ |
| `yt-dlp` | 2026.7.4 | Unlicense | https://github.com/yt-dlp/yt-dlp |

### music/web

music search UI mounted at /music; deliberately no torch. Venv: `E:\Projects\resolve-remote-sync\music\web\.venv` — 32 package(s).

| Package | Version | Licence | Home page |
|---|---|---|---|
| `annotated-doc` | 0.0.5 | MIT | https://github.com/fastapi/annotated-doc |
| `annotated-types` | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| `anyio` | 4.14.2 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| `certifi` | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | https://github.com/certifi/python-certifi |
| `click` | 8.4.2 | BSD-3-Clause | https://github.com/pallets/click/ |
| `colorama` | 0.4.6 | BSD License | https://github.com/tartley/colorama |
| `fastapi` | 0.141.1 | MIT | https://github.com/fastapi/fastapi |
| `flatbuffers` | 25.12.19 | Apache Software License | https://google.github.io/flatbuffers/ |
| `h11` | 0.16.0 | MIT License | https://github.com/python-hyper/h11 |
| `httpcore` | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| `httptools` | 0.8.0 | MIT | https://github.com/MagicStack/httptools |
| `httpx` | 0.28.1 | BSD License | https://github.com/encode/httpx |
| `idna` | 3.18 | BSD-3-Clause | https://github.com/kjd/idna |
| `iniconfig` | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| `numpy` | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| `onnxruntime` | 1.28.0 | MIT License | https://onnxruntime.ai |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| `pluggy` | 1.6.0 | MIT License | UNKNOWN |
| `protobuf` | 7.35.1 | 3-Clause BSD License | https://developers.google.com/protocol-buffers/ |
| `pydantic` | 2.13.4 | MIT | https://github.com/pydantic/pydantic |
| `pydantic_core` | 2.46.4 | MIT | https://github.com/pydantic |
| `Pygments` | 2.20.0 | BSD-2-Clause | https://pygments.org |
| `pytest` | 9.1.1 | MIT | https://docs.pytest.org/en/latest/ |
| `python-dotenv` | 1.2.2 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| `python-multipart` | 0.0.32 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| `PyYAML` | 6.0.3 | MIT License | https://pyyaml.org/ |
| `starlette` | 1.6.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| `typing-inspection` | 0.4.2 | MIT | https://github.com/pydantic/typing-inspection |
| `typing_extensions` | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| `uvicorn` | 0.52.1 | BSD-3-Clause | https://uvicorn.dev/ |
| `watchfiles` | 1.2.0 | MIT License | https://github.com/samuelcolvin/watchfiles |
| `websockets` | 17.0.1 | BSD-3-Clause | https://github.com/python-websockets/websockets |

### broll/web

b-roll search UI mounted at /broll; borrowed from the pre-fold repo. Venv: `E:\Projects\broll-platform\web\.venv` — 50 package(s).

| Package | Version | Licence | Home page |
|---|---|---|---|
| `annotated-doc` | 0.0.4 | MIT | https://github.com/fastapi/annotated-doc |
| `annotated-types` | 0.7.0 | MIT License | https://github.com/annotated-types/annotated-types |
| `anyio` | 4.14.2 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| `broll-web` | 0.1.0 | UNKNOWN | UNKNOWN |
| `certifi` | 2026.6.17 | Mozilla Public License 2.0 (MPL 2.0) | https://github.com/certifi/python-certifi |
| `charset-normalizer` | 3.4.9 | MIT | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| `click` | 8.4.2 | BSD-3-Clause | https://github.com/pallets/click/ |
| `colorama` | 0.4.6 | BSD License | https://github.com/tartley/colorama |
| `fastapi` | 0.139.2 | MIT | https://github.com/fastapi/fastapi |
| `fastembed` | 0.8.0 | Other/Proprietary License | https://github.com/qdrant/fastembed |
| `filelock` | 3.31.1 | MIT | https://github.com/tox-dev/py-filelock |
| `flatbuffers` | 25.12.19 | Apache Software License | https://google.github.io/flatbuffers/ |
| `fsspec` | 2026.6.0 | BSD-3-Clause | https://github.com/fsspec/filesystem_spec |
| `h11` | 0.16.0 | MIT License | https://github.com/python-hyper/h11 |
| `hf-xet` | 1.5.2 | Apache-2.0 | https://github.com/huggingface/xet-core |
| `httpcore` | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| `httptools` | 0.8.0 | MIT | https://github.com/MagicStack/httptools |
| `httpx` | 0.28.1 | BSD License | https://github.com/encode/httpx |
| `huggingface_hub` | 1.24.0 | Apache Software License | https://github.com/huggingface/huggingface_hub |
| `idna` | 3.18 | BSD-3-Clause | https://github.com/kjd/idna |
| `iniconfig` | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| `jieba` | 0.42.1 | MIT License | https://github.com/fxsjy/jieba |
| `loguru` | 0.7.3 | MIT License | https://github.com/Delgan/loguru |
| `mmh3` | 5.2.1 | MIT License | https://pypi.org/project/mmh3/ |
| `numpy` | 2.5.1 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| `onnxruntime` | 1.27.0 | MIT License | https://onnxruntime.ai |
| `opencc-python-reimplemented` | 0.1.7 | Apache Software License | https://github.com/yichen0831/opencc-python |
| `packaging` | 26.2 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| `pillow` | 12.3.0 | MIT-CMU | https://python-pillow.github.io |
| `pluggy` | 1.6.0 | MIT License | UNKNOWN |
| `protobuf` | 7.35.1 | 3-Clause BSD License | https://developers.google.com/protocol-buffers/ |
| `py_rust_stemmers` | 0.1.8 | UNKNOWN | UNKNOWN |
| `pydantic` | 2.13.4 | MIT | https://github.com/pydantic/pydantic |
| `pydantic_core` | 2.46.4 | MIT | https://github.com/pydantic |
| `Pygments` | 2.20.0 | BSD-2-Clause | https://pygments.org |
| `pytest` | 9.1.1 | MIT | https://docs.pytest.org/en/latest/ |
| `python-dotenv` | 1.2.2 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| `PyYAML` | 6.0.3 | MIT License | https://pyyaml.org/ |
| `RapidFuzz` | 3.14.5 | MIT | https://github.com/rapidfuzz/RapidFuzz |
| `requests` | 2.34.2 | Apache Software License | https://github.com/psf/requests |
| `starlette` | 1.3.1 | BSD-3-Clause | https://github.com/Kludex/starlette |
| `tokenizers` | 0.23.1 | Apache Software License | https://github.com/huggingface/tokenizers |
| `tqdm` | 4.69.0 | MPL-2.0 AND MIT | https://tqdm.github.io |
| `typing-inspection` | 0.4.2 | MIT | https://github.com/pydantic/typing-inspection |
| `typing_extensions` | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| `urllib3` | 2.7.0 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| `uvicorn` | 0.51.0 | BSD-3-Clause | https://uvicorn.dev/ |
| `watchfiles` | 1.2.0 | MIT License | https://github.com/samuelcolvin/watchfiles |
| `websockets` | 16.1.1 | BSD-3-Clause | https://github.com/python-websockets/websockets |
| `win32_setctime` | 1.2.0 | MIT License | https://github.com/Delgan/win32-setctime |

## All pip dependencies (merged)

103 distinct (package, version) pair(s) across every scanned venv.

| Package | Version | Licence | Components | Licence text on disk |
|---|---|---|---|---|
| `altgraph` | 0.17.5 | MIT License | companion | yes |
| `annotated-doc` | 0.0.5 | MIT | dashboard, music/web | yes |
| `annotated-doc` | 0.0.4 | MIT | broll/web | yes |
| `annotated-types` | 0.8.0 | MIT | dashboard, music/web | yes |
| `annotated-types` | 0.7.0 | MIT License | broll/web | yes |
| `anthropic` | 0.122.0 | MIT License | dashboard | yes |
| `anyio` | 4.14.2 | MIT | dashboard, music/web, broll/web | yes |
| `asn1crypto` | 1.5.1 | MIT License | companion | yes |
| `bcrypt` | 5.0.0 | Apache Software License | dashboard | yes |
| `bgutil-ytdlp-pot-provider` | 1.3.1 | GNU General Public License v3 (GPLv3) | dashboard | no |
| `broll-web` | 0.1.0 | UNKNOWN | broll/web | no |
| `ccsync-companion` | 0.9.4 | UNKNOWN | companion, companion | no |
| `ccsync-dashboard` | 0.1.0 | UNKNOWN | dashboard, dashboard | no |
| `certifi` | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | dashboard, music/web | yes |
| `certifi` | 2026.6.17 | Mozilla Public License 2.0 (MPL 2.0) | broll/web | yes |
| `cffi` | 2.1.1 | MIT-0 | dashboard | yes |
| `charset-normalizer` | 3.5.1 | MIT | dashboard | yes |
| `charset-normalizer` | 3.4.9 | MIT | broll/web | yes |
| `click` | 8.4.2 | BSD-3-Clause | dashboard, music/web, broll/web | yes |
| `colorama` | 0.4.6 | BSD License | companion, dashboard, music/web, broll/web | yes |
| `cryptography` | 50.0.0 | Apache-2.0 OR BSD-3-Clause | dashboard | yes |
| `distro` | 1.9.0 | Apache Software License | dashboard | yes |
| `docstring_parser` | 0.18.0 | MIT License | dashboard | yes |
| `fastapi` | 0.141.1 | MIT | dashboard, music/web | yes |
| `fastapi` | 0.139.2 | MIT | broll/web | yes |
| `fastembed` | 0.8.0 | Other/Proprietary License | broll/web | yes |
| `filelock` | 3.31.1 | MIT | broll/web | yes |
| `flatbuffers` | 25.12.19 | Apache Software License | companion, dashboard, music/web, broll/web | no |
| `fsspec` | 2026.6.0 | BSD-3-Clause | broll/web | yes |
| `h11` | 0.16.0 | MIT License | dashboard, music/web, broll/web | yes |
| `hf-xet` | 1.5.2 | Apache-2.0 | broll/web | yes |
| `httpcore` | 1.0.9 | BSD-3-Clause | dashboard, music/web, broll/web | yes |
| `httptools` | 0.8.0 | MIT | music/web, broll/web | yes |
| `httpx` | 0.28.1 | BSD License | dashboard, music/web, broll/web | yes |
| `huggingface_hub` | 1.24.0 | Apache Software License | broll/web | yes |
| `idna` | 3.18 | BSD-3-Clause | dashboard, music/web, broll/web | yes |
| `iniconfig` | 2.3.0 | MIT | companion, dashboard, music/web, broll/web | yes |
| `invoke` | 3.0.3 | BSD-2-Clause | dashboard | yes |
| `jieba` | 0.42.1 | MIT License | dashboard, broll/web | no |
| `Jinja2` | 3.1.6 | BSD License | dashboard | yes |
| `jiter` | 0.16.0 | MIT | dashboard | yes |
| `loguru` | 0.7.3 | MIT License | broll/web | no |
| `MarkupSafe` | 3.0.3 | BSD-3-Clause | dashboard | yes |
| `mmh3` | 5.2.1 | MIT License | broll/web | yes |
| `numpy` | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | companion, dashboard, music/web | yes |
| `numpy` | 2.5.1 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | broll/web | yes |
| `onnxruntime` | 1.29.0 | MIT License | companion | yes |
| `onnxruntime` | 1.28.0 | MIT License | dashboard, music/web | yes |
| `onnxruntime` | 1.27.0 | MIT License | broll/web | yes |
| `opencc-python-reimplemented` | 0.1.7 | Apache Software License | dashboard, broll/web | yes |
| `packaging` | 26.2 | Apache-2.0 OR BSD-2-Clause | companion, broll/web | yes |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | dashboard, music/web | yes |
| `paramiko` | 5.0.0 | LGPL-2.1 | dashboard | yes |
| `pefile` | 2024.8.26 | MIT | companion | yes |
| `pg8000` | 1.31.5 | BSD License | companion | yes |
| `pillow` | 12.3.0 | MIT-CMU | companion, broll/web | yes |
| `pluggy` | 1.6.0 | MIT License | companion, dashboard, music/web, broll/web | yes |
| `protobuf` | 7.35.1 | 3-Clause BSD License | companion, dashboard, music/web, broll/web | yes |
| `py-spy` | 0.4.2 | MIT License | companion | yes |
| `py_rust_stemmers` | 0.1.8 | UNKNOWN | broll/web | yes |
| `pycparser` | 3.0 | BSD-3-Clause | dashboard | yes |
| `pydantic` | 2.13.4 | MIT | dashboard, music/web, broll/web | yes |
| `pydantic_core` | 2.46.4 | MIT | dashboard, music/web, broll/web | yes |
| `Pygments` | 2.20.0 | BSD-2-Clause | companion, music/web, broll/web | yes |
| `Pygments` | 2.21.0 | BSD-2-Clause | dashboard | yes |
| `pyinstaller` | 6.21.0 | GNU General Public License v2 (GPLv2) | companion | yes |
| `pyinstaller-hooks-contrib` | 2026.6 | Apache Software License; GNU General Public License v2 (GPLv2) | companion | yes |
| `PyJWT` | 2.13.0 | MIT | dashboard | yes |
| `PyNaCl` | 1.6.2 | Apache Software License | dashboard | yes |
| `pyspnego` | 0.12.1 | MIT | dashboard | yes |
| `pystray` | 0.19.5 | GNU Lesser General Public License v3 (LGPLv3) | companion | yes |
| `pytest` | 9.1.1 | MIT | companion, dashboard, music/web, broll/web | yes |
| `python-dateutil` | 2.9.0.post0 | Apache Software License; BSD License | companion | yes |
| `python-dotenv` | 1.2.2 | BSD-3-Clause | music/web, broll/web | yes |
| `python-multipart` | 0.0.32 | Apache-2.0 | dashboard, music/web | yes |
| `pywin32-ctypes` | 0.2.3 | BSD-3-Clause | companion | yes |
| `PyYAML` | 6.0.3 | MIT License | music/web, broll/web | yes |
| `RapidFuzz` | 3.14.5 | MIT | dashboard, broll/web | yes |
| `requests` | 2.34.2 | Apache Software License | dashboard, broll/web | yes |
| `scramp` | 1.4.17 | MIT No Attribution License (MIT-0) | companion | yes |
| `six` | 1.17.0 | MIT License | companion | yes |
| `smbprotocol` | 1.17.0 | MIT | dashboard | yes |
| `sniffio` | 1.3.1 | Apache Software License; MIT License | dashboard | yes |
| `sspilib` | 0.5.0 | MIT | dashboard | yes |
| `starlette` | 1.6.0 | BSD-3-Clause | dashboard, music/web | yes |
| `starlette` | 1.3.1 | BSD-3-Clause | broll/web | yes |
| `tokenizers` | 0.23.1 | Apache Software License | broll/web | no |
| `tqdm` | 4.69.0 | MPL-2.0 AND MIT | broll/web | yes |
| `typing-inspection` | 0.4.4 | MIT | dashboard | yes |
| `typing-inspection` | 0.4.2 | MIT | music/web, broll/web | yes |
| `typing_extensions` | 4.16.0 | PSF-2.0 | dashboard, music/web, broll/web | yes |
| `urllib3` | 2.7.0 | MIT | dashboard, broll/web | yes |
| `uvicorn` | 0.52.3 | BSD-3-Clause | dashboard | yes |
| `uvicorn` | 0.52.1 | BSD-3-Clause | music/web | yes |
| `uvicorn` | 0.51.0 | BSD-3-Clause | broll/web | yes |
| `watchdog` | 6.0.0 | Apache Software License | companion | yes |
| `watchfiles` | 1.2.0 | MIT License | music/web, broll/web | yes |
| `websockets` | 17.0.1 | BSD-3-Clause | music/web | yes |
| `websockets` | 16.1.1 | BSD-3-Clause | broll/web | yes |
| `win32_setctime` | 1.2.0 | MIT License | broll/web | yes |
| `xxhash` | 4.0.1 | BSD-2-Clause | companion | yes |
| `yt-dlp` | 2026.7.4 | Unlicense | dashboard | yes |
| `zstandard` | 0.25.0 | BSD-3-Clause | companion | yes |

<!-- BEGIN HAND-MAINTAINED -->
## Non-pip components (hand-maintained)

Everything CC Sync ships, embeds, or arranges the download of that pip cannot
see. This section is written by hand and preserved verbatim by
`tools/gen_notices.py`; the generator cannot produce it, and every copyleft
obligation the product actually carries is in here rather than in the tables
above.

### How a component is conveyed — the distinction the licences turn on

Three modes, because "we ship it" and "we tell the customer's own machine to
fetch it" are different acts under GPL §6 / MPL §3:

- **(A) EMBEDDED** — inside an artefact we build and publish (the frozen
  companion exe, the dashboard image, a file we SFTP onto a customer's NAS).
  We are conveying. Copyleft obligations attach to us.
- **(B) FETCHED BY THE CUSTOMER'S MACHINE** — our installer or companion tells
  the editor's workstation or the customer's NAS to download it directly from
  upstream, over a pinned URL, and verifies it. Upstream conveys to the
  customer; we convey nothing. We do choose and pin the build, which is why the
  written offers below are given anyway where the licence is GPL.
- **(C) CUSTOMER-SUPPLIED** — the customer already has it, or installs it from
  their own vendor's catalogue. We only talk to it.

TODO(legal): confirm that mode (B) is accepted as non-conveying in the target
jurisdictions. The FSF's position on "the user downloads it themselves" is
well known but this product automates the download, which is the fact pattern
counsel should look at.

### Inventory

| Component | Version / pin | Licence | Verification | Where obtained | Mode |
|---|---|---|---|---|---|
| rclone | `rclone-current-*` (unpinned, resolved at install time) | MIT | *stated from knowledge — confirm* | `downloads.rclone.org` (`installer/windows_bootstrap.ps1:771`, `installer/macos_bootstrap.sh:1437-1439`) | B |
| Syncthing (editor side) | latest release resolved at install time | MPL-2.0 | *stated from knowledge — confirm* | `github.com/syncthing/syncthing` releases (`installer/windows_bootstrap.ps1:935-941`, `installer/macos_bootstrap.sh:1536-1539`) | B |
| Syncthing (NAS side) | whatever the NAS vendor's catalogue offers | MPL-2.0 | *stated from knowledge — confirm* | the TrueNAS/Synology app catalogue, installed through the NAS's own API (`server/install_syncthing_app.py:93-151`) | C |
| **ffmpeg (editor side)** | `eugeneware/ffmpeg-static` tag `b6.1.1`; binary reports `6.1.1-essentials_build` | **GPLv3** | version string measured 2026-08-16 (`sidecar_tools.py:41`) — VERIFIED; licence *stated from knowledge — confirm* | GitHub release assets, sha256-pinned per asset (`companion/src/ccsync_companion/sidecar_tools.py:94-133`) | B |
| **ffmpeg (NAS side)** | `ffmpeg-7.0.2-amd64-static.tar.xz`, sha256 `abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67` | **GPLv3** | pin VERIFIED in `server/install_dashboard_app.py:308-314`; licence *stated from knowledge — confirm* | `johnvansickle.com/ffmpeg/releases/` | B by default since 2026-08-17; **A** under `--push-ffmpeg-from-local` |
| yt-dlp (NAS side) | `yt-dlp>=2026.6.9` | Unlicense | *stated from knowledge — confirm* | PyPI, installed by the container's own `pip` (`dashboard/deploy/requirements.txt`, the `yt-dlp` pin) | B |
| yt-dlp (editor side) | latest, refreshed daily | Unlicense | *stated from knowledge — confirm* | GitHub releases (`companion/src/ccsync_companion/ytdlp_manager.py`) | B |
| deno | `v2.9.5` | MIT | version string measured 2026-08-16 (`sidecar_tools.py:44`) — VERIFIED; licence *stated from knowledge — confirm* | `github.com/denoland/deno` releases, sha256-pinned (`sidecar_tools.py:96-133`) | B |
| bgutil PO-token provider | `bgutil-ytdlp-pot-provider==1.3.1` + the matching sidecar container image | **GPLv3** — see below | plugin licence VERIFIED 2026-08-17 from installed metadata (`dashboard` venv table above); sidecar image licence *stated from knowledge — confirm* | PyPI (plugin, `dashboard/deploy/requirements-unblock.txt`) + a container image pinned in `server/install_dashboard_app.py` (`POT_PROVIDER_IMAGE`) — BOTH ONLY on a site with `[features] youtube_unblock` on | A (plugin, into our own container venv) / B (sidecar image, pulled by the customer's own docker) |
| Tailscale | customer's own | client BSD-3-Clause; the coordination service is a paid SaaS | *stated from knowledge — confirm* | the customer installs and pays for it (`docs/SERVER-SYNOLOGY.md`) | C |
| CLAP text tower (ONNX export) | derived from `laion/larger_clap_music_and_speech`, exported 2026-08-10 | Apache-2.0 | model id, dim 512 and 125,302,016 text params VERIFIED from `music/web/data/text_encoder/manifest.json`; licence *stated from knowledge — confirm* | Hugging Face, exported on the base rig by `music/indexer/export_text_encoder.py` | **A** |
| MiniLM (b-roll embeddings) | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` via fastembed | Apache-2.0 | model id VERIFIED in `broll/web/app/semantic.py:51-53`; licence *stated from knowledge — confirm* | Hugging Face / the fastembed CDN, on the base rig only | not shipped — see below |
| Whisper (transcription) | an external `faster-whisper` environment the operator already has | faster-whisper MIT, model weights MIT | path VERIFIED in `broll/indexer/broll_index/config.py:115-116`; licences *stated from knowledge — confirm* | operator-supplied, outside this repo (`%USERPROFILE%\tools\whisper` by default) | C |
| **llama.cpp** (b-roll local indexing runtime, 2026-08-18) | release `b10470`, `llama-server` — one asset per platform (Windows CUDA 12.4, macOS arm64 Metal, Linux Vulkan) | **MIT** | asset names + sha256 pinned and VERIFIED against `api.github.com/repos/ggml-org/llama.cpp/releases/tags/b10470`'s own digests, `broll/indexer/broll_index/local_models.py:RUNTIMES`; licence *stated from knowledge — confirm* | `github.com/ggml-org/llama.cpp` releases, sha256-pinned per asset (`broll_index/local_runtime.py`) | B |
| **Qwen3-VL-4B/8B-Instruct-GGUF** (b-roll local indexing model, 2026-08-18) | `Qwen/Qwen3-VL-4B-Instruct-GGUF`@`1cd86af…`, `Qwen/Qwen3-VL-8B-Instruct-GGUF`@`f982a07…`, `Q4_K_M` quant + F16 mmproj each | **Apache-2.0** | repo/revision/filename/sha256 pinned in `broll_index/local_models.py:TIERS`; 4B sha256 VERIFIED by local download+hash 2026-08-18, 8B sha256 is Hugging Face's own API-reported `lfs.oid` (not independently re-downloaded); licence *stated from knowledge — confirm against the model card* | Hugging Face, sha256-pinned per file (`broll_index/local_runtime.py`) | B |
| htmx | `1.9.12` | 0BSD | version VERIFIED (`version:"1.9.12"` in `dashboard/static/htmx.min.js`); licence *stated from knowledge — confirm* | vendored into `dashboard/static/` | **A** |
| Tcl/Tk | 8.6 (`tcl86t.dll`, `tk86t.dll`) | BSD-style (Tcl/Tk licence) | presence VERIFIED by byte-scanning `companion/dist/ccsync-companion.exe` (0.7.11, built 2026-08-17); licence *stated from knowledge — confirm* | the CPython 3.12.10 install on the build machine, collected by PyInstaller | **A** |
| CPython (`python312.dll`) | 3.12.10 | PSF-2.0 | presence VERIFIED by the same byte scan; build-machine interpreter VERIFIED as 3.12.10 | the CPython install on the build machine | **A** |
| Pillow | 12.3.0 | `MIT-CMU` (the HPND/PIL-style licence) | VERIFIED from installed metadata **and** the licence text on disk; presence in the exe VERIFIED by byte scan | PyPI | **A** |
| Microsoft Visual C++ runtime | `VCRUNTIME140` | Microsoft redistributable terms | presence VERIFIED by byte scan | the build machine's toolchain, collected by PyInstaller | **A** |
| PyInstaller bootloader | 6.21.0 | **GPL-2.0-or-later WITH Bootloader-exception** | VERIFIED — SPDX id and the exception text both read off `companion/.venv/Lib/site-packages/pyinstaller-6.21.0.dist-info/licenses/COPYING.txt` | PyPI | **A** (bootloader only) |
| yt-credit-downloader (vendored) | copied 2026-08-11 | **NO LICENCE GRANT** | VERIFIED by inspection 2026-08-17: no LICENSE/COPYING in `ytdl/web/ytdlweb/vendor/`, no header on either module | `E:\Projects\Utilities\yt-credit-downloader` (`vendor/__init__.py:1-2`) | **A** |

### ffmpeg — the GPLv3 component, and both copies of it

ffmpeg builds that include `libx264`/`libx265` are **GPLv3**, not LGPL. Both
copies CC Sync arranges are such builds.

**Editor side.** `companion/src/ccsync_companion/sidecar_tools.py` installs
`ffmpeg`/`ffprobe` into `%LOCALAPPDATA%\ccsync\tools` from the
`eugeneware/ffmpeg-static` GitHub release `b6.1.1`, which republishes gyan.dev's
Windows "essentials" build and evermeet's macOS builds one-file-per-platform.
Each asset is sha256-pinned in that module. The download is performed by the
editor's own machine from GitHub, so upstream is the one conveying (mode B);
we choose the build.

*Scope change 2026-08-18:* `ensure_ffmpeg_pair` is no longer behind the
`youtube_download` feature gate, because b-roll and music ingest need ffmpeg on
any machine an editor drops files on. The mode is unchanged (still B, still the
editor's own machine fetching from GitHub) but the population is: **every**
editor machine now installs a GPLv3 ffmpeg, where before only a
youtube-enabled fleet's did. Counsel should read the written offer below
knowing that, rather than as an edge case.

**NAS side.** `server/install_dashboard_app.py` puts johnvansickle's
`ffmpeg-7.0.2-amd64-static` on the customer's NAS for `/music`'s ingest
transcode. As of **2026-08-17** (`DEFAULT_FFMPEG_FETCH = "remote"`,
`install_dashboard_app.py:344-347`) the default has the NAS curl the pinned
tarball itself — precisely so this stops being a conveyance. The
`--push-ffmpeg-from-local` flag remains for air-gapped sites and **does**
convey; choosing it prints `FFMPEG_LOCAL_PUSH_GPL_NOTICE`
(`install_dashboard_app.py:352-366`) at the operator.

**WRITTEN OFFER (GPLv3 §6).** Where CC Sync has conveyed an ffmpeg binary to
you — that is, where the deployment used `--push-ffmpeg-from-local`, or where
a build was handed to you on media — Cablewrap Creative offers, for a period
of three years from that conveyance, to give any third party a complete
machine-readable copy of the corresponding source code of that ffmpeg build,
on a physical medium customarily used for software interchange, for no more
than the cost of physically performing the distribution. Direct such a request
to the address in `docs/legal/EULA.md`. The same source is available without
charge from upstream:

- upstream ffmpeg source and release tarballs — <https://ffmpeg.org/download.html>
- johnvansickle build scripts and source links — <https://johnvansickle.com/ffmpeg/>
- gyan.dev Windows build configuration and sources — <https://www.gyan.dev/ffmpeg/builds/>
- the exact assets the companion fetches — <https://github.com/eugeneware/ffmpeg-static/releases/tag/b6.1.1>

TODO(legal): the offer above names no address because the contracting entity is
not yet decided. It is not valid until one is set.

TODO(operator): the pinned versions above (`b6.1.1` / `7.0.2`) must be updated
in this file whenever `sidecar_tools.py` or `install_dashboard_app.py` bumps a
pin. A written offer that names the wrong build is not an offer.

### PyInstaller — why a GPLv2 tool does not make the exe GPL

`pyinstaller` is GPL-2.0-or-later, and pip-licenses flags it above. It does not
infect the frozen companion, for two independent reasons:

1. PyInstaller is a **build tool**. It is not distributed to customers; it is
   not in the exe. Using a GPL tool to build proprietary software has never
   created an obligation, exactly as `gcc` does not.
2. The one PyInstaller-authored artefact that *is* inside the exe — the
   **bootloader** — carries an explicit exception. VERIFIED, quoted from
   `pyinstaller-6.21.0.dist-info/licenses/COPYING.txt` on this machine:

   > In addition to the permissions in the GNU General Public License, the
   > authors give you unlimited permission to link or embed compiled bootloader
   > and related files into combinations with other programs, and to distribute
   > those combinations without any restriction coming from the use of those
   > files.

   The SPDX id in PyInstaller's own source headers is
   `(GPL-2.0-or-later WITH Bootloader-exception)`.

The exception covers embedding and distributing the **compiled** bootloader. It
does not cover distributing a **modified** bootloader; CC Sync does not modify
one (`companion/build.spec` uses the stock one).

### pystray — being removed, and not in the shipped build

`pystray` 0.19.5 is **LGPLv3** (VERIFIED from installed metadata, with
`COPYING.LGPL` present in its dist-info). It is the finding that opened
`docs/COMMERCIAL_READINESS.md` item 3, and it is being replaced with an
in-house ctypes/PyObjC tray backend in that same work item.

It still appears in the companion venv table above, because it is still
installed there as a **dev-only optional escape hatch** — `companion/build.spec`
bundles it only `if` it imports at build time.

TODO(operator): a byte scan of `companion/dist/ccsync-companion.exe` (0.7.11,
built 2026-08-17T08:23:41Z, `git_commit e270aef`) still finds the string
`pystray`, i.e. **the currently published build does contain it**. This section
becomes accurate only once a build made after the tray replacement is published.
Until then, the LGPLv3 §4/§6 obligations for that build stand: it is a
single-file binary with an LGPL library statically inside it and no relinking
mechanism offered.

### CLAP, MiniLM, Whisper, Qwen3-VL/llama.cpp — what actually ships

- **CLAP text tower — SHIPPED (mode A).** `music/web/data/text_encoder/` is an
  ONNX export of the 125M-parameter text half of
  `laion/larger_clap_music_and_speech`, produced on the base rig and shipped to
  the customer's NAS beside `music.db`. That is a derivative work of an
  Apache-2.0 model, so Apache-2.0 §4 applies to us: retain the licence, retain
  attribution/NOTICE, and state that the file has been modified (it has: it is
  a partial ONNX export, not the original checkpoint).
  TODO(legal/operator): ship the Apache-2.0 text and a NOTICE file alongside
  `music/web/data/text_encoder/`, and record the modification there.
- **MiniLM — NOT SHIPPED.** `fastembed` is deliberately excluded from the
  container (VERIFIED — `dashboard/deploy/requirements.txt` says so in the
  b-roll section's comment, and gives the reason). The model is downloaded only on the base rig during
  indexing; what reaches the customer is precomputed float32 vectors inside
  `broll.db`. Apache-2.0 imposes no copyleft on those.
- **Whisper — NOT SHIPPED, NOT IN THIS REPO.** `broll/indexer` shells out to an
  operator-supplied `faster-whisper` environment
  (`broll/indexer/broll_index/transcribe.py:1-17`). Only the resulting
  transcript text reaches a customer, inside `broll.db`.
- **Qwen3-VL / llama.cpp (b-roll local indexing, 2026-08-18) — NOT SHIPPED.**
  Same posture as Whisper: `broll_index/local_runtime.py` has the INDEXING
  machine's own `llama-server` process download the runtime binary from
  GitHub and the GGUF weights from Hugging Face, sha256-verified against the
  pins in `broll_index/local_models.py` before either is trusted. Only the
  resulting shot descriptions (text) reach a customer, inside `broll.db` —
  the model weights themselves never leave the indexing machine and are never
  bundled into `companion` or the `dashboard` container, which is why
  `tools/check_licenses.py`'s gate (scoped to those two shipped artefacts —
  see its own docstring) does not see this row; it is inventoried here by
  hand instead, same as Whisper above.

TODO(legal): model weights are frequently licensed by terms that are *not* the
repository's stated software licence (RAIL/OpenRAIL riders, "no commercial use"
model cards). The three above are believed to be Apache-2.0/MIT, but that is
*stated from knowledge — confirm* against each model card before sale.

### bgutil PO-token provider — GPLv3, and split out of the base container 2026-08-17

Its licence is now **VERIFIED**: installed metadata in the `dashboard` venv
reads **GNU General Public License v3 (GPLv3)** (the plugin table above). Its
upstream repository is `Brainicism/bgutil-ytdlp-pot-provider`; the sidecar
container image's own licence is still *stated from knowledge — confirm from
the repository's own LICENSE file*.

**2026-08-17 (CI run 32041222871's licence gate, `docs/COMMERCIAL_READINESS.md`
items 2/3): moved OUT of the base `dashboard/deploy/requirements.txt`/`.lock`
that every deployment installs and the image bakes, into its own
`dashboard/deploy/requirements-unblock.txt`/`.lock`.** Before this split, the
base container lock — the one thing every customer's dashboard installs
regardless of which optional features they turned on — conveyed a GPLv3
anti-anti-automation package unconditionally; `tools/check_licenses.py`'s
`dashboard-container` target is now clean of it (see its own `dashboard-
container-unblock` target and `tools/license_allowlist.toml`'s
`[allow.bgutil-ytdlp-pot-provider]` entry, `targets = ["dashboard-container-
unblock"]`). `dashboard/deploy/run.sh` installs the unblock lock into the same
container venv only when `DASH_SITE_YOUTUBE_UNBLOCK=1` — which is only ever
"1" on a site whose `site.toml` sets `[features] youtube_unblock` (see
`server/install_dashboard_app.py compose_config()`). `docs/CI.md` documents
why the strict CI run (`--only dashboard-container`) does not scan this
package at all: it is a customer-enabled optional feature, not something the
vendor build always conveys, so it does not belong in a gate whose whole
point is "what does the vendor build always convey".

Independently of licensing, this component exists to defeat YouTube's bot
check, which `docs/COMMERCIAL_READINESS.md` item 2 treats as DMCA §1201 /
EUCD Art. 6 exposure and gates behind the same customer-enabled
`youtube_unblock` site flag. Counsel should read items 2 and 3 together for
it. The written-offer/source-availability obligations GPLv3 §6 imposes on us
whenever this is actually conveyed (i.e. on a site with the feature on) are
still open, same as ffmpeg's above — no address exists yet to make the offer
from.

### yt-credit-downloader — NO LICENCE GRANT (open item)

`ytdl/web/ytdlweb/vendor/downloader.py` and `ytsearch.py` were copied verbatim
from a separate personal utility on 2026-08-11 (`vendor/__init__.py:1-2`).
VERIFIED by inspection on 2026-08-17: **the directory contains no LICENSE or
COPYING file, and neither module carries a copyright or licence header.**

**NO LICENCE GRANT — written permission required from the author** before this
code is distributed to, or run for, a customer. If the author is the operator,
this is a five-minute assignment/licence to self; it still has to exist in
writing, because "I wrote it" is not a record that survives a due-diligence
review or a change of employer.

### LGPL components that remain, and why they are compliant

Two LGPL-2.1 dependencies stay in the product after pystray goes. Both are
compliant on the same §4/§5 reasoning: they are **dynamically imported into a
normal Python installation**, they are **not inside any single-file binary we
distribute**, and the customer can replace them with a modified version by
`pip install`-ing over them — which is exactly the "user can relink/replace the
library" freedom §4 exists to protect.

**`paramiko` 5.0.0 — LGPL-2.1.** VERIFIED from installed metadata, with the
licence text on disk. Imported by exactly two places (VERIFIED by grep across
the repo):

- `dashboard/src/ccsync_dashboard/nas/synology.py` — the Synology backend's SSH
  session, needed because DSM exposes no API for writing an editor's
  `authorized_keys`;
- `server/common.py` — the NAS-side install scripts, run from the operator's own
  Python on the base rig.

Neither is frozen. The dashboard runs from a source tree on `/app` with its
deps pip-installed into a persistent `/data/venv` inside the customer's own
container (`dashboard/deploy/requirements.txt` header) — the customer can
replace `paramiko` in that venv without touching anything of ours. The
`server/` scripts are plain `.py` files run under an ordinary interpreter.

**`soundfile` / `librosa` — LGPL-2.1 via bundled `libsndfile`/`libsoxr`.**
Imported by exactly one module, `music/indexer/music_index/features.py`
(VERIFIED by grep). That is the **GPU indexer on the base rig** — the operator's
own machine, never shipped and never installed on a customer's NAS or an
editor's workstation. `music/web/.venv` deliberately carries no torch and no
audio stack; only precomputed features reach `music.db`.

**VERIFIED, not asserted:** a byte scan of the published
`companion/dist/ccsync-companion.exe` (0.7.11) finds **zero** occurrences of
`paramiko`, `soundfile` or `librosa`, and `companion/build.spec` names none of
them. `onboarding/build_onboard.spec:69-87` and
`build_onboard_macos.spec:137-152` explicitly *exclude* `pystray`, `PIL` and
`watchdog`, and name no LGPL package at all. **No LGPL library other than
pystray has ever been frozen into a CC Sync binary.**

### What is still missing from this file

- TODO(legal): licence texts. This file names licences; it does not reproduce
  them. MIT, BSD, Apache-2.0, MPL-2.0, LGPL and GPL all require the licence
  text to accompany a distribution. A `docs/legal/licenses/` directory
  assembled from the `LicenseText` field `tools/gen_notices.py` already
  collects would satisfy this; it has not been built.
- TODO(legal): htmx has no licence header vendored beside
  `dashboard/static/htmx.min.js`.
- TODO(operator): the `ytdl/web` component has no venv on this machine, so its
  dependencies are absent from every table above. Its runtime deps are in
  `dashboard/deploy/requirements.txt`; create the venv, or add its `pyproject`
  deps by hand, before this file is relied on.
<!-- END HAND-MAINTAINED -->
