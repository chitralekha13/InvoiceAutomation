-- Add template and addl_comments columns if they don't exist (for existing databases)
-- Run this if your invoices table was created before these columns were added

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS template VARCHAR(100);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS addl_comments TEXT;
