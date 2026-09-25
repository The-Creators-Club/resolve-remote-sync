<!-- Maintainers: GENERATED FILE. The pip sections below are produced by
     `python tools/gen_notices.py`; edit that script, not these tables,
     and `git log` on this file is when they were last regenerated.
     The block between <!-- BEGIN HAND-MAINTAINED --> and
     <!-- END HAND-MAINTAINED --> is written by hand and is preserved
     verbatim across regeneration: it carries the components pip
     cannot see, which is where every copyleft obligation actually is.
     The developer-venv tables list what is installed for development;
     the dashboard-container table is the shipped image's own lock
     (server-tools-1, 2026-09-18), with its licences read from a venv. -->

# CC Sync: third-party notices

**Issued 2026-09-25 by Cablewrap Creative Ltd.**

CC Sync is proprietary software, licensed under `docs/legal/EULA.md`. It
incorporates, links against, or arranges the download of the third-party
components listed here. Each remains licensed by its own author under its
own terms, which prevail over the EULA for that component.

**How to read the verification column.** `metadata` means the fact came
out of the installed distribution's own metadata via `pip-licenses`, and
`+text` means the distribution also ships the licence text on disk. In the
hand-maintained section, *as published upstream* means the licence is the
one the component's publisher states, and was not re-read from a shipped
file.

## LICENCES NEEDING ATTENTION

Copyleft or otherwise non-permissive licences found in the venvs. Being
listed here is not a finding of non-compliance: it means a human must
decide whether the way we ship this one is compliant. See the
"LGPL and MPL components that remain" subsection for the ones already reasoned
through.

| Package | Version | Licence | Present in | Verification |
|---|---|---|---|---|
| `bgutil-ytdlp-pot-provider` | 1.3.1 | **GNU General Public License v3 (GPLv3)** (GPL) | dashboard | metadata |
| `certifi` | 2026.7.22 | **Mozilla Public License 2.0 (MPL 2.0)** (MPL) | dashboard, music/web, broll/web, dashboard-container | metadata+text |
| `paramiko` | 5.0.0 | **LGPL-2.1** (LGPL) | dashboard, dashboard-container | metadata+text |
| `psycopg2-binary` | 2.9.13 | **GNU Library or Lesser General Public License (LGPL)** (LGPL) | companion, dashboard | metadata+text |
| `psycopg2-binary` | 2.9.12 | **GNU Library or Lesser General Public License (LGPL)** (LGPL) | dashboard-container | metadata |

## Python dependencies by component

What is installed in each component's development virtualenv. This is
**not** the same as what a customer receives: the frozen companion ships
only what `companion/build.spec` collects, and the deployed container
installs `dashboard/deploy/requirements.txt`.

### companion

editor tray app; the frozen build ships a SUBSET of this (see build.spec). Venv: `companion/.venv`, 22 package(s).

| Package | Version | Licence | Home page |
|---|---|---|---|
| `asn1crypto` | 1.5.1 | MIT License | https://github.com/wbond/asn1crypto |
| `ccsync-companion` | 0.9.71 | UNKNOWN | UNKNOWN |
| `ccsync-companion` | 0.9.80 | UNKNOWN | UNKNOWN |
| `colorama` | 0.4.6 | BSD License | https://github.com/tartley/colorama |
| `flatbuffers` | 25.12.19 | Apache Software License | https://google.github.io/flatbuffers/ |
| `iniconfig` | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| `numpy` | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| `onnxruntime` | 1.29.0 | MIT License | https://onnxruntime.ai |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| `pg8000` | 1.31.5 | BSD License | https://codeberg.org/tlocke/pg8000 |
| `pillow` | 12.3.0 | MIT-CMU | https://python-pillow.github.io |
| `pluggy` | 1.6.0 | MIT License | UNKNOWN |
| `protobuf` | 7.35.1 | 3-Clause BSD License | https://developers.google.com/protocol-buffers/ |
| `psycopg2-binary` | 2.9.13 | GNU Library or Lesser General Public License (LGPL) | https://psycopg.org/ |
| `Pygments` | 2.21.0 | BSD-2-Clause | https://pygments.org |
| `pytest` | 9.1.1 | MIT | https://docs.pytest.org/en/latest/ |
| `python-dateutil` | 2.9.0.post0 | Apache Software License; BSD License | https://github.com/dateutil/dateutil |
| `scramp` | 1.4.17 | MIT No Attribution License (MIT-0) | https://codeberg.org/tlocke/scramp |
| `six` | 1.17.0 | MIT License | https://github.com/benjaminp/six |
| `watchdog` | 6.0.0 | Apache Software License | https://github.com/gorakhargosh/watchdog |
| `xxhash` | 4.0.1 | BSD-2-Clause | https://github.com/ifduyue/python-xxhash |
| `zstandard` | 0.25.0 | BSD-3-Clause | https://github.com/indygreg/python-zstandard |

### dashboard

FastAPI fleet dashboard; the deployed container installs dashboard/deploy/requirements.txt, not this venv. Venv: `dashboard/.venv`, 59 package(s).

| Package | Version | Licence | Home page |
|---|---|---|---|
| `a2wsgi` | 1.10.10 | Apache-2.0 | https://github.com/abersheeran/a2wsgi |
| `annotated-doc` | 0.0.5 | MIT | https://github.com/fastapi/annotated-doc |
| `annotated-types` | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| `anthropic` | 0.122.0 | MIT License | https://github.com/anthropics/anthropic-sdk-python |
| `anyio` | 4.14.2 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| `bcrypt` | 5.0.0 | Apache Software License | https://github.com/pyca/bcrypt/ |
| `bgutil-ytdlp-pot-provider` | 1.3.1 | GNU General Public License v3 (GPLv3) | UNKNOWN |
| `ccsync-dashboard` | 0.7.43 | UNKNOWN | UNKNOWN |
| `ccsync-dashboard` | 0.7.43 | UNKNOWN | UNKNOWN |
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
| `psycopg2-binary` | 2.9.13 | GNU Library or Lesser General Public License (LGPL) | https://psycopg.org/ |
| `pycparser` | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| `pydantic` | 2.13.4 | MIT | https://github.com/pydantic/pydantic |
| `pydantic_core` | 2.46.4 | MIT | https://github.com/pydantic |
| `Pygments` | 2.21.0 | BSD-2-Clause | https://pygments.org |
| `PyJWT` | 2.13.0 | MIT | https://github.com/jpadilla/pyjwt |
| `PyNaCl` | 1.6.2 | Apache Software License | https://github.com/pyca/pynacl |
| `pypinyin` | 0.55.0 | MIT License | https://github.com/mozillazg/python-pinyin |
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
| `yt-dlp` | 2026.8.19 | Unlicense | https://github.com/yt-dlp/yt-dlp |
| `zstandard` | 0.25.0 | BSD-3-Clause | https://github.com/indygreg/python-zstandard |

