-- =========================================================================
-- HealthContracts AI — Bootstrap Grants
-- Run once per environment with admin privileges.
-- Replace {app_catalog}, {app_schema}, {customer_catalog}, {customer_schema}
-- with actual values for the target environment.
-- Dev defaults: dev.doc_intel / dev.doc_intel
-- =========================================================================

-- Catalog access
GRANT USE CATALOG ON CATALOG dev TO `sp-healthcontracts-ai`;

-- Schema access
GRANT USE SCHEMA ON SCHEMA dev.doc_intel TO `sp-healthcontracts-ai`;

-- Table creation
GRANT CREATE TABLE ON SCHEMA dev.doc_intel TO `sp-healthcontracts-ai`;

-- App tables: full CRUD
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA dev.doc_intel TO `sp-healthcontracts-ai`;

-- Customer tables: write parsed + current data
GRANT SELECT, INSERT ON SCHEMA dev.doc_intel TO `sp-healthcontracts-ai`;

-- Volume access
GRANT READ VOLUME, WRITE VOLUME ON VOLUME dev.doc_intel.prvdr_contracts TO `sp-healthcontracts-ai`;

-- NOTE: hipaa_audit_log and review_actions are append-only.
-- Do NOT grant UPDATE or DELETE on these tables to any non-admin principal.
-- The service principal gets INSERT only on these two tables.
