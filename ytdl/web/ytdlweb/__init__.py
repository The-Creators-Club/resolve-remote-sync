"""`ytdlweb` -- the YouTube downloader sub-app mounted by the dashboard at /ytdl.

The package is `ytdlweb`, deliberately NOT `app` and not `ytdl`: broll/web is
deployed by putting its tree on PYTHONPATH and importing it as the top-level
package `app`, and all three sub-apps share one PYTHONPATH inside the dashboard
container, so a name either of the others could plausibly use would collide in
sys.modules and one would silently win. Same rule music/web follows.
"""
