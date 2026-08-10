"""Music search web app -- the read half of the music platform.

The package is `musicweb`, NOT `app`. `broll/web` is deployed by putting its
tree on PYTHONPATH and importing it as the top-level package `app`; a second
`app` package would collide in sys.modules and one of the two would silently
win. The FastAPI instance inside main.py is still called `app`, because that is
the object the dashboard mounts.

Folded in from the standalone `music-tagger` repo on 2026-08-10 (pre-fold git
history stays there). See ../SPEC.md.
"""
