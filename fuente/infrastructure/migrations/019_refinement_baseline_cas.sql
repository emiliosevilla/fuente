ALTER TABLE refinement_candidates ADD COLUMN baseline_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE refinement_candidates ADD COLUMN baseline_content_hash TEXT NOT NULL DEFAULT '';
