-- Add comments column for SOW validation and no-match messages (accounts dashboard Comments column)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS comments TEXT;
