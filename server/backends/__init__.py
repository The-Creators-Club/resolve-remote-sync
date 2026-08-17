"""Install-time NAS backends for the server scripts.

One module per platform. `base.ServerBackend` is the Protocol every script
codes against; `truenas.TrueNASBackend` is the production implementation (the
bodies that used to sit inline in install_dashboard_app.py,
install_syncthing_app.py, setup_editor_account.py, setup_tree.py and
check_health.py, moved here unchanged on 2026-08-17);
`synology.SynologyBackend` is the DSM 7.2 stub the port fills in.

Nothing here is imported at script import time by default -- `common.get_backend`
imports the chosen module lazily, so a broken or unfinished backend can never
stop a script that does not use it from running.

See docs/SYNOLOGY_PORT_PLAN.md (WP3) for the mapping table this package
implements, and server/README.md for the operator view.
"""
