"""Ask the dashboard where a file went, before giving it up for deleted.

`docs/HAND_MOVES_ON_THE_SERVER.md` phase 2, companion 0.9.73. A folder moved
by hand on the NAS looks to lane B exactly like a deletion: the files left the
path this machine syncs, so `rclone sync` walks the local copies into
`.ccsync-trash` and, past 50 in one pass, the breaker parks the lane (CR-45).
CR-44's probe already asks "were they moved?" -- but it asks by re-listing the
SCOPE, and every move that has actually cost a day of an editor's proxies went
to a DIFFERENT project, which is outside the only question it can ask.

`POST /api/v1/files/locate` is that question asked tree-wide, answered from
the dashboard's own 15-minute-old inventory. Two rules govern every use of it:

  * **Any failure contributes nothing.** No dashboard URL, no token, a
    timeout, an HTTP error, a body that will not parse, `walked: false` -- all
    of them are "I cannot tell", and the caller must then behave exactly as a
    companion with no locate call at all. This is the code path that decides
    NOT to stop a lane which is removing files, so the fallback has to be the
    strict one (lane_guard._count_relocations says the same thing).
  * **Comparison is NFC, the rename is not** (CR-90). The names go up folded,
    and the `rel_path` that comes back is the server's own spelling, which is
    what a rename must use: there the bytes on disk are the truth.

The call is deliberately SHORT (10 s) and made at most once per lane B pass.
A dashboard that is slow or down must cost a pass its extra knowledge, never
the pass itself.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger("ccsync.sync.locate")

# The dashboard's own ceiling (locate.MAX_LOCATE_FILES). Asking about more is
# a 413, so the batch is cut here and the shortfall logged: a caller that
# silently asked about half its files would read the other half as deleted.
MAX_LOCATE_FILES = 2000

LOCATE_TIMEOUT_SECONDS = 10.0

RequestFn = Callable[[str, str, Optional[dict], dict, float], tuple[int, Any]]


def nfc(text: str) -> str:
    """Fold for COMPARISON only. Never for a path something opens or renames."""
    return unicodedata.normalize("NFC", str(text or ""))


class LocateAnswer:
    """What the server knows about a batch of (basename, size) pairs.

    `walked` false means the dashboard has never completed an inventory walk,
    so "found nothing" is NOT evidence of anything and every caller treats the
    whole answer as absent. `as_of` is how old the server's picture is, and is
    carried for the log line rather than for a decision: a companion cannot
    usefully second-guess the collector's cadence.
    """

    def __init__(self, walked: bool, as_of: str,
                 found: dict[tuple[str, int], list[dict[str, str]]]) -> None:
        self.walked = bool(walked)
        self.as_of = str(as_of or "")
        self._found = found

    @property
    def usable(self) -> bool:
        return self.walked

    def places(self, name: str, size: int) -> list[dict[str, str]]:
        """Every (project_slug, rel_path) holding this basename+size."""
        if not self.walked:
            return []
        return list(self._found.get((nfc(name), int(size)), ()))

    def __len__(self) -> int:
        return sum(1 for places in self._found.values() if places)


class ServerLocator:
    """The locate call, wired to the companion's own dashboard credentials.

    The same pair every fleet route takes (jobs_runner._headers, and H5's
    reasoning): the shared or per-editor token proves a fleet machine, the
    dashboard-signed identity proves whose. Both are read PER CALL, because
    IdentityManager republishes a rotated token into the same cfg dict at
    sign-in.
    """

    def __init__(self, cfg: Optional[dict] = None,
                 identity_token_fn: Optional[Callable[[], str]] = None,
                 request_fn: Optional[RequestFn] = None,
                 timeout: float = LOCATE_TIMEOUT_SECONDS) -> None:
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._identity_token_fn = identity_token_fn
        self._request = request_fn
        self.timeout = float(timeout)

    # -- wiring ---------------------------------------------------------
    @property
    def _dashboard_url(self) -> str:
        return str(self.cfg.get("dashboard_url", "") or "").strip().rstrip("/")

    @property
    def _token(self) -> str:
        return str(self.cfg.get("dashboard_token", "") or "").strip()

    def _headers(self) -> dict[str, str]:
        identity = ""
        if self._identity_token_fn is not None:
            try:
                identity = str(self._identity_token_fn() or "")
            except Exception:
                log.debug("locate: identity_token_fn failed", exc_info=True)
        return {"Content-Type": "application/json",
                "X-CCSync-Token": self._token,
                "X-CCSync-Identity": identity}

    # -- the call -------------------------------------------------------
    def locate(self, entries: Iterable[tuple[str, int]]) -> Optional[LocateAnswer]:
        """(basename, size) pairs -> the answer, or None when we cannot tell.

        NEVER RAISES. A transport failure is an exception out of the request
        function (broll_ingest.default_request's contract), and here it is
        simply another way of not knowing.
        """
        pairs: list[tuple[str, int]] = []
        seen: set[tuple[str, int]] = set()
        for name, size in entries:
            try:
                key = (nfc(name), int(size))
            except (TypeError, ValueError):
                continue
            if not key[0] or key in seen:
                continue
            seen.add(key)
            pairs.append(key)
        if not pairs:
            return None
        if len(pairs) > MAX_LOCATE_FILES:
            log.info("locate: asking about the first %d of %d file(s) - the rest "
                     "keep this build's old behaviour", MAX_LOCATE_FILES, len(pairs))
            pairs = pairs[:MAX_LOCATE_FILES]
        url = self._dashboard_url
        if not url or not self._token:
            return None

        request = self._request
        if request is None:
            from ..broll_ingest import default_request
            request = default_request
        body = {"files": [{"name": name, "size": size} for name, size in pairs]}
        try:
            status, parsed = request("POST", f"{url}/api/v1/files/locate",
                                     body, self._headers(), self.timeout)
        except Exception as exc:
            log.info("locate: the dashboard could not be asked where these files "
                     "went (%s) - treating them as deletions", exc)
            return None
        if status != 200 or not isinstance(parsed, dict):
            log.info("locate: the dashboard answered HTTP %s - treating these "
                     "files as deletions", status)
            return None

        found: dict[tuple[str, int], list[dict[str, str]]] = {}
        for entry in (parsed.get("files") or []):
            if not isinstance(entry, dict):
                continue
            try:
                key = (nfc(entry.get("name")), int(entry.get("size")))
            except (TypeError, ValueError):
                continue
            places: list[dict[str, str]] = []
            for place in (entry.get("found") or []):
                if not isinstance(place, dict):
                    continue
                slug = str(place.get("project_slug") or "").strip()
                rel = str(place.get("rel_path") or "").strip()
                if slug and rel:
                    places.append({"project_slug": slug, "rel_path": rel})
            found[key] = places
        answer = LocateAnswer(bool(parsed.get("walked")), str(parsed.get("as_of") or ""),
                              found)
        if not answer.walked:
            # An inventory that has never run cannot tell a deletion from a
            # move, and saying so is the whole reason the flag is on the wire.
            log.info("locate: the dashboard has not walked the tree yet - "
                     "treating these files as deletions")
        return answer
