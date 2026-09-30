-- Proves sql/backup.sql. The block rolls back.
-- Apply sql/backup.sql first. Run with ON_ERROR_STOP=1.
BEGIN;

DO $$
DECLARE
    pause_id uuid := 'b0c0a000-0000-4000-8000-000000000001';
    first_id uuid;
    again uuid;
BEGIN
    first_id := backup_store(
        pause_id,
        'backup_api',
        '[{"id":"jellyfin","mark":"adopted"}]'::jsonb,
        '{}'
    );
    again := backup_store(
        pause_id,
        'backup_api',
        '[{"id":"jellyfin","mark":"adopted"}]'::jsonb,
        '{}'
    );
    IF first_id IS DISTINCT FROM again THEN
        RAISE EXCEPTION 'retry stored a second manifest';
    END IF;
    IF (SELECT count(*) FROM backup_manifests) <> 1 THEN
        RAISE EXCEPTION 'expected one manifest';
    END IF;
    IF (SELECT passphrase_stored FROM backup_manifests WHERE id = first_id) THEN
        RAISE EXCEPTION 'passphrase was stored';
    END IF;

    BEGIN
        PERFORM backup_store(gen_random_uuid(), 'live_file', '[{"id":"jellyfin","mark":"managed"}]'::jsonb, '{}');
        RAISE EXCEPTION 'live sqlite was stored';
    EXCEPTION
        WHEN check_violation THEN
            IF SQLERRM IS DISTINCT FROM 'live_sqlite' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        PERFORM backup_store(
            gen_random_uuid(),
            'backup_api',
            '[{"id":"jellyfin","mark":"adopted"}]'::jsonb,
            ARRAY['movies']
        );
        RAISE EXCEPTION 'movies were stored';
    EXCEPTION
        WHEN check_violation THEN
            IF SQLERRM IS DISTINCT FROM 'optional_app_excluded' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        PERFORM backup_store(
            gen_random_uuid(),
            'clean_shutdown',
            '[{"id":"jellyfin","mark":"guest"}]'::jsonb,
            '{}'
        );
        RAISE EXCEPTION 'bad registry mark was stored';
    EXCEPTION
        WHEN check_violation THEN
            IF SQLERRM IS DISTINCT FROM 'registry_mark' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO backup_manifests (
            pause_id, sqlite_method, has_postgres, has_qdrant,
            has_journal, has_soul, secrets_encrypted, passphrase_stored,
            excludes_optional_apps, registry
        ) VALUES (
            gen_random_uuid(), 'backup_api', true, true,
            true, true, true, true,
            true, '[{"id":"jellyfin","mark":"managed"}]'::jsonb
        );
        RAISE EXCEPTION 'direct insert stored a passphrase';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;
END
$$;

ROLLBACK;
