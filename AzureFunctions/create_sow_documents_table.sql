-- SOW (Statement of Work) documents table for matching with invoices
-- Run this in your PostgreSQL database

CREATE TABLE IF NOT EXISTS sow_documents (
    id SERIAL PRIMARY KEY,
    sow_id VARCHAR(255) UNIQUE NOT NULL,
    doc_name VARCHAR(500),
    pdf_url TEXT,
    resource_name VARCHAR(255),
    consultancy_name VARCHAR(255),
    sow_start_date DATE,
    sow_end_date DATE,
    net_terms VARCHAR(100),
    max_sow_hours DECIMAL(10, 2),
    rate_per_hour DECIMAL(10, 2),
    project_role VARCHAR(255),
    sow_project_duration VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sow_resource_consultancy ON sow_documents(resource_name, consultancy_name);
CREATE INDEX IF NOT EXISTS idx_sow_created_at ON sow_documents(created_at DESC);
