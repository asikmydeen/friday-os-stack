-- Queue for app webhooks. The receiver checks the Friday-Webhook header
-- before it calls webhook_store. This table keeps the raw body for the
-- log. The announcement column can hold only one of the four fixed
-- sentences, so a stored row cannot smuggle the body into the prompt.
--
-- There is no foreign key to approvals. The receiver does not write one,
-- and it does not call the executor. The image compose attaches the
-- receiver to apps and to core so it can write this table. An app stays
-- on apps and is not given a route to Postgres. The dev compose.yml
-- has no webhooks service.

CREATE TABLE IF NOT EXISTS webhook_events (
    id            UUID PRIMARY KEY,
    source        TEXT NOT NULL,
    route         TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    announcement  TEXT NOT NULL,
    body          JSONB,
    body_raw      TEXT NOT NULL,
    body_sha256   TEXT NOT NULL,
    received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT webhook_events_source_check CHECK (source IN ('jellyfin', 'radarr', 'sonarr')),
    CONSTRAINT webhook_events_route_check CHECK (route IN ('media', 'arr')),
    CONSTRAINT webhook_events_type_check CHECK (event_type IN ('grab', 'failure', 'health', 'other')),
    CONSTRAINT webhook_events_sentence_check CHECK (
        (event_type = 'grab' AND announcement = 'A download was grabbed.')
        OR (event_type = 'failure' AND announcement = 'A download failed.')
        OR (event_type = 'health' AND announcement = 'An app health state changed.')
        OR (event_type = 'other' AND announcement = 'An app sent an event.')
    ),
    CONSTRAINT webhook_events_delivery_key UNIQUE (source, body_sha256)
);

-- Return type changed from uuid. CREATE OR REPLACE cannot do that.
DROP FUNCTION IF EXISTS webhook_store(text, text, text, text, jsonb, text, text);

CREATE FUNCTION webhook_store(
    p_source text,
    p_route text,
    p_event_type text,
    p_announcement text,
    p_body jsonb,
    p_body_raw text,
    p_body_sha256 text
) RETURNS TABLE (id uuid, inserted boolean)
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    existing uuid;
    fresh uuid;
BEGIN
    fresh := gen_random_uuid();
    INSERT INTO webhook_events (
        id, source, route, event_type, announcement, body, body_raw, body_sha256
    ) VALUES (
        fresh, p_source, p_route, p_event_type, p_announcement, p_body, p_body_raw, p_body_sha256
    )
    ON CONFLICT (source, body_sha256) DO NOTHING;
    IF FOUND THEN
        id := fresh;
        inserted := true;
        RETURN NEXT;
        RETURN;
    END IF;
    SELECT webhook_events.id INTO existing
      FROM webhook_events
     WHERE source = p_source AND body_sha256 = p_body_sha256;
    id := existing;
    inserted := false;
    RETURN NEXT;
END;
$$;
