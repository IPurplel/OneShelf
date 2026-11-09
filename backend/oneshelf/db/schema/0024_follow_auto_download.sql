-- A Follow may download its new releases on its own, when the person turns that on for this Work (ADR 0005).
-- Off by default, so every existing Follow keeps notifying only.
ALTER TABLE follows ADD COLUMN auto_download INTEGER NOT NULL DEFAULT 0 CHECK (auto_download IN (0, 1));
