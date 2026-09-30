-- Coordinated backup manifest.
--
-- backup/coordinated.py pauses writers before it calls backup_store.
-- A live SQLite copy, a stored passphrase, a movie file, or an
-- unmarked app cannot be inserted. Compose has no backup service.

CREATE TABLE IF NOT EXISTS backup_manifests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pause_id UUID NOT NULL UNIQUE,
    sqlite_method TEXT NOT NULL,
    has_postgres BOOLEAN NOT NULL,
    has_qdrant BOOLEAN NOT NULL,
    has_journal BOOLEAN NOT NULL,
    has_soul BOOLEAN NOT NULL,
    secrets_encrypted BOOLEAN NOT NULL,
    passphrase_stored BOOLEAN NOT NULL,
    excludes_optional_apps BOOLEAN NOT NULL,
    registry JSONB NOT NULL,
    included_extra TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT backup_sqlite_method_check CHECK (
        sqlite_method IN ('backup_api', 'clean_shutdown')
    ),
    CONSTRAINT backup_stores_check CHECK (has_postgres AND has_qdrant),
    CONSTRAINT backup_journal_check CHECK (has_journal),
    CONSTRAINT backup_soul_check CHECK (has_soul),
    CONSTRAINT backup_secrets_check CHECK (secrets_encrypted AND NOT passphrase_stored),
    CONSTRAINT backup_excludes_check CHECK (excludes_optional_apps),
    CONSTRAINT backup_no_optional CHECK (included_extra = '{}')
);

CREATE OR REPLACE FUNCTION backup_store(
    p_pause_id uuid,
    p_sqlite_method text,
    p_registry jsonb,
    p_included_extra text[]
) RETURNS uuid
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    existing uuid;
    new_id uuid;
    mark text;
BEGIN
    IF p_sqlite_method IS DISTINCT FROM 'backup_api'
       AND p_sqlite_method IS DISTINCT FROM 'clean_shutdown' THEN
        RAISE EXCEPTION 'live_sqlite'
            USING ERRCODE = 'check_violation';
    END IF;
    IF p_included_extra IS DISTINCT FROM '{}'::text[] THEN
        RAISE EXCEPTION 'optional_app_excluded'
            USING ERRCODE = 'check_violation';
    END IF;
    IF p_registry IS NULL OR jsonb_typeof(p_registry) <> 'array'
       OR jsonb_array_length(p_registry) = 0 THEN
        RAISE EXCEPTION 'registry_mark'
            USING ERRCODE = 'check_violation';
    END IF;
    FOR mark IN
        SELECT elem->>'mark'
          FROM jsonb_array_elements(p_registry) AS elem
    LOOP
        IF mark IS DISTINCT FROM 'managed' AND mark IS DISTINCT FROM 'adopted' THEN
            RAISE EXCEPTION 'registry_mark'
                USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;

    SELECT id INTO existing
      FROM backup_manifests
     WHERE pause_id = p_pause_id;
    IF FOUND THEN
        RETURN existing;
    END IF;

    new_id := gen_random_uuid();
    INSERT INTO backup_manifests (
        id, pause_id, sqlite_method, has_postgres, has_qdrant,
        has_journal, has_soul, secrets_encrypted, passphrase_stored,
        excludes_optional_apps, registry, included_extra
    ) VALUES (
        new_id, p_pause_id, p_sqlite_method, true, true,
        true, true, true, false,
        true, p_registry, '{}'
    );
    RETURN new_id;
END;
$$;
