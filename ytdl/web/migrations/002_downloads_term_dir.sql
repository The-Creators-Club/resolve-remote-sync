-- v2: the ledger records the FOLDER a clip landed in, not just the term.
--
-- YTDL-31 (2026-08-11): downloads.term is what the editor typed, while the
-- directory on disk is safe_term_dirname(term) -- for any term carrying
-- <>:"/\|?* or more than 80 UTF-8 bytes the "ALREADY IN <label>/<term>" badge
-- named a path that does not exist over SMB, and the disk-scan half of the same
-- badge named the real one. term_dir is filled from the ledgered rel_path
-- ('Youtube/<term_dir>/<file>') on write; NULL on old rows, where ledger_map
-- falls back to the raw term exactly as it did before.
ALTER TABLE downloads ADD COLUMN term_dir TEXT;
