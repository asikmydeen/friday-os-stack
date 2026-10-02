-- Proves sql/approvals.sql against a live Postgres. The block rolls back.
-- Apply sql/approvals.sql first. Run with ON_ERROR_STOP=1.
BEGIN;

DO $$
DECLARE
    ok_id uuid;
    mismatch_id uuid;
    expired_id uuid;
    stored uuid;
    op1 uuid;
    op2 uuid;
    op_stored uuid;
    op_again uuid;
    journals integer;
BEGIN
    BEGIN
        INSERT INTO approvals (kind, owner_id, body, expires_at, created_by)
        VALUES (
            'life', 'owner',
            '{"action_class":"send","target":"a","payload_digest":"d"}'::jsonb,
            now() + interval '5 minutes',
            'chat'
        );
        RAISE EXCEPTION 'chat insert was stored';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO approvals (kind, owner_id, body, expires_at)
        VALUES (
            'machine', 'owner',
            '{"operation":"install","app_id":"jellyfin"}'::jsonb,
            now() + interval '5 minutes'
        );
        RAISE EXCEPTION 'install row was stored';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    INSERT INTO approvals (kind, owner_id, body, expires_at)
    VALUES (
        'life', 'owner',
        '{"action_class":"send","target":"a","payload_digest":"d"}'::jsonb,
        now() + interval '5 minutes'
    )
    RETURNING id INTO ok_id;

    BEGIN
        PERFORM approval_exchange(
            'chat', ok_id,
            '{"action_class":"send","target":"a","payload_digest":"d"}'::jsonb
        );
        RAISE EXCEPTION 'chat exchange was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'actor_cannot_exchange' THEN
                RAISE;
            END IF;
    END;
    IF (SELECT status FROM approvals WHERE id = ok_id) <> 'approved' THEN
        RAISE EXCEPTION 'chat exchange changed the row';
    END IF;

    op1 := approval_exchange(
        'board', ok_id,
        '{"action_class":"send","target":"a","payload_digest":"d"}'::jsonb
    );
    op2 := approval_exchange(
        'board', ok_id,
        '{"action_class":"send","target":"a","payload_digest":"d"}'::jsonb
    );
    IF op1 IS NULL OR op1 IS DISTINCT FROM op2 THEN
        RAISE EXCEPTION 'second exchange did not return the same journal';
    END IF;
    SELECT count(*) INTO journals FROM operation_journal WHERE approval_id = ok_id;
    IF journals <> 1 THEN
        RAISE EXCEPTION 'expected one journal row, found %', journals;
    END IF;

    BEGIN
        PERFORM approval_exchange(
            'board', ok_id,
            '{"action_class":"send","target":"a","payload_digest":"other"}'::jsonb
        );
        RAISE EXCEPTION 'changed body was exchanged again';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'already_exchanged' THEN
                RAISE;
            END IF;
    END;
    IF (SELECT status FROM approvals WHERE id = ok_id) <> 'exchanged' THEN
        RAISE EXCEPTION 'a replay rewrote an exchanged approval';
    END IF;

    INSERT INTO approvals (kind, owner_id, body, expires_at)
    VALUES (
        'life', 'owner',
        '{"action_class":"pay","target":"shop","payload_digest":"card"}'::jsonb,
        now() + interval '5 minutes'
    )
    RETURNING id INTO mismatch_id;
    IF approval_exchange(
        'board', mismatch_id,
        '{"action_class":"pay","target":"shop","payload_digest":"changed"}'::jsonb
    ) IS NOT NULL THEN
        RAISE EXCEPTION 'mismatch returned a journal';
    END IF;
    IF (SELECT status FROM approvals WHERE id = mismatch_id) <> 'void' THEN
        RAISE EXCEPTION 'mismatch did not void the approval';
    END IF;
    SELECT count(*) INTO journals FROM operation_journal WHERE approval_id = mismatch_id;
    IF journals <> 0 THEN
        RAISE EXCEPTION 'void approval created a journal';
    END IF;

    INSERT INTO approvals (kind, owner_id, body, expires_at)
    VALUES (
        'life', 'owner',
        '{"action_class":"delete","target":"note","payload_digest":"x"}'::jsonb,
        now() - interval '1 minute'
    )
    RETURNING id INTO expired_id;
    IF approval_exchange(
        'board', expired_id,
        '{"action_class":"delete","target":"note","payload_digest":"x"}'::jsonb
    ) IS NOT NULL THEN
        RAISE EXCEPTION 'expired approval returned a journal';
    END IF;
    IF (SELECT status FROM approvals WHERE id = expired_id) <> 'expired' THEN
        RAISE EXCEPTION 'expired approval was not marked expired';
    END IF;

    stored := approval_store(
        'board', 'owner', 'life',
        '{"action_class":"publish","target":"note","payload_digest":"p"}'::jsonb
    );
    IF stored IS NULL THEN
        RAISE EXCEPTION 'approval_store returned null';
    END IF;
    op_stored := approval_exchange_owner(
        'board', stored, 'owner',
        '{"action_class":"publish","target":"note","payload_digest":"p"}'::jsonb
    );
    op_again := approval_exchange_owner(
        'board', stored, 'owner',
        '{"action_class":"publish","target":"note","payload_digest":"p"}'::jsonb
    );
    IF op_stored IS NULL OR op_stored IS DISTINCT FROM op_again THEN
        RAISE EXCEPTION 'owner exchange did not keep one journal';
    END IF;
    SELECT count(*) INTO journals FROM operation_journal WHERE approval_id = stored;
    IF journals <> 1 THEN
        RAISE EXCEPTION 'approval_store exchange wrote % journals', journals;
    END IF;

    BEGIN
        PERFORM approval_store(
            'chat', 'owner', 'life',
            '{"action_class":"send","target":"a","payload_digest":"d"}'::jsonb
        );
        RAISE EXCEPTION 'chat store was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'actor_cannot_approve' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        PERFORM approval_exchange_owner(
            'board', stored, 'other',
            '{"action_class":"publish","target":"note","payload_digest":"p"}'::jsonb
        );
        RAISE EXCEPTION 'owner mismatch was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'owner_mismatch' THEN
                RAISE;
            END IF;
    END;
    IF (SELECT status FROM approvals WHERE id = stored) <> 'exchanged' THEN
        RAISE EXCEPTION 'owner mismatch rewrote an exchanged approval';
    END IF;

    BEGIN
        UPDATE approvals SET status = 'approved' WHERE id = ok_id;
        RAISE EXCEPTION 'exchanged approval moved backwards';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM NOT LIKE 'approval status cannot move%' THEN
                RAISE;
            END IF;
    END;
END $$;

ROLLBACK;
