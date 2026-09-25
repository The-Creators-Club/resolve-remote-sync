# tools/notices_extra

Licence texts for what a frozen CC Sync binary carries that is not a pip
distribution, plus fallbacks for the few wheels that ship no licence file.
`python tools/gen_notices.py --write-texts` reads them into
`docs/legal/licenses/<component>/THIRD_PARTY_LICENSES.txt`, which
`companion/build.spec` and the two onboarding specs bundle (LG-12,
`docs/LEGAL_GAP_FEATURES_PLAN.md`, 2026-09-25).

Every file starts with a title line, then says what it covers in the binary
and exactly where its text was copied from. The texts themselves are verbatim.

| File | Covers | Refresh when |
|---|---|---|
| `pyinstaller-bootloader.txt` | the PyInstaller bootloader and run-time hooks in every exe | the `pyinstaller==` pin in `tools/release.ps1`, `tools/release_macos.sh` or the release workflows moves |
| `cpython.txt` | CPython 3.12 and what its Windows build bundles (bzip2, libffi, OpenSSL, Tcl/Tk, the Microsoft runtime) | the build machines move to another CPython minor |
| `tcl-tk.txt` | Tcl/Tk 8.6, for tkinter | Tcl/Tk moves to 9 |
| `openssl.txt` | OpenSSL 3 (CPython's, and psycopg2-binary's in the companion) | never for a 3.x bump; OpenSSL 3 is Apache-2.0 throughout |
| `libpq.txt` | libpq inside psycopg2-binary (companion only) | psycopg2-binary's bundled libpq changes major version |
| `dists/<name>.txt` | a locked distribution whose wheel ships no licence file (`flatbuffers`, `pyobjc-core` as of 2026-09-25) | the distribution starts shipping its own, then delete the fallback |
| `music_text_encoder/{NOTICE,LICENSE}` | the Apache-2.0 notice and modification statement for the exported CLAP text tower; copies live in `music/web/data/text_encoder/`, which is gitignored | the text tower is re-exported (`music/indexer/export_text_encoder.py` does not copy them yet) |

The per-distribution texts are read from each wheel's own `.dist-info`, not
from here. A distribution that is not installed in the venv
`gen_notices.py --write-texts` scans (pyobjc on Windows) keeps the text a
previous run wrote where it was installed; pass
`--venv companion=<a venv built from companion/requirements.lock>` to use
another venv.