### music/web

music search UI mounted at /music; deliberately no torch. Venv: `music/web/.venv`, 32 package(s).

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
| `Pygments` | 2.21.0 | BSD-2-Clause | https://pygments.org |
| `pytest` | 9.1.1 | MIT | https://docs.pytest.org/en/latest/ |
| `python-dotenv` | 1.2.3 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| `python-multipart` | 0.0.32 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| `PyYAML` | 6.0.3 | MIT License | https://pyyaml.org/ |
| `starlette` | 1.6.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| `typing-inspection` | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection |
| `typing_extensions` | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| `uvicorn` | 0.52.3 | BSD-3-Clause | https://uvicorn.dev/ |
| `watchfiles` | 1.2.0 | MIT License | https://github.com/samuelcolvin/watchfiles |
| `websockets` | 17.0.1 | BSD-3-Clause | https://github.com/python-websockets/websockets |

### broll/web

b-roll search UI mounted at /broll. Venv: `broll/web/.venv`, 31 package(s).

| Package | Version | Licence | Home page |
|---|---|---|---|
| `annotated-doc` | 0.0.5 | MIT | https://github.com/fastapi/annotated-doc |
| `annotated-types` | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| `anyio` | 4.14.2 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| `certifi` | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | https://github.com/certifi/python-certifi |
| `click` | 8.4.2 | BSD-3-Clause | https://github.com/pallets/click/ |
| `colorama` | 0.4.6 | BSD License | https://github.com/tartley/colorama |
| `fastapi` | 0.141.1 | MIT | https://github.com/fastapi/fastapi |
| `h11` | 0.16.0 | MIT License | https://github.com/python-hyper/h11 |
| `httpcore` | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| `httptools` | 0.8.0 | MIT | https://github.com/MagicStack/httptools |
| `httpx` | 0.28.1 | BSD License | https://github.com/encode/httpx |
| `idna` | 3.18 | BSD-3-Clause | https://github.com/kjd/idna |
| `iniconfig` | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| `jieba` | 0.42.1 | MIT License | https://github.com/fxsjy/jieba |
| `numpy` | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| `opencc-python-reimplemented` | 0.1.7 | Apache Software License | https://github.com/yichen0831/opencc-python |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| `pluggy` | 1.6.0 | MIT License | UNKNOWN |
| `pydantic` | 2.13.4 | MIT | https://github.com/pydantic/pydantic |
| `pydantic_core` | 2.46.4 | MIT | https://github.com/pydantic |
| `Pygments` | 2.21.0 | BSD-2-Clause | https://pygments.org |
| `pytest` | 9.1.1 | MIT | https://docs.pytest.org/en/latest/ |
| `python-dotenv` | 1.2.3 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| `PyYAML` | 6.0.3 | MIT License | https://pyyaml.org/ |
| `RapidFuzz` | 3.14.5 | MIT | https://github.com/rapidfuzz/RapidFuzz |
| `starlette` | 1.6.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| `typing-inspection` | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection |
| `typing_extensions` | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| `uvicorn` | 0.52.3 | BSD-3-Clause | https://uvicorn.dev/ |
| `watchfiles` | 1.2.0 | MIT License | https://github.com/samuelcolvin/watchfiles |
| `websockets` | 17.0.1 | BSD-3-Clause | https://github.com/python-websockets/websockets |

### dashboard-container

what the deployed dashboard image installs -- the artefact a customer receives, not a developer venv. Lock: `dashboard/deploy/requirements.lock`, 52 package(s). A lock carries no licence metadata, so each licence below is the one the same package's metadata declares in a developer venv on this machine; the version column is the CONTAINER's.

| Package | Version (container) | Licence | Licence read from |
|---|---|---|---|
| `a2wsgi` | 1.10.10 | Apache-2.0 | a venv's 1.10.10 |
| `annotated-doc` | 0.0.5 | MIT | a venv's 0.0.5 |
| `annotated-types` | 0.8.0 | MIT | a venv's 0.8.0 |
| `anthropic` | 0.122.0 | MIT License | a venv's 0.122.0 |
| `anyio` | 4.14.2 | MIT | a venv's 4.14.2 |
| `bcrypt` | 5.0.0 | Apache Software License | a venv's 5.0.0 |
| `certifi` | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | a venv's 2026.7.22 |
| `cffi` | 2.1.1 | MIT-0 | a venv's 2.1.1 |
| `charset-normalizer` | 3.5.1 | MIT | a venv's 3.5.1 |
| `click` | 8.4.2 | BSD-3-Clause | a venv's 8.4.2 |
| `colorama` | 0.4.6 | BSD License | a venv's 0.4.6 |
| `cryptography` | 50.0.0 | Apache-2.0 OR BSD-3-Clause | a venv's 50.0.0 |
| `distro` | 1.9.0 | Apache Software License | a venv's 1.9.0 |
| `docstring-parser` | 0.18.0 | MIT License | a venv's 0.18.0 |
| `fastapi` | 0.141.1 | MIT | a venv's 0.141.1 |
| `flatbuffers` | 25.12.19 | Apache Software License | a venv's 25.12.19 |
| `h11` | 0.16.0 | MIT License | a venv's 0.16.0 |
| `httpcore` | 1.0.9 | BSD-3-Clause | a venv's 1.0.9 |
| `httpx` | 0.28.1 | BSD License | a venv's 0.28.1 |
| `idna` | 3.18 | BSD-3-Clause | a venv's 3.18 |
| `invoke` | 3.0.3 | BSD-2-Clause | a venv's 3.0.3 |
| `jieba` | 0.42.1 | MIT License | a venv's 0.42.1 |
| `jinja2` | 3.1.6 | BSD License | a venv's 3.1.6 |
| `jiter` | 0.16.0 | MIT | a venv's 0.16.0 |
| `markupsafe` | 3.0.3 | BSD-3-Clause | a venv's 3.0.3 |
| `numpy` | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | a venv's 2.5.2 |
| `onnxruntime` | 1.28.0 | MIT License | a venv's 1.29.0 |
| `opencc-python-reimplemented` | 0.1.7 | Apache Software License | a venv's 0.1.7 |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | a venv's 26.3 |
| `paramiko` | 5.0.0 | LGPL-2.1 | a venv's 5.0.0 |
| `protobuf` | 7.35.1 | 3-Clause BSD License | a venv's 7.35.1 |
| `psycopg2-binary` | 2.9.12 | GNU Library or Lesser General Public License (LGPL) | a venv's 2.9.13 |
| `pycparser` | 3.0 | BSD-3-Clause | a venv's 3.0 |
| `pydantic` | 2.13.4 | MIT | a venv's 2.13.4 |
| `pydantic-core` | 2.46.4 | MIT | a venv's 2.46.4 |
| `pyjwt` | 2.13.0 | MIT | a venv's 2.13.0 |
| `pynacl` | 1.6.2 | Apache Software License | a venv's 1.6.2 |
| `pypinyin` | 0.55.0 | MIT License | a venv's 0.55.0 |
| `pyspnego` | 0.12.1 | MIT | a venv's 0.12.1 |
| `python-multipart` | 0.0.32 | Apache-2.0 | a venv's 0.0.32 |
| `rapidfuzz` | 3.14.5 | MIT | a venv's 3.14.5 |
| `requests` | 2.34.2 | Apache Software License | a venv's 2.34.2 |
| `smbprotocol` | 1.17.0 | MIT | a venv's 1.17.0 |
| `sniffio` | 1.3.1 | Apache Software License; MIT License | a venv's 1.3.1 |
| `sspilib` | 0.5.0 | MIT | a venv's 0.5.0 |
| `starlette` | 1.6.0 | BSD-3-Clause | a venv's 1.6.0 |
| `typing-extensions` | 4.16.0 | PSF-2.0 | a venv's 4.16.0 |
| `typing-inspection` | 0.4.4 | MIT | a venv's 0.4.4 |
| `urllib3` | 2.7.0 | MIT | a venv's 2.7.0 |
| `uvicorn` | 0.52.3 | BSD-3-Clause | a venv's 0.52.3 |
| `yt-dlp` | 2026.8.19 | Unlicense | a venv's 2026.8.19 |
| `zstandard` | 0.25.0 | BSD-3-Clause | a venv's 0.25.0 |

