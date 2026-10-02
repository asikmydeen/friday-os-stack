-- Approval records and the task journal.
--
-- The Board is the only creator. Chat, a messaging door, and an inbound
-- MCP caller cannot insert a row: created_by must be 'board'.
-- Catalog install cannot be stored. Exchange is one transaction in
-- approval_exchange: the row moves from approved to exchanged, and one
-- operation journal row is inserted. A second call with the same body
-- returns that same journal id. A different body voids an approved row
-- and leaves an already-exchanged row alone.
--
-- gate/rules.py is the same transition, including mount and port checks
-- this function does not repeat. With POSTGRES_HOST set, the executor
-- calls approval_store and approval_exchange_owner. Without that host,
-- the process file remains. A second exchange of the same body returns
-- the same operation id. gate/recover.py compares a journal with objects
-- the caller supplies. It does not inspect Docker, it does not start a
-- container, and a label alone does not write applied. A void or an
-- expiry is kept by returning NULL: raising afterwards would roll the
-- status change back. An exception means the row was not changed.
-- Nothing in compose.yml runs containers from these rows. See
-- docs/architecture.md.

CREATE TABLE IF NOT EXISTS approvals (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind          TEXT NOT NULL,
    owner_id      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'approved',
    body          JSONB NOT NULL,
    expires_at    TIMESTAMPTZ NOT NULL,
    operation_id  UUID,
    created_by    TEXT NOT NULL DEFAULT 'board',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    exchanged_at  TIMESTAMPTZ,
    CONSTRAINT approvals_kind_check CHECK (kind IN ('machine', 'life')),
    CONSTRAINT approvals_status_check CHECK (status IN ('approved', 'exchanged', 'void', 'expired')),
    CONSTRAINT approvals_created_by_check CHECK (created_by = 'board'),
    CONSTRAINT approvals_no_install CHECK (COALESCE(body->>'operation', '') <> 'install')
);

CREATE TABLE IF NOT EXISTS operation_journal (
    id           UUID PRIMARY KEY,
    approval_id  UUID NOT NULL UNIQUE REFERENCES approvals (id),
    owner_id     TEXT NOT NULL,
    kind         TEXT NOT NULL,
    operation    TEXT NOT NULL,
    steps        JSONB NOT NULL,
    state        TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT operation_journal_state_check
        CHECK (state IN ('ready', 'running', 'waiting', 'done', 'blocked', 'applied'))
);

CREATE TABLE IF NOT EXISTS task_journal (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    TEXT NOT NULL,
    role_id     TEXT,
    goal        TEXT NOT NULL,
    steps       JSONB NOT NULL,
    state       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT task_journal_state_check
        CHECK (state IN ('ready', 'running', 'waiting', 'done', 'blocked'))
);

CREATE OR REPLACE FUNCTION approvals_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NEW.body IS DISTINCT FROM OLD.body
       OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
        RAISE EXCEPTION 'approval body is immutable';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF OLD.status = 'approved' AND NEW.status IN ('exchanged', 'void', 'expired') THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'approval status cannot move from % to %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS approvals_guard ON approvals;
CREATE TRIGGER approvals_guard
    BEFORE UPDATE ON approvals
    FOR EACH ROW
    EXECUTE FUNCTION approvals_guard();

CREATE OR REPLACE FUNCTION approval_exchange(
    p_actor text,
    p_approval_id uuid,
    p_body jsonb,
    p_now timestamptz DEFAULT now()
) RETURNS uuid
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    rec approvals%ROWTYPE;
    new_id uuid;
    op_name text;
