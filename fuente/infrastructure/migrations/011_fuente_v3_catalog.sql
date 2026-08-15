-- Task 6: the catalog writes Fuente v3 vocabulary. Migration 009 remains the
-- historical source of the legacy column for existing installations.

ALTER TABLE note_catalog RENAME COLUMN source_kind TO origin_kind;
