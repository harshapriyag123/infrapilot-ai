-- Migration: add error_hint to analysis_jobs
-- For SQLite, ALTER TABLE ADD COLUMN is supported for simple columns.

ALTER TABLE analysis_jobs ADD COLUMN error_hint VARCHAR(200);