## All pip dependencies (merged)

75 distinct (package, version) pair(s) across every scanned venv.

| Package | Version | Licence | Components | Licence text on disk |
|---|---|---|---|---|
| `a2wsgi` | 1.10.10 | Apache-2.0 | dashboard, dashboard-container | yes |
| `annotated-doc` | 0.0.5 | MIT | dashboard, music/web, broll/web, dashboard-container | yes |
| `annotated-types` | 0.8.0 | MIT | dashboard, music/web, broll/web, dashboard-container | yes |
| `anthropic` | 0.122.0 | MIT License | dashboard, dashboard-container | yes |
| `anyio` | 4.14.2 | MIT | dashboard, music/web, broll/web, dashboard-container | yes |
| `asn1crypto` | 1.5.1 | MIT License | companion | yes |
| `bcrypt` | 5.0.0 | Apache Software License | dashboard, dashboard-container | yes |
| `bgutil-ytdlp-pot-provider` | 1.3.1 | GNU General Public License v3 (GPLv3) | dashboard | no |
| `ccsync-companion` | 0.9.71 | UNKNOWN | companion | no |
| `ccsync-companion` | 0.9.80 | UNKNOWN | companion | no |
| `ccsync-dashboard` | 0.7.43 | UNKNOWN | dashboard, dashboard | no |
| `certifi` | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | dashboard, music/web, broll/web, dashboard-container | yes |
| `cffi` | 2.1.1 | MIT-0 | dashboard, dashboard-container | yes |
| `charset-normalizer` | 3.5.1 | MIT | dashboard, dashboard-container | yes |
| `click` | 8.4.2 | BSD-3-Clause | dashboard, music/web, broll/web, dashboard-container | yes |
| `colorama` | 0.4.6 | BSD License | companion, dashboard, music/web, broll/web, dashboard-container | yes |
| `cryptography` | 50.0.0 | Apache-2.0 OR BSD-3-Clause | dashboard, dashboard-container | yes |
| `distro` | 1.9.0 | Apache Software License | dashboard, dashboard-container | yes |
| `docstring_parser` | 0.18.0 | MIT License | dashboard, dashboard-container | yes |
| `fastapi` | 0.141.1 | MIT | dashboard, music/web, broll/web, dashboard-container | yes |
| `flatbuffers` | 25.12.19 | Apache Software License | companion, dashboard, music/web, dashboard-container | no |
| `h11` | 0.16.0 | MIT License | dashboard, music/web, broll/web, dashboard-container | yes |
| `httpcore` | 1.0.9 | BSD-3-Clause | dashboard, music/web, broll/web, dashboard-container | yes |
| `httptools` | 0.8.0 | MIT | music/web, broll/web | yes |
| `httpx` | 0.28.1 | BSD License | dashboard, music/web, broll/web, dashboard-container | yes |
| `idna` | 3.18 | BSD-3-Clause | dashboard, music/web, broll/web, dashboard-container | yes |
| `iniconfig` | 2.3.0 | MIT | companion, dashboard, music/web, broll/web | yes |
| `invoke` | 3.0.3 | BSD-2-Clause | dashboard, dashboard-container | yes |
| `jieba` | 0.42.1 | MIT License | dashboard, broll/web, dashboard-container | no |
| `Jinja2` | 3.1.6 | BSD License | dashboard, dashboard-container | yes |
| `jiter` | 0.16.0 | MIT | dashboard, dashboard-container | yes |
| `MarkupSafe` | 3.0.3 | BSD-3-Clause | dashboard, dashboard-container | yes |
| `numpy` | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | companion, dashboard, music/web, broll/web, dashboard-container | yes |
| `onnxruntime` | 1.29.0 | MIT License | companion | yes |
| `onnxruntime` | 1.28.0 | MIT License | dashboard, music/web, dashboard-container | yes |
| `opencc-python-reimplemented` | 0.1.7 | Apache Software License | dashboard, broll/web, dashboard-container | yes |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | companion, dashboard, music/web, broll/web, dashboard-container | yes |
| `paramiko` | 5.0.0 | LGPL-2.1 | dashboard, dashboard-container | yes |
| `pg8000` | 1.31.5 | BSD License | companion | yes |
| `pillow` | 12.3.0 | MIT-CMU | companion | yes |
| `pluggy` | 1.6.0 | MIT License | companion, dashboard, music/web, broll/web | yes |
| `protobuf` | 7.35.1 | 3-Clause BSD License | companion, dashboard, music/web, dashboard-container | yes |
| `psycopg2-binary` | 2.9.13 | GNU Library or Lesser General Public License (LGPL) | companion, dashboard | yes |
| `psycopg2-binary` | 2.9.12 | GNU Library or Lesser General Public License (LGPL) | dashboard-container | no |
| `pycparser` | 3.0 | BSD-3-Clause | dashboard, dashboard-container | yes |
| `pydantic` | 2.13.4 | MIT | dashboard, music/web, broll/web, dashboard-container | yes |
| `pydantic_core` | 2.46.4 | MIT | dashboard, music/web, broll/web, dashboard-container | yes |
| `Pygments` | 2.21.0 | BSD-2-Clause | companion, dashboard, music/web, broll/web | yes |
| `PyJWT` | 2.13.0 | MIT | dashboard, dashboard-container | yes |
| `PyNaCl` | 1.6.2 | Apache Software License | dashboard, dashboard-container | yes |
| `pypinyin` | 0.55.0 | MIT License | dashboard, dashboard-container | yes |
| `pyspnego` | 0.12.1 | MIT | dashboard, dashboard-container | yes |
| `pytest` | 9.1.1 | MIT | companion, dashboard, music/web, broll/web | yes |
| `python-dateutil` | 2.9.0.post0 | Apache Software License; BSD License | companion | yes |
| `python-dotenv` | 1.2.3 | BSD-3-Clause | music/web, broll/web | yes |
| `python-multipart` | 0.0.32 | Apache-2.0 | dashboard, music/web, dashboard-container | yes |
| `PyYAML` | 6.0.3 | MIT License | music/web, broll/web | yes |
| `RapidFuzz` | 3.14.5 | MIT | dashboard, broll/web, dashboard-container | yes |
| `requests` | 2.34.2 | Apache Software License | dashboard, dashboard-container | yes |
| `scramp` | 1.4.17 | MIT No Attribution License (MIT-0) | companion | yes |
| `six` | 1.17.0 | MIT License | companion | yes |
| `smbprotocol` | 1.17.0 | MIT | dashboard, dashboard-container | yes |
| `sniffio` | 1.3.1 | Apache Software License; MIT License | dashboard, dashboard-container | yes |
| `sspilib` | 0.5.0 | MIT | dashboard, dashboard-container | yes |
| `starlette` | 1.6.0 | BSD-3-Clause | dashboard, music/web, broll/web, dashboard-container | yes |
| `typing-inspection` | 0.4.4 | MIT | dashboard, music/web, broll/web, dashboard-container | yes |
| `typing_extensions` | 4.16.0 | PSF-2.0 | dashboard, music/web, broll/web, dashboard-container | yes |
| `urllib3` | 2.7.0 | MIT | dashboard, dashboard-container | yes |
| `uvicorn` | 0.52.3 | BSD-3-Clause | dashboard, music/web, broll/web, dashboard-container | yes |
| `watchdog` | 6.0.0 | Apache Software License | companion | yes |
| `watchfiles` | 1.2.0 | MIT License | music/web, broll/web | yes |
| `websockets` | 17.0.1 | BSD-3-Clause | music/web, broll/web | yes |
| `xxhash` | 4.0.1 | BSD-2-Clause | companion | yes |
| `yt-dlp` | 2026.8.19 | Unlicense | dashboard, dashboard-container | yes |
| `zstandard` | 0.25.0 | BSD-3-Clause | companion, dashboard, dashboard-container | yes |

