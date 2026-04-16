-- Add payment_details column for storing iGentic payment agent output (JSON)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_details TEXT;
