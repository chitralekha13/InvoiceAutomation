-- Create invoices table for PostgreSQL
-- Run this script in your PostgreSQL database to create the invoices table

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id VARCHAR(255) PRIMARY KEY,
    vendor_id VARCHAR(255),
    vendor_name VARCHAR(255),
    doc_name VARCHAR(500),
    pdf_url TEXT,
    invoice_number VARCHAR(100),
    invoice_amount DECIMAL(15, 2),
    invoice_hours DECIMAL(10, 2),
    hourly_rate DECIMAL(10, 2),
    invoice_date DATE,
    due_date DATE,
    status VARCHAR(50) DEFAULT 'Pending',
    approval_status VARCHAR(50) DEFAULT 'Pending',
    resource_name VARCHAR(255),
    project_name VARCHAR(500),
    payment_terms VARCHAR(100),
    business_unit VARCHAR(255),
    start_date DATE,
    end_date DATE,
    approved_hours DECIMAL(10, 2),
    vendor_hours DECIMAL(10, 2),
    approved_by VARCHAR(255),
    notes TEXT,
    template VARCHAR(100),
    addl_comments TEXT,
    orchestrator_summary TEXT,
    last_agent_text TEXT,
    bill_pay_initiated_on TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    invoice_received_date TIMESTAMP DEFAULT NOW(),
    last_updated_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_invoices_vendor_id ON invoices(vendor_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_invoices_approval_status ON invoices(approval_status);
CREATE INDEX IF NOT EXISTS idx_invoices_created_at ON invoices(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_invoices_invoice_number ON invoices(invoice_number);
