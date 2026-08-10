-- Where each share's footage actually lives, pushed from the indexer.
--
-- The web app cannot work this out for itself: share -> source root, and
-- whether a share archives originals or proxies, live in the indexer's
-- config.queue.yaml, which app/config.py notes explicitly it does not read and
-- may not even be on the same machine.
--
-- It matters for the final-export relink. A remote editor cuts against a proxy;
-- at conform the TRUE original has to be found, most likely on a backup
-- external drive. Without this table the B-roll origin manifest can record a
-- share name and a relative path but nothing to resolve them against.
--
-- `source` carries the same meaning as indexer ShareConfig.source: for a
-- 'proxies' share the archived original IS the Proxy/*.mov, so a conform must
-- not go hunting for camera files that were deliberately left behind.
CREATE TABLE IF NOT EXISTS share_roots (
    share       TEXT PRIMARY KEY,
    root        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'originals'
                CHECK (source IN ('originals', 'proxies')),
    description TEXT NOT NULL DEFAULT '',
    indexed     INTEGER NOT NULL DEFAULT 1,   -- ShareConfig.index
    updated_at  TEXT
);

PRAGMA user_version = 6;