## Binaries the installer fetches

Generated from the pins in the code (LG-13, 2026-09-25): every binary
CC Sync downloads onto a customer's machine at install or run time, by
version and the sha256 of the asset as downloaded. A download whose
bytes do not match is deleted, not installed. The licence of each is in
the hand-maintained inventory below.

| Component | Version | Platform | Asset | sha256 | Fetched by | Pinned in |
|---|---|---|---|---|---|---|
| rclone | `v1.75.0` | Windows x64 | `rclone-v1.75.0-windows-amd64.zip` | `203581f0a7baeae873f2347483a798c79e2eaf5c384a4e9d866aa374f1c89ac0` | the editor installer | `installer/windows_bootstrap.ps1`: `$RcloneVersion`, `$RcloneZipSha256` |
| Syncthing | `v2.1.3` | Windows x64 | `syncthing-windows-amd64-v2.1.3.zip` | `c0b79cffa6ce5dad5ed41ede86454f3325d13ccac33447a528cb59d65fbc3a21` | the editor installer | `installer/windows_bootstrap.ps1`: `$SyncthingVersion`, `$SyncthingZipSha256` |
| rclone | `v1.75.0` | macOS arm64 | `rclone-v1.75.0-osx-arm64.zip` | `35e8f2a666ce789b29111db0dd843ddabc0d59c6b609d07bcaae5d1a07cba6f8` | the editor installer | `installer/macos_bootstrap.sh`: `RCLONE_VERSION`, `RCLONE_SHA256_ARM64` |
| rclone | `v1.75.0` | macOS x64 | `rclone-v1.75.0-osx-amd64.zip` | `19edbb8e5e73096eb66e92a42abbc5c34bfa8981ea3986a53872c7eef85a22f4` | the editor installer | `installer/macos_bootstrap.sh`: `RCLONE_VERSION`, `RCLONE_SHA256_AMD64` |
| Syncthing | `v2.1.3` | macOS arm64 | `syncthing-macos-arm64-v2.1.3.zip` | `e0f0d8df05bf0118c48c6515214a96bf3a3f11dbd115f56c3c0b52251b3f71aa` | the editor installer | `installer/macos_bootstrap.sh`: `SYNCTHING_VERSION`, `SYNCTHING_SHA256_ARM64` |
| Syncthing | `v2.1.3` | macOS x64 | `syncthing-macos-amd64-v2.1.3.zip` | `207557c0f708578375be9a286d13078cd709bfccae43d61d004913bb512b10aa` | the editor installer | `installer/macos_bootstrap.sh`: `SYNCTHING_VERSION`, `SYNCTHING_SHA256_AMD64` |
| ffmpeg | `b6.1.1` | Windows x64 | `ffmpeg-win32-x64.gz` | `8883a3dffbd0a16cf4ef95206ea05283f78908dbfb118f73c83f4951dcc06d77` | the companion, on first use | `companion/src/ccsync_companion/sidecar_tools.py`: `FFMPEG_RELEASE_TAG`, `PINNED_ASSETS` |
| ffprobe | `b6.1.1` | Windows x64 | `ffprobe-win32-x64.gz` | `f309e6223ad89d2fe54bccd420a7709b66fd27540674e92309578ed491a43c8d` | the companion, on first use | `companion/src/ccsync_companion/sidecar_tools.py`: `FFMPEG_RELEASE_TAG`, `PINNED_ASSETS` |
| deno | `v2.9.5` | Windows x64 | `deno-x86_64-pc-windows-msvc.zip` | `171efab55ac6b9881fd53ee4c20f8bf3bb1340ffc618483746909014db12216a` | the companion, on first use | `companion/src/ccsync_companion/sidecar_tools.py`: `DENO_RELEASE_TAG`, `PINNED_ASSETS` |
| ffmpeg | `b6.1.1` | macOS arm64 | `ffmpeg-darwin-arm64.gz` | `8923876afa8db5585022d7860ec7e589af192f441c56793971276d450ed3bbfa` | the companion, on first use | `companion/src/ccsync_companion/sidecar_tools.py`: `FFMPEG_RELEASE_TAG`, `PINNED_ASSETS` |
| ffprobe | `b6.1.1` | macOS arm64 | `ffprobe-darwin-arm64.gz` | `d986a8ec7b030899fe66a8a288ed809a3543338705a3ce178cfb85869c5d80be` | the companion, on first use | `companion/src/ccsync_companion/sidecar_tools.py`: `FFMPEG_RELEASE_TAG`, `PINNED_ASSETS` |
| deno | `v2.9.5` | macOS arm64 | `deno-aarch64-apple-darwin.zip` | `b796aadd131f6930560c1ee040cf0d6f53933fbb987464e9ff46bd7ea4830615` | the companion, on first use | `companion/src/ccsync_companion/sidecar_tools.py`: `DENO_RELEASE_TAG`, `PINNED_ASSETS` |
| ffmpeg | `b6.1.1` | macOS x64 | `ffmpeg-darwin-x64.gz` | `929b375c1182d956c51f7ac25e0b2b0411fb01f6f407aa15c9758efeb4242106` | the companion, on first use | `companion/src/ccsync_companion/sidecar_tools.py`: `FFMPEG_RELEASE_TAG`, `PINNED_ASSETS` |
| ffprobe | `b6.1.1` | macOS x64 | `ffprobe-darwin-x64.gz` | `d4da574d6e2e197bd259b47d69cf262df9e312af24ad960444f6d806d3d4c186` | the companion, on first use | `companion/src/ccsync_companion/sidecar_tools.py`: `FFMPEG_RELEASE_TAG`, `PINNED_ASSETS` |
| deno | `v2.9.5` | macOS x64 | `deno-x86_64-apple-darwin.zip` | `c1b8b89a81e91b2a8b3f96def3195d08cfe3a105651da7908d53061f7140510d` | the companion, on first use | `companion/src/ccsync_companion/sidecar_tools.py`: `DENO_RELEASE_TAG`, `PINNED_ASSETS` |
| ffmpeg (NAS side) | `7.0.2` | Linux x64 (the dashboard container) | `ffmpeg-7.0.2-amd64-static.tar.xz` | `abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67` | the dashboard deploy | `server/install_dashboard_app.py`: `DEFAULT_FFMPEG_URL`, `DEFAULT_FFMPEG_SHA256` |