BEGIN
    IF p_actor IS DISTINCT FROM 'board' THEN
        RAISE EXCEPTION 'actor_cannot_exchange';
    END IF;
    IF p_body->>'operation' = 'install' THEN
        RAISE EXCEPTION 'catalog_install_closed';
    END IF;

    SELECT * INTO rec FROM approvals WHERE id = p_approval_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown_approval';
    END IF;
    IF rec.body->>'operation' = 'install' THEN
        RAISE EXCEPTION 'catalog_install_closed';
    END IF;

    IF rec.status = 'exchanged' THEN
        IF rec.body IS DISTINCT FROM p_body THEN
            RAISE EXCEPTION 'already_exchanged';
        END IF;
        RETURN rec.operation_id;
    END IF;
    IF rec.status <> 'approved' THEN
        RAISE EXCEPTION 'not_approved';
    END IF;
    IF p_now >= rec.expires_at THEN
        UPDATE approvals SET status = 'expired' WHERE id = rec.id;
        RETURN NULL;
    END IF;
    IF rec.body IS DISTINCT FROM p_body THEN
        UPDATE approvals SET status = 'void' WHERE id = rec.id;
        RETURN NULL;
    END IF;

    op_name := COALESCE(rec.body->>'operation', rec.body->>'action_class');
    new_id := gen_random_uuid();
    INSERT INTO operation_journal (id, approval_id, owner_id, kind, operation, steps, state)
    VALUES (
        new_id,
        rec.id,
        rec.owner_id,
        rec.kind,
        op_name,
        jsonb_build_array(jsonb_build_object('name', op_name, 'state', 'pending')),
        'ready'
    );
    UPDATE approvals
       SET status = 'exchanged',
           operation_id = new_id,
           exchanged_at = p_now
     WHERE id = rec.id;
    RETURN new_id;
END;
$$;

-- One approved row. Chat, install, an empty owner, and an unknown kind
-- raise before the insert. The expiry is ten minutes. Nothing is sent.
CREATE OR REPLACE FUNCTION approval_store(
    p_actor text,
    p_owner_id text,
    p_kind text,
    p_body jsonb
) RETURNS uuid
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    new_id uuid;
BEGIN
    IF p_actor IS DISTINCT FROM 'board' THEN
        RAISE EXCEPTION 'actor_cannot_approve';
    END IF;
    IF p_owner_id IS NULL OR btrim(p_owner_id) = '' THEN
        RAISE EXCEPTION 'missing_owner';
    END IF;
    IF p_kind IS DISTINCT FROM 'life' AND p_kind IS DISTINCT FROM 'machine' THEN
        RAISE EXCEPTION 'unknown_kind';
    END IF;
    IF p_body IS NULL OR jsonb_typeof(p_body) <> 'object' THEN
        RAISE EXCEPTION 'unknown_action';
    END IF;
    IF p_body->>'operation' = 'install' OR p_body->>'action' = 'install' THEN
        RAISE EXCEPTION 'catalog_install_closed';
    END IF;

    new_id := gen_random_uuid();
    INSERT INTO approvals (id, kind, owner_id, status, body, expires_at, created_by)
    VALUES (
        new_id,
        p_kind,
        p_owner_id,
        'approved',
        p_body,
        now() + interval '10 minutes',
        'board'
    );
    RETURN new_id;
END;
$$;

-- Same exchange, after the owner on the row is checked. A mismatch does
-- not void the row. The operation id still comes from approval_exchange.
CREATE OR REPLACE FUNCTION approval_exchange_owner(
    p_actor text,
    p_approval_id uuid,
    p_owner_id text,
    p_body jsonb,
    p_now timestamptz DEFAULT now()
) RETURNS uuid
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    stored text;
BEGIN
    IF p_actor IS DISTINCT FROM 'board' THEN
        RAISE EXCEPTION 'actor_cannot_exchange';
    END IF;
    SELECT owner_id INTO stored FROM approvals WHERE id = p_approval_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown_approval';
    END IF;
    IF stored IS DISTINCT FROM p_owner_id THEN
        RAISE EXCEPTION 'owner_mismatch';
    END IF;
    RETURN approval_exchange(p_actor, p_approval_id, p_body, p_now);
END;
$$;
