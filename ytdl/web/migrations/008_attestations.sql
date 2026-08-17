-- 008: the rights/ToS attestation record (COMMERCIAL_READINESS.md item 2,
-- 2026-08-17). One row per (user, wording version): re-accepting a re-worded
-- notice adds a row, it never overwrites the record of the old one, because
-- "what did this editor agree to in March" is the question this table exists
-- to answer.
--
-- Additive and idempotent, like every migration here. A database that never
-- gets this table simply refuses every download with the attestation refusal,
-- which is the safe direction to fail.
CREATE TABLE IF NOT EXISTS attestations (
    username     TEXT NOT NULL,
    version      TEXT NOT NULL,          -- attestation.TEXT_VERSION at accept time
    -- The digest of the exact wording accepted. The version is the contract;
    -- this is the evidence that the contract's text had not been edited
    -- underneath it without a version bump.
    text_sha256  TEXT NOT NULL,
    accepted_at  TEXT NOT NULL,
    PRIMARY KEY (username, version)
);