<!-- BEGIN HAND-MAINTAINED -->
## Non-pip components (hand-maintained)

Everything CC Sync ships, embeds, or arranges the download of that pip cannot
see. This section is written by hand and preserved verbatim by
`tools/gen_notices.py`; the generator cannot produce it, and the copyleft
obligations the product carries are set out here rather than in the tables
above.

### How a component is conveyed: the distinction the licences turn on

Three modes, because "we ship it" and "we tell the customer's own machine to
fetch it" are different acts under GPL §6 and MPL §3:

- **(A) EMBEDDED**: inside an artefact we build and publish (the frozen
  companion exe, the dashboard image, a file we copy onto a customer's NAS).
  We are conveying, and copyleft obligations attach to us.
- **(B) FETCHED BY THE CUSTOMER'S MACHINE**: our installer or companion tells
  the editor's workstation or the customer's NAS to download it directly from
  upstream, over a pinned URL, and verifies it. Upstream conveys to the
  customer; the Licensor does not convey it. Because we choose and pin the
  build, the written offers below are given anyway where the licence is GPL.
- **(C) CUSTOMER-SUPPLIED**: the customer already has it, or installs it from
  its own vendor's catalogue. We only talk to it.

### Inventory

*As published upstream* means the licence is the one the component's
publisher states, and was not re-read from a file we ship.

| Component | Version / pin | Licence | Verification | Where obtained | Mode |
|---|---|---|---|---|---|
| rclone | `rclone-current-*` (resolved at install time) | MIT | *as published upstream* | `downloads.rclone.org` (`installer/windows_bootstrap.ps1`, `installer/macos_bootstrap.sh`) | B |
| Syncthing (editor side) | latest release resolved at install time | MPL-2.0 | *as published upstream* | `github.com/syncthing/syncthing` releases (`installer/windows_bootstrap.ps1`, `installer/macos_bootstrap.sh`) | B |
| Syncthing (NAS side) | whatever the NAS vendor's catalogue offers | MPL-2.0 | *as published upstream* | the TrueNAS/Synology app catalogue, installed through the NAS's own API (`server/install_syncthing_app.py`) | C |
| **ffmpeg (editor side)** | `eugeneware/ffmpeg-static` tag `b6.1.1`; binary reports `6.1.1-essentials_build` | **GPLv3** | pin VERIFIED (`sidecar_tools.py:FFMPEG_RELEASE_TAG`); licence *as published upstream* | GitHub release assets, sha256-pinned per asset (`companion/src/ccsync_companion/sidecar_tools.py`) | B |
| **ffmpeg (NAS side)** | `ffmpeg-7.0.2-amd64-static.tar.xz`, sha256 `abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67` | **GPLv3** | pin VERIFIED (`server/install_dashboard_app.py:DEFAULT_FFMPEG_URL`, `DEFAULT_FFMPEG_SHA256`); licence *as published upstream* | `johnvansickle.com/ffmpeg/releases/` | B by default; **A** under `--push-ffmpeg-from-local` |
| yt-dlp (NAS side) | the version pinned in `dashboard/deploy/requirements.lock` | Unlicense | metadata (the dashboard-container table above) | PyPI, installed by the container's own `pip` | B |
| yt-dlp (editor side) | latest, refreshed daily | Unlicense | *as published upstream* | GitHub releases (`companion/src/ccsync_companion/ytdlp_manager.py`) | B |
| deno | `v2.9.5` | MIT | pin VERIFIED (`sidecar_tools.py:DENO_RELEASE_TAG`); licence *as published upstream* | `github.com/denoland/deno` releases, sha256-pinned (`sidecar_tools.py`) | B |
| bgutil PO-token provider | `bgutil-ytdlp-pot-provider==1.3.1` + the matching sidecar container image | **GPLv3** (see below) | plugin licence VERIFIED from installed metadata (`dashboard` venv table above); sidecar image licence *as published upstream* | PyPI (plugin, `dashboard/deploy/requirements-unblock.txt`) + a container image pinned in `server/install_dashboard_app.py` (`POT_PROVIDER_IMAGE`), BOTH ONLY on a site with `[features] youtube_unblock` on | A (plugin, into our own container venv) / B (sidecar image, pulled by the customer's own docker) |
| Tailscale | the customer's own | client BSD-3-Clause; the coordination service is a paid service | *as published upstream* | the customer installs and pays for it (`docs/SERVER-SYNOLOGY.md`) | C |
| CLAP text tower (ONNX export) | derived from `laion/larger_clap_music_and_speech`, exported 2026-08-10 | Apache-2.0 | model id, dim 512 and 125,302,016 text params VERIFIED from `music/web/data/text_encoder/manifest.json`; licence *as published upstream* | Hugging Face, exported on the base rig by `music/indexer/export_text_encoder.py` | **A** |
| MiniLM (b-roll embeddings) | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` via fastembed | Apache-2.0 | model id VERIFIED in `broll/web/app/semantic.py`; licence *as published upstream* | Hugging Face / the fastembed CDN, on the indexing machine only | not shipped (see below) |
| Whisper (transcription) | an external `faster-whisper` environment the operator already has | faster-whisper MIT, model weights MIT | path VERIFIED in `broll/indexer/broll_index/config.py`; licences *as published upstream* | operator-supplied, outside this repo (`%USERPROFILE%\tools\whisper` by default) | C |
| **llama.cpp** (b-roll local indexing runtime) | release `b10470`, `llama-server`: one asset per platform (Windows CUDA 12.4, macOS arm64 Metal, Linux Vulkan) | **MIT** | asset names + sha256 pinned and VERIFIED against the release's own digests (`broll/indexer/broll_index/local_models.py:RUNTIMES`); licence *as published upstream* | `github.com/ggml-org/llama.cpp` releases, sha256-pinned per asset (`broll_index/local_runtime.py`) | B |
| **Qwen3-VL-4B/8B-Instruct-GGUF** (b-roll local indexing model) | `Qwen/Qwen3-VL-4B-Instruct-GGUF`@`1cd86af…`, `Qwen/Qwen3-VL-8B-Instruct-GGUF`@`f982a07…`, `Q4_K_M` quant + F16 mmproj each | **Apache-2.0** | repo/revision/filename/sha256 pinned in `broll_index/local_models.py:TIERS`; licence *as published upstream* on the model card | Hugging Face, sha256-pinned per file (`broll_index/local_runtime.py`) | B |
| htmx | `1.9.12` | 0BSD | version VERIFIED (`version:"1.9.12"` in `dashboard/static/htmx.min.js`); licence *as published upstream* | vendored into `dashboard/static/` | **A** |
| Tcl/Tk | 8.6 (`tcl86t.dll`, `tk86t.dll`) | BSD-style (Tcl/Tk licence) | presence VERIFIED by byte-scanning the Windows companion build (re-checked 2026-09-25); licence *as published upstream* | the CPython 3.12 install on the build machine, collected by PyInstaller | **A** |
| CPython (`python312.dll`) | 3.12 | PSF-2.0 | presence VERIFIED by the same byte scan | the CPython install on the build machine | **A** |
| Pillow | 12.3.0 | `MIT-CMU` (the HPND/PIL-style licence) | VERIFIED from installed metadata **and** the licence text on disk | PyPI | **A** |
| Microsoft Visual C++ runtime | `VCRUNTIME140` | Microsoft redistributable terms | presence VERIFIED by byte scan | the build machine's toolchain, collected by PyInstaller | **A** |
| psycopg2 (in the companion exe) | the `psycopg2-binary` version resolved at build time (`companion/pyproject.toml`: `>=2.9,<3`), with the `libpq` and OpenSSL libraries its wheel carries | **LGPL-3.0-or-later with psycopg2's exceptions**; libpq PostgreSQL Licence; OpenSSL Apache-2.0 | presence VERIFIED by byte-scanning the Windows companion build (2026-09-25) and in `companion/build.spec` (`hiddenimports`); licences *as published upstream* | PyPI, collected by PyInstaller | **A** (see below) |
| PyInstaller bootloader | 6.21.0 | **GPL-2.0-or-later WITH Bootloader-exception** | VERIFIED: SPDX id and the exception text both read off `pyinstaller-6.21.0.dist-info/licenses/COPYING.txt` | PyPI | **A** (bootloader only) |
| yt-credit-downloader (vendored) | copied 2026-08-11 | Proprietary: part of the Software, licensed under `docs/legal/EULA.md` | provenance recorded in `ytdl/web/ytdlweb/vendor/PROVENANCE.md` | the Licensor's own utility (`vendor/__init__.py`) | **A** |

### ffmpeg: the GPLv3 component, and both copies of it

ffmpeg builds that include `libx264`/`libx265` are **GPLv3**, not LGPL. Both
copies CC Sync arranges are such builds.

**Editor side.** `companion/src/ccsync_companion/sidecar_tools.py` installs
`ffmpeg`/`ffprobe` into `%LOCALAPPDATA%\ccsync\tools` from the
`eugeneware/ffmpeg-static` GitHub release `b6.1.1`, which republishes gyan.dev's
Windows "essentials" build and evermeet's macOS builds one file per platform.
Each asset is sha256-pinned in that module. The download is performed by the
editor's own machine from GitHub, so upstream is the one conveying (mode B);
we choose the build. Every editor machine installs it, because b-roll and
music ingest need ffmpeg on any machine an editor drops files on, so the
written offer below applies to every deployment.

**NAS side.** `server/install_dashboard_app.py` puts johnvansickle's
`ffmpeg-7.0.2-amd64-static` on the customer's NAS for `/music`'s ingest
transcode. By default (`DEFAULT_FFMPEG_FETCH = "remote"`) the NAS downloads
the pinned tarball itself, so this is not a conveyance. The
`--push-ffmpeg-from-local` flag remains for air-gapped sites and **does**
convey; choosing it prints `FFMPEG_LOCAL_PUSH_GPL_NOTICE` at the operator.

**WRITTEN OFFER (GPLv3 §6).** Where CC Sync has conveyed an ffmpeg binary to
you, that is, where the deployment used `--push-ffmpeg-from-local`, or where
a build was handed to you on media, Cablewrap Creative Ltd. offers, for a
period of three years from that conveyance, to give any third party a
complete machine-readable copy of the corresponding source code of that ffmpeg
build, on a physical medium customarily used for software interchange, for no
more than the cost of physically performing the distribution. Send requests
to Cablewrap Creative Ltd., No. 111, Minquan Road, Zhuwei Village, Tamsui
District, New Taipei City 251, Taiwan (R.O.C.), or to
contact@thecreatorsclub.co. The same source is available without charge from
upstream:

- upstream ffmpeg source and release tarballs: <https://ffmpeg.org/download.html>
- johnvansickle build scripts and source links: <https://johnvansickle.com/ffmpeg/>
- gyan.dev Windows build configuration and sources: <https://www.gyan.dev/ffmpeg/builds/>
- the exact assets the companion fetches: <https://github.com/eugeneware/ffmpeg-static/releases/tag/b6.1.1>

<!-- Maintainers: the pins named in this section (b6.1.1 / 7.0.2) must be
     updated here whenever sidecar_tools.py or install_dashboard_app.py bumps
     one. A written offer that names the wrong build is not an offer. -->

### PyInstaller: why a GPLv2 tool does not make the exe GPL

`pyinstaller` is GPL-2.0-or-later. It does not affect the licence of the
frozen companion, for two independent reasons:

1. PyInstaller is a **build tool**. It is not distributed to customers and is
   not in the exe. Using a GPL tool to build proprietary software creates no
   obligation, exactly as `gcc` does not.
2. The one PyInstaller-authored artefact that *is* inside the exe, the
   **bootloader**, carries an explicit exception, quoted from
   `pyinstaller-6.21.0.dist-info/licenses/COPYING.txt`:

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

### pystray: removed

`pystray` (LGPLv3) was the companion's tray library until 2026-08-17. It has
been replaced by CC Sync's own tray code (`tray_native.py`), is no longer a
dependency (`companion/pyproject.toml`), is not collected by
`companion/build.spec`, and `tools/check_licenses.py` fails a build that
re-adds it. A byte scan of the current Windows companion build (re-checked
2026-09-25) finds no occurrence of it. Companion builds published before the
replacement contained it; any customer still running one should update.

### CLAP, MiniLM, Whisper, Qwen3-VL/llama.cpp: what actually ships

- **CLAP text tower: SHIPPED (mode A).** `music/web/data/text_encoder/` is an
  ONNX export of the 125M-parameter text half of
  `laion/larger_clap_music_and_speech`, produced on the base rig and shipped to
  the customer's NAS beside `music.db`. It is a derivative work of an
  Apache-2.0 model. **Attribution and modification notice (Apache-2.0 §4):**
  the files in `music/web/data/text_encoder/` are derived from
  `laion/larger_clap_music_and_speech` by LAION, licensed under the Apache
  License, Version 2.0 (<https://www.apache.org/licenses/LICENSE-2.0>); they
  have been modified by Cablewrap Creative Ltd. by exporting only the text
  encoder to ONNX, and are not the original checkpoint.
- **MiniLM: NOT SHIPPED.** `fastembed` is deliberately excluded from the
  container (`dashboard/deploy/requirements.txt` says so in the b-roll
  section's comment, and gives the reason). The model is downloaded only on
  the indexing machine; what reaches the customer is precomputed float32
  vectors inside `broll.db`. Apache-2.0 imposes no copyleft on those.
- **Whisper: NOT SHIPPED, NOT IN THIS REPO.** `broll/indexer` calls an
  operator-supplied `faster-whisper` environment
  (`broll/indexer/broll_index/transcribe.py`). Only the resulting transcript
  text reaches a customer, inside `broll.db`.
- **Qwen3-VL / llama.cpp: NOT SHIPPED.** `broll_index/local_runtime.py` has the
  indexing machine download the runtime binary from GitHub and the GGUF
  weights from Hugging Face itself, sha256-verified against the pins in
  `broll_index/local_models.py` before either is trusted. Only the resulting
  shot descriptions (text) reach a customer, inside `broll.db`; the weights
  never leave the indexing machine and are never bundled into the companion
  or the dashboard container, which is why `tools/check_licenses.py` (scoped
  to those two shipped artefacts) does not see this row and it is inventoried
  here by hand.

Model weights can carry terms separate from their repository's software
licence. The licences stated above for the CLAP, MiniLM, Whisper and Qwen3-VL
weights are those on each model's published model card.

### bgutil PO-token provider: GPLv3, and outside the base container

Its licence is VERIFIED: installed metadata in the `dashboard` venv reads
**GNU General Public License v3 (GPLv3)** (the table above). Its upstream
repository is `Brainicism/bgutil-ytdlp-pot-provider`; the sidecar container
image's licence is *as published upstream*.

It is not in the base `dashboard/deploy/requirements.txt`/`.lock` that every
deployment installs and the image bakes. It lives in its own
`dashboard/deploy/requirements-unblock.txt`/`.lock`, which
`dashboard/deploy/run.sh` installs into the container venv only when
`DASH_SITE_YOUTUBE_UNBLOCK=1`, which is set only on a site whose `site.toml`
sets `[features] youtube_unblock` (`server/install_dashboard_app.py
compose_config()`). `tools/check_licenses.py`'s `dashboard-container` target
is clean of it; its `dashboard-container-unblock` target and
`tools/license_allowlist.toml`'s `[allow.bgutil-ytdlp-pot-provider]` entry
cover it. The component exists to get past YouTube's bot check, and is
governed by `docs/legal/YOUTUBE_FEATURE_NOTICE.md`.

**WRITTEN OFFER (GPLv3 §6).** On a site where this plugin has been installed,
Cablewrap Creative Ltd. makes the same offer as for ffmpeg above, on the same
terms and at the same address, for the corresponding source of the version
installed. The same source is available without charge from
<https://github.com/Brainicism/bgutil-ytdlp-pot-provider> and from PyPI.

### yt-credit-downloader: the Licensor's own code

`ytdl/web/ytdlweb/vendor/downloader.py` and `ytsearch.py` were adapted on
2026-08-11 from `yt-credit-downloader`, a utility written by the Licensor's
own author (`vendor/__init__.py`). They are not third-party code and carry no
open-source licence: they are part of the Software and are licensed to you
under `docs/legal/EULA.md`. Their provenance is recorded in
`ytdl/web/ytdlweb/vendor/PROVENANCE.md`.

### LGPL and MPL components that remain, and why they are compliant

Three LGPL dependencies are installed as ordinary Python packages:
**dynamically imported into a normal Python installation**, **not inside any
single-file binary we distribute**, and replaceable by the customer with a
modified version by `pip install`-ing over them, which is exactly the "user
can replace the library" freedom the LGPL exists to protect. A fourth,
psycopg2, is also frozen into the companion executable; it is described
separately below.

**`paramiko` 5.0.0 (LGPL-2.1).** VERIFIED from installed metadata, with the
licence text on disk. Imported by exactly two places:

- `dashboard/src/ccsync_dashboard/nas/synology.py`: the Synology backend's SSH
  session, needed because DSM exposes no API for writing an editor's
  `authorized_keys`;
- `server/common.py`: the NAS-side install scripts, run from the operator's own
  Python on the base rig.

Neither is frozen. The dashboard runs from a source tree with its
dependencies pip-installed into the customer's own container venv, where the
customer can replace `paramiko` without touching anything of ours. The
`server/` scripts are plain `.py` files run under an ordinary interpreter.

**`psycopg2-binary` in the dashboard container (LGPL with psycopg2's own
exceptions).** Installed and replaceable exactly as `paramiko` is (the
dashboard-container table above). It is imported only by the mounted Timeline
Cards page's project-library route, which reads DaVinci Resolve's PostgreSQL
database, on a site that enables that page (`tools/license_allowlist.toml`,
`[allow.psycopg2-binary]`).

**`psycopg2` in the companion executable.** The companion's Timeline Cards
role reads DaVinci Resolve's PostgreSQL project library, and for that
`companion/build.spec` collects `psycopg2` (from `psycopg2-binary`, a
dependency in `companion/pyproject.toml`) into the frozen companion, together
with the `libpq` and OpenSSL libraries its wheel carries. They are packed as
separate extension-module and shared-library files that the executable
extracts and loads at run time, unmodified. The source of psycopg2 at the
version in a given build is available without charge from
<https://github.com/psycopg/psycopg2> and from PyPI, and Cablewrap Creative
Ltd. makes the same written offer for it as for ffmpeg above, on the same
terms and at the same address, for three years from the build's
publication. Every companion build, whether built on the Licensor's own
machine or by its build service for the release feed, is built from the same
locked list of dependencies, which names psycopg2, and a release build fails
if it freezes a package that list does not name.

**`soundfile` / `librosa` (LGPL-2.1 via bundled `libsndfile`/`libsoxr`).**
Imported by exactly one module, `music/indexer/music_index/features.py`: the
**GPU indexer on the base rig**, the operator's own machine, never shipped and
never installed on a customer's NAS or an editor's workstation.
`music/web/.venv` deliberately carries no torch and no audio stack; only
precomputed features reach `music.db`.

**`certifi` (MPL-2.0).** Used unmodified. Its source is available from
<https://github.com/certifi/python-certifi> and from PyPI.

**VERIFIED:** a byte scan of the current Windows companion build (re-checked
2026-09-25) finds no occurrence of `paramiko`, `soundfile` or `librosa`; the
only LGPL package `companion/build.spec` collects is `psycopg2`, described
above. `onboarding/build_onboard.spec` and `build_onboard_macos.spec`
explicitly *exclude* `pystray`, `PIL` and `watchdog`, and name no LGPL
package.

The source of every LGPL and MPL component listed here, at the version we
install, is available without charge from PyPI and from the project's home
page in the tables above; Cablewrap Creative Ltd. will also supply it on
request at the address given for the ffmpeg offer.

### Licence texts

This document names each licence rather than reproducing it. The full text of
each licence is available from the component's home page listed in the tables
above and, for Python packages, inside the installed distribution (the
"Licence text on disk" column). Cablewrap Creative Ltd. will supply a copy of
any of them on request at contact@thecreatorsclub.co. htmx is licensed under
the Zero-Clause BSD licence (0BSD), which requires no notice to accompany it.

### The ytdl/web component

`ytdl/web` has no environment of its own, so the generator reports it as
skipped. It runs inside the dashboard container, and its runtime dependencies
are the container's: they appear in the dashboard-container table above.

### Fonts (the dashboard's terminal look)

EMBEDDED (A) in the dashboard image under `dashboard/static/fonts/`, served to
the dashboard's own pages and the three mounted apps. Both are licensed under
the SIL Open Font License, Version 1.1; the full licence text ships beside the
font files (`OFL-JetBrainsMono.txt`, `OFL-Orbitron.txt`).

| Font | Files | Licence | Home page | Notes |
|---|---|---|---|---|
| JetBrains Mono | `jetbrains-mono-regular.woff2`, `jetbrains-mono-medium.woff2`, `jetbrains-mono-bold.woff2` | OFL-1.1, Copyright 2020 The JetBrains Mono Project Authors | https://github.com/JetBrains/JetBrainsMono | Subset to Latin, Latin-1, Latin Extended-A, punctuation, symbols, arrows and box drawing; no Reserved Font Name. |
| Orbitron | `orbitron-variable.woff2` | OFL-1.1, Copyright 2018 The Orbitron Project Authors, Reserved Font Name "Orbitron" | https://github.com/theleagueof/orbitron | Shipped whole (the upstream variable font, converted to WOFF2 without subsetting), because Orbitron carries a Reserved Font Name. |
<!-- END HAND-MAINTAINED -->
