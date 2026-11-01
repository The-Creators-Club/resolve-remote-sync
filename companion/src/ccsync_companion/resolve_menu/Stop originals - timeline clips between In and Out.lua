-- CC Sync menu script. Installed and rewritten by the CC Sync companion; edits here are overwritten.
-- Stops bringing the originals of the clips between the In and Out marks (no marks: the clip under the playhead). Files already here stay.
-- docs/SELECTIVE_ORIGINALS.md section 12. The companion splices the shared
-- body (_originals_common.lua) in at the marker below when it installs this.
CCSYNC_ACTION = "remove"
CCSYNC_SCOPE = "timeline_range"
--@@CCSYNC_COMMON@@
