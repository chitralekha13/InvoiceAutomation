-- Fix existing sow_documents table: add missing columns if they don't exist.
-- Run this if you get "column resource_name does not exist" (table was created with an older schema).
-- In psql, run the whole file with: \i alter_sow_documents_add_columns.sql

ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS sow_id VARCHAR(255);
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS doc_name VARCHAR(500);
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS pdf_url TEXT;
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS resource_name VARCHAR(255);
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS consultancy_name VARCHAR(255);
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS sow_start_date DATE;
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS sow_end_date DATE;
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS net_terms VARCHAR(100);
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS max_sow_hours DECIMAL(10, 2);
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS rate_per_hour DECIMAL(10, 2);
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS project_role VARCHAR(255);
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS sow_project_duration VARCHAR(255);
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
ALTER TABLE sow_documents ADD COLUMN IF NOT EXISTS last_updated_at TIMESTAMP DEFAULT NOW();

-- Indexes for matching and listing
CREATE INDEX IF NOT EXISTS idx_sow_resource_consultancy ON sow_documents(resource_name, consultancy_name);
CREATE INDEX IF NOT EXISTS idx_sow_created_at ON sow_documents(created_at DESC);
