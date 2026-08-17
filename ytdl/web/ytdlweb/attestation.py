"""The rights/ToS attestation every editor accepts before they may download.

DRAFT FOR COUNSEL. The wording in NOTICE_TEXT, COPYRIGHT_NOTICE and
RATE_DISCLAIMER below was written by engineers, not lawyers, and is a starting
point for a review -- not advice, and not a warranty that accepting it makes
any particular download lawful. Change the text and BUMP `TEXT_VERSION`: the
version is stored with each acceptance, so a re-worded notice re-prompts
everybody instead of leaving the fleet's records pointing at wording nobody
agreed to. docs/legal/YOUTUBE_FEATURE_NOTICE.md is the operator-facing
companion to this file (COMMERCIAL_READINESS.md item 2, 2026-08-17).

WHY IT EXISTS. This product hands an editor a search box and downloads other
people's video with it. Whether any given download is lawful depends on the
material, the use, the jurisdiction and the editor's own agreement with
YouTube -- none of which the software can know. So the software refuses to
guess: the person who chose the clip states that they have the right to use
it, and the record of that statement (who, when, which wording) lives beside
the clips.

WHERE IT IS ENFORCED, three places, because one is not enough:
  - routes_api (create a job / start a download) -- the browser path;
  - routes_fleet (claim) -- the companion path, which has no browser and
    could otherwise be driven straight past the SPA;
  - the companion itself (ytdl_attestation.py), per MACHINE, because "this
    machine downloads YouTube video" is a fact about a machine and its owner
    as much as about an account.

The store is deliberately append-only-ish: one row per (user, version), so a
re-accepted new wording does not erase the record of the old one.
"""
import hashlib
import logging

log = logging.getLogger(__name__)

# Bump on ANY change to the three text blocks below. Date-plus-serial rather
# than an integer so an operator reading a database row can see when the
# wording they are looking at was written.
TEXT_VERSION = '2026-08-17.1'

NOTICE_TITLE = 'Before you download: your responsibilities'

# The attestation itself -- what the editor is agreeing to. Kept short enough
# to actually be read: a wall of text is a click-through, and a click-through
# is not a record of anything.
NOTICE_TEXT = """\
This tool downloads video from YouTube at your request. Before you use it:

1. YOU CONFIRM YOU HAVE THE RIGHT TO USE THIS MATERIAL. You are the person
   choosing each clip, and you are stating that your intended use of it is
   permitted -- because you own it, because you have a licence or written
   permission, because it is public domain or openly licensed, or because
   your use is covered by an exception in your jurisdiction (for example
   fair dealing or fair use). If you are not sure, ask before you download.

2. YOU ARE RESPONSIBLE FOR COMPLYING WITH YOUTUBE'S TERMS OF SERVICE and with
   copyright law. YouTube's terms restrict downloading content except through
   features YouTube itself provides or where you have the rights holder's
   permission. Whether a particular download is permitted is between you (and
   your organisation) and YouTube; it is not something this software decides.

3. CC SYNC GRANTS YOU NO RIGHTS IN ANY DOWNLOADED MATERIAL. It is a tool. It
   does not license, clear, or vouch for anything it fetches, and it makes no
   representation that any download is lawful.

4. WHAT IS RECORDED. Your username, this machine's name, the clip and the time
   are written to your organisation's own records, so that what was downloaded
   -- and on whose say-so -- can be answered later. Downloads are attributed to
   you.

If you cannot make these statements about the material you are about to fetch,
do not download it.
"""

# Shown on the downloader's pages, always -- not only at the accept prompt.
COPYRIGHT_NOTICE = (
    'Material downloaded here belongs to whoever made it. Clearing the rights '
    'for anything you cut into a deliverable is your responsibility, and this '
    'tool grants you none of them.'
)

# The rate/volume disclaimer, also always on the page. It is here because the
# honest reason downloads are slow is a policy one, not a technical one.
RATE_DISCLAIMER = (
    'Downloads are paced deliberately and are not guaranteed to succeed. '
    'YouTube rate-limits, blocks and changes its service without notice; bulk '
    'or automated retrieval may breach its terms and may stop working at any '
    'time. Do not build a workflow that depends on this feature being fast, '
    'available, or complete.'
)


def text_sha256(version=None):
    """A digest of the exact wording a given acceptance covers.

    Stored alongside the version so a text edit that FORGOT to bump
    TEXT_VERSION is still visible in the records afterwards -- the version is
    the contract, this is the evidence.
    """
    blob = '\n'.join((str(version or TEXT_VERSION), NOTICE_TITLE, NOTICE_TEXT,
                      COPYRIGHT_NOTICE, RATE_DISCLAIMER))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def payload(accepted_row=None):
    """What GET /api/attestation answers: the wording, plus this user's state.

    One shape whether or not they have accepted, so the SPA renders the same
    notice block either way and only the gate changes.

    Takes a sqlite3.Row (or a dict, or None) -- a Row is a MAPPING but has no
    .get(), and reaching for one on a real row is an AttributeError at the one
    moment this endpoint has something to say.
    """
    row = dict(accepted_row) if accepted_row is not None else {}
    return {
        'version': TEXT_VERSION,
        'title': NOTICE_TITLE,
        'text': NOTICE_TEXT,
        'copyright_notice': COPYRIGHT_NOTICE,
        'rate_disclaimer': RATE_DISCLAIMER,
        'accepted': bool(row.get('version') == TEXT_VERSION),
        'accepted_at': row.get('accepted_at'),
        'accepted_version': row.get('version'),
    }


# The refusal, in one place: routes_api and routes_fleet both raise it, and an
# editor who hits it in the API must be told the same thing the page says.
REFUSAL = ('you have not accepted the YouTube download terms. Open the '
           'YouTube downloader and read the notice at the top of the page, '
           'then press Accept.')
