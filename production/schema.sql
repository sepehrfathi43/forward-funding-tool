-- INACTIVE / SUPERSEDED: workplace uses file inputs; no SQL deployment is required or planned.
-- DESIGN DRAFT: not applied or integration-tested. See PRODUCTION_ROADMAP.md.
-- Run migrations as a separate owner. Do not run the application as that owner.
BEGIN;
CREATE SCHEMA funding;
SET LOCAL search_path = funding, pg_catalog;

CREATE TABLE tenants (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE cases (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id uuid NOT NULL,
    reference text NOT NULL,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE documents (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    object_key text NOT NULL,
    original_filename text NOT NULL,
    media_type text NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    uploaded_by text NOT NULL,
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, case_id, id),
    UNIQUE (tenant_id, case_id, sha256),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);
CREATE TABLE accounts (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    bank_account_reference text NOT NULL, -- use a token, not an exposed full account number
    currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, case_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);
CREATE TABLE statements (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    document_id uuid NOT NULL,
    account_id uuid NOT NULL,
    extraction_version text NOT NULL,
    period_start date,
    period_end date,
    opening_balance numeric(20,2),
    closing_balance numeric(20,2),
    extraction jsonb NOT NULL,
    integrity_report jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    CHECK (period_end >= period_start),
    FOREIGN KEY (tenant_id, case_id, document_id) REFERENCES documents(tenant_id, case_id, id),
    FOREIGN KEY (tenant_id, case_id, account_id) REFERENCES accounts(tenant_id, case_id, id)
);
CREATE TABLE transactions (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    statement_id uuid NOT NULL,
    source_sequence integer NOT NULL CHECK (source_sequence > 0),
    transaction_date date,
    description text,
    amount numeric(20,2),
    direction text CHECK (direction IN ('debit', 'credit')),
    source_evidence jsonb NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, statement_id, source_sequence),
    CHECK (amount > 0),
    FOREIGN KEY (tenant_id, statement_id) REFERENCES statements(tenant_id, id)
);
CREATE TABLE transaction_reviews (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    transaction_id uuid NOT NULL,
    classification text NOT NULL,
    actor_id text NOT NULL,
    reason text NOT NULL CHECK (length(trim(reason)) > 0),
    revision bigint NOT NULL CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, transaction_id, revision),
    FOREIGN KEY (tenant_id, transaction_id) REFERENCES transactions(tenant_id, id)
);
CREATE TABLE debt_positions (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    terms jsonb NOT NULL,
    monthly_payment numeric(20,2) CHECK (monthly_payment >= 0),
    verified_by text,
    evidence_reference text,
    revision bigint NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);
CREATE TABLE model_versions (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('policy', 'pd')),
    version text NOT NULL,
    specification jsonb NOT NULL,
    artifact_sha256 text CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, kind, version)
);
CREATE TABLE calculations (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    policy_id uuid NOT NULL,
    pd_model_id uuid,
    case_revision bigint NOT NULL,
    input_snapshot jsonb NOT NULL,
    input_sha256 text NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
    result jsonb NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, case_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id),
    FOREIGN KEY (tenant_id, policy_id) REFERENCES model_versions(tenant_id, id),
    FOREIGN KEY (tenant_id, pd_model_id) REFERENCES model_versions(tenant_id, id)
);
CREATE TABLE decisions (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    calculation_id uuid NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('approved', 'declined', 'review_required')),
    authorized_amount numeric(20,2) CHECK (authorized_amount >= 0),
    currency char(3) NOT NULL,
    actor_id text NOT NULL,
    reason text NOT NULL CHECK (length(trim(reason)) > 0),
    override_evidence jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id, calculation_id) REFERENCES calculations(tenant_id, case_id, id)
);
CREATE TABLE audit_events (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id bigint GENERATED ALWAYS AS IDENTITY,
    case_id uuid,
    actor_id text NOT NULL,
    request_id uuid NOT NULL,
    action text NOT NULL,
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);
CREATE INDEX audit_case_time ON audit_events(tenant_id, case_id, id);
CREATE INDEX statement_account_period ON statements(tenant_id, account_id, period_start, period_end);
CREATE INDEX transaction_statement ON transactions(tenant_id, statement_id, transaction_date);

CREATE FUNCTION reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'History is append-only; append a correction or superseding record';
END;
$$;
DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['documents','statements','transactions','transaction_reviews',
                                     'model_versions','calculations','decisions','audit_events'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE OR TRUNCATE ON funding.%I
                        FOR EACH STATEMENT EXECUTE FUNCTION funding.reject_history_change()', table_name);
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY['cases','documents','accounts','statements','transactions',
        'transaction_reviews','debt_positions','model_versions','calculations','decisions','audit_events'] LOOP
        EXECUTE format('ALTER TABLE funding.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE funding.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('CREATE POLICY tenant_isolation ON funding.%I
            USING (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid)
            WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid)', table_name);
    END LOOP;
END;
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA funding FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA funding FROM PUBLIC;
-- Explicit application-role grants, tenant provisioning, job/outbox/idempotency
-- tables, transactional audit writes and deployment migrations remain to implement.
-- Set app.tenant_id transaction-locally from VERIFIED server identity, never user input.
COMMIT;
